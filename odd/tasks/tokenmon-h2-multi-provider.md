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
- [ ] T1 — Daemon providers package + Claude via `/api/oauth/usage` + Codex + Kimi + config + loop + tests (RED→GREEN). Route: delegated writer A.
- [ ] T2 — Firmware slots, RX queue, per-slot freshness, carousel, Fable bar, sim scenario. Route: delegated writer B (after T1 defines the payload contract; may run in parallel once contract is fixed in this document).
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
(pending)

## Next step
Wait for H1 commit, branch, launch writer A (daemon) and writer B (firmware) in parallel — disjoint edit surfaces.
