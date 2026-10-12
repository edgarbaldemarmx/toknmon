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
- [x] T1 — Art: four scenes by the Kimi agent; converter clean; `--verify` strips reviewed. Route: the multiplexer `kimi` agent `animator`. Landed in `e765a46`; see evidence below.
- [x] T2 — Firmware: gesture navigation, tap-advances-on-splash, scene wiring, serial QA. Route: delegated writer (one bounded writer: `splash.{cpp,h}`, `ui.{cpp,h}`, `main.cpp`, README, CLAUDE.md). Uncommitted; see evidence below.
- [ ] T3 — Verify: sim autoshots of each scene full-size (pending); hardware flash + `screen splash codex|kimi` + `splash next` ×N screenshots of all four scenes, parade and `swipe up` (done, hardware part, 2026-10-12 — see evidence below); **user finger swipes on the device (pending)**. Commit (pending).

## Verification
- `node --test tools/test/`; `node tools/convert_grid_animations.js` idempotent
- `pio run -d firmware -e sim` + autoshots (`SIM_SPLASH_PROVIDER=codex|kimi`)
- `pio run -d firmware -e waveshare_amoled_216` + flash + screenshots

## Verification evidence
### T1 art (2026-10-12, commit `e765a46`)
- Files: `assets/animations/codex.scene.wave.txt` (5.8 KB source), `codex.scene.rain.txt` (13.7 KB), `kimi.scene.night.txt` (18.4 KB), `kimi.scene.orbit.txt` (16.4 KB); `firmware/src/custom_animations.h` regenerated (13 animations).
- `node tools/convert_grid_animations.js` (re-run on the committed tree, exit 0, tree stays clean = idempotent):
  - `codex.scene.wave 53x11 at 1,26  9 frames, 5 colors, loop 0-8, 5.1 KB` (hold 120)
  - `codex.scene.rain 49x22 at 3,15  12 frames, 4 colors, loop 0-11, 12.6 KB` (hold 130)
  - `kimi.scene.night 53x36 at 1,1  9 frames, 5 colors, loop 0-8, 16.8 KB` (hold 140)
  - `kimi.scene.orbit 53x37 at 1,0  8 frames, 6 colors, loop 0-7, 15.3 KB` (hold 150)
  - Only the expected `exceeds the 28x21 mascot envelope; usable on the splash only` warning per scene; no errors.

### T3 hardware scenes (2026-10-12, AMOLED 2.16 on `/dev/cu.usbmodem101`, flashed from `e765a46` as "ToknMon Desk One", Flash 67.4 %, RAM 33.9 %)
- Daemon reconnected within the 70 s window: `BLE: packet p=claude ok=1`, `p=codex ok=1`, `p=kimi ok=1`.
- Serial path (pyserial, `dsrdtr=False, rtscts=False`): `screen splash codex` → `splash: -> codex.idle`; `splash next` ×5 logs `codex.dots → codex.think → codex.bike → codex.scene.wave → codex.scene.rain`, one more wraps to `codex.idle` (no "not in catalog" skip lines any more). `screen splash kimi` → `kimi.idle`; `splash next` ×5 → `kimi.glow → kimi.sleep → kimi.bike → kimi.scene.night → kimi.scene.orbit`, then `kimi.idle`.
- PNGs in scratchpad `h7/hw-scenes/` (480×480, taken ~1 s after the switch and ~3–4 s later; a `splash next` probe after each pair confirmed which scene was on screen):
  - `codex.scene.wave.png` / `-2.png`: nine teal dots in a row along the bottom (y ≈ 295–390, x ≈ 25–455), middle dot with the eyes, crest moves one dot to the right between shots. "Codex" label top-center untouched (art starts ~260 px below it). No corner clipping; the row leaves the upper ~60 % of the panel black (53×11 at oy 26, by design).
  - `codex.scene.rain.png` / `-2.png`: first shot shows the drops (plus-shaped) in a diagonal staircase on the left half with two flat drops mid-squash; second shot has an 8-segment bar filled from the left and four drops still falling on the right. Fits x ≈ 40–435, y ≈ 200–390; no clipping, no label overlap. Note: the fall reads as a diagonal shower rather than vertical rain.
  - `kimi.scene.night.png` / `-2.png`: big crescent (eyes closed, two vertical marks) centered, star field of blue dots and white plus-flares that changes between shots, shooting-star streak at the top-left moves left. Topmost stars at y ≈ 100, label at y ≈ 15–35: no overlap; edge stars (x ≈ 35 / 435) sit at mid-height, clear of the rounded corners.
  - `kimi.scene.orbit.png` / `-2.png`: round shaded moon centered; star at the upper-left (with a two-dot trail) in the first shot and at the right edge (x ≈ 415–450, mid-height) in the second, eyes shifted toward it. Whole glyphs, no clipping. Caveat: with the 1.2 s loop a capture at a fixed offset after the switch returns the same frame (three runs byte-identical) — the second offset had to differ to show motion.
  - `parade-on.png`: `parade on` → `ok`; parade opened on the Claude crab (default rate-group pick, no label), as designed.
  - `swipe-up-usage.png`: `swipe up` → `ok`; usage view for Codex (100 %, Weekly, dot grid, "Envisioning…"). Finished with `screen usage` → `ok`.
- Defects seen: none in the scenes or the gesture wiring. QA-tool observation: the `screenshot` raw dump stalled intermittently (3 of ~20 captures: 312920/460800, 2538/460800, 309685/460800 bytes, then the 10 s read timeout) while the daemon was pushing BLE packets; a retry succeeded every time. `screenshot.sh` also loops forever waiting for `SCREENSHOT_START` when the device keeps logging — had to kill the orphaned python holding the port once.
- Pending: real finger taps/swipes on the panel (serial `swipe`/`splash next` exercise the same handlers but not the LVGL indev gesture detection).

### T2 firmware (2026-10-12, writer; scenes not yet in the catalog — `grep -c "scene\." firmware/src/custom_animations.h` → 0)
- `pio run -d firmware -e sim`: SUCCESS. `pio run -d firmware -e waveshare_amoled_216`: SUCCESS. `grep -rn "ifdef BOARD_" firmware/src/*.cpp firmware/src/*.h`: only the pre-existing `BOARD_HAS_PSRAM` guards.
- Sim autoshots (scratchpad `h7/`): `SIM_SPLASH_PROVIDER=codex` at 2 s = `codex.idle` with the Codex label, at 9 s = `codex.dots` (set advanced on completion); default boot splash at 3 s = Claude (magnifier). No regression.
- Hardware (AMOLED 2.16, `/dev/cu.usbmodem101`, flashed as "ToknMon Desk One"), serial → screenshot: `screen splash codex` → codex.idle (`hw-01`); `splash next` → `splash: -> codex.dots` (`hw-02`); `splash next` → `splash: -> codex.think` (`hw-03`, frame 0 is the shared idle pose, so the still looks like idle; the log names the act); `splash prev` → codex.dots (`hw-04`); `swipe up` → usage view, Codex (`hw-05`); `swipe left` → Kimi (`hw-06`); `swipe right` → Codex (`hw-07`); `swipe down` → default Claude splash (`hw-08`); `swipe left` on the splash → `splash: -> claude.bike` (`hw-09`); `screen usage` → ok.
- Missing-name skip: `screen splash codex` + `splash next` ×4 steps idle → dots → think → bike → idle, logging `splash: set entry 'codex.scene.wave' not in catalog; skipped` and the same for `codex.scene.rain` once each; `splash prev` from idle logs nothing new and lands on bike.
- LVGL 9.6.0 (`.pio/libdeps/sim/lvgl/src/indev/lv_indev.c`): a swipe emits `LV_EVENT_GESTURE` (bubbling to the screen object) and still ends with RELEASED → SHORT_CLICKED → CLICKED, so `ui.cpp` guards the tap/long-press handlers with `gesture_seen` (set in the gesture handler, cleared on the indev `LV_EVENT_PRESSED`). Real finger taps/swipes on the panel are not covered by the serial path: the user verifies them on the device.

## Next step
User finger-swipe/tap test on the device (vertical swipe splash ↔ usage, horizontal swipe prev/next, tap advances on the splash, long-press still opens mascot mode); sim autoshots of the four scenes (`SIM_SPLASH_PROVIDER=codex|kimi`); then close T3 and commit.
