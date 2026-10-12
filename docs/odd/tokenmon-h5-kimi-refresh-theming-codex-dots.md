# TokenMon — H5 Kimi token refresh, per-provider theming, Codex dot screen

## Objective
1. The Kimi slot stays fresh without the Kimi CLI running: the daemon refreshes the OAuth access token itself.
2. Each provider has its own color identity on the device: Claude keeps the orange/clay theme; Codex and Kimi get their own accent, bar tiers and status-line color — nothing orange on their screens.
3. Codex gets a dedicated "dot grid" screen: a grid of dots fills up to the weekly percentage, with a big percentage and reset time. The 5h bar is omitted when the plan has no 5h window.

## Problem / Why
- Kimi access tokens live ~15 minutes and only the CLI refreshes them; `~/.kimi-code/credentials/*.json` carries `refresh_token`, `scope`, `token_type`.
- Bars use one global tier palette (green/amber/red) and the status line uses the Claude accent, so Codex at 54% renders amber-orange and reads as "Claude".
- The user's Codex plan reports only the weekly window; the daemon sends `s:0, sr:0` and the device draws an empty "Current — Resets in 0m" panel.

## Scope
### Daemon
- `providers/kimi.py`: when no non-expired access token exists (or it expires within 60 s), POST the refresh grant to the Kimi OAuth token endpoint using `refresh_token` from the freshest credential file; persist the new `access_token`/`refresh_token`/`expires_at` back to the same file atomically (write `.tmp` + rename, keep mode 0600); on refresh failure fall back to `ok:false` with a log line, never loop. Discover the endpoint from the Kimi CLI's own config/source on this machine (read-only inspection of `~/.kimi-code/`, the installed `kimi` binary/package) — do not guess; if it cannot be determined with evidence, implement the refresh behind a configurable `kimi_token_url` config key with the discovered default and document it.
- `providers/codex.py`: omit `s`/`sr` keys (and the bar) when the plan reports no short window; `to_payload` emits only present bars.
- Tests for both (fixtures: expired token + refresh response; weekly-only rollout).
### Firmware
- `data.h`/`main.cpp`: `has_session` (key `s` present) and `has_weekly`; missing keys mean "no window".
- `theme.h`: per-provider palette `{accent, bar_ok, bar_warn, bar_danger, status_text}`; Claude = current colors; Codex = teal/green family (accent `#10A37F`, warn a yellow-green, danger red); Kimi = blue/violet family (accent `#3B6CF6`, warn violet, danger red). `pct_color(pct, provider)`.
- `ui.cpp`: title/pill, bar fills, reset labels and the status spinner use the provider palette. New Codex layout `LAYOUT_DOTS`: a 10×10 grid of round dots (100 = 1% each) below the title, filled left-to-right/top-to-bottom to the weekly percentage in the accent color, unfilled dots in a dim tint; big percentage (`styrene_48`) and "Resets in …" line; when `has_session` is true show the 5h value as a single compact bar under the grid; otherwise nothing. The dots mascot stays in the corner. Keep the sim scenario updated (Codex line without `s/sr`).
- Splash unaffected.
### Out of scope
New art; Linux/Windows daemons; Kimi monthly limits.

## Constraints
- Branch `feat/tokenmon-h5-polish` from H4 (`a4b79d2`).
- No `#ifdef BOARD_*` in shared code; 480-height layout first, keep 368/240 compiling.
- Token values never logged; refresh request only via HTTPS; file writes atomic.

## Delivery strategy
`ask-on-risk`. Forecast ~700 authored changed lines (daemon ~250 incl. tests, firmware ~450).

## Tasks
- [x] T1 — Daemon: Kimi refresh (evidence-based endpoint) + Codex key omission + tests. Route: delegated writer A (mapping + writer triggers: >5 lookups in the Kimi bundle, 10 files). Evidence below; commit pending (parent).
- [x] T2 — Firmware: provider palettes + dot-grid Codex screen + has_* flags + sim scenario; autoshots. Route: delegated writer B (mapping + writer triggers: ui.cpp 1.2k lines, 5 files). Done, uncommitted; evidence below.
- [ ] T3 — Hardware: flash, restart daemon, screenshots of Codex dot screen and Kimi screen with a refreshed token; commit. Route: parent + verification.

## Verification
- `daemon/.venv/bin/python -m pytest daemon/tests -q`
- `pio run -d firmware -e sim` + autoshots; `pio run -d firmware -e waveshare_amoled_216`
- Live: `launchctl kickstart -k gui/$(id -u)/com.user.claude-usage-daemon` → log shows `Sending[kimi]` with `ok:true` after a refresh; `screenshot.sh --screen usage` + `slot 1`/`slot 2`.

## Verification evidence

### Firmware evidence (T2)
Changes: `data.h` (`has_session`/`has_weekly`), `main.cpp` (flags from key presence + transitional
Codex `s:0,sr:0` → no window), `theme.h` (`ProviderTheme` + `provider_theme()`; Codex warn `#C9D42B`,
Kimi warn `#8B5CF6`, danger `#E5484D`), `ui.cpp` (`pct_color(pct, provider)`, status line and bars in
the provider palette, `LAYOUT_DOTS` for Codex, `layout_for()` picks BARS/DENSE/DOTS),
`sim/scenario.jsonl` (Codex weekly-only line + Codex-with-5h line, 12 s each).
- Dot grid is one `lv_canvas` over a PSRAM buffer (`heap_caps_malloc`, 254×254×2 at 480 px), drawn
  row by row with `lv_draw_rect` radius-circle. The first attempt (100 `lv_obj` circles) segfaulted
  in `lv_draw_add_task`: the builtin LVGL pool is the 64 KB default on every env (no `LV_MEM_SIZE`
  override), and the draw tasks of 100 objects exhausted it. Canvas gated on `BOARD_HAS_PSRAM`
  (existing pattern); C6 keeps the bar layout for Codex.
- Geometry at 480: percentage row 100-151, grid pitch 26 / dot 20 (254 px) without the 5h row,
  pitch 23 / dot 17 with it; 5h row sits at 400-421, status line starts at 431.
- `pio run -d firmware -e sim`: SUCCESS. Headless autoshots (temporary `SCREEN_USAGE` boot, reverted;
  `git diff --stat firmware/src/main.cpp` = 12 insertions, parse block only):
  `<scratchpad>/h5/codex-dots.png` (54 %, no 5h row), `codex-5h.png` (40 % + "5h - 12% - Resets in 4h 0m"
  bar), `codex-legacy.png` (`s:0,sr:0` → no row), `kimi.png` (63 % violet / 9 % blue, blue status line),
  `claude3.png` (3 bars, unchanged colors).
- `pio run -d firmware -e waveshare_amoled_216`: SUCCESS — RAM 33.9 % (110984 B), Flash 65.7 % (2194463 B).
- `grep -rn "ifdef BOARD_" firmware/src/*.cpp firmware/src/*.h`: only `BOARD_HAS_PSRAM` (splash.cpp:407,
  main.cpp:33, ui.cpp:297, ui.cpp:928).
- Hardware (board re-enumerated as `/dev/cu.usbmodem101`): flashed with `--name "ToknMon Desk One"`;
  live daemon data arrived before the first poll. `hw-codex.png` (91 % weekly, dot grid, no 5h row),
  `hw-kimi.png` (0 % / 0 %, blue title + status), `hw-claude.png` (15/91/18 %, terra-cotta). Board left on
  `screen usage`.

### Daemon evidence (T1)
Kimi refresh endpoint, read out of the CLI bundle (`~/.kimi-code/bin/kimi` v2.1.1 is a
Mach-O arm64 Bun bundle; `strings -n 6` dump line numbers, source region
`packages/oauth/src/oauth.ts`):
- `DEFAULT_KIMI_CODE_OAUTH_HOST = "https://auth.kimi.com"`, env overrides `KIMI_CODE_OAUTH_HOST` / `KIMI_OAUTH_HOST`, `clientId: "17e5f671-d194-4dfb-9706-5516cb48c098"` — strings:337096 (`KIMI_CODE_FLOW_CONFIG`).
- `refreshAccessToken`: `POST ${oauthHost}/api/oauth/token`, form body `client_id`, `grant_type: "refresh_token"`, `refresh_token` — strings:335686-335698.
- `postForm`: `Content-Type: application/x-www-form-urlencoded`, `Accept: application/json`, plus `X-Msh-*` device headers (not required by us; see open question) — strings:335610-335625.
- Response -> `tokenFromResponse`: `access_token`, `refresh_token` (required), `expires_in` (s), `scope`, `token_type`; `expires_at = floor(now) + expires_in` — strings:335595-335608.
- Storage: `~/.kimi-code/credentials/<name>.json`, write `<name>.json.tmp.<pid>.<rand>` + fsync + rename, mode 0600 — strings:335477-335530.
- Live credential files: `kimi-code.json` (expired since Aug) and `kimi-code-env-<hash>.json` (scoped key, live); keys `access_token, expires_at, expires_in, refresh_token, scope, token_type`, mode 0600.

Implementation: `daemon/providers/kimi.py` (`read_credentials`, `refresh_access_token`, `token_url`, `read_config` hook; refresh when expired or within 60 s, one request, atomic 0600 write-back), `base.py` label-keyed `to_payload`, `codex.py` omits unreported windows, `claude_usage_daemon.py` wires `kimi_provider.read_config = read_config_value`, `config.example` + README document `kimi_token_url`.

Checks:
- RED: 11 failed (new/updated tests) before implementation.
- `daemon/.venv/bin/python -m pytest daemon/tests -q`: 212 passed, 2 skipped, 2 warnings (same 2 pre-existing mock warnings as the 200/2 baseline).
- `daemon/.venv/bin/python -c "import sys; sys.path.insert(0,'daemon'); import claude_usage_daemon"`: ok.
- Live poll 1 (token still valid, +225 s): `ok:true`, payload `{"p":"kimi","s":2,"sr":64,"w":0,"wr":2284,...}`, file untouched (correct: outside the 60 s margin).
- Live poll 2 (token at +48 s, inside the margin): one `POST https://auth.kimi.com/api/oauth/token` -> 200; `ok:true`, payload `{"p":"kimi","s":2,"sr":61,"w":0,"wr":2281,...}`; `kimi-code-env-<hash>.json` rewritten (access and refresh token rotated, `expires_at` +898 s, `expires_in` 900, mode 0600, no `.tmp` left behind).

Deviation: pre-existing `test_poll_without_valid_token_is_not_ok_and_makes_no_request` asserted "expired token -> zero requests", which the refresh contract replaces; renamed to `..._never_calls_usages` and it now asserts exactly one refresh POST and no `/usages` call.

## Next step
Launch writers A and B.
