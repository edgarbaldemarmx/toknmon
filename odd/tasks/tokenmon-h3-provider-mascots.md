# TokenMon — H3 Provider mascots (Codex dots, Kimi) + grid animation pipeline

## Objective
Each provider screen shows its own corner mascot: Clawd for Claude (unchanged), a "three dots" character for Codex, and a crescent-moon character for Kimi. New art is hand-authored as text grids and compiled into the existing animation format by a small converter, so H4 (mountain-bike variants) only adds files.

## Problem / Why
All mascot art comes from the official Clawd pipeline (`tools/convert_official_clawd.js`), which cannot be imported, fills enclosed holes with ink, and clusters colors — unsuitable for hand-drawn art. The engine looks animations up by name from a single generated table (`splash_anims[]`, `SPLASH_ANIM_COUNT`), and the corner mascot is hard-wired to Clawd names (`walking`, `lurking`, `MAS_ACTS_BY_RATE`).

## Scope
### Pipeline
- `assets/animations/<provider>.<role>.txt` authoring format (one file per animation): header `name`, `origin <x> <y>` (stage cell of grid col 0/row 0), `palette` legend (`.` = index 0 transparent; black ink must be a non-zero index such as `#141413`), default `hold`, `loop a-b` (inclusive), frames separated by `---` lines with optional `hold=<ms>`.
- `tools/convert_grid_animations.js` (pure Node, no deps): validates (≤15 colors + transparent, uniform frame size, `oy + h == 37`, warn on edge snap `ox == 0`/`ox + w == 55`, mascot-eligible ≤ 28×21 cells), crops to bounding box, emits `firmware/src/custom_animations.h` with `custom_<id>_{palette,frames,holds}`, `CUSTOM_ANIM_COUNT`, `custom_anims[]` (same `splash_anim_def_t`), plus `--verify DIR` PNG previews via ImageMagick. Emits a valid header with `CUSTOM_ANIM_COUNT 0` when there are no inputs.
### Engine
- `splash.cpp`: `anim_count()` / `anim_at(i)` spanning both tables; replace every direct `splash_anims[]` index (`resolve_group_lists`, `splash_mini_create`, `anim_by_name`, `splash_init`, `splash_tick`, `splash_next`, `splash_pick_for_current_rate`).
- Mascot spec per provider `{idle, walk, acts[], lurk}`; `splash_mascot_set_provider(slot)` called by the UI when the carousel changes slot. Null `walk` disables walk-off/lurk trips. `mas_buf` sized from the largest act across specs (remove the hard-coded 28×21 assumption or enforce it in the converter).
### Art (hand-authored, ≤ 24×16 cells, feet on stage row 36, idle inside stage x 15..38 / y 21..36)
- `codex.idle` (1 frame): three round dots in Codex green-teal, small eyes on the middle dot.
- `codex.dots` (6–8 frames, loop): the three dots bounce in a wave (the Codex CLI "thinking" dots).
- `kimi.idle` (1 frame): crescent moon character in Kimi blue with eyes.
- `kimi.glow` (6 frames, loop): the moon pulses/blinks with two small stars.
- Clawd keeps the official set.
### Out of scope
Bike variants (H4); full-splash per-provider scenes; replacing official Clawd art.

## Constraints
- Branch `feat/tokenmon-h3-provider-mascots` from H2.
- No `#ifdef BOARD_*` in shared code. C6 boards (no PSRAM) keep the static still; new mascots only on PSRAM boards — gate on existing `BOARD_HAS_PSRAM`-based paths already used by the mascot.
- Index 0 renders opaque black on the full splash but transparent on the corner mascot; art must never rely on index 0 for visible black.
- Flash: each animation ≈ 2–3 KB; current headroom ≈ 1.1 MB on the 2.16 env.

## Delivery strategy
`ask-on-risk`. Forecast ~700 authored changed lines (converter ~200, engine ~150, art files ~250, docs/tests ~100).

## Tasks
- [x] T1 — Converter + authoring format + a Node test (fixture grid → expected header bytes). Route: delegated writer. Evidence: `tools/convert_grid_animations.js` (parse → validate/crop → emit, `--verify DIR` via `magick`), `tools/test/convert_grid_animations.test.js` (8 tests: struct fields, header bytes, empty set, too many colors, uneven frames, feet rule, unknown char / loop range, edge-snap + mascot-envelope warnings). RED observed on the missing module, then GREEN 8/8.
- [x] T2 — Engine: dual-table registry, provider mascot spec, `splash_mascot_set_provider`, UI hook on carousel change. Route: same writer. Evidence: `anim_count()`/`anim_at()`/`anim_by_name()` replace every `splash_anims[]` index in `splash.cpp`; `MASCOT_SPECS[PROVIDER_COUNT]` `{idle, walk, gait, acts[4][4], lurk}` (Claude = previous behavior); `splash_mascot_set_provider()` called from `show_slot()`; `mas_buf` sized from the largest frame across specs and `mas_render()` takes a byte cap (skip + log once). Decision: trips are paused while the dense layout is active (`apply_usage_layout` → `splash_mascot_set_trips(!dense)`) — simpler than clamping the walk range, and the walk-off itself never crossed the panels; only the full-size lurk did.
- [x] T3 — Art: `codex.idle`, `codex.dots`, `kimi.idle`, `kimi.glow`; iterate in `sim` with autoshots until clean. Route: same writer. Evidence: `assets/animations/*.txt` (24×16 grids at `origin: 15 21`, crops 23×7 / 23×15 / 19×15 / 23×16, same `ox` 15 per provider), verify PNG strips and sim autoshots listed below. Docs done alongside: `CLAUDE.md` "Custom animations (grid pipeline)", README Development bullet.
- [ ] T4 — Build + flash + hardware screenshot; commit. (Parent: hardware verification + commit. Flash build passes, see below.)

## Verification
- `node tools/convert_grid_animations.js` (regenerates `custom_animations.h`; idempotent)
- `node --test tools/test/` (converter test)
- `pio run -d firmware -e sim` + autoshots per provider slot
- `pio run -d firmware -e waveshare_amoled_216` + flash + `screenshot.sh`

## Verification evidence
- `node --test tools/test/`: pass 8, fail 0 (RED first: module missing).
- `node tools/convert_grid_animations.js` ×3: identical md5 of `firmware/src/custom_animations.h` (idempotent); output `codex.dots 23x15 at 15,22 8 frames`, `codex.idle 23x7 at 15,30`, `kimi.glow 23x16 at 15,21 6 frames`, `kimi.idle 19x15 at 15,22`; no warnings.
- `node tools/convert_grid_animations.js --verify <scratch>/anim-verify`: PNG strips read as three bouncing dots with a face on the middle dot, and a crescent moon with eyes, glow ring, blink and two twinkling stars.
- `pio run -d firmware -e sim`: SUCCESS. Headless autoshots (temporary `SCREEN_USAGE` boot, reverted; `grep -rn QA-TEMP firmware/src` → 0 hits, `main.cpp` has no diff), scratch single-provider scenarios: `codex-10350.png` / `codex-10650.png` (dots mid-wave), `kimi-10350.png` / `kimi-10700.png` (moon + star), `claude-10500.png` / `claude-30000.png` (Fable dense layout, Clawd in the corner, third panel never covered).
- `pio run -d firmware -e waveshare_amoled_216`: SUCCESS, RAM 33.8%, Flash 65.2% (2180783 / 3342336 bytes).
- `grep -rn "ifdef BOARD_" firmware/src/*.cpp firmware/src/*.h`: only the three pre-existing `BOARD_HAS_PSRAM` hits.
- Pending: hardware flash + `screenshot.sh` (T4, parent).

## Next step
T4: flash the 2.16, screenshot each provider slot on hardware, commit (`feat(firmware): per-provider corner mascots + grid animation pipeline`).
