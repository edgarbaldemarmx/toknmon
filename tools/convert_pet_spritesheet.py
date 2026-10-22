#!/usr/bin/env python3
"""Convert ChatGPT pet sprite sheets into grid animations for the Codex splash.

Petmeter archives the eight ChatGPT pets as 1536 x 1872 WebP sheets laid out
as an 8 x 9 grid of 192 x 208 cells. Each ROW is one animation and rows are
ragged (idle 6, walking 8, running 8, waving 4, jumping 5, dizzy 8, thinking 6,
laptop 6, happy 6 frames). `tools/fetch_codex_pets.sh` downloads them into
`research/codex-pets/` (git-ignored); this script turns each sheet into ONE
text grid in our authoring format, `assets/animations/codex.pet-<slug>.txt`,
which `tools/convert_grid_animations.js` then compiles into the firmware
header like any hand-drawn animation.

Per pet the emitted clip is: the idle row as the looped region (`loop: 0-5`,
330 ms per frame) followed by waving, jumping and happy at 90 ms as the outro,
so the splash engine plays idle for SCENE_LOOP_MS and then the three acts
before moving on to the next entry of the Codex set.

The sprites are anti-aliased with soft shading, so there is no pixel grid to
recover; each cell is area-downsampled (premultiplied alpha, so transparent
pixels do not darken the edges) to the stage scale and then quantized with
a median cut over the RGB565-rounded colours to at most 15 entries plus
transparent. One bounding box per pet, shared by every emitted frame, keeps
the character anchored between rows. Index 0 of our palettes draws as opaque
black on the full splash, so palette entries darker than #141413 are lifted
to that ink, and a palette whose brightest colour would vanish on the black
AMOLED is brightened uniformly (Null Signal and Stacky are drawn for a
white page). Output is deterministic: same sheet, byte-identical grid.

`--icon PET` additionally renders PET's idle row into the usage view's Codex
corner icon, `assets/animations/codex.icon.txt` (`name: codex.icon`, so
`MASCOT_SPECS` keeps resolving it): the six idle frames at 330 ms, scaled
to at most 24x21 cells so the grid fits the 28x21 corner-mascot envelope,
feet on row 36, one shared box so every frame keeps the same left edge.
Given alone it writes only the icon; with `--pets` it writes both.

Run with the daemon venv (Pillow lives there) in isolated mode, since the
sheets are downloaded data:

  daemon/.venv/bin/python -I tools/convert_pet_spritesheet.py \\
      --src research/codex-pets --out assets/animations [--pets a,b] [--icon PET] [--verify DIR]
"""
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required (daemon/.venv has it): daemon/.venv/bin/python -I ...")

# ── Sheet geometry (ChatGPT pets custom-pet layout, as archived by Petmeter) ──
COLS, ROWS = 8, 9
CELL_W, CELL_H = 192, 208
SHEET_W, SHEET_H = COLS * CELL_W, ROWS * CELL_H
# Row order and frame counts; the sheet itself carries no timing.
ROW_ANIMS = [
    ("idle", 6), ("walking", 8), ("running", 8), ("waving", 4), ("jumping", 5),
    ("dizzy", 8), ("thinking", 6), ("laptop", 6), ("happy", 6),
]
IDLE_HOLD_MS = 330
ACT_HOLD_MS = 90
# The clip: idle loops, then these rows play once as the outro.
CLIP_ROWS = ["idle", "waving", "jumping", "happy"]

# ── Stage ────────────────────────────────────────────────────────────────────
STAGE_W, STAGE_H = 55, 37       # the official art stage; feet on row 36
TARGET_W = 30                   # pet width in cells (26-32 wanted)
MIN_W, MAX_W, MAX_H = 26, 32, 34
PALETTE_COLORS = 15             # plus the transparent entry (index 0)
ALPHA_FLOOR = 8                 # source alpha at or below this is empty
COVERAGE_FLOOR = 0.40           # fraction of a cell's area that must be opaque
INK = (0x14, 0x14, 0x13)        # darkest visible colour (index 0 is opaque black)
MIN_PEAK_LUMA = 150             # brighten palettes whose brightest colour is dimmer
LEGEND = "abcdefghijklmno"      # one character per palette colour
SHEET_SUFFIX = "-spritesheet.webp"

# ── Corner icon (--icon PET → codex.icon, the usage view's Codex mascot) ─────
ICON_NAME = "codex.icon"
MASCOT_MAX_W, MASCOT_MAX_H = 28, 21   # the corner-mascot envelope (convert_grid_animations.js)
ICON_MAX_W, ICON_MAX_H = 24, 21       # Clawd-sized width, never taller than the envelope
ICON_COVERAGE_FLOOR = 0.25            # thinner features (antennae) survive the smaller scale


def slice_rows(sheet):
    """{row name: [192x208 RGBA frame, ...]} following the fixed 8x9 layout."""
    if sheet.size != (SHEET_W, SHEET_H):
        raise ValueError(f"sheet is {sheet.size[0]}x{sheet.size[1]}, expected {SHEET_W}x{SHEET_H}")
    rows = {}
    for r, (name, count) in enumerate(ROW_ANIMS):
        rows[name] = [sheet.crop((c * CELL_W, r * CELL_H, (c + 1) * CELL_W, (r + 1) * CELL_H))
                      for c in range(count)]
    return rows


def alpha_bbox(frame):
    return frame.getchannel("A").point(lambda p: 255 if p > ALPHA_FLOOR else 0).getbbox()


def union_bbox(frames):
    """One content box over every frame so the pet never jitters between rows."""
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for f in frames:
        bb = alpha_bbox(f)
        if bb:
            x0, y0, x1, y1 = min(x0, bb[0]), min(y0, bb[1]), max(x1, bb[2]), max(y1, bb[3])
    if x1 < 0:
        raise ValueError("every frame is transparent")
    return x0, y0, x1, y1


def stage_size(bw, bh):
    """Cells for a source box of bw x bh px: ~TARGET_W wide, at most MAX_H tall."""
    scale = max(bw / TARGET_W, bh / MAX_H)
    w = max(1, round(bw / scale))
    h = max(1, round(bh / scale))
    return min(w, MAX_W), min(h, MAX_H)


def downsample(frame, box, size, coverage=COVERAGE_FLOOR):
    """Area-average the box of `frame` to `size` cells -> [(rgb, drawn)] row-major.

    Premultiplied alpha keeps the fully transparent neighbours (whose RGB is
    arbitrary) from bleeding into edge cells; a cell is drawn only when enough
    of its area is opaque, otherwise the soft outline becomes a halo.
    """
    small = frame.crop(box).convert("RGBa").resize(size, Image.BOX).convert("RGBA")
    px = small.load()
    out = []
    for y in range(size[1]):
        for x in range(size[0]):
            r, g, b, a = px[x, y]
            out.append(((r, g, b), a >= 255 * coverage))
    return out


def rgb565_round(rgb):
    """The colour as the panel stores it (RGB565), expanded back to 8 bits."""
    r, g, b = rgb
    r5, g6, b5 = r >> 3, g >> 2, b >> 3
    return (r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2)


def luminance(rgb):
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def build_palette(colors):
    """<= PALETTE_COLORS colours by median cut over the 565-rounded pixels.

    Median cut hands slots out by colour distribution, not frequency, so a
    small but distant cluster such as the dark outline keeps an entry.
    """
    px = sorted(set(rgb565_round(c) for c in colors))
    if not px:
        raise ValueError("no drawn cells")
    if len(px) <= PALETTE_COLORS:
        return px
    strip = Image.new("RGB", (len(px), 1))
    strip.putdata(px)
    q = strip.quantize(colors=PALETTE_COLORS, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    data = q.get_flattened_data() if hasattr(q, "get_flattened_data") else q.getdata()
    used = sorted(set(data))
    return sorted(set(rgb565_round(tuple(pal[i * 3:i * 3 + 3])) for i in used))


def nearest(rgb, palette):
    r, g, b = rgb
    best = min(range(len(palette)),
               key=lambda i: (r - palette[i][0]) ** 2 + (g - palette[i][1]) ** 2 + (b - palette[i][2]) ** 2)
    return best


def display_palette(palette):
    """Lift a too-dark palette uniformly, then clamp entries to the ink floor."""
    peak = max(luminance(c) for c in palette)
    k = MIN_PEAK_LUMA / peak if 0 < peak < MIN_PEAK_LUMA else 1.0
    out = []
    for c in palette:
        c = tuple(min(255, int(round(ch * k))) for ch in c)
        if max(c) < INK[0]:
            c = INK
        out.append(c)
    return out, k


def quantize_frames(cells, size, slug):
    """Downsampled frames -> (w, h, palette shown, index grids, lift).

    Trims the shared box to the cells actually drawn after the coverage test,
    so the bottom row always carries ink (the converter's feet rule) and
    every frame keeps the same left edge, then quantizes to one palette.
    """
    w, h = size
    x0, y0, x1, y1 = w, h, -1, -1
    for frame in cells:
        for i, (_, drawn) in enumerate(frame):
            if drawn:
                x, y = i % w, i // w
                x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
    if x1 < 0:
        raise ValueError(f"{slug}: no cell reaches the coverage floor")
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    cropped = [[frame[(y0 + y) * w + (x0 + x)] for y in range(ch) for x in range(cw)] for frame in cells]

    palette = build_palette([rgb for frame in cropped for rgb, drawn in frame if drawn])
    shown, lift = display_palette(palette)
    grid = [[(nearest(rgb565_round(rgb), palette) + 1) if drawn else 0 for rgb, drawn in frame]
            for frame in cropped]
    return cw, ch, shown, grid, lift


def convert_pet(sheet, slug):
    """Sheet image -> {name, origin, palette, frames, holds, loop, w, h, lift}."""
    rows = slice_rows(sheet)
    src_frames = [(name, f) for name in CLIP_ROWS for f in rows[name]]
    box = union_bbox([f for _, f in src_frames])
    size = stage_size(box[2] - box[0], box[3] - box[1])
    cells = [downsample(f, box, size) for _, f in src_frames]
    cw, ch, shown, grid, lift = quantize_frames(cells, size, slug)
    holds = [IDLE_HOLD_MS if name == "idle" else ACT_HOLD_MS for name, _ in src_frames]
    idle_n = len(rows["idle"])
    return dict(name=f"codex.pet-{slug}", slug=slug, w=cw, h=ch,
                origin=((STAGE_W - cw) // 2, STAGE_H - ch), palette=shown,
                frames=grid, holds=holds, rows=[name for name, _ in src_frames],
                loop=(0, idle_n - 1), lift=lift,
                intro=[f"# ChatGPT pet \"{slug}\" for the Codex splash, generated by"],
                clip=[f"# Clip: idle x{idle_n} looped, then waving, jumping and happy as the outro."])


def icon_size(bw, bh):
    """Cells for a source box of bw x bh px inside the corner envelope.

    The corner mascot buffer is cut for the 28x21-cell envelope; the icon
    aims at Clawd's ~24-cell width and never exceeds 21 rows, so a pet
    taller than wide (every ChatGPT pet) is capped by the height instead.
    """
    scale = max(bw / ICON_MAX_W, bh / ICON_MAX_H)
    w = max(1, round(bw / scale))
    h = max(1, round(bh / scale))
    return min(w, ICON_MAX_W), min(h, ICON_MAX_H)


def convert_icon(sheet, slug):
    """Sheet image -> the pet's idle row as the Codex corner icon (`codex.icon`).

    The six idle frames are kept whole, each held IDLE_HOLD_MS, so the corner
    act (MASCOT_SPECS plays the file once and returns to frame 0) reads as
    the pet's calm idle rather than a single blink. One box over the idle
    row keeps the left edge shared by every frame.
    """
    rows = slice_rows(sheet)
    idle = rows["idle"]
    box = union_bbox(idle)
    size = icon_size(box[2] - box[0], box[3] - box[1])
    cells = [downsample(f, box, size, ICON_COVERAGE_FLOOR) for f in idle]
    cw, ch, shown, grid, lift = quantize_frames(cells, size, slug)
    return dict(name=ICON_NAME, slug=slug, w=cw, h=ch,
                origin=((STAGE_W - cw) // 2, STAGE_H - ch), palette=shown,
                frames=grid, holds=[IDLE_HOLD_MS] * len(idle), rows=["idle"] * len(idle),
                loop=(0, len(idle) - 1), lift=lift,
                intro=["# Codex corner icon (usage view only, never a splash entry): the ChatGPT",
                       f"# pet \"{slug}\" idle row scaled into the {MASCOT_MAX_W}x{MASCOT_MAX_H} mascot envelope, generated by"],
                clip=[f"# Frames: the {len(idle)} idle poses at {IDLE_HOLD_MS} ms; frame 0 is the corner still and",
                      "# the whole file is the corner act (MASCOT_SPECS names codex.icon for both)."])


def emit_grid(pet):
    """The pet as our grid text format (see tools/convert_grid_animations.js)."""
    w, h = pet["w"], pet["h"]
    lines = [
        *pet["intro"],
        "# tools/convert_pet_spritesheet.py from Petmeter's research/codex-pets sheet",
        "# (OpenAI artwork, see NOTICE.md). Do not edit by hand; re-run the converter.",
        *pet["clip"],
        f"name: {pet['name']}",
        f"origin: {pet['origin'][0]} {pet['origin'][1]}",
        "palette:",
        "  . = transparent",
    ]
    for ch, (r, g, b) in zip(LEGEND, pet["palette"]):
        lines.append(f"  {ch} = #{r:02X}{g:02X}{b:02X}")
    lines.append(f"hold: {IDLE_HOLD_MS}")
    lines.append(f"loop: {pet['loop'][0]}-{pet['loop'][1]}")
    chars = "." + LEGEND
    counters = {}
    for frame, hold, row in zip(pet["frames"], pet["holds"], pet["rows"]):
        k = counters.get(row, 0)
        counters[row] = k + 1
        lines.append(f"--- hold={hold} # {row} {k}")
        for y in range(h):
            lines.append("".join(chars[frame[y * w + x]] for x in range(w)))
    return "\n".join(lines) + "\n"


def write_verify_png(pet, path, scale=4):
    """Every frame side by side at `scale` px per cell, index 0 as black."""
    w, h = pet["w"], pet["h"]
    n = len(pet["frames"])
    im = Image.new("RGB", ((w + 1) * n * scale, h * scale), (0, 0, 0))
    px = im.load()
    for fi, frame in enumerate(pet["frames"]):
        for y in range(h):
            for x in range(w):
                code = frame[y * w + x]
                if not code:
                    continue
                c = pet["palette"][code - 1]
                for dy in range(scale):
                    for dx in range(scale):
                        px[(fi * (w + 1) + x) * scale + dx, y * scale + dy] = c
    im.save(path, optimize=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", required=True, help="directory holding <slug>-spritesheet.webp")
    ap.add_argument("--out", required=True, help="directory for codex.pet-<slug>.txt")
    ap.add_argument("--pets", help="comma-separated slugs to convert (default: every sheet, "
                                   "or none when --icon is given)")
    ap.add_argument("--icon", metavar="PET",
                    help=f"also render PET's idle row as the corner icon {ICON_NAME}.txt")
    ap.add_argument("--verify", help="also write one PNG frame strip per pet here")
    args = ap.parse_args(argv)

    src, out = Path(args.src), Path(args.out)
    sheets = sorted(src.glob(f"*{SHEET_SUFFIX}"))
    available = {p.name[: -len(SHEET_SUFFIX)]: p for p in sheets}
    if args.icon and args.icon not in available:
        sys.exit(f"no sheet for pet {args.icon} in {src} (have: {', '.join(available) or 'none'})")
    slugs = {} if args.icon and not args.pets else dict(available)
    if args.pets:
        wanted = [s.strip() for s in args.pets.split(",") if s.strip()]
        missing = [s for s in wanted if s not in available]
        if missing:
            sys.exit(f"no sheet for pet(s) {', '.join(missing)} in {src} (have: {', '.join(available) or 'none'})")
        slugs = {s: available[s] for s in wanted}
    if not slugs and not args.icon:
        sys.exit(f"no *{SHEET_SUFFIX} in {src}; run tools/fetch_codex_pets.sh first")

    out.mkdir(parents=True, exist_ok=True)
    if args.verify:
        Path(args.verify).mkdir(parents=True, exist_ok=True)
    jobs = [(slug, path, convert_pet) for slug, path in sorted(slugs.items())]
    if args.icon:
        jobs.append((args.icon, available[args.icon], convert_icon))
    total = 0
    for slug, path, convert in jobs:
        with Image.open(path) as im:
            pet = convert(im.convert("RGBA"), slug)
        text = emit_grid(pet)
        target = out / f"{pet['name']}.txt"
        target.write_text(text)
        total += len(text)
        cells = len(pet["frames"]) * pet["w"] * pet["h"]
        lift = f", lifted x{pet['lift']:.2f}" if pet["lift"] != 1.0 else ""
        print(f"{pet['name']:24} {pet['w']:2}x{pet['h']:<2} at {pet['origin'][0]},{pet['origin'][1]}  "
              f"{len(pet['frames'])} frames, {len(pet['palette'])} colors{lift}, {cells / 1024:.1f} KB of cells")
        if args.verify:
            write_verify_png(pet, Path(args.verify) / f"{pet['name']}.png")
    print(f"Wrote {len(jobs)} grid file(s) to {out} ({total / 1024:.1f} KB of text)")


if __name__ == "__main__":
    main()
