# TokenMon — H4 Mountain-bike animations (Clawd, Codex, Kimi)

## Objective
Each provider mascot gets a mountain-bike riding animation: a looping pedaling cycle with rotating wheels, playable as a corner-mascot act on the provider's screen and as a full-size splash animation.

## Problem / Why
The user wants a shared visual identity across the three providers ("each one on a mountain bike"). H3 delivered the grid authoring pipeline and the per-provider mascot spec; H4 only adds art files and wires them in.

## Scope
- Art (`assets/animations/`): `claude.bike`, `codex.bike`, `kimi.bike` — each 6–8 frames, loop over the pedaling frames, bookend coast frames; wheels with 4 visible spokes rotating 45° per frame, rider silhouette matching the H3 idle art (Clawd body colors from the official palette `#D97757` body / `#141413` ink; Codex `#10A37F`; Kimi `#3B6CF6`), frame `#141413` ink, tires dark gray `#3A3A3A` (non-zero index). Mascot-eligible size: ≤ 28×21 cells, feet (tires) on stage row 36, `origin` inside stage x 13..40.
- Engine: add `<provider>.bike` to each provider's act list in the mascot spec (so it plays as a rate-scaled act) and register the three bike animations in the splash rotation (`splash_next` cycles them with the PWR button; `GROUP_NAMES` gets a bike entry in the "busy" groups if `GROUP_MAX` allows, else extend `GROUP_MAX`).
- Sim scenario: no change needed beyond H3.
- Docs: README gallery line; `CLAUDE.md` note.

## Constraints
- Branch `feat/tokenmon-h4-mountain-bike` from H3.
- Same pipeline rules as H3 (no index 0 for visible black; ≤15 colors; converter validations).
- Splash walkers are hard-coded to `walking`/`crab walking`; bikes are stationary loops (background does not scroll) — out of scope to add a scrolling ground.

## Delivery strategy
`ask-on-risk`. Forecast ~450 authored changed lines (mostly art grids).

## Tasks
- [ ] T1 — Author `claude.bike`, `codex.bike`, `kimi.bike`; `--verify` PNGs read clearly as a rider on a bike with turning wheels. Route: delegated writer.
- [ ] T2 — Wire as mascot acts + splash rotation; sim autoshots of each provider mid-pedal and of the splash bike scene. Route: same writer.
- [ ] T3 — Hardware: flash, screenshot splash bike + a provider screen mid-act; commit. Route: verification worker.

## Verification
- `node --test tools/test/`, `node tools/convert_grid_animations.js` (idempotent)
- `pio run -d firmware -e sim` + autoshots
- `pio run -d firmware -e waveshare_amoled_216` + flash + `screenshot.sh`

## Verification evidence
(pending)

## Next step
Branch from H3 once committed; launch writer.
