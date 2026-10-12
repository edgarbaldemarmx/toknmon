# TokenMon — H7 Full-screen provider scenes + gesture navigation

## Objective
1. Codex and Kimi get full-screen splash scenes (art that uses most of the 55×37 stage), authored by a Kimi K3 agent through the grid pipeline.
2. Navigation by gesture: on the splash a **tap** advances to the next animation of the active set; a **vertical swipe** moves between splash and the token meter (both directions); a **horizontal swipe** goes to the previous/next item (animation on the splash, provider on the meter). Long-press on the meter still opens mascot mode.

## Problem / Why
Custom art is corner-sized (≤ 28×21 cells ≈ 224×168 px) so full-size it leaves most of the panel black. Today a tap on the splash returns to the meter, so there is no way to browse animations without the PWR button.

## Scope
### Art (Kimi K3 agent, `assets/animations/` + regenerated `firmware/src/custom_animations.h`)
Splash-only scenes (not corner acts): size up to 55×37 cells, feet row 36, `origin` chosen so the art is centered on the stage; ≤ 15 colors; index 0 transparent; loops of 6–12 frames. Fixed names (the engine wires these; missing names are skipped at runtime):
- `codex.scene.wave` — a long row of dots (7–9) doing a travelling wave across the stage, the middle one with the face.
- `codex.scene.rain` — dots falling like rain and piling up into a bar that fills left→right.
- `kimi.scene.night` — big moon with a star field twinkling, a shooting star crossing every loop.
- `kimi.scene.orbit` — moon in the center with a star orbiting, moon eyes following it.
Each file must pass `node tools/convert_grid_animations.js` with no errors (size warnings about the mascot envelope are expected for scenes and acceptable) and look right in `--verify` strips.
### Firmware (writer)
- `splash.cpp`: `PROVIDER_SETS` include the scene names after the existing acts (`codex`: idle, dots, think, bike, scene.wave, scene.rain; `kimi`: idle, glow, sleep, bike, scene.night, scene.orbit); entries not found in the catalog are skipped. The provider label stays.
- `ui.cpp`: LVGL gesture handling (`LV_EVENT_GESTURE` + `lv_indev_get_gesture_dir`) on the splash root and the usage container: vertical swipe (up or down) toggles splash ↔ usage; horizontal swipe = next/prev (splash: animation within the active set — for the Claude default set use `splash_next`/a new `splash_prev`; usage: next/prev provider). Tap on the splash = next animation (parade included; the parade keeps rotating providers on its timer). Long-press on the usage screen unchanged (mascot mode). Alert overlay keeps precedence. Parade exits on a vertical swipe (back to meter), not on tap.
- `main.cpp`: serial `splash next|prev` and `swipe up|down|left|right` QA commands that call the same handlers.
- Sim: the SDL mouse already maps to touch, so swipes work with a drag; add nothing else.
### Docs
README controls table; CLAUDE.md gesture paragraph.

## Constraints
- Branch `feat/tokenmon-h7-big-scenes-gestures` from H6 (`404969c`).
- Two concurrent writers in the same tree: the Kimi agent owns `assets/animations/*` and `firmware/src/custom_animations.h` only (it runs the converter); the firmware writer never runs the converter and never edits those paths.
- LVGL gesture threshold defaults (`LV_INDEV_DEF_GESTURE_LIMIT` 50 px) are fine on 480 px; keep taps from being misread as swipes.
- No `#ifdef BOARD_*` in shared code.

## Delivery strategy
`ask-on-risk`. Forecast ~500 authored changed lines (firmware ~250, art data separate).

## Tasks
- [ ] T1 — Art: four scenes by the Kimi agent; converter clean; `--verify` strips reviewed. Route: the multiplexer `kimi` agent `animator`.
- [x] T2 — Firmware: gesture navigation, tap-advances-on-splash, scene wiring, serial QA. Route: delegated writer (one bounded writer: `splash.{cpp,h}`, `ui.{cpp,h}`, `main.cpp`, README, CLAUDE.md). Uncommitted; see evidence below.
- [ ] T3 — Verify: sim autoshots of each scene full-size (pending the art); hardware flash + `screen splash codex` + `splash next` ×N screenshots (done, firmware part); swipe tested by the user on the device (pending). Commit (pending).

## Verification
- `node --test tools/test/`; `node tools/convert_grid_animations.js` idempotent
- `pio run -d firmware -e sim` + autoshots (`SIM_SPLASH_PROVIDER=codex|kimi`)
- `pio run -d firmware -e waveshare_amoled_216` + flash + screenshots

## Verification evidence
### T2 firmware (2026-10-12, writer; scenes not yet in the catalog — `grep -c "scene\." firmware/src/custom_animations.h` → 0)
- `pio run -d firmware -e sim`: SUCCESS. `pio run -d firmware -e waveshare_amoled_216`: SUCCESS. `grep -rn "ifdef BOARD_" firmware/src/*.cpp firmware/src/*.h`: only the pre-existing `BOARD_HAS_PSRAM` guards.
- Sim autoshots (scratchpad `h7/`): `SIM_SPLASH_PROVIDER=codex` at 2 s = `codex.idle` with the Codex label, at 9 s = `codex.dots` (set advanced on completion); default boot splash at 3 s = Claude (magnifier). No regression.
- Hardware (AMOLED 2.16, `/dev/cu.usbmodem101`, flashed as "ToknMon Desk One"), serial → screenshot: `screen splash codex` → codex.idle (`hw-01`); `splash next` → `splash: -> codex.dots` (`hw-02`); `splash next` → `splash: -> codex.think` (`hw-03`, frame 0 is the shared idle pose, so the still looks like idle; the log names the act); `splash prev` → codex.dots (`hw-04`); `swipe up` → usage view, Codex (`hw-05`); `swipe left` → Kimi (`hw-06`); `swipe right` → Codex (`hw-07`); `swipe down` → default Claude splash (`hw-08`); `swipe left` on the splash → `splash: -> claude.bike` (`hw-09`); `screen usage` → ok.
- Missing-name skip: `screen splash codex` + `splash next` ×4 steps idle → dots → think → bike → idle, logging `splash: set entry 'codex.scene.wave' not in catalog; skipped` and the same for `codex.scene.rain` once each; `splash prev` from idle logs nothing new and lands on bike.
- LVGL 9.6.0 (`.pio/libdeps/sim/lvgl/src/indev/lv_indev.c`): a swipe emits `LV_EVENT_GESTURE` (bubbling to the screen object) and still ends with RELEASED → SHORT_CLICKED → CLICKED, so `ui.cpp` guards the tap/long-press handlers with `gesture_seen` (set in the gesture handler, cleared on the indev `LV_EVENT_PRESSED`). Real finger taps/swipes on the panel are not covered by the serial path: the user verifies them on the device.

## Next step
Wait for T1 (art) to land in `custom_animations.h`, rebuild + autoshot each scene (`SIM_SPLASH_PROVIDER=codex|kimi`), flash, user swipe test on the device, then commit T2 + T3.
