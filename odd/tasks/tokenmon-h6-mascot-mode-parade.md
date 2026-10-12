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
- [ ] T1 — Art: `codex.think`, `kimi.sleep` via the grid pipeline; `--verify` strips read clearly. Route: delegated writer.
- [ ] T2 — Engine: provider sets, `splash_set_provider`, parade rotation, provider label; serial QA commands. Route: same writer.
- [ ] T3 — UI: long-press → mascot mode; inactivity → parade; touch exits. Route: same writer.
- [ ] T4 — Verify: sim autoshots of Codex and Kimi full-size (idle/act/bike) and parade handoff; hardware flash + `screen splash codex` / `screen splash kimi` / `parade on` screenshots; commit. Route: writer self-verification + parent spot check.

## Verification
- `node --test tools/test/`, `node tools/convert_grid_animations.js` (idempotent)
- `pio run -d firmware -e sim` + autoshots; `pio run -d firmware -e waveshare_amoled_216`
- Hardware: flash, `screen splash codex` → screenshot; `screen splash kimi` → screenshot; `parade on` → two screenshots 25 s apart show different providers; `screen usage` to finish.

## Verification evidence
(pending)

## Next step
Launch writer.
