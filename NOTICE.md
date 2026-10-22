# Notices and attribution

ToknMon is a personal open-source project by Edgar Ramos. The project's own
code and original art are released under the MIT License (see `LICENSE`).
This file lists what ToknMon is built on and which bundled assets are **not**
covered by that license.

## Derived from Clawdmeter

ToknMon is a fork of [Clawdmeter](https://github.com/HermannBjorgvin/Clawdmeter)
by Hermann Bjorgvin: a single-provider Claude Code usage monitor for Waveshare
ESP32 boards. The firmware architecture (HAL, per-board folders, LVGL UI,
splash engine, BLE data + HID services), the desktop simulator, the board
ports, the asset converters and the original macOS/Linux/Windows daemons all
come from that project. The macOS host pieces of Clawdmeter were contributed
upstream by Chris Davidson ([@lorddavidson](https://github.com/lorddavidson)).

Upstream publishes no license file. ToknMon's MIT license applies to the
changes made in this fork and to the files authored here; it cannot grant
rights to upstream code that its author did not grant. The fork keeps the
upstream credits in `CLAUDE.md`, `README.md` and the per-board hardware notes.

## Third-party assets bundled WITHOUT a license

The following files are the property of Anthropic, PBC and are used here
without a license, in the same posture as upstream Clawdmeter. They are
included so the device looks the way it does; **you must evaluate your own
exposure before redistributing this repository or firmware built from it.**

| Asset | Where | Owner |
| --- | --- | --- |
| Clawd mascot animations (17 official poses and scenes, converted to indexed pixel frames) | `firmware/src/splash_animations.h`, `firmware/src/clawd_still.h` | Anthropic |
| Tiempos Text (generated LVGL bitmap fonts) | `firmware/src/font_tiempos_*.c`, `assets/TiemposText-400-Regular.otf` | Klim Type Foundry, licensed to Anthropic |
| Styrene B (generated LVGL bitmap fonts) | `firmware/src/font_styrene_*.c`, `assets/StyreneB-Regular.otf` | Commercial Type, licensed to Anthropic |
| Claude Code logo | `assets/Claude Code Logo.png`, `firmware/src/logo.h` | Anthropic |

The source GIF/Lottie files for the Clawd animations are **not** committed;
`tools/fetch_official_clawd.sh` downloads them on demand from claude.ai into a
git-ignored directory, and only the generated header ships.

The following files are the property of OpenAI and are used here without a
license, in the same posture as the Clawd set above. They will be removed on
request from the rights holder.

| Asset | Where | Owner |
| --- | --- | --- |
| ChatGPT pet artwork (the eight pets Bsod, Codex, Dewey, Fireball, Null Signal, Rocky, Seedy and Stacky; idle, waving, jumping and happy rows converted to indexed pixel frames) | `assets/animations/codex.pet-*.txt`, the generated `firmware/src/custom_animations.h` | OpenAI |

The pet sprite sheets are **not** committed; `tools/fetch_codex_pets.sh`
downloads them on demand from [Petmeter](https://github.com/nathanjohnpayne/Petmeter)'s
`research/codex-pets/` archive into a git-ignored directory, and
`tools/convert_pet_spritesheet.py` writes the committed grids. No license
is granted for the pet artwork by this repository.

## Original art in this repository

The Codex, Kimi and Grok mascots and scenes (`assets/animations/codex.*.txt`
except the `codex.pet-*` grids listed above,
`assets/animations/kimi.*.txt`, `assets/animations/grok.*.txt`, their entries in the generated `firmware/src/custom_animations.h`
and the GIF previews under `docs/media/animations/`) are original pixel art
created for ToknMon. They are **not** official brand assets of OpenAI,
Moonshot AI or xAI; the names "Codex", "Kimi" and "Grok" belong to their respective owners
and are used only to identify the monitored services. The Clawd mountain-bike
grid (`assets/animations/claude.bike.txt`) is an original drawing in the style
of Anthropic's mascot and is subject to the same caution as the official set.

## Third-party software

Firmware (PlatformIO, see `firmware/platformio.ini`):

| Library | License |
| --- | --- |
| [LVGL](https://github.com/lvgl/lvgl) 9 | MIT |
| [NimBLE-Arduino](https://github.com/h2zero/NimBLE-Arduino) | Apache-2.0 |
| [ArduinoJson](https://arduinojson.org/) | MIT |
| [GFX Library for Arduino](https://github.com/moononournation/Arduino_GFX) | see the upstream repository (the PlatformIO package ships no license file) |
| [XPowersLib](https://github.com/lewisxhe/XPowersLib) | MIT |
| [SensorLib](https://github.com/lewisxhe/SensorLib) | MIT |
| [pioarduino platform-espressif32](https://github.com/pioarduino/platform-espressif32) (Arduino core 3.x) | Apache-2.0 |
| [Lucide](https://lucide.dev) icons (bluetooth, battery, plug glyphs) | ISC |
| DejaVu Sans Mono (`assets/DejaVuSansMono.ttf`, generated mono fonts) | Bitstream Vera / DejaVu license |

Host daemon (Python, `daemon/requirements-macos.txt`):

| Package | License |
| --- | --- |
| [bleak](https://github.com/hbldh/bleak) | MIT |
| [httpx](https://www.python-httpx.org/) | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | HPND |
| [pytest](https://pytest.org/) | MIT |

Tools: Node.js (no runtime dependencies), ImageMagick (external, for previews
and GIF export), [blueutil](https://github.com/toy/blueutil) (optional, MIT).

## Hardware

The verified target is the Waveshare ESP32-S3-Touch-AMOLED-2.16. Pin maps and
bring-up notes for every board under `firmware/src/boards/` were documented by
the Clawdmeter project and its contributors.
