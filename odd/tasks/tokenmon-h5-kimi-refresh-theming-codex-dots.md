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
- [ ] T1 — Daemon: Kimi refresh (evidence-based endpoint) + Codex key omission + tests. Route: delegated writer A.
- [ ] T2 — Firmware: provider palettes + dot-grid Codex screen + has_* flags + sim scenario; autoshots. Route: delegated writer B.
- [ ] T3 — Hardware: flash, restart daemon, screenshots of Codex dot screen and Kimi screen with a refreshed token; commit. Route: parent + verification.

## Verification
- `daemon/.venv/bin/python -m pytest daemon/tests -q`
- `pio run -d firmware -e sim` + autoshots; `pio run -d firmware -e waveshare_amoled_216`
- Live: `launchctl kickstart -k gui/$(id -u)/com.user.claude-usage-daemon` → log shows `Sending[kimi]` with `ok:true` after a refresh; `screenshot.sh --screen usage` + `slot 1`/`slot 2`.

## Verification evidence
(pending)

## Next step
Launch writers A and B.
