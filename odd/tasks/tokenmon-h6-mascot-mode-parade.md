# TokenMon — H6 Mascot mode (per provider) + ambient parade

## Objective
1. **Mascot mode**: long-pressing a provider's usage screen opens the full-size splash playing *that provider's* animation set (idle → acts → bike), cycling automatically; tap returns to usage.
2. **Ambient parade**: after a period without touch, the device plays the full-size mascots of every fresh provider in turn (Claude official scenes, Codex, Kimi); any touch returns to the usage screen.
3. One extra act per custom mascot so full-size sets do not feel repetitive: `codex.think` (slow wave, dots dim/brighten) and `kimi.sleep` (moon closes its eyes, "z" particles).

## Problem / Why
The splash is Claude-only: animations are picked by Claude's usage-rate group and the PWR button walks the whole catalog with no provider notion. Codex and Kimi art exists full-size but is unreachable in a meaningful way.

## Scope
### Firmware
- `splash.{h,cpp}`: provider play-lists `SPLASH_SETS[PROVIDER_COUNT]` — Claude keeps the rate-group behavior unchanged; Codex/Kimi lists are explicit name arrays (`codex.idle`, `codex.dots`, `codex.think`, `codex.bike`; `kimi.idle`, `kimi.glow`, `kimi.sleep`, `kimi.bike`). `splash_set_provider(int slot)` switches the active set; the scene timer (`SCENE_LOOP_MS`) advances within the set; `splash_next` (PWR) advances within the active set. Small provider label at the top in the provider accent (hidden for Claude to keep the official look).
- Parade mode: `splash_parade(bool on, const bool fresh[PROVIDER_COUNT])` rotates providers every `PARADE_PROVIDER_MS` (20 s) through fresh slots, each playing its set; exits on any touch/button.
- `ui.{h,cpp}`: long-press on the usage screen → `splash_set_provider(visible_slot)` then show splash; inactivity timer `IDLE_PARADE_MS` (5 min, constant) started on the usage screen, reset by any touch/button/alert; on expiry → parade with the fresh-slot mask; touch on the splash → usage (existing).
- `main.cpp` serial QA: `screen splash [claude|codex|kimi]` (mascot mode for that provider), `parade on|off`.
- Sim scenario: no change needed; QA via serial-less path: `SIM_SPLASH_PROVIDER=codex` env in `ble_sim.cpp`/sim board (optional) or the headless swap trick.
### Art
- `assets/animations/codex.think.txt` (8 frames, slow wave with brightness steps), `assets/animations/kimi.sleep.txt` (6 frames, eyes closed + rising "z" sparks). Same crop/`ox` rules as H3 (≤ 28×21, left edge consistent with the idle).
### Out of scope
Reactive animations by usage state; provider-aware attention mascot (H7).

## Constraints
- Branch `feat/tokenmon-h6-mascot-mode-parade` from H5 (`3fbeb54`).
- No `#ifdef BOARD_*` in shared code; C6 boards (no PSRAM) keep today's behavior (static still) — gate on the existing `BOARD_HAS_PSRAM` pattern.
- Keep Claude's official splash behavior byte-for-byte when no provider is selected (boot path unchanged).
- Any touch exits parade/mascot mode to the usage screen; PWR still cycles within the active set.

## Delivery strategy
`ask-on-risk`. Forecast ~600 authored changed lines (engine ~300, UI ~120, art ~180).

## Tasks
- [x] T1 — Art: `codex.think` (8 frames, bright pulse then dim pulse across the dots, hold 180) and `kimi.sleep` (6 frames, eyes closed, two 4x4 "z" glyphs rising and fading, hold 250) via the grid pipeline; `--verify` strips read clearly (the first 3x3 "z" read as an "I" and was replaced). Route: delegated writer (trigger: 2+ non-trivial files, art + engine + UI).
- [x] T2 — Engine: `PROVIDER_SETS`, `splash_set_provider`, set playback at completion, `splash_next` within the set, rate pick no-op, `styrene_20` provider label, `splash_parade_start/stop/is_parade` with `PARADE_PROVIDER_MS` 20 s; serial `screen splash [claude|codex|kimi]`, `parade on|off`; `screenshot.sh --screen splash:<provider>`; sim `SIM_SPLASH_PROVIDER`, `SIM_PARADE` (ble_sim.cpp, documented in board.h). Route: same writer.
- [x] T3 — UI: long-press → `ui_show_mascot(visible_slot)`; `ui_show_screen()` resets provider and stops the parade on non-splash screens; `IDLE_PARADE_MS` 5 min `lv_timer`, reset by indev `LV_EVENT_PRESSED` and `ui_note_activity()` from the three button handlers in main.cpp; `ui_parade_start()` builds the fresh mask. Route: same writer.
- [x] T4 — Verify: sim autoshots (Codex and Kimi idle/dots-glow/think-sleep/bike, parade Claude → Codex → Kimi → Claude, default splash unchanged, inactivity path with a temporarily shortened timer, reverted); hardware flash + `screen splash codex` ×2 / `screen splash kimi` / `parade on` ×2 screenshots. Commit: pending (parent). Route: writer self-verification + parent spot check.

## Verification
- `node --test tools/test/`, `node tools/convert_grid_animations.js` (idempotent)
- `pio run -d firmware -e sim` + autoshots; `pio run -d firmware -e waveshare_amoled_216`
- Hardware: flash, `screen splash codex` → screenshot; `screen splash kimi` → screenshot; `parade on` → two screenshots 25 s apart show different providers; `screen usage` to finish.

## Verification evidence
Scratch: `<scratchpad>/h6/` (PNGs listed below are relative to it).
- `node --test tools/test/`: 8 tests, 8 pass, 0 fail.
- `node tools/convert_grid_animations.js` ×3: `custom_animations.h` md5 unchanged across runs (idempotent); `--verify`: `verify/codex_think.png`, `verify/kimi_sleep.png` read as intended.
- `pio run -e sim`: SUCCESS. Autoshots (`sim/`): `codex-{2000,9000,16000,23000}.png` = idle, dots wave, think (dim pulse), bike with teal "Codex" label; `kimi-{2000,9000,16000,23000}.png` = idle, glow, sleep (z), bike with blue "Kimi" label; `parade-5000.png` Claude (pointing, no label) → `parade-25000.png` Codex → `parade-45000.png` Kimi → `parade-65000.png` Claude walking; `default-3000.png` = official magnifier (boot pick unchanged). `idle-parade-27000.png`: with `IDLE_PARADE_MS` temporarily 5 s and boot on usage, the parade had started and handed off to Codex by 27 s (edits reverted, sim rebuilt).
- `pio run -e waveshare_amoled_216`: SUCCESS, RAM 33.9%, Flash 65.8% (2199239 bytes).
- Hardware (`/dev/cu.usbmodem101`, flashed as "ToknMon Desk One", live data at 41 s): `hw-codex-splash.png` (idle), `hw-codex-splash-2.png` (+8 s, dots wave), `hw-kimi-splash.png` (idle), `hw-parade-1.png` (Claude magnifier), `hw-parade-3.png` (+30 s, Codex, with a three-provider payload batch landing at 21 s mid-parade). Labels sit top-center clear of the art; battery icon hidden on the splash as before. Finished on `screen usage`.
- Anomaly: one earlier parade run came back on the usage screen within 25 s with no serial evidence (no alert line, no command); not reproduced on the rerun. The only firmware paths to usage from the parade are a splash touch or a daemon alert, so a touch on the device is the likely cause. Two parade screenshot transfers also stalled once (serial, transient) and succeeded on retry.
- `grep -rn "ifdef BOARD_" firmware/src/*.cpp firmware/src/*.h`: only `BOARD_HAS_PSRAM`.

## Next step
Parent spot check, then the work-unit commit (writer did not commit).
