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
- [x] T1 — Author `claude.bike`, `codex.bike`, `kimi.bike`; `--verify` PNGs read clearly as a rider on a bike with turning wheels. Route: delegated writer (done; see evidence).
- [x] T2 — Wire as mascot acts + splash rotation; sim autoshots of each provider mid-pedal and of the splash bike scene. Route: same writer (done; see evidence).
- [ ] T3 — Hardware: flash, screenshot splash bike + a provider screen mid-act; commit. Route: verification worker.

## Verification
- `node --test tools/test/`, `node tools/convert_grid_animations.js` (idempotent)
- `pio run -d firmware -e sim` + autoshots
- `pio run -d firmware -e waveshare_amoled_216` + flash + `screenshot.sh`

## Verification evidence
T1/T2 (writer, worktree `feat/tokenmon-h4-mountain-bike` on c3c3260, uncommitted):
- Art: three grids, 25×21 crop at stage (15,16) — same `ox` 15 as every idle — 6 frames each (f0/f5 coast hold 400, f1–f4 pedal loop hold 110), 9 colors. Wheels are 11-cell: tire ring `#3A3A3A`, rim ring `#9A9A9A`, 4 spokes (`#6E6E6E`) with a light pair (`#E8E8E8`) stepping 45° per loop frame (`| / — \`, 180° period, so the 4-frame loop is seamless and the turning direction reads). Crank radius 2, 90° per frame (top/front/bottom/back), near leg over the frame, far leg in a darker tint behind it.
- Deviation: the bike metal (frame, fork, cranks) is ivory `#F9F8F4`, not `#141413` — on the full splash index 0 is opaque black and a `#141413` frame was invisible in the first render. Saddle/handlebar `#6E6E6E`, pedals/hub `#9A9A9A`.
- `node --test tools/test/`: 8 pass, 0 fail.
- `node tools/convert_grid_animations.js` ×2: no warnings; header identical after the second run (shasum equal); 7 animations, each bike 3.1 KB.
- `--verify` strips + a black-backdrop render (scratch) read as Clawd / the three dots / the moon riding a spoked bike.
- `pio run -e sim`: SUCCESS. Headless autoshots (temporary `SCREEN_USAGE` boot and a temporary bike-first idle group for Claude, both reverted; `git diff --stat firmware/src/main.cpp` empty): corner bike mid-pedal for Claude (~10.6 s), Codex and Kimi (~21.7 s, final wiring: bike is the second act of the idle group). Splash full-size `claude.bike` (temporary group-0 boot pick, reverted) at 1.5/1.7/1.9 s shows the wheels stepping.
- `pio run -e waveshare_amoled_216`: SUCCESS, RAM 33.9%, Flash 65.5% (2190595 / 3342336 bytes).
- `grep -rn "ifdef BOARD_" firmware/src/*.cpp firmware/src/*.h`: only the three pre-existing `BOARD_HAS_PSRAM`.
- Wiring: `GROUP_MAX` 4→6 (`claude.bike` in group 2; `codex.bike`, `kimi.bike` in group 3); `MAS_ACT_MAX` 4→5; Claude keeps its official acts and adds `claude.bike` to the normal/active/heavy groups; Codex/Kimi alternate dots/glow with the bike in every group. `splash_next` already walks the custom table, so the PWR button reaches all three.
- Scenario: "claude only again" dwell 6 s → 12 s; the rest already ≥ 12 s.
- Note: in the sim the rate group is always 0 (`MIN_WINDOW_MS` 240 s), so Claude's corner bike only shows on hardware once the pace is at least "normal".

## Next step
T3 (parent): flash `waveshare_amoled_216`, `screenshot.sh` the splash bike (PWR-cycle to it) and a provider screen mid-act, then commit the work unit.
