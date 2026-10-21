# Asset tools

## Splash animations (official Clawd set)

```bash
bash fetch_official_clawd.sh                 # download the sources (once; git-ignored)
node convert_official_clawd.js               # → firmware/src/splash_animations.h
node convert_official_clawd.js --verify /tmp/verify   # + per-animation PNGs
node convert_official_clawd.js --src /path/to/sources # sources elsewhere
```

The official Anthropic Clawd GIFs and Lottie exports are not committed to this
repository (they are Anthropic's assets); `fetch_official_clawd.sh` downloads
them on demand into `research/clawd-official/` (git-ignored; pass a directory
to put them elsewhere) and probes claude.ai for new seasonal names. The
generated `firmware/src/splash_animations.h` *is* committed, so you only need
this pipeline when adding or re-converting animations.

`convert_official_clawd.js` reads the sources from `--src DIR` (default
`research/clawd-official`; GIFs decoded via ImageMagick, the Laptop and
Soccer Lottie exports read directly) and writes a single
`firmware/src/splash_animations.h`:

- frames as bounding-box crops on the shared 55×37 art stage, one byte per
  cell into a per-animation ≤16-color RGB565 palette (index 0 = background)
- per-frame hold in ms, with consecutive duplicate frames collapsed
- a detected loop region per animation (gait cycles, scene middles) that the
  engine can hold or release for walk-to-target and timed scenes
- the eyes — transparent holes in the source GIFs — inked as `#141413`
- contrast recolors (trumpet notes → ivory, magnifier fedora → gray) and the
  sailing-loop cross-match that defines the sailing scene's loop window

See `CLAUDE.md` ("Splash animations") for asset provenance and the format
details; `--out FILE` overrides the output path. Rebuild firmware after
running.

## Custom animations (grid pipeline)

```bash
node convert_grid_animations.js              # assets/animations/*.txt → firmware/src/custom_animations.h
node convert_grid_animations.js --verify DIR # + one PNG frame strip per animation
node convert_grid_animations.js --gif DIR    # + one looping GIF per animation (×6 scale, per-frame holds; ImageMagick)
node --test test/                            # converter unit tests
bash test/shell/test_device_name_validator.sh   # install-mac.sh / flash-mac.sh name validator
```

Hand-authored provider mascots (Codex, Kimi, Grok) live as text grids under
`assets/animations/`; the format and rules are documented in
`docs/animations.md` and `CLAUDE.md` ("Custom animations"). `--gif` writes
`<name>.gif` per animation, byte-deterministic between runs; the committed
previews are under `docs/media/animations/`.

## Gallery (docs/media)

```bash
bash make_gallery.sh                         # build the sim, capture docs/media/screens/*.png, export docs/media/animations/*.gif
SKIP_BUILD=1 bash make_gallery.sh            # reuse the existing sim binary
```

`make_gallery.sh` plays `firmware/sim/gallery.jsonl` headless
(`SDL_VIDEODRIVER=dummy`, one `SIM_AUTOSHOT_MS` capture per screen, PNGs
stripped of date chunks) and then runs the GIF export. Needs PlatformIO,
SDL2, ImageMagick and Node 18+. Hardware shots (`docs/media/screens/hw-*.png`)
are taken manually with `./screenshot.sh`. See `docs/media/README.md`.

`fetch_official_clawd.sh [DEST_DIR]` (above) takes an optional destination
directory; the default `research/clawd-official/` is git-ignored.

## Icons

```bash
node png_to_lvgl.js input.png symbol_name [W_MACRO] [H_MACRO] [--tint=RRGGBB | --no-tint]
```

Converts an alpha PNG to an LVGL RGB565A8 C array. Default tint is white —
Lucide PNGs ship black-on-transparent and would render invisible without it.
Paste the output into `firmware/src/icons.h`.
