# Providers

The daemon monitors up to four AI coding assistants and pushes one BLE
payload per provider. The board keeps one usage slot per provider and shows
them as a carousel with a palette and a mascot of their own.

| Provider | Config id | Data source | Network | What the board shows |
| --- | --- | --- | --- | --- |
| Claude Code | `claude` | `GET https://api.anthropic.com/api/oauth/usage` with the Claude Code OAuth token (Keychain service `Claude Code-credentials`, or `~/.claude/.credentials.json`) | one GET per poll, **no token spend** | **Current** (5-hour session), **Weekly**, and the model-scoped weekly bar (**Fable**) when the subscription has one; reset countdowns; the Clawd corner mascot |
| OpenAI Codex CLI | `codex` | newest `rate_limits` entry in `${CODEX_HOME:-~/.codex}/sessions/**/rollout-*.jsonl` modified in the last 7 days | **none** (local files only) | a **10×10 dot grid** filled to the weekly percentage with the large percentage and reset time; a compact 5h bar only when the plan reports a short window; the three-dots mascot |
| Kimi Code | `kimi` | `GET ${KIMI_CODE_BASE_URL:-https://api.kimi.com/coding/v1}/usages` with the freshest token in `~/.kimi-code/credentials/*.json` | one GET per poll, plus a token refresh when needed | **Current** (5h) and **Weekly** bars in blue; the crescent-moon mascot |
| Grok Build CLI | `grok` | `GET ${GROK_CLI_CHAT_PROXY_BASE_URL:-https://cli-chat-proxy.grok.com/v1}/billing?format=credits` with the `key` in `${GROK_HOME:-~/.grok}/auth.json`; fallback: the newest `billing: fetched credits config` line in `~/.grok/logs/unified.jsonl` when it is newer than 6 h | one GET per poll, plus a token refresh (Grok's own OIDC protocol) when needed | the **dot grid** filled to the weekly credit percentage (Grok has no 5-hour window); the black-hole Grokbot-style ball mascot |

Palettes: Claude clay (`#D97757`), Codex teal (`#10A37F`), Kimi blue
(`#3B6CF6`), Grok: cool silver, dot grid, weekly only; each provider also has
its own warning and danger tiers for the bars so nothing on a Codex, Kimi or
Grok screen reads as Claude's orange.

## Choosing providers

The `providers` key in `~/.config/toknmon/config` decides what is polled:

```ini
providers = auto                 # default: detect what is installed, every poll
providers = claude, codex        # explicit list, any order
providers = claude, grok         # Claude and Grok only
```

- **`auto`** (default, also used when the key is absent): on every poll the
  daemon checks which providers are usable on this Mac and sends only those.
  Detection is local and never touches the network:

  | Provider | Counts as available when |
  | --- | --- |
  | `claude` | an OAuth token exists in the macOS Keychain (`Claude Code-credentials`) or in `<config_dir>/.credentials.json` for any dir in `config_dirs` |
  | `codex` | at least one `rollout-*.jsonl` exists under `${CODEX_HOME:-~/.codex}/sessions` (any age; polling then reads the last 7 days) |
  | `kimi` | a credential file with an access token exists under `~/.kimi-code/credentials` (an expired token is fine, the daemon refreshes it) |
  | `grok` | `${GROK_HOME:-~/.grok}/auth.json` has an entry with a non-empty `key` (an expired token is fine, the daemon refreshes it) |

  Logging in to a new tool or running it once is picked up within a minute,
  no reinstall and no restart. The daemon logs the resolved set whenever it
  changes: `Providers (auto): claude, codex — kimi skipped: Kimi Code CLI not
  found: ~/.kimi-code/credentials has no credential files. …`
- **Explicit list** (`providers = claude, codex`): only the named providers
  are polled, even ones detection would reject. A listed provider that has no
  data this cycle sends `{"p": "<id>", "ok": false}`, the board marks that
  slot stale and the carousel skips it; the others are unaffected. Unknown
  names are logged and ignored; a list with no known name falls back to
  `auto`. `auto` cannot be combined with a list.
- The installer runs the same detection and prints what it found and how to
  enable anything missing:

  ```text
  +-- Provider detection (this Mac) -----------------------------------
  | claude: found
  | codex: found
  | kimi: not found
  |   Kimi Code CLI not found: ~/.kimi-code/credentials has no credential files. Install the Kimi Code CLI and run it once to log in.
  |   Once it is installed and logged in, 'auto' picks it up on the next
  |   poll — no reinstall, no restart.
  +--------------------------------------------------------------------
  ```

  The raw report is available any time (one line per provider,
  `<id>: available` or `<id>: unavailable — <reason>`, exit code 0):

  ```bash
  daemon/.venv/bin/python daemon/claude_usage_daemon.py --detect
  ```
- `./install-mac.sh --providers auto|<list>` sets the key without prompting
  (an unknown name is an error there).

### Enabling each provider

- **Claude**: run `claude` and log in (`/login`). The daemon reads the OAuth
  token from the Keychain on every poll, so re-logging in is enough after an
  expiry; `~/Library/Logs/toknmon.err.log` shows `token expired` / `HTTP 401`
  otherwise. Several plans in separate config dirs (`CLAUDE_CONFIG_DIR`) can be
  polled together with `config_dirs = ~/.claude, ~/.claude-work`; the board
  shows the plan whose usage rose most recently.
- **Codex**: run the Codex CLI once; a `rollout-*.jsonl` with a `rate_limits`
  entry appears under `~/.codex/sessions/`. Logs older than 7 days are ignored,
  so a Codex slot goes stale after a week without using Codex. No credentials
  are read.
- **Kimi**: log in once with the Kimi Code CLI. Kimi access tokens live about
  15 minutes; when the freshest one is expired or within 60 s of expiring, the
  daemon posts the refresh grant to `kimi_token_url` (default
  `https://auth.kimi.com/api/oauth/token`, HTTPS only) and writes the rotated
  tokens back to the same file atomically with mode 0600, exactly like the
  CLI does. A failed refresh logs one line and sends `ok: false`; it never
  loops.
- **Grok**: run `grok login` once (Grok Build CLI). The daemon sends the `key`
  from `~/.grok/auth.json` as a bearer to the CLI's own credits endpoint with
  the headers `x-grok-client-version` (from `~/.grok/version.json`) and
  `x-grok-client-mode: cli`. A `GROK_CLI_CHAT_PROXY_BASE_URL` override must
  be `https://`; any other value is ignored (logged once) and the default
  endpoint is used.
- **Grok token refresh**: when the token is expired or within 300 s of
  expiring (Grok's own `GROK_AUTH_EARLY_INVALIDATION_SECS` default), the
  daemon refreshes it the way Grok does, so the slot stays live while Grok is
  closed:
  1. It takes Grok's cross-process lock, an exclusive `flock` on
     `~/.grok/auth.json.lock`, and writes `<pid>:<epoch>` into it like Grok.
     If Grok holds the lock, the daemon skips the refresh for this poll.
  2. Under the lock it re-reads `auth.json`; if another process already
     stored a fresh token, it uses that one and sends nothing.
  3. It posts `grant_type=refresh_token`, `refresh_token` and
     `client_id=<oidc_client_id>` to the issuer's `token_endpoint`,
     discovered from `<oidc_issuer>/.well-known/openid-configuration`
     (currently `https://auth.x.ai/oauth2/token`) or set with the
     `grok_token_url` config key. The issuer and the endpoint must be HTTPS.
  4. It writes `key`, the rotated `refresh_token` (when the response has one)
     and `expires_at` back atomically (temp file + rename, mode 0600); every
     other entry and field stays as it was.

  A rejected grant (`invalid_grant`) leaves `auth.json` untouched, reports
  "Grok sign-in expired; run `grok login`" and is not retried until the
  refresh token changes. Any other failure also leaves the file untouched.
  Tokens never appear in the log.
- **Grok fallback**: when there is no usable token or the endpoint fails, the
  daemon reads the newest `billing: fetched credits config` line that the CLI
  logged in `~/.grok/logs/unified.jsonl` (scanned off the event loop, at most
  the last 8 MiB). That value is used only when the line is newer than 6 h;
  an older one, or no line at all, sends `ok: false` so the slot drops out
  instead of showing an old value as live. The endpoint failure is logged
  once per change of state, not on every poll. Grok reports one credit window
  (`currentPeriod`, weekly or monthly); it lands on the weekly keys `w`/`wr`
  and the countdown runs to the real period end. A period whose end has
  passed reads 0 %.

### Removing a provider

Set an explicit list without it, or log out / remove the tool and keep
`auto`. The board drops the slot from the carousel after 90 s without a fresh
payload.

## What the screens show

- **Claude**: two or three horizontal bars (Current, Weekly, Fable) with
  "Resets in …" labels, the status line, and the corner mascot that plays
  busier acts as your usage rate climbs. An attention alert from Claude Code
  (see [`install-macos.md`](install-macos.md#attention-alerts-from-claude-code-optional))
  rides on this payload only.
- **Codex**: the dot grid (one dot = 1 % of the weekly window), the percentage
  in large type and the reset time; on plans with a 5-hour window a compact
  bar sits under the grid. The grid needs PSRAM (all S3 boards); C6 boards
  fall back to bars.
- **Kimi**: Current and Weekly bars in the Kimi palette.
- **Grok**: the dot grid (one dot = 1 % of the credit window), the
  percentage in large type and the reset time, in cool silver. Grok has no
  5-hour window, so there is never a compact bar under the grid.
- **Carousel**: with two or more fresh slots the meter rotates every 8 s; tap
  or swipe left/right to page; the title shows the provider name in its
  accent. Data older than 90 s is stale (the daemon polls every 60 s), and a
  stale slot is skipped.

## Payload format

One JSON object per provider per poll, written to the BLE RX characteristic
(`4c41555a-4465-7669-6365-000000000002`); each write is a complete update.

```json
{"p":"claude","s":17,"sr":110,"w":73,"wr":860,"f":1,"fr":860,"st":"allowed","ok":true,"t":1760000000,"tf":24}
{"p":"codex","w":40,"wr":5000,"st":"allowed","ok":true,"t":1760000000,"tf":24}
{"p":"grok","w":5,"wr":7200,"st":"allowed","ok":true,"t":1760000000,"tf":24}
{"p":"kimi","ok":false}
```

| Key | Meaning |
| --- | --- |
| `p` | provider id (`claude`, `codex`, `kimi`, `grok`); missing means `claude` (compatible with Clawdmeter payloads) |
| `s`, `sr` | session (5h) percent used and minutes until it resets; omitted when the plan has no such window |
| `w`, `wr` | weekly percent used and minutes until reset (Grok: its credit window, weekly or monthly) |
| `f`, `fr` | model-scoped weekly window (Fable) percent and minutes; Claude only, only when present |
| `st` | status string from the API (`allowed`, …) |
| `ok` | `true` when the poll succeeded; `false` carries no numbers and marks the slot unavailable |
| `t`, `tf` | host local time (epoch seconds with the UTC offset applied) and hour format (`12`/`24`) for the on-screen clock |
| `c` | chime on session reset (`chime = on`); Claude only |
| `b`, `m`, `x` | attention alert: beep once, message text, end the alert; Claude only |
| `acct` | account kind (`pro`, `ent`, …); Claude only |

Payloads stay under 180 bytes. The firmware acks on the TX characteristic
(`…0003`) and asks for a refresh on `…0004` once per connection.

## Adding a provider

1. Create `daemon/providers/<id>.py` returning a `ProviderResult(id, bars,
   status, ok, extra)` where `bars` is a list of `(label, percent,
   reset_minutes)`; `base.py` maps labels to the payload keys above.
2. Register its `poll` and `detect` in `PROVIDERS` and `DETECTORS` in
   `daemon/providers/__init__.py` (registry order is the `auto` order), and
   add it to the installer's provider list (`install-mac.sh`).
3. Firmware: add a slot (`PROVIDER_COUNT`, `provider_short()` in
   `main.cpp`), a palette in `theme.h`, and optionally a mascot spec and
   provider set in `splash.cpp` ([`animations.md`](animations.md)).
4. Add fixtures and tests under `daemon/tests/` (`test_providers_*.py`) and a
   scenario line in `firmware/sim/scenario.jsonl`.
