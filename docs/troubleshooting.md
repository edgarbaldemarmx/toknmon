# Troubleshooting

Start with the logs: `tail -F ~/Library/Logs/toknmon.out.log` (activity) and
`~/Library/Logs/toknmon.err.log` (errors). `launchctl list | grep toknmon`
shows whether the agent is loaded and its last exit code. The board's serial
console (115200 baud) prints every BLE event and payload.

## Daemon

| Symptom | Cause | Fix |
| --- | --- | --- |
| The agent is loaded but the log never gets past startup; `ps` shows the Python process stuck | The clone lives under `~/Documents`, `~/Desktop`, `~/Downloads` or another TCC-protected folder and launchd's Python has no permission to read it | Grant the venv's Python access in **System Settings → Privacy & Security → Files and Folders** (or Full Disk Access), or move the clone to `~/toknmon` and run `./install-mac.sh` again |
| `Bluetooth permission` dialog never appeared; `CBManager` errors in the log | The daemon was first started by launchd, not from a terminal | Run `./install-mac.sh` again without `--no-prime`, or `daemon/.venv/bin/python daemon/claude_usage_daemon.py` once from a terminal and accept the prompt |
| Two daemons fight for the board; alternating connects/disconnects | The Clawdmeter-era `com.user.claude-usage-daemon` agent is still loaded, or a second checkout runs its own agent | `launchctl bootout gui/$(id -u)/com.user.claude-usage-daemon`; `./install-mac.sh` retires it automatically and parks the plist under `~/.config/toknmon/legacy/` |
| `Device not found` / `Not paired` for minutes | The board is not paired with this Mac, or macOS holds a stale bond | Pair in System Settings → Bluetooth (hold PWR 3 s on the board for pairing mode). With `blueutil` installed the daemon drops a stale bond itself; otherwise forget the device and pair again |
| Connected, but one provider never shows | `providers` lists it and it has no data | `daemon/.venv/bin/python daemon/claude_usage_daemon.py --detect` tells you what is detected and why not; see the provider rows below |
| `Alert dropped: Claude is not an enabled provider` | Claude Code hooks are installed but Claude is not polled | Alerts ride on the Claude payload: add `claude` to `providers` (or use `auto`) |
| Config edits do nothing | Typo in the key, or a `#` in a value | Keys are documented in `daemon/config.example`; `#` starts a comment, so device names cannot contain it |

### Claude

| Symptom | Fix |
| --- | --- |
| `token expired`, `HTTP 401` | Run `claude` and log in again; the daemon re-reads the Keychain on the next poll |
| `Warning: Claude Code OAuth token not found in Keychain` at install | Log in to Claude Code first (service `Claude Code-credentials`), or make sure `~/.claude/.credentials.json` exists |
| No Fable bar | The subscription has no model-scoped weekly window; the bar appears only when `/api/oauth/usage` reports one |
| Wrong plan shown with several Claude accounts | Set `config_dirs = ~/.claude, ~/.claude-work`; the daemon shows the plan whose usage rose most recently |

### Codex

| Symptom | Fix |
| --- | --- |
| `codex: no data` / slot stale | The Codex provider reads `~/.codex/sessions/**/rollout-*.jsonl` from the last 7 days; run Codex once. A custom `CODEX_HOME` must be visible to the launchd agent (set it in the plist or symlink `~/.codex`) |
| Only the dot grid, no 5h bar | The plan reports a weekly window only; the bar appears when `rate_limits` carries a short window |

### Kimi

| Symptom | Fix |
| --- | --- |
| `kimi: no data (no valid token)` | Log in once with the Kimi Code CLI so `~/.kimi-code/credentials/*.json` exists. Afterwards the daemon refreshes the token itself |
| `Kimi token refresh failed` | The refresh token was revoked or the endpoint changed. Log in again with the CLI; if Kimi moved its OAuth host, set `kimi_token_url` (HTTPS only) |
| Credential file permissions error | The daemon rewrites the file atomically with mode 0600; make sure the directory is writable by your user |

### Grok

| Symptom | Fix |
| --- | --- |
| `grok: unavailable — Grok CLI not found` / `not logged in` (`--detect`, or `grok skipped` in the log) | Run `grok login`; `~/.grok/auth.json` needs an entry with a `key`. A custom `GROK_HOME` must be visible to the launchd agent (set it in the plist or symlink `~/.grok`) |
| ``Provider grok: no data (token expired; Grok sign-in expired; run `grok login`; …)`` | The refresh token was rejected (`invalid_grant`), so the sign-in is gone. Run `grok login`; the daemon does not retry the rejected refresh token, and picks up the new one on the next poll |
| `Provider grok: no data (token expired; refresh skipped: auth.json.lock is held by another process …)` | Grok itself is refreshing the token right now. Nothing to do: the next poll reads the token Grok stored |
| `Provider grok: no data (token expired; refresh refused: … is not https …)` | `oidc_issuer` in `auth.json`, the discovered `token_endpoint` or the `grok_token_url` config key is not HTTPS. Remove the `grok_token_url` override, or run `grok login` to rewrite `auth.json` |
| `Provider grok: no data (…; last billing line in logs/unified.jsonl is older than 6 h)` | The live endpoint failed and the logged value is too old to show as live, so the slot drops out. Fix the live path (see the line above it in the log); running `grok` once also logs a fresh value |
| `Provider grok: no data (…; no billing line in logs/unified.jsonl)` | The live endpoint failed and Grok has not logged a credits fetch in the last 8 MiB of its log. Check the reason before the `;`; run `grok` once so it logs one |
| `Grok: live billing unavailable (…)` in the log | The live endpoint failed (logged once per change, then `Grok: live billing endpoint OK again` when it recovers). While it lasts the slot shows the logged value if it is newer than 6 h |
| `Grok: ignoring GROK_CLI_CHAT_PROXY_BASE_URL=… (not https)` | The override is not HTTPS, so the daemon uses the default endpoint. Use an `https://` URL or unset the variable |
| `auth.json` permissions after a refresh | The daemon rewrites `~/.grok/auth.json` atomically with mode 0600 and keeps every other field; make sure `~/.grok` is writable by your user |
| Grok shows 0 % with a 0 m countdown | The credit period in the last value has ended; the next live poll or Grok run brings the new period |

## Board

| Symptom | Cause | Fix |
| --- | --- | --- |
| Board shows a different name than you set, or does not appear after a rename | macOS caches the advertised name with the bond | Forget the device in System Settings → Bluetooth and pair again |
| `BLE: name rejected (need 1-18 printable ASCII chars, no '#')` | The name breaks the rules | Shorten it, ASCII only, no `#` |
| Stays on the splash, meter never appears | No payload has arrived yet (the meter needs fresh data), or the daemon is not connected | Check the daemon log for `Connected` and `Sending[...]`; swipe up to see the meter's status line |
| Carousel skips a provider | Its slot is older than 90 s | That provider failed its last polls; see the daemon section |
| Meter shows "Resets in 0m" around a reset | Known: aged countdowns clamp at 0 until the next poll | Wait for the next poll (60 s) |
| Splash shows idle animations only | The mood group follows the Claude usage rate; a quiet session stays calm | Expected; mascot mode and the parade play the full sets regardless |
| Side buttons type nothing | HID keys go to the paired host only, and only after pairing | Pair the board; the keys land in the focused window |
| `./screenshot.sh` prints `Timeout: got N of 460800 bytes` and `retrying (n/3)` | The raw dump stalled while the board was logging BLE traffic | Normal; the script retries up to 3 times by itself. If all three fail, run it again right after a daemon poll (every 60 s) or stop the agent for the capture |
| `./screenshot.sh` fails 3 times, or waits for `SCREENSHOT_START` with no data | An orphaned reader holds the port, or the board is on a C6 (no `screenshot`) | `lsof /dev/cu.usbmodem*` and kill the stale Python holding the port |
| `--screen usage:codex` captures another provider | That slot is not fresh (`slot 1` → `err slot not fresh`) | Wait for the daemon to send that provider's payload, or check the provider rows above |
| `screenshot` → nothing on a C6 board | `LV_USE_SNAPSHOT` is off without PSRAM | Use the simulator or eyeball on hardware |

## Flashing

| Symptom | Fix |
| --- | --- |
| `No /dev/cu.usbmodem* found` | Data cable, other USB-C port on the board, or pass the port explicitly (`ls /dev/cu.*`) |
| `This chip is ESP32-C6, not ESP32-S3` | Use the env that matches the board (`*_c6` for C6 hardware) |
| Upload OK but naming timed out | The port number changed after reset: `./flash-mac.sh --rename "<name>" <new port>` |
| Black screen after flashing an inherited board | Those ports are untested with ToknMon; check the env, power-cycle, and open an issue with the serial boot log |

More detail in [`flashing.md`](flashing.md).

## Simulator

| Symptom | Fix |
| --- | --- |
| `sdl2-config: not found` when building `-e sim` | `brew install sdl2` (Linux: `apt install libsdl2-dev`) |
| Default scenario not found | Run the binary from the `firmware/` directory, or pass `SIM_SCENARIO=<path>` |
| Window opens but the meter never shows | The sim boots on the splash like hardware; the scenario needs a payload line, then swipe (drag) or wait for an alert line |

## Still stuck

Open an issue with the board, macOS version, the installer output and the
relevant log lines (remove tokens and your device name). See
[CONTRIBUTING](../CONTRIBUTING.md).
