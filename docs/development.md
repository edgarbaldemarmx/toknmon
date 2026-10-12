# Development

How the repository is laid out, how to build and test each part, and how a
release is cut. `CLAUDE.md` is the deeper technical reference (pin maps, HAL,
gotchas, animation engine internals).

## Layout

```text
firmware/
  platformio.ini            one [env:...] per board + sim
  src/
    main.cpp                setup()/loop(), JSON parsing, serial QA commands, buttons, pairing gesture
    ui.{h,cpp}              meter + splash screens, carousel, gestures, mascot mode, parade, alerts
    splash.{h,cpp}          animation engine (60×60 stage), corner mascots, provider sets, parade
    ble.{h,cpp}             NimBLE peripheral: data service (RX queue) + HID keyboard, device name in NVS
    theme.h                 palettes per provider
    data.h                  UsageData slots
    splash_animations.h     generated: official Clawd set
    custom_animations.h     generated: Codex/Kimi grids
    font_*.c, icons.h, logo.h
    hal/                    board-agnostic interfaces
    boards/<name>/          one folder per board (display, touch, input, power, imu, caps)
    boards/sim/             SDL2 desktop simulator + Arduino shims
  sim/                      scenario.jsonl (dev), gallery.jsonl (docs captures)
daemon/
  claude_usage_daemon.py    macOS daemon (bleak); poll loop, config, BLE, HID fallback, stale-bond repair
  providers/                claude.py, codex.py, kimi.py, base.py (ProviderResult → payload)
  com.toknmon.daemon.plist  launchd template
  requirements-macos.txt
  tests/                    pytest suite (fixtures under tests/fixtures)
  attention-hook.sh         Claude Code hook that raises/clears attention alerts
  *_windows.py, *.sh, *.service   inherited Linux/Windows daemons (Claude-only, untested)
assets/
  animations/*.txt          custom animation sources (text grids)
  *.otf, *.ttf, *.png       font and icon sources
tools/
  convert_grid_animations.js   grids → custom_animations.h, --verify, --gif
  convert_official_clawd.js    official sources → splash_animations.h
  fetch_official_clawd.sh      downloads the official sources on demand
  make_gallery.sh              regenerates docs/media (sim captures + GIFs)
  png_to_lvgl.js               icon converter
  test/                        node --test suite + shell validator test
docs/
  install-macos.md, flashing.md, providers.md, controls.md, animations.md,
  troubleshooting.md, simulator.md, development.md, fonts.md
  porting/                  adding-a-board.md, hal-contract.md, capability-flags.md
  media/                    screenshots and GIFs used by the docs
  odd/                      design log: one feature document per milestone (H0–H8)
flash-mac.sh, install-mac.sh, screenshot.sh     macOS scripts
flash.sh, install.sh, install-windows.ps1       inherited Linux/Windows scripts
.github/workflows/ci.yml                        CI
```

## Toolchain

| Tool | Used for | Install |
| --- | --- | --- |
| PlatformIO CLI | firmware and simulator builds, flashing | `brew install platformio` or `pip install platformio` |
| SDL2 | desktop simulator | `brew install sdl2` / `apt install libsdl2-dev` |
| Python 3.10+ | daemon, tests | `python3 -m venv daemon/.venv && daemon/.venv/bin/pip install -r daemon/requirements-macos.txt` |
| Node 18+ | asset converters and their tests | `brew install node` |
| ImageMagick | PNG previews and GIF export (`--verify`, `--gif`, `make_gallery.sh`) | `brew install imagemagick` |
| pyserial | `screenshot.sh`, the naming step of `flash-mac.sh` (falls back to PlatformIO's Python) | optional |

## Build

```bash
pio run -d firmware -e waveshare_amoled_216            # target firmware → firmware/.pio/build/waveshare_amoled_216/firmware.bin
pio run -d firmware -e sim                             # desktop simulator → firmware/.pio/build/sim/program
pio run -d firmware -e waveshare_amoled_18             # any other env from platformio.ini (inherited, untested)
./flash-mac.sh waveshare_amoled_216 [port] --name "<Your name>"
```

Rules for shared firmware code: no `#ifdef BOARD_*` (use `BoardCaps` or a
per-board file), even-aligned flush regions, touch read only from the board's
`touch.cpp`. The twelve gotchas in `CLAUDE.md` are worth reading before
touching display or memory code.

## Simulator

```bash
pio run -d firmware -e sim && (cd firmware && .pio/build/sim/program)
```

The full firmware loop runs against SDL2 with scenario playback from
`firmware/sim/scenario.jsonl`; the mouse is the touch panel (drag to swipe),
keys drive buttons, battery and BLE state. Headless captures:

```bash
cd firmware
SDL_VIDEODRIVER=dummy SIM_AUTOSHOT_MS=6000 SIM_AUTOSHOT_PATH=shot.bmp .pio/build/sim/program
SDL_VIDEODRIVER=dummy SIM_AUTOSHOT_MS=9000 SIM_SPLASH_PROVIDER=codex .pio/build/sim/program
SDL_VIDEODRIVER=dummy SIM_AUTOSHOT_MS=31000 SIM_PARADE=1 SIM_SCENARIO=sim/gallery.jsonl .pio/build/sim/program
```

Full key map, scenario format and environment hooks:
[`simulator.md`](simulator.md). The sim renders with desktop LVGL and
synthetic data: panel-level behavior (column offsets, rotation, rounding)
only shows on hardware.

## Tests

```bash
daemon/.venv/bin/python -m pytest daemon/tests -q                 # ~240 tests: providers, detection, payloads, config, device name, alerts, migration
node --test tools/test/                                            # grid converter: parsing, validation, header bytes, GIF export
bash tools/test/shell/test_device_name_validator.sh                # the name validator shared by install-mac.sh / flash-mac.sh
node tools/convert_grid_animations.js && git diff --exit-code firmware/src/custom_animations.h   # generated header is current
```

Two pytest cases are Linux-only (subprocess tests for the inherited Windows
daemon) and skip on macOS. The GIF test skips with a message when ImageMagick
is absent. There is no unit-test runner for the firmware: UI changes are
verified with simulator autoshots and hardware screenshots.

## Serial QA on hardware

The firmware has a serial command set for hands-free checks (115200 baud):
`screen usage|splash [provider]`, `slot 0-2`, `next`, `splash next|prev`,
`swipe up|down|left|right`, `parade on|off`, `name [text]`, `screenshot`,
`buzz`. `./screenshot.sh out.png [port] [--screen usage|splash[:provider]]`
wraps the capture. The full table is in
[`controls.md`](controls.md#serial-qa-commands). Workflow for a UI change:
build, flash, `./screenshot.sh`, look at the PNG, iterate.

## Media and gallery

```bash
bash tools/make_gallery.sh                 # rebuild the sim, capture docs/media/screens/*.png, export docs/media/animations/*.gif
node tools/convert_grid_animations.js --gif docs/media/animations
./screenshot.sh docs/media/screens/hw-<name>.png [port]      # hardware shots are manual
```

Keep captures free of personal data (the gallery scenario is synthetic;
hardware shots must not show your device name or tokens). See
[`media/README.md`](media/README.md).

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | What it does |
| --- | --- |
| **Daemon tests (pytest)** | Ubuntu, Python 3.12, `pip install -r daemon/requirements-macos.txt`, `python -m pytest daemon/tests -q` |
| **Tools tests (node + shell)** | Node 20: `node --test tools/test/`, the shell validator test, and the converter idempotency check (`git diff --exit-code firmware/src/custom_animations.h`) |
| **Firmware sim (native, SDL2)** | installs `libsdl2-dev`, caches PlatformIO, `pio run -d firmware -e sim`, headless autoshot uploaded as an artifact |
| **Firmware waveshare_amoled_216** | `pio run -d firmware -e waveshare_amoled_216`, `firmware.bin` uploaded as an artifact |

Dependabot keeps the GitHub Actions versions current
(`.github/dependabot.yml`). Issue templates live in `.github/ISSUE_TEMPLATE/`.

## Conventions

- Conventional Commits, one reviewable work unit per commit, tests and docs
  with the behavior ([CONTRIBUTING](../CONTRIBUTING.md)).
- Feature work is planned and evidenced in `docs/odd/<feature>.md`; read the
  latest before resuming a milestone.
- Generated headers (`splash_animations.h`, `custom_animations.h`) are
  regenerated by the tools, never edited by hand.
- English everywhere; no tokens, personal emails, real device names or
  absolute home paths in committed files.
- Keep "Clawdmeter" only in attribution and in legacy-compatibility
  constants (NVS namespaces, `LEGACY_DEVICE_NAMES`, the legacy config dir).

## Release flow

1. Make sure the branch is green locally (tests above) and in CI.
2. Update `CHANGELOG.md`: move the `Unreleased` items under a new
   `## x.y.z — YYYY-MM-DD` heading and add the compare links at the bottom.
3. Commit (`chore(release): x.y.z`), tag `vx.y.z`, push the tag.
4. Create the GitHub release from the tag; attach
   `firmware/.pio/build/waveshare_amoled_216/firmware.bin` (the CI artifact of
   that commit is the same file) so users can flash without building.
5. Flash the release build on the verified board and run through
   [`controls.md`](controls.md) once before announcing.

Versions follow SemVer; the firmware and the daemon are released together
because the payload contract is shared.

## Further reading

- [`fonts.md`](fonts.md): regenerating the LVGL fonts (LVGL 9 patching).
- [`porting/adding-a-board.md`](porting/adding-a-board.md),
  [`porting/hal-contract.md`](porting/hal-contract.md),
  [`porting/capability-flags.md`](porting/capability-flags.md).
- [`tools/README.md`](../tools/README.md): every asset tool and its flags.
- [`odd/`](odd/): the milestone documents (H0 baseline → H8 publish) with the
  decisions and verification evidence behind each feature.
