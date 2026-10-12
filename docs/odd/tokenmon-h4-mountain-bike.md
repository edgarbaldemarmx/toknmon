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
- [x] T3 — Hardware: flash, screenshot splash bike + a provider screen mid-act; commit. Route: verification worker (done on `1513865`, 2026-10-12; see "T3 hardware evidence"). Commit is the parent's; the splash bike could not be reached from serial (PWR-only, see below).

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

### T3 hardware evidence (verification worker on `1513865`, 2026-10-12; PNGs in `<scratchpad>/final/`)
- Full checks: `daemon/.venv/bin/python -m pytest daemon/tests -q` → `200 passed, 2 skipped`; `node --test tools/test/` → `pass 8, fail 0`; `bash tools/test/shell/test_device_name_validator.sh` → `All device-name validator tests passed.`; `node tools/convert_grid_animations.js && git status --short firmware/src/custom_animations.h` → 7 animations written, status empty (idempotent with the committed header).
- `PATH=~/.platformio/penv/bin:$PATH ./flash-mac.sh waveshare_amoled_216 /dev/cu.usbmodem214201 --name "ToknMon Desk One"` → `waveshare_amoled_216 SUCCESS 00:00:26.972`, RAM 33.9%, Flash 65.6% (2191171 / 3342336), `board> BLE: name set to "ToknMon Desk One", restarting`. Serial `name` → `BLE: name=ToknMon Desk One`.
- Multi-provider on hardware: upstream launchd daemon stopped, config temporarily extended with `providers = claude, codex, kimi`, repo daemon run through a temporary launchd agent. Log: `Sending[claude]: {"p":"claude","s":48,"sr":31,"w":81,"wr":781,"f":13,"fr":781,"st":"allowed","acct":"pro","ok":true,"c":1}`, `Sending[codex]: {"p":"codex","s":0,"sr":0,"w":54,"wr":9401,"st":"allowed","ok":true}`, `Provider kimi: no data (no valid token)` → `Sending[kimi]: {"p":"kimi","ok":false}` (expected: Kimi tokens expired on this machine).
- Serial QA replies: `screen usage` → `ok`; `slot 0` → `ok`; `slot 1` → `ok`; `slot 2` → `err slot not fresh` (Kimi ok:false); `next` (on Codex, 2 fresh slots) → `ok` and paged to Claude; `screen splash` → `ok`.
- `claude.png`: Claude usage screen, three bars (48% Current / 81% Weekly / 13% Fable), orange Clawd idle in the corner, "Elucidating…" status line; no overlap or clipping. `next.png`: same screen after `next` from Codex ("Actioning…"). `codex.png`: Codex screen, green "Codex" title, two panels (0% Current "Resets in 0m", 54% Weekly "Resets in 6d 12h"), three green dots idle in the corner, "Perusing…".
- `codex-act.png` (+ `codex-act-corners-sheet.png`): `codex.dots` act caught mid-play on hardware — the three dots bouncing in a wave (frames at 10.8 s, 25.3 s, 27.5 s, 53.9 s of a 60 s capture loop that re-pinned `slot 1` every ~2 s). Caught via a scratch pyserial loop (`burst.py`) because the 8 s carousel dwell is shorter than the 10 s rate-group-0 still; the mascot idle timer survives slot swaps, so acts fire on whichever slot is visible. The bike act did not come up in the window (rate group 0 alternates `codex.dots` / `codex.bike`; four act frames were all dots).
- `splash.png`: splash after `screen splash` shows the official idle Clawd. The bike splash scenes live in busy groups 2–3 (`GROUP_NAMES`) and the PWR button cannot be pressed from serial, so the full-size splash bike is verified by the T2 sim autoshots only, not on hardware.
- Environment restored: test agent removed, config restored (`diff` identical), `com.user.claude-usage-daemon` re-bootstrapped and `Connected` / `Sending` within 5 s; board left on the splash.
- Not verified on hardware: full-size splash bike (PWR-only), `claude.bike` / `codex.bike` corner acts (need a busy rate group or luck in the act rotation).

## Next step
Parent: review the T3 evidence; no further hardware step. Delivery (push / PR) stays the user's decision.
