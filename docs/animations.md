# Animations

Two catalogs feed the splash engine (`firmware/src/splash.cpp`) and the
corner mascots:

| Catalog | Source | Generated header | Redistributed? |
| --- | --- | --- | --- |
| **Official Clawd set** (17 animations: core poses and persona scenes) | Anthropic's GIF/Lottie assets, fetched on demand | `firmware/src/splash_animations.h` | the header ships; the sources are not committed (see `NOTICE.md`) |
| **Custom grid animations** (16: Codex, Kimi and Grok mascots, scenes, the four bikes) | hand-authored text grids in `assets/animations/` | `firmware/src/custom_animations.h` | yes, original art (MIT) |

Both headers are generated: do not hand-edit them. The engine treats the two
tables as one catalog (`anim_count()` / `anim_at()`), so a custom animation
can be used anywhere an official one can. Previews of every custom animation
are in [`media/README.md`](media/README.md).

## Official Clawd set

```bash
bash tools/fetch_official_clawd.sh [DEST_DIR]        # download sources → research/clawd-official/ (git-ignored)
node tools/convert_official_clawd.js                  # → firmware/src/splash_animations.h
node tools/convert_official_clawd.js --verify DIR     # + one PNG per animation to eyeball
node tools/convert_official_clawd.js --src DIR        # sources fetched elsewhere
```

Needs ImageMagick. Frames are bounding-box crops on the official 55×37 art
stage, one byte per cell into a ≤16-color palette per animation (index 0 is
the background), with per-frame holds and a detected loop region (gait
cycles, scene middles). The converter also inks the eyes, applies two
contrast recolors and locates the sailing scene's loop. `CLAUDE.md` ("Splash
animations") has the provenance notes and how new seasonal drops are found.
You only need this pipeline when adding or re-converting official
animations; the committed header is current.

## Custom grid animations

### Format

One file per animation, `assets/animations/<provider>.<role>.txt`:

```text
# comments start with #
name: codex.dots
origin: 15 21            # stage cell of grid column 0 / row 0 (55×37 stage)
palette:
. = transparent          # exactly one transparent entry
k = #141413              # visible black must be a real color (index 0 is not drawable)
g = #10A37F
hold: 120                # default ms per frame
loop: 1-6                # inclusive frame range the engine loops

........gggg........
.......gkggkg.......
---                      # frame separator
--- hold=400             # per-frame hold override, optional trailing # comment
........gggg........
```

Rules the converter enforces (errors):

- feet on stage row 36: `origin_y + height == 37`
- uniform frame size, every grid character declared in the palette
- at most 15 colors plus the transparent entry
- `loop` inside the frame range

Warnings: art snapped to the stage edge (`ox == 0` or `ox + w == 55`) and art
larger than the **28×21-cell mascot envelope** (fine for splash-only scenes,
unusable as a corner mascot).

Two things to keep in mind:

- **Index 0 is opaque black on the full splash but transparent on the corner
  mascot.** Use `#141413` for visible ink; the bikes use ivory metal because a
  dark frame vanished on the splash. A large dark body needs a visible color
  and an outline: the Grok orb's core is slate `#2B2F36` inside a violet rim,
  because `#141413` would read as a hole on the black panel.
- **Keep idle and act files of one mascot at the same left edge (`origin_x`)
  and the same crop height.** The corner mascot is bottom-left anchored and
  ignores `origin`, so a different crop would make the character jump
  between idle and act.

### Converter

```bash
node tools/convert_grid_animations.js                 # assets/animations/*.txt → firmware/src/custom_animations.h
node tools/convert_grid_animations.js --verify DIR    # + one PNG frame strip per animation (ImageMagick)
node tools/convert_grid_animations.js --gif DIR       # + one looping GIF per animation, ×6 scale, per-frame delays (ImageMagick)
node --test tools/test/                               # converter unit tests
```

The converter is pure Node (no dependencies) and deterministic: running it
twice yields a byte-identical header, which CI checks. It prints one line per
animation (`codex.dots 23x15 at 15,22 8 frames, 5 colors, loop 1-6, 2.1 KB`).
Each corner-sized animation costs 2–3 KB of flash, a full-screen scene
12–17 KB; the 2.16 build has well over 1 MB free.

### Wiring an animation into the firmware

Everything is looked up **by name** in `firmware/src/splash.cpp`:

| Where | What it controls |
| --- | --- |
| `MASCOT_SPECS[provider]` | the corner mascot: `idle`, optional walk gait, `acts[]` per usage-rate group, `lurk`. Codex, Kimi and Grok have no walk gait, so they act in place. |
| `PROVIDER_SETS[provider]` | the mascot-mode play-list (idle, acts, bike, scenes) used by long-press, the parade and `screen splash <provider>`. A name missing from the catalog is skipped and logged once. |
| `GROUP_NAMES` | the mood groups the default Claude splash picks from by usage rate (`claude.bike` lives in the busy groups). |

Adding a new act for an existing provider is: write the grid, run the
converter, append the name to the provider's `acts`/set, rebuild. Adding a
provider mascot also needs a slot in `MASCOT_SPECS` and a palette in
`theme.h` ([`providers.md`](providers.md#adding-a-provider)).

### Preview without hardware

```bash
pio run -d firmware -e sim
cd firmware && SIM_SPLASH_PROVIDER=codex .pio/build/sim/program          # mascot mode for Codex
SDL_VIDEODRIVER=dummy SIM_AUTOSHOT_MS=9000 SIM_SPLASH_PROVIDER=kimi \
  SIM_AUTOSHOT_PATH=kimi.bmp .pio/build/sim/program                       # headless capture at 9 s
```

The set advances every 6 s of loop, so time your capture (`SIM_AUTOSHOT_MS`)
to land on the entry you want; `splash next` is unavailable in the sim
(no serial input), but a tap or horizontal swipe with the mouse steps it.
On hardware: `./screenshot.sh out.png [port] --screen splash:codex` then
`splash next` over serial ([`controls.md`](controls.md#serial-qa-commands)).

### Regenerating the gallery

```bash
bash tools/make_gallery.sh                                            # sim screens + GIFs (builds the sim first)
SKIP_BUILD=1 bash tools/make_gallery.sh                               # reuse the existing sim binary
node tools/convert_grid_animations.js --gif docs/media/animations    # GIFs only
```

Outputs land in `docs/media/`; see [`media/README.md`](media/README.md) for
the file list and which captures vary by frame phase between runs.

## Authoring with an AI agent

The four full-screen scenes (`codex.scene.wave`, `codex.scene.rain`,
`kimi.scene.night`, `kimi.scene.orbit`) were drawn by an AI coding agent
(Kimi K3, driven through a terminal multiplexer) using nothing but the text-grid
format above. The workflow works with any agent that can run shell commands:

1. Give the agent the **format section of this page** and one existing file
   (for example `assets/animations/kimi.glow.txt`) as a concrete example.
2. State the **constraints**: the fixed name the firmware expects, scene size
   up to 55×37 cells with feet on row 36 (or ≤ 28×21 for a corner act at the
   same `origin_x` as the idle), ≤ 15 colors, index 0 transparent, 6–12
   frames, a loop range, the palette hex values of the provider.
3. Describe the motion in one or two sentences ("a long row of dots doing a
   travelling wave, the middle one with the face").
4. Ask the agent to run `node tools/convert_grid_animations.js` until it
   exits clean and `--verify DIR` for strips, and to describe what the strips
   show. Review the PNG strips yourself; iterate on the description.
5. Wire the name into `PROVIDER_SETS` (scenes) or a mascot's `acts` (corner
   acts), check in the sim, then on hardware.

Keep the agent's edit surface to `assets/animations/` and the generated
header; the engine wiring is a human change. Only original art, please: the
converter cannot import existing images, and the repository must stay free of
assets you cannot redistribute.
