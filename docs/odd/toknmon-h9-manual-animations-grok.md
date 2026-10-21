# ToknMon — H9 Manual animations and Grok provider

Objective: keep the meter on screen until the user touches it, and add Grok Build CLI ("Grok Code") as a fourth provider. Branch `feat/h9-manual-animations-grok` from `a76ca77`. Delivery strategy `ask-on-risk`; test runners `daemon/.venv/bin/python -m pytest daemon/tests -q`, `node --test tools/test/`, `pio run -d firmware -e sim`, `pio run -d firmware -e waveshare_amoled_216`.

## Specs

- **S1** — "Que no se pongan las animaciones automáticas, que se mantenga en los medidores a menos que nosotros toquemos para que se active la animación." The idle parade timer (5 min without input → parade) is removed; the meter stays up until a touch (tap / swipe / long-press) or PWR on the splash brings up the animations. Serial `parade on` still starts the parade for QA.
- **S2** — "Que agreguemos el uso de grok code, ya lo tengo instalado y funcionando." Grok Build CLI (`grok`, data dir `$GROK_HOME`, default `~/.grok`) becomes provider id `grok`.
  - **S2.1 Daemon data source** (verified 2026-10-21 with one live call → HTTP 200): `GET https://cli-chat-proxy.grok.com/v1/billing?format=credits` with headers `Authorization: Bearer <key>`, `x-grok-client-version: <grok version>`, `x-grok-client-mode: cli`, `Accept: application/json`. Token = `key` of the single entry in `$GROK_HOME/auth.json` (`auth_mode: oidc`, `expires_at` ISO). Response: `{"config": {"currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY", "start": ISO, "end": ISO}, "creditUsagePercent": 5.0, "productUsage": [...], "billingPeriodStart": ISO, "billingPeriodEnd": ISO, ...}}`. Period type can also be monthly. Map to one bar labelled `"Weekly"` (payload `w`/`wr`), percent = `creditUsagePercent`, reset = `currentPeriod.end`. No 5-hour window exists.
  - **S2.2 No token refresh.** The daemon never uses Grok's `refresh_token` (Grok refreshes and re-reads `auth.json` itself; a second refresher could invalidate its copy).
  - **S2.3 Fallback.** When the token is missing/expired or the endpoint fails, read the newest `"msg":"billing: fetched credits config"` line in `$GROK_HOME/logs/unified.jsonl` (`ctx.config.creditUsagePercent`, `ctx.config.currentPeriod.end`); a period whose end is past reads 0 % (existing `window_bar`). Neither source → `ok: false`.
  - **S2.4 Detection** (`providers = auto`): available when `$GROK_HOME/auth.json` has an entry with a non-empty `key`; reason strings never contain a token.
  - **S2.5 Firmware**: `PROVIDER_GROK = 3`, `PROVIDER_COUNT 4`, name "Grok", BLE id `grok`; a Grok theme (cool silver accent, not black); Grok uses the dot-grid layout (weekly only, like a weekly-only Codex plan); BLE RX queue deep enough for four back-to-back payloads; QA strings (`slot 0-3`, provider lists) updated; simulator scenarios carry a Grok payload.
  - **S2.6 Mascot**: an original character (no xAI/Grok logo): a small black-hole orb with a ring. `grok.idle`, `grok.spin` (act) and `grok.bike` grids; wired into `MASCOT_SPECS` and `PROVIDER_SETS` (idle, spin, bike; scenes are a later follow-up).
  - **S2.7 Docs**: README, CLAUDE.md, docs/providers.md, controls, install, troubleshooting, config.example, install-mac.sh, screenshot.sh, NOTICE (Grok/xAI trademark note), CHANGELOG.

## Tasks

| ID | Specs | Route | Status | Commit |
| --- | --- | --- | --- | --- |
| T1 | S1 | inline | done | `af8b6b9` |
| T2 | S2.1–S2.4, S2.7 (daemon docs) | delegated writer (parallelism with T3) | done | see Log L4 |
| T3 | S2.5, S2.6, S2.7 (firmware docs) | delegated writer (parallelism with T2) | pending | |
| T4 | S2.7 shared docs (README, CLAUDE.md, CHANGELOG, NOTICE), seam check, flash | inline | pending | |

Route evidence: T2 and T3 are independent units with disjoint edit surfaces (daemon vs firmware/art), each several files and well over 100 changed lines → Writer trigger (a). Shared files (README.md, CLAUDE.md, CHANGELOG.md, NOTICE.md) are owned by the parent in T4.

## Log

- **L1** (2026-10-21, user, verbatim): "Necesito que modifiquemos dos cosas: 1. Que no se pongan las animaciones automáticas, que se mantenga en los medidores a menos que nosotros toquemos para que se active la animación. 2. Que agreguemos el uso de grok code, ya lo tengo instalado y funcionando. El device ya esta conectado."
- **L2** T1: removed `parade_timer`, `IDLE_PARADE_MS`, `ui_note_activity()` (only fed that timer). Sim and 2.16 builds pass. The alert path keeps the meter (it switches splash → usage), so no other auto-animation trigger exists. Review assess: medium, `under_budget`, stays pending in the slice.
- **L3** Research: Grok exposes only a weekly (or monthly) credit window; `/usage` is interactive only; headless JSON has per-session cost only. Endpoint verified live (HTTP 200, 5 % weekly). The device is connected over BLE only; no USB serial port is present, so flashing waits for a USB-C cable.
- **L4** T2 (writer): `daemon/providers/grok.py` + registry, installer, config.example, providers/install/troubleshooting docs. RED: collection ImportError; GREEN: 16 passed. Full suite: 254 passed, 2 skipped, 1 failed — `test_providers_codex.py::test_poll_ignores_files_older_than_7_days`, which also fails at `HEAD` (date-dependent: mixes `time.time()` with a fixed `NOW`; pre-existing, out of scope). `--detect` prints `grok: available`; log fallback on the real file returns `('Weekly', 5, 7606)`. Parent spot check: grok tests 16 passed, PII scan clean.
