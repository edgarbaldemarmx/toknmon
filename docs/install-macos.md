# Installing ToknMon on macOS

This guide covers the host side: the Python daemon that polls your providers
and pushes usage to the board over Bluetooth Low Energy. Flashing the board is
covered in [`flashing.md`](flashing.md); the README's
[Quick start](../README.md#quick-start) is the short version of both.

The daemon is **macOS-only**. The Linux and Windows daemons in `daemon/` are
inherited from Clawdmeter, poll Claude only and are untested with ToknMon.

## Requirements

| What | Why | How to get it |
| --- | --- | --- |
| macOS 13 (Ventura) or newer with Bluetooth | CoreBluetooth via `bleak`; launchd user agent | — |
| Python 3.10 or newer (3.13 is what the project is developed on) | the daemon and its tests | `brew install python` or python.org; the installer picks the first of `python3.13` … `python3.10`, then `python3`, found on `PATH` |
| Claude Code logged in | the Claude provider reads the OAuth token from the Keychain (service `Claude Code-credentials`) | `claude` → `/login` |
| Codex CLI with at least one session under `~/.codex/sessions` (optional) | the Codex provider reads local session logs; no network, no credentials | run `codex` once |
| Kimi Code CLI logged in once (optional) | `~/.kimi-code/credentials/*.json`; the daemon refreshes the token itself afterwards | run `kimi` and log in |
| Grok Build CLI logged in (optional) | `~/.grok/auth.json`; the daemon refreshes the Grok token itself with Grok's own protocol (under Grok's `auth.json.lock`), and falls back to the CLI's own log only while that value is newer than 6 h | `grok login` |
| `blueutil` (optional) | automatic repair of a stale Bluetooth bond | `brew install blueutil` (the installer offers it) |

A board already flashed with ToknMon and paired with this Mac
([`flashing.md`](flashing.md)).

> **Where to clone.** launchd starts the daemon with the Python binary inside
> `daemon/.venv`. If that folder lives under `~/Documents`, `~/Desktop`,
> `~/Downloads` or another folder protected by macOS privacy controls (TCC),
> the agent can hang at startup until you grant that Python access in
> **System Settings → Privacy & Security → Files and Folders**. Cloning into
> `~/toknmon`, `~/src/toknmon` or similar avoids the prompt entirely.

## 1. Clone

```bash
git clone https://github.com/edgarbaldemarmx/toknmon.git ~/toknmon
cd ~/toknmon
```

## 2. Flash and name the board

```bash
./flash-mac.sh waveshare_amoled_216 --name "<Your name>"
```

Details, port selection, renaming and the name rules are in
[`flashing.md`](flashing.md). The name you choose here is what the board
advertises over Bluetooth and what the installer stores as `device_name`.

## 3. Pair the board

Open **System Settings → Bluetooth** and click **Connect** next to your
board's name. The daemon never scans for arbitrary devices: it only talks to
the ToknMon peripheral this Mac is paired with, found by its service UUID.
Pairing also enables the HID keyboard the side buttons use.

If you rename a board later, **unpair it and pair again**: macOS caches the
advertised name with the bond.

## 4. Install the daemon

Interactive:

```bash
./install-mac.sh
```

Non-interactive (defaults everywhere, provider auto-detection, no
permission-priming run):

```bash
./install-mac.sh --yes --providers auto --device-name "<Your name>" --no-prime
```

What the installer does, in order (the banners it prints):

1. `[1/7] Checking prerequisites`: `curl`, a Python interpreter (3.10+), and
   the Claude Code OAuth token in the Keychain. The token check is silent
   when the token exists and prints a warning when it is missing.
2. `[2/7] Creating Python virtualenv`: creates `daemon/.venv` and installs
   `daemon/requirements-macos.txt` (`bleak`, `httpx`, `pillow`, `pytest`).
3. `[3/7] Rendering launchd plist`: renders `daemon/com.toknmon.daemon.plist`
   into `~/Library/LaunchAgents/com.toknmon.daemon.plist` (not loaded yet).
4. `[4/7] Configuring the daemon`: first migrates a Clawdmeter-era setup if
   one exists (copies `~/.config/claude-usage-monitor/{config,ble-address}`
   to `~/.config/toknmon/` only when the new files are absent; nothing is
   deleted; the `Migrated …` lines appear only when a legacy install is
   present), then walks the configuration prompts (each one is skipped with
   `--yes`, which keeps existing values):
   - **Claude config dirs**: if several `~/.claude*` directories exist you can
     have the daemon poll all of them and show the plan in active use
     (`config_dirs`).
   - **Providers**: which services to monitor. The installer runs the
     daemon's own detection (`claude_usage_daemon.py --detect`, local files
     only) and prints a box with `<provider>: found` / `not found` plus the
     reason and how to fix it (install Claude Code and run `claude login`,
     run the Codex CLI once, log in with the Kimi Code CLI, run `grok login`). The default
     `auto` makes the daemon repeat that detection on every poll, so a CLI
     installed later shows up by itself; type an explicit list
     (`claude,codex`) to pin the set. With no provider detected the daemon
     still installs and connects, and the board stays on its splash until a
     CLI is logged in. See [`providers.md`](providers.md).
   - **Device name**: the Bluetooth name set when flashing (prefilled from the
     value `flash-mac.sh` saved).
   - **Clock** (`off|auto|12|24`), **chime** on session reset and **beep** on
     attention alerts.
5. `[5/7] Bluetooth permission check`: runs the daemon once in the foreground
   so macOS shows its **Bluetooth permission** prompt for the right process
   (skip with `--no-prime`, then run the printed command once yourself; with
   `--yes` the run is bounded to a few seconds). Accept the prompt. If
   `blueutil` is installed, it is primed the same way (bounded to 20 s) so
   stale-bond recovery can use it.
6. `[6/7] Loading launchd service`: retires the legacy
   `com.user.claude-usage-daemon` agent if present (stops it and moves its
   plist to `~/.config/toknmon/legacy/`), then loads the agent with
   `launchctl bootstrap gui/$(id -u) <plist>` (after a `bootout` of any
   previous copy). On a system that refuses `bootstrap` the script falls back
   to `launchctl load -w` and says so.
7. `[7/7] Menu-bar app`: builds `ToknMon.app` with py2app
   (`tools/build_mac_app.sh`), copies it to `~/Applications/ToknMon.app`,
   renders `daemon/com.toknmon.menubar.plist` into `~/Library/LaunchAgents/`
   and starts it, so a ToknMon icon appears in the menu bar at every login.
   See [gui.md](gui.md). `--no-gui` skips this step; a build failure is
   reported and the daemon stays installed.

Options (`./install-mac.sh --help`):

| Flag | Effect |
| --- | --- |
| `--yes`, `-y` | accept the default answer for every prompt; keep existing config values |
| `--providers <list>` | `auto`, or a comma-separated subset of `claude,codex,kimi,grok`; an unknown name is an error |
| `--device-name <name>` | the board's Bluetooth name (1–18 printable ASCII characters, no `#`) |
| `--apps meter\|suite` | what the board offers: `suite` (default) is the meter plus the Focus timer behind the app center, `meter` hides them; stored as `apps` and pushed to the board |
| `--no-prime` | skip the permission-priming foreground run |
| `--no-gui` | do not build or start the menu-bar app |
| `-h`, `--help` | usage |

### What gets installed where

| Item | Path |
| --- | --- |
| Virtual environment | `daemon/.venv/` inside the clone |
| launchd agent | `~/Library/LaunchAgents/com.toknmon.daemon.plist` (label `com.toknmon.daemon`, runs at login, restarts on exit) |
| Configuration | `~/.config/toknmon/config` (re-read every poll, no restart needed) |
| Cached board address | `~/.config/toknmon/ble-address` |
| Logs | `~/Library/Logs/toknmon.out.log`, `~/Library/Logs/toknmon.err.log` |
| Status for the menu-bar app | `~/.config/toknmon/status.json` (rewritten after every poll) and `state.json` (last config pushed to the board) |
| Menu-bar app | `~/Applications/ToknMon.app`, agent `~/Library/LaunchAgents/com.toknmon.menubar.plist`, log `~/Library/Logs/toknmon-menubar.log` |
| Retired Clawdmeter agent | `~/.config/toknmon/legacy/com.user.claude-usage-daemon.plist` (if one existed) |

## 5. Check that it works

```bash
launchctl list | grep toknmon                 # the agent is loaded (PID or last exit code)
tail -F ~/Library/Logs/toknmon.out.log        # "Connected" then one "Sending[<provider>]" line per provider
```

Within about a minute the board leaves its "waiting" state and the meter shows
your first provider. Swipe up or down on the splash to reach the meter, tap or
swipe left/right to page through providers ([`controls.md`](controls.md)).

## Managing the daemon

```bash
tail -F ~/Library/Logs/toknmon.err.log                                 # errors and tracebacks
launchctl kickstart -k gui/$(id -u)/com.toknmon.daemon                 # restart now
launchctl bootout gui/$(id -u)/com.toknmon.daemon                      # stop and unload
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.toknmon.daemon.plist   # load again
daemon/.venv/bin/python daemon/claude_usage_daemon.py                  # run in the foreground instead (stop the agent first)
daemon/.venv/bin/python daemon/claude_usage_daemon.py --detect         # print which providers are detected on this Mac
```

Re-running `./install-mac.sh` is safe: it reuses the venv, keeps your config,
re-renders the agents and rebuilds the menu-bar app.

## Configuration file

`~/.config/toknmon/config` is a flat `key = value` file; `#` starts a comment.
Every key is documented in `daemon/config.example`; the README's
[Configuration](../README.md#configuration) table summarizes them. The daemon
re-reads the file on every poll, so edits take effect within about a minute.

## Attention alerts from Claude Code (optional)

When a Claude Code session waits for you (permission prompt, question, idle
prompt after a reply), the Claude corner mascot walks off, a full-size Clawd
walks on and waves, and the message scrolls on the status line. Add these
hooks to `~/.claude/settings.json` (merge into existing hook arrays) and point
the path at your clone. The script needs `jq` (`/usr/bin/jq` on recent macOS,
or `brew install jq`).

```json
{
  "hooks": {
    "Notification": [
      { "matcher": "permission_prompt|idle_prompt|elicitation_dialog",
        "hooks": [{ "type": "command", "command": "/path/to/toknmon/daemon/attention-hook.sh alert" }] }
    ],
    "PreToolUse": [
      { "matcher": "AskUserQuestion",
        "hooks": [{ "type": "command", "command": "/path/to/toknmon/daemon/attention-hook.sh alert" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "/path/to/toknmon/daemon/attention-hook.sh clear" }] }
    ],
    "PostToolUse": [
      { "matcher": "*",
        "hooks": [{ "type": "command", "command": "/path/to/toknmon/daemon/attention-hook.sh clear" }] }
    ]
  }
}
```

The alert clears when you tap the screen, after 2 minutes, or when the
session moves on. It appears about 5 s after the notification (the daemon
checks once per tick) and rides on the Claude payload, so it requires the
Claude provider to be enabled. `beep = on` adds a sound.

## Uninstall

```bash
launchctl bootout gui/$(id -u)/com.toknmon.menubar
rm ~/Library/LaunchAgents/com.toknmon.menubar.plist
rm -rf ~/Applications/ToknMon.app
launchctl bootout gui/$(id -u)/com.toknmon.daemon
rm ~/Library/LaunchAgents/com.toknmon.daemon.plist
rm -rf ~/.config/toknmon ~/Library/Logs/toknmon.*.log
rm -rf daemon/.venv
```

Then forget the board in **System Settings → Bluetooth** if you no longer
want the HID keyboard connection.

## Troubleshooting

See [`troubleshooting.md`](troubleshooting.md): daemon hanging at startup
under `~/Documents`, board not connecting, legacy agent conflicts, Kimi token
problems, stale Grok values, re-pairing after a rename.
