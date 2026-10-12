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
- [ ] T1 — Converter + authoring format + a Node test (fixture grid → expected header bytes). Route: delegated writer.
- [ ] T2 — Engine: dual-table registry, provider mascot spec, `splash_mascot_set_provider`, UI hook on carousel change. Route: same writer.
- [ ] T3 — Art: `codex.idle`, `codex.dots`, `kimi.idle`, `kimi.glow`; iterate in `sim` with autoshots until clean. Route: same writer.
- [ ] T4 — Build + flash + hardware screenshot; docs (`CLAUDE.md` section "Custom animations", README); commit.

## Verification
- `node tools/convert_grid_animations.js` (regenerates `custom_animations.h`; idempotent)
- `node --test tools/` (converter test)
- `pio run -d firmware -e sim` + autoshots per provider slot
- `pio run -d firmware -e waveshare_amoled_216` + flash + `screenshot.sh`

## Verification evidence
(pending)

## Next step
Branch from H2 once committed; launch writer.
