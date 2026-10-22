"""Tests for tools/convert_pet_spritesheet.py.

Run with `daemon/.venv/bin/python -m pytest tools/test -q`. The converter is
exercised through its CLI (`python -I convert_pet_spritesheet.py ...`) on
synthetic 1536x1872 sheets built here, so no OpenAI artwork is needed.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

TOOLS = Path(__file__).resolve().parents[1]
SCRIPT = TOOLS / "convert_pet_spritesheet.py"
sys.path.insert(0, str(TOOLS))
import convert_pet_spritesheet as conv  # noqa: E402

SHEET_W, SHEET_H = 1536, 1872
CELL_W, CELL_H = 192, 208
ROW_FRAMES = [6, 8, 8, 4, 5, 8, 6, 6, 6]
STAGE_W, STAGE_H = 55, 37


def cell_color(row, col):
    """A distinct opaque colour per occupied cell (geometry oracle)."""
    return (20 + row * 25, 30 + col * 28, 200 - row * 15, 255)


def make_sheet(path, body=(40, 160, 200), gradient=False):
    """A sheet in the pets layout: one blob per occupied cell.

    Every blob shares the same body rectangle so the global bounding box is
    stable; a small marker in the top-left corner carries cell_color(row, col)
    so a slice can be traced back to its cell. With `gradient` the body is a
    many-colour ramp that forces the quantizer to work.
    """
    img = Image.new("RGBA", (SHEET_W, SHEET_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for r, n in enumerate(ROW_FRAMES):
        for c in range(n):
            x0, y0 = c * CELL_W, r * CELL_H
            # body: 150 wide x 180 tall (real pets are ~150-180 x 196), feet 8 px up
            bx0, by0, bx1, by1 = x0 + 21, y0 + 20, x0 + 171, y0 + 200
            if gradient:
                for i in range(by0, by1):
                    t = (i - by0) * 255 // (by1 - by0 - 1)
                    d.line([(bx0, i), (bx1 - 1, i)], fill=(t, 255 - t, (t * 7) % 256, 255))
            else:
                d.rectangle([bx0, by0, bx1 - 1, by1 - 1], fill=body + (255,))
            d.rectangle([bx0, by0, bx0 + 23, by0 + 23], fill=cell_color(r, c))
    img.save(path, lossless=True)      # lossy WebP would shift the oracle colours
    return path


def run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def parse_grid(text):
    """Minimal reader of our grid format: header fields, legend, frames."""
    name = origin = loop = None
    legend = {}
    frames, cur, holds = [], [], []
    default_hold = 120
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^---(?:\s+hold=(\d+))?(?:\s+#.*)?$", s)
        if m:
            if cur:
                frames.append(cur)
                cur = []
            holds.append(int(m.group(1)) if m.group(1) else default_hold)
            continue
        m = re.match(r"^(\S)\s*=\s*(transparent|#[0-9A-Fa-f]{6})$", s)
        if m:
            legend[m.group(1)] = m.group(2)
            continue
        m = re.match(r"^([a-z_]+):\s*(.*)$", s)
        if m and not cur and m.group(1) in ("name", "origin", "palette", "hold", "loop"):
            k, v = m.groups()
            if k == "name":
                name = v
            elif k == "origin":
                origin = tuple(int(t) for t in v.split())
            elif k == "hold":
                default_hold = int(v)
            elif k == "loop":
                loop = tuple(int(t) for t in v.split("-"))
            continue
        cur.append(s)
    if cur:
        frames.append(cur)
    if len(holds) < len(frames):          # frame 0 without an opening separator
        holds.insert(0, default_hold)
    return dict(name=name, origin=origin, legend=legend, frames=frames, holds=holds, loop=loop)


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    d = tmp_path_factory.mktemp("src")
    make_sheet(d / "alpha-spritesheet.webp")
    make_sheet(d / "beta-spritesheet.webp", body=(200, 60, 60), gradient=True)
    return d


# ── geometry ────────────────────────────────────────────────────────────────

def test_slice_rows_follows_the_8x9_grid_of_192x208_cells(src):
    sheet = Image.open(src / "alpha-spritesheet.webp").convert("RGBA")
    rows = conv.slice_rows(sheet)
    assert [name for name, _ in conv.ROW_ANIMS] == list(rows)
    for (name, count), (row_index, frames) in zip(conv.ROW_ANIMS, enumerate(rows.values())):
        assert len(frames) == count == ROW_FRAMES[row_index]
        for col, frame in enumerate(frames):
            assert frame.size == (CELL_W, CELL_H)
            # the marker sits at (36..59, 20..43) inside the cell
            assert frame.getpixel((40, 24)) == cell_color(row_index, col)


def test_slice_rows_rejects_a_sheet_with_the_wrong_size():
    with pytest.raises(ValueError, match="1536x1872"):
        conv.slice_rows(Image.new("RGBA", (1536, 1000)))


# ── end-to-end: one grid file per pet ───────────────────────────────────────

def test_grid_file_shape_palette_and_feet_row(src, tmp_path):
    out = tmp_path / "out"
    res = run("--src", src, "--out", out)
    assert res.returncode == 0, res.stderr
    for pet in ("alpha", "beta"):
        text = (out / f"codex.pet-{pet}.txt").read_text()
        g = parse_grid(text)
        assert g["name"] == f"codex.pet-{pet}"
        # idle 6 (looped, 330 ms) + waving 4 + jumping 5 + happy 6 at 90 ms
        assert len(g["frames"]) == 21
        assert g["loop"] == (0, 5)
        assert g["holds"] == [330] * 6 + [90] * 15
        # palette: exactly one transparent entry, at most 15 colours
        values = list(g["legend"].values())
        assert values.count("transparent") == 1
        assert 1 <= len(values) - 1 <= 15
        # uniform frames, pet 26-32 wide and <= 34 tall, centred, feet on row 36
        h = len(g["frames"][0])
        w = len(g["frames"][0][0])
        assert all(len(f) == h and all(len(r) == w for r in f) for f in g["frames"])
        assert 26 <= w <= 32 and h <= 34
        ox, oy = g["origin"]
        assert oy + h == STAGE_H
        assert abs(ox + w / 2 - STAGE_W / 2) <= 1
        # the bottom row carries ink in at least one frame (no empty feet row)
        assert any(set(f[-1]) - {"."} for f in g["frames"])
        # no visible cell darker than #141413 (index 0 is opaque black)
        for v in values:
            if v != "transparent":
                rgb = tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
                assert max(rgb) >= 0x13


def test_output_is_byte_identical_between_runs(src, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert run("--src", src, "--out", a).returncode == 0
    assert run("--src", src, "--out", b).returncode == 0
    for f in sorted(a.iterdir()):
        assert f.read_bytes() == (b / f.name).read_bytes(), f.name


def test_pets_filter_selects_sheets_and_rejects_unknown(src, tmp_path):
    out = tmp_path / "out"
    res = run("--src", src, "--out", out, "--pets", "beta")
    assert res.returncode == 0, res.stderr
    assert sorted(p.name for p in out.iterdir()) == ["codex.pet-beta.txt"]
    res = run("--src", src, "--out", tmp_path / "none", "--pets", "gamma")
    assert res.returncode != 0
    assert "gamma" in res.stderr


# ── corner icon mode (--icon PET → codex.icon.txt) ──────────────────────────

def test_icon_mode_renders_the_idle_row_into_the_corner_envelope(src, tmp_path):
    out = tmp_path / "out"
    res = run("--src", src, "--out", out, "--icon", "alpha")
    assert res.returncode == 0, res.stderr
    # only the icon is written: no pet clip unless --pets asks for one
    assert sorted(p.name for p in out.iterdir()) == ["codex.icon.txt"]
    g = parse_grid((out / "codex.icon.txt").read_text())
    assert g["name"] == "codex.icon"          # MASCOT_SPECS keeps resolving it
    # the six idle frames, each held as a calm idle, looped over all of them
    assert len(g["frames"]) == 6
    assert g["holds"] == [330] * 6
    assert g["loop"] == (0, 5)
    # uniform frames inside the 28x21 mascot envelope, at most 24 wide
    h = len(g["frames"][0])
    w = len(g["frames"][0][0])
    assert all(len(f) == h and all(len(r) == w for r in f) for f in g["frames"])
    assert 1 <= w <= 24 and 1 <= h <= 21
    # feet on stage row 36, off the stage edges (no edge-snap warning)
    ox, oy = g["origin"]
    assert oy + h == STAGE_H
    assert 0 < ox and ox + w < STAGE_W
    assert any(set(f[-1]) - {"."} for f in g["frames"])
    # palette: one transparent entry, <= 15 colours, nothing darker than the ink
    values = list(g["legend"].values())
    assert values.count("transparent") == 1
    assert 1 <= len(values) - 1 <= 15
    for v in values:
        if v != "transparent":
            rgb = tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
            assert max(rgb) >= 0x13


def test_icon_mode_is_deterministic_and_combines_with_pets(src, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert run("--src", src, "--out", a, "--icon", "beta", "--pets", "alpha").returncode == 0
    assert run("--src", src, "--out", b, "--icon", "beta", "--pets", "alpha").returncode == 0
    assert sorted(p.name for p in a.iterdir()) == ["codex.icon.txt", "codex.pet-alpha.txt"]
    for f in sorted(a.iterdir()):
        assert f.read_bytes() == (b / f.name).read_bytes(), f.name
    res = run("--src", src, "--out", tmp_path / "none", "--icon", "gamma")
    assert res.returncode != 0
    assert "gamma" in res.stderr


def test_verify_writes_one_png_strip_per_pet(src, tmp_path):
    out, verify = tmp_path / "out", tmp_path / "verify"
    res = run("--src", src, "--out", out, "--pets", "alpha", "--verify", verify)
    assert res.returncode == 0, res.stderr
    strips = sorted(verify.iterdir())
    assert [p.name for p in strips] == ["codex.pet-alpha.png"]
    with Image.open(strips[0]) as im:
        assert im.size[0] > im.size[1]      # frames laid out side by side
