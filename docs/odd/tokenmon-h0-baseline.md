# TokenMon — H0 Baseline

## Objective
Get the upstream Clawdmeter stack building and running end to end on this Mac and on the Waveshare ESP32-S3 Touch AMOLED 2.16 board, so later milestones (custom BLE name, multi-provider Claude/Codex/Kimi, new mascots) start from a verified baseline.

## Problem / Why
The fork's roadmap (H1–H4) changes firmware, protocol and daemon. Without a known-good build, flash and data path, every later failure is ambiguous. H0 also answers one open question: whether the Anthropic rate-limit headers expose a Fable-specific window.

## Scope
- Toolchain: ImageMagick installed (asset converter dependency).
- Firmware: `sim` env builds and renders; `waveshare_amoled_216` env builds and flashes to the connected board.
- Daemon: venv created, one real poll against the API, raw `anthropic-ratelimit-*` headers captured for the Fable question.
- Out of scope: any feature change (name, providers, animations), launchd install, GitHub fork creation.

## Constraints
- Branch: `feat/tokenmon-h0-baseline` off `main` (clean tree at `1f446fd`).
- RDD switch: off (global) — ordinary checks only.
- Board port: `/dev/cu.usbmodem214201`.
- Pairing in System Settings and permission dialogs require the user; defer to next session.

## Delivery strategy
`ask-on-risk`. Forecast authored changed lines: < 50 (docs/notes only). No PR slicing needed.

## Tasks
- [x] T1 — Install ImageMagick via Homebrew. Route: inline (bash state). Evidence: `brew install imagemagick` exit 0.
- [x] T2 — Build `sim` env + headless autoshot. Route: delegated verification worker. Evidence: `pio run -d firmware -e sim` succeeded (15.7 s); autoshot BMP 480×480 produced, splash mascot rendered.
- [x] T3 — Build `waveshare_amoled_216`. Route: delegated verification worker. Evidence: succeeded (61 s); RAM 32.8% (107584/327680), Flash 64.9% (2169731/3342336) → ~1.1 MB headroom for new animations.
- [x] T4 — Flash + boot. Route: delegated verification worker. Evidence: `flash-mac.sh` wrote 2170128 bytes, hash verified. Boot log: AXP2101/QMI8658/ES8311/touch OK, `BLE: advertising start=OK`, MAC `AA:BB:CC:DD:EE:01`; a previously bonded host `AA:BB:CC:DD:EE:02` reconnected (`bonded=1 enc=1`). `screenshot.sh` captured the splash (parent spot check: viewed PNG, Clawd detective pose). Benign first-boot noise: core-dump size error, NVS namespace NOT_FOUND.
- [x] T5 — Daemon venv + tests. Route: delegated verification worker. Evidence: with only `bleak httpx pytest` → collection error (`test_windows_icon.py` imports PIL unconditionally; Pillow only in `requirements-windows.txt`). With `pillow` added → **124 passed, 2 skipped**. Follow-up (H2): make the PIL import lazy or `importorskip`.
- [x] T6 — Probe: Fable window. Route: delegated worker (scratchpad scripts, no repo writes). Evidence: Messages API headers (HTTP 200) carry only `unified-5h/7d/overage/*` — no per-model window; requesting `claude-fable-5-1` returns 400 (`claude_code_version_too_old`, UA 2.1.5) / 429 (UA 2.1.296) with zero ratelimit headers. `GET /api/oauth/usage` (same Bearer + `anthropic-beta: oauth-2025-04-20`) returns `limits[]` with `kind: session (17%)`, `weekly_all (73%)`, `weekly_scoped` + `scope.model.display_name: "Fable"` (1%), each with `percent` and `resets_at`. This matches `claude -p /usage` output exactly. Implication for H2: source Claude data from `/api/oauth/usage` (one GET, no token spend, includes Fable) and drop the 1-token Haiku probe; daemon's hard-coded `User-Agent: claude-code/2.1.5` is a latent breakage.
- [x] T7 — Findings recorded; committed on `feat/tokenmon-h0-baseline`.

## Acceptance criteria
- [x] `sim` produces a screenshot; firmware build succeeds; board boots the flashed image.
- [x] pytest suite result recorded (124 passed, 2 skipped after adding Pillow).
- [x] Fable question answered with raw header list + `/api/oauth/usage` JSON as evidence.

## Verification evidence
See per-task evidence above. Parent spot check: board screenshot PNG viewed (splash renders). Board BLE bond peer `AA:BB:CC:DD:EE:02` == this Mac's Bluetooth address, and `~/Library/LaunchAgents/com.user.claude-usage-daemon.plist` + `~/.config/claude-usage-monitor/config` already exist → upstream Clawdmeter was previously installed and paired on this Mac; no manual pairing needed for H1.

## Decisions carried into H1/H2
- Claude data source: `GET /api/oauth/usage` (session, weekly_all, weekly_scoped/Fable) replaces the 1-token Haiku probe.
- UI: carousel (one provider per screen, tap cycles, auto-rotate).
- Protocol: add `"p"` provider field; one BLE write per provider; firmware keeps one `UsageData` slot per provider; missing `p` → claude.
- Collection model follows Clawdmeter: resident daemon polls each provider on an interval and pushes over BLE (Codex from local rollout JSONL `payload.rate_limits`; Kimi from `GET /coding/v1/usages`).

## Next step
H1 — configurable BLE device name (NVS + serial command + `flash-mac.sh`/`install-mac.sh` prompt + daemon `device_name` config). Note: the existing bond caches the name "Clawdmeter" on macOS; after renaming, unpair and re-pair once.
