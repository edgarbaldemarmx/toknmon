# TokenMon — H2 Multi-provider (Claude + Codex + Kimi, carousel)

## Objective
The resident macOS daemon polls three providers and pushes one BLE payload per provider; the device keeps one usage slot per provider and shows them as a carousel (one provider per screen, tap cycles, auto-rotate). The Claude screen also shows the Fable weekly bar when the subscription exposes it.

## Problem / Why
Upstream has no provider concept: one `UsageData`, one payload per poll, global freshness. Codex and Kimi have no data source in the repo. Claude's current source (1-token Haiku probe + rate-limit headers) cannot see the Fable window and depends on a hard-coded, already-rejected User-Agent.

## Scope
### Daemon (`daemon/`)
- `providers/` package: `ProviderResult(id, bars[(label, pct, reset_mins)], status, ok, extra)` + `to_payload()` mapping bars → `s/sr`, `w/wr`, `f/fr`, adding `"p": id`. Importable both as `daemon.providers` (tests) and `providers` (launchd runs the file as a script).
- `providers/claude.py`: `GET https://api.anthropic.com/api/oauth/usage` with Bearer token (existing keychain/credentials path) and `anthropic-beta: oauth-2025-04-20`; map `limits[]`: `kind==session` → bar 0, `kind==weekly_all` → bar 1, `kind==weekly_scoped` (any `scope.model`) → bar 2 (label from `scope.model.display_name`). Keep `poll_api`/`PlanSelector`/`poll_active` as module attributes for existing tests; Enterprise path keeps using the old header probe.
- `providers/codex.py`: newest `payload.rate_limits` line in `${CODEX_HOME:-~/.codex}/sessions/**/rollout-*.jsonl` modified in last 7 days; `primary`/`secondary` → `used_percent`, `window_minutes`, `resets_at` (epoch s); bars labelled by window (300 → "5h", 10080 → "Weekly"); expired reset → 0%.
- `providers/kimi.py`: `GET ${KIMI_CODE_BASE_URL:-https://api.kimi.com/coding/v1}/usages`, Bearer = freshest non-expired `access_token` in `~/.kimi-code/credentials/*.json`; `usages.limit_5h`, `usages.limit_7d` → `used_ratio`×100, `reset_time` ISO → minutes.
- Config key `providers = claude, codex, kimi` (default `claude` only → identical behavior to upstream). Poll loop writes one payload per enabled provider with a short gap (≥0.3 s); `c/b/m/x` ride only on Claude; `t/tf` on all.
- Tests: fixtures for each provider (JSON samples), payload mapping, config parsing, failure → `{"p":id,"ok":false}`.

### Firmware (`firmware/src/`)
- `data.h`: `fable_pct`, `fable_reset_mins`, `has_fable`, `slot`/provider id.
- `main.cpp`: `slots[3]`; `parse_json` maps `p` (missing/"claude"→0, "codex"→1, "kimi"→2), parses `f/fr`; `usage_rate_sample` + reset chime fed by slot 0 only.
- `ble.cpp`: RX becomes a small queue (3-deep) so back-to-back writes are not lost.
- `ui.cpp`: per-slot freshness; `render_slot(i)`; carousel timer (8 s) + tap advances when >1 slot fresh (long-press goes to splash); provider name + accent color in title area; optional third bar "Fable" on slot 0 (dense layout at 480 h). `theme.h`: accent colors for Codex and Kimi.
- `firmware/sim/scenario.jsonl`: add `p` lines (`hold_ms: 0` for back-to-back) so the carousel is visible in the sim.

### Out of scope
New mascots (H3/H4); Linux/Windows daemons; Kimi monthly limits.

## Constraints
- Branch `feat/tokenmon-h2-multi-provider` from H1.
- No `#ifdef BOARD_*` in shared code. Payload per provider must stay ≤ 180 bytes.
- Keep upstream tests green; new behavior is additive and backward compatible with `p`-less payloads.

## Delivery strategy
`ask-on-risk`. Forecast ~900 authored changed lines across two work units (daemon, firmware). Exceeds 400 → chain strategy decision deferred to the user; both units land as separate commits on the same feature branch.

## Tasks
- [x] T1 — Daemon providers package + Claude via `/api/oauth/usage` + Codex + Kimi + config + loop + tests (RED→GREEN). Route: delegated writer A. Done (uncommitted; see "Daemon evidence"). Commit pending.
- [x] T2 — Firmware slots, RX queue, per-slot freshness, carousel, Fable bar, sim scenario. Route: delegated writer B (ran in parallel with T1 on the fixed payload contract). Done 2026-10-12: sim + 2.16 hardware verified, not yet committed (see Firmware evidence).
- [ ] T3 — Integration: flash board, run the repo daemon manually (stop the upstream launchd daemon from `~/Downloads/Clawdmeter` during the test, restore after), observe all three providers on device via `screenshot.sh`. Route: verification worker.
- [ ] T4 — Docs (README providers section) + commits.

## Payload contract (fixed)
```
{"p":"claude","s":17,"sr":110,"w":73,"wr":860,"f":1,"fr":860,"st":"allowed","acct":"pro","ok":true,"c":1,"t":...,"tf":24}
{"p":"codex","s":12,"sr":240,"w":40,"wr":5000,"st":"allowed","ok":true,"t":...,"tf":24}
{"p":"kimi","s":3,"sr":200,"w":9,"wr":6000,"st":"allowed","ok":true,"t":...,"tf":24}
{"p":"kimi","ok":false}
```
`f/fr` optional (only when a scoped weekly limit exists). Missing `p` ⇒ claude.

## Verification
- `daemon/.venv/bin/python -m pytest daemon/tests -q`
- `pio run -d firmware -e sim` + headless autoshot with the new scenario
- `pio run -d firmware -e waveshare_amoled_216`, flash, `screenshot.sh` for each carousel slot

## Verification evidence

### Daemon evidence (T1, writer A, 2026-10-12)
- RED: `daemon/.venv/bin/python -m pytest daemon/tests/test_providers_*.py -q` → 4 collection errors (`daemon.providers` missing) before implementation.
- GREEN: `daemon/.venv/bin/python -m pytest daemon/tests -q` → `184 passed, 2 skipped` (baseline 137 passed, 2 skipped; +47 new across `test_providers_{claude,codex,kimi,payload}.py`). The 2 skips and 2 `Event.wait` warnings are pre-existing (Windows tests).
- `bash -n install-mac.sh` → OK.
- Script-mode import (launchd path, `daemon/` as cwd): `providers` resolves as a sibling package; `PROVIDERS = {claude, codex, kimi}`, `TokenExpired` is `providers.claude.TokenExpired`.
- Live read-only smoke (no BLE, no launchd, real local sources):
  - claude: `{"p":"claude","s":30,"sr":83,"w":76,"wr":833,"f":6,"fr":833,"st":"allowed","acct":"pro","ok":true}`; full `poll_api` adds `"c":1` from the real config. Fable bar present (f=6).
  - codex: `{"p":"codex","s":0,"sr":0,"w":48,"wr":9454,"st":"allowed","ok":true}` — this plan (`plan_type: prolite`) reports only the 10080-minute window as `primary` with `secondary: null`, so the 5h bar is 0/0.
  - kimi: `{"p":"kimi","ok":false}` — both `~/.kimi-code/credentials/*.json` have `expires_at` in the past (1790961004 and 1787961124 < now); no request is made without a live token. Re-login with the Kimi CLI to exercise the live path.
- Files: `daemon/providers/{__init__,base,claude,codex,kimi}.py`, `daemon/claude_usage_daemon.py` (poll_api → usage endpoint with header-probe fallback as `poll_api_headers`; `read_providers`, `collect_payloads`, tagged `Sending[<id>]` writes, 0.35 s inter-write gap), `daemon/config.example`, `install-mac.sh` (`configure_providers`), `README.md` ("Providers" section), tests + fixtures.

### Firmware evidence (T2, writer B, 2026-10-12)
- Test-first exception: no runnable firmware unit-test runner exists (PlatformIO `sim` is a playback simulator, not a test env); verification is build + headless autoshots + hardware screenshot/serial.
- `~/.platformio/penv/bin/pio run -d firmware -e sim 2>&1 | tail -3` → `sim SUCCESS`, no warnings.
- Headless autoshots (`SDL_VIDEODRIVER=dummy SIM_AUTOSHOT_MS=<ms>`, boot temporarily switched to `SCREEN_USAGE`, reverted afterwards; `grep QA-TEMP firmware/src` → none): t=5000 legacy p-less Claude, 2 panels, title "Claude" in accent; t=29000 Claude with 3 bars (Current / Weekly / Fable, dense layout, status line clear); t=34000 Codex (green pill beside the clock); t=42000 Kimi (blue pill); t=50000 Kimi `ok:false` dropped out → Codex shown; t=62000 Claude without `f` → 2-panel layout restored. Sim log shows the three `hold_ms:0` lines drained in one pass (`BLE: packet p=claude … +third`, `p=codex`, `p=kimi`).
- Found + fixed while QA'ing: the "Period" pill (enterprise) never reverted to "Weekly" on pro payloads (pre-existing upstream bug, visible across providers).
- `~/.platformio/penv/bin/pio run -d firmware -e waveshare_amoled_216 2>&1 | tail -3` → SUCCESS, RAM 33.8%, Flash 65.1% (2174291 / 3342336 bytes).
- Hardware (`./flash-mac.sh waveshare_amoled_216 /dev/cu.usbmodem214201 --name "ToknMon Desk One"`) → upload OK, `board> BLE: name=ToknMon Desk One`. With the upstream launchd daemon still sending p-less payloads: serial `BLE: packet p=claude ok=1 s=30.0%` (poll + heartbeat, twice in 70 s); `./screenshot.sh` → Claude screen, 30% / 76%, title "Claude" (no `t` from the upstream daemon → no clock, no pill). Final (splash-boot) binary reflashed; boot log: `BLE: name=ToknMon Desk One` → `owner loaded` → `advertising start=OK` → `connected from fc:b2:…` → `auth complete bonded=1 enc=1` → `req_char onSubscribe` → `BLE: packet p=claude ok=1 s=30.0%`.
- `grep -rn "ifdef BOARD_" firmware/src/*.cpp firmware/src/*.h` → 3 hits, all `BOARD_HAS_PSRAM`, identical to HEAD (nothing new).
- Not verified: 368×448 and 240×240 dense breakpoints (values derived arithmetically, no sim profile for them); 12-hour clock + pill width; real multi-provider BLE traffic on hardware (T3).

## Next step
Wait for H1 commit, branch, launch writer A (daemon) and writer B (firmware) in parallel — disjoint edit surfaces.
