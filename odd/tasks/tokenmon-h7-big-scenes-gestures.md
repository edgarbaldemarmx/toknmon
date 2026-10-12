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
- [ ] T2 — Firmware: gesture navigation, tap-advances-on-splash, scene wiring, serial QA. Route: delegated writer.
- [ ] T3 — Verify: sim autoshots of each scene full-size; hardware flash + `screen splash codex` + `splash next` ×N screenshots; swipe tested by the user on the device. Commit.

## Verification
- `node --test tools/test/`; `node tools/convert_grid_animations.js` idempotent
- `pio run -d firmware -e sim` + autoshots (`SIM_SPLASH_PROVIDER=codex|kimi`)
- `pio run -d firmware -e waveshare_amoled_216` + flash + screenshots

## Verification evidence
(pending)

## Next step
Start the Kimi agent (art) and the firmware writer in parallel.
