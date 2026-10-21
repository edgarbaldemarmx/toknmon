# Desktop simulator (`-e sim`)

The native desktop simulator runs the full firmware loop in an SDL2 window
standing in for the 480×480 AMOLED — `main.cpp`, `ui.cpp`, `splash.cpp`, idle
fade, pair gesture, JSON parsing, and usage-rate/chime logic all run
unmodified. Only `ble.cpp`/`chime.cpp` are swapped for stubs. Sources live in
`firmware/src/boards/sim/` (HAL against SDL2 + Arduino shims in `shim/`), with
scenario data in `firmware/sim/`.

This is the fastest way to work on ToknMon's UI without a board: the meter,
the carousel, mascot mode, the parade and the gestures all behave as on
hardware ([`controls.md`](controls.md)). `tools/make_gallery.sh` uses the
headless hooks below to produce the screenshots in
[`media/README.md`](media/README.md); the rest of the developer workflow is in
[`development.md`](development.md).

## Build & run

```bash
sudo apt install libsdl2-dev        # one-time (macOS: brew install sdl2)
pio run -d firmware -e sim
cd firmware && .pio/build/sim/program
```

Launch from the `firmware/` directory — the default scenario path
(`sim/scenario.jsonl`) is resolved relative to it.

## Controls

| Key | Action |
|---|---|
| mouse / left-drag | touch (tap toggles splash ↔ usage) |
| `space` | play/pause scenario playback |
| `←` / `→` | step one scenario state (pauses playback) |
| `1`–`9` | jump to scenario state N (pauses playback) |
| `d` | toggle BLE connected/disconnected |
| `b` (hold) | PRIMARY button (BOOT — HID Space PTT on hardware) |
| `n` (hold) | SECONDARY button (HID Shift+Tab on hardware) |
| `p` | PWR button (short press; hold ~3s + release = pair gesture) |
| `c` | toggle charging |
| `u` | toggle no battery / USB power only (shows the plug-zap icon) |
| `-` / `=` | battery down / up 5% |
| `s` | save screenshot BMP to the current directory |
| `esc` / window close | quit |

Full, authoritative map: `firmware/src/boards/sim/board.h`.

## Scenarios

`firmware/sim/scenario.jsonl` plays in a loop — one JSON object per line, the
daemon payload plus two optional keys:

- `"name"` — shown in the window title
- `"hold_ms"` — time on this state (default 3000)

Lines starting with `#` are comments. Every other line is one daemon payload
exactly as the host daemon would write it over BLE: the quota fields (`s`,
`sr`, `w`, `wr`, `st`, `ok`, `t`, `tf`, …) plus `p` for the provider
(`claude` when absent, `codex`, `kimi`, `grok`) so multi-provider scenarios can fill
several carousel slots. The sim's `ble_sim.cpp` hands each line to the same
JSON parser the firmware uses on hardware; there is no separate session
channel.

Override the scenario file with `SIM_SCENARIO=<path>`. If the file is missing,
a small built-in state list is used.

## Environment variables

| Variable | Effect |
|---|---|
| `SIM_SCENARIO=<path>` | scenario file to play instead of `sim/scenario.jsonl` |
| `SIM_AUTOSHOT_MS=<ms>` | headless hook: save a screenshot after `<ms>` and exit |
| `SIM_AUTOSHOT_PATH=<file>` | where the autoshot BMP goes (default `sim-autoshot.bmp`) |
| `SIM_SPLASH_PROVIDER=claude\|codex\|kimi\|grok` | open mascot mode for that provider once the first payloads land (same as serial `screen splash <p>`) |
| `SIM_PARADE=1` | start the ambient parade once a fresh slot exists (same as serial `parade on`); pair it with a multi-provider scenario |
| `SIM_SLOT=0-3` | start with that usage slot picked (0 Claude, 1 Codex, 2 Kimi, 3 Grok), as if the user had swiped to it before a reboot; the carousel never moves on its own |
| `SIM_NO_BATTERY=1` | start in "USB power only" mode (plug-zap icon) |
| `SDL_VIDEODRIVER=dummy` | SDL's own switch: render off-screen, for CI and headless captures |

## Headless screenshots (CI-friendly)

```bash
SDL_VIDEODRIVER=dummy SIM_AUTOSHOT_MS=6000 .pio/build/sim/program
SDL_VIDEODRIVER=dummy SIM_AUTOSHOT_MS=8000 SIM_SPLASH_PROVIDER=codex \
  SIM_AUTOSHOT_PATH=/tmp/mascot-codex.bmp .pio/build/sim/program
```

Saves `sim-autoshot.bmp` (override with `SIM_AUTOSHOT_PATH`) after the given
delay and exits. Combine with `SIM_SCENARIO` pointing at a single-state file,
or with `SIM_SLOT` / `SIM_SPLASH_PROVIDER` / `SIM_PARADE`, to capture any specific screen.
`*.bmp` and `sim-autoshot*` are git-ignored; `tools/make_gallery.sh` uses
these hooks to regenerate the screenshots under `docs/media/`.

## Caveat

The sim mirrors the S3 2.16 geometry but renders with desktop LVGL and fake
data. It's ideal for iterating UI layouts, but panel-level behavior — column
offsets, rotation, flush rounding — lives in the hardware board folders, so
always do a final check on real hardware before merging panel-related changes.
