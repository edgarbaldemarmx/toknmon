#!/bin/bash
# macOS installer for Clawdmeter daemon (Python + bleak + launchd).
# Mirrors install.sh but uses LaunchAgents instead of systemd user units.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_LABEL="com.user.claude-usage-daemon"
PLIST_SRC="$SCRIPT_DIR/daemon/$SERVICE_LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$SERVICE_LABEL.plist"
VENV_DIR="$SCRIPT_DIR/daemon/.venv"
DAEMON_PY="$SCRIPT_DIR/daemon/claude_usage_daemon.py"
LOG_DIR="$HOME/Library/Logs"
LOG_OUT="$LOG_DIR/claude-usage-daemon.out.log"
LOG_ERR="$LOG_DIR/claude-usage-daemon.err.log"
CONFIG_FILE="$HOME/.config/claude-usage-monitor/config"

# Render an absolute path under $HOME back to a ~ form for tidy config entries.
_tilde() { case "$1" in "$HOME"/*) echo "~${1#"$HOME"}";; *) echo "$1";; esac; }

# Echo the current value of a config key (trimmed), or empty if unset.
current_config_value() {
    [ -f "$CONFIG_FILE" ] || return 0
    grep -E "^[[:space:]]*$1[[:space:]]*=" "$CONFIG_FILE" | tail -1 \
        | tr -d '\r' \
        | sed -E "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//; s/[[:space:]]*(#.*)?$//"
}

# Insert or replace `key = value`, preserving every other key in the file.
upsert_config_key() {
    local key="$1" value="$2"
    mkdir -p "$(dirname "$CONFIG_FILE")"
    touch "$CONFIG_FILE"
    grep -vE "^[[:space:]]*$key[[:space:]]*=" "$CONFIG_FILE" > "$CONFIG_FILE.tmp" 2>/dev/null || true
    mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
    echo "$key = $value" >> "$CONFIG_FILE"
}

# Validate a Bluetooth device name and echo the trimmed value on success.
# Rules: leading/trailing whitespace is trimmed, then the name must be 1-18
# printable ASCII characters (0x20-0x7E, so no newlines or other control
# characters) and must not contain '#' (config readers strip "#..." comments).
# The firmware enforces the same printable-ASCII/length rule.
# NOTE: this function is duplicated verbatim in flash-mac.sh and install-mac.sh;
# keep both copies byte-identical (tools/test/shell/test_device_name_validator.sh
# fails otherwise).
valid_device_name() {
    local n="$1"
    n="${n#"${n%%[![:space:]]*}"}"   # trim leading whitespace
    n="${n%"${n##*[![:space:]]}"}"   # trim trailing whitespace
    [ -n "$n" ] || return 1
    # Any byte left after deleting printable ASCII is a control or non-ASCII
    # character. tr is byte-based under LC_ALL=C and the count survives an
    # embedded newline, unlike a per-line grep or a $(...) that strips it.
    [ $(printf '%s' "$n" | LC_ALL=C tr -d '\040-\176' | wc -c) -eq 0 ] || return 1
    case "$n" in *'#'*) return 1 ;; esac
    [ ${#n} -le 18 ] || return 1
    printf '%s\n' "$n"
}

# Detect ~/.claude* config dirs and, if more than one is found, let the user pick
# which plans to show. The daemon polls all chosen dirs and displays whichever is
# active. macOS note: the default ~/.claude stores its token in Keychain (often no
# .credentials.json file), so it always counts as a candidate; additional dirs are
# recognised by their credentials file — matching the daemon's read_token_for.
configure_config_dirs() {
    local -a candidates=()
    local d
    for d in "$HOME"/.claude*; do
        [ -d "$d" ] || continue
        if [ -f "$d/.credentials.json" ] || [ "$d" = "$HOME/.claude" ]; then
            candidates+=("$d")
        fi
    done

    if [ ${#candidates[@]} -le 1 ]; then
        echo "  One Claude config dir found — using the default (~/.claude)."
        return 0
    fi

    echo "  Found multiple Claude config dirs. The daemon can poll several plans"
    echo "  and show whichever one you're actively using."
    if [ ! -t 0 ]; then
        local list=""
        for d in "${candidates[@]}"; do list="${list:+$list, }$(_tilde "$d")"; done
        echo "  Non-interactive shell — skipping. To enable, add to $CONFIG_FILE:"
        echo "    config_dirs = $list"
        return 0
    fi

    local -a selected=()
    local ans
    for d in "${candidates[@]}"; do
        if [ "$d" = "$HOME/.claude" ]; then
            read -r -p "  Poll $(_tilde "$d")? [Y/n] " ans || ans=""
            if [[ ! "$ans" =~ ^[Nn]$ ]]; then selected+=("$d"); fi
        else
            read -r -p "  Also poll $(_tilde "$d")? [y/N] " ans || ans=""
            if [[ "$ans" =~ ^[Yy]$ ]]; then selected+=("$d"); fi
        fi
    done

    if [ ${#selected[@]} -eq 0 ]; then
        echo "  Nothing selected — leaving the default (~/.claude)."
        return 0
    fi
    if [ ${#selected[@]} -eq 1 ] && [ "${selected[0]}" = "$HOME/.claude" ]; then
        echo "  Default (~/.claude) only — no config change needed."
        return 0
    fi

    local joined="" sd
    for sd in "${selected[@]}"; do joined="${joined:+$joined, }$(_tilde "$sd")"; done

    upsert_config_key config_dirs "$joined"
    echo "  Wrote: config_dirs = $joined"
    echo "  -> $CONFIG_FILE"
}

# Offer the optional clock display (shown in place of the "Usage" title). Only
# writes the key when it actually changes the current/default value.
configure_clock() {
    [ -t 0 ] || return 0
    local ans cur
    cur=$(current_config_value clock)
    read -r -p "  Show a clock instead of the \"Usage\" title? [off/auto/12/24] (default off) " ans || ans=""
    ans=$(echo "$ans" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    [ -z "$ans" ] && ans="off"
    case "$ans" in
        off|auto|12|24) ;;
        *) echo "  Unrecognized '$ans' — leaving clock unchanged."; return 0 ;;
    esac
    if [ "$ans" = "off" ] && { [ -z "$cur" ] || [ "$cur" = "off" ]; }; then
        echo "  Clock off (default)."
        return 0
    fi
    upsert_config_key clock "$ans"
    echo "  Set: clock = $ans"
}

# Offer the optional session-reset chime (sound through the board speaker).
configure_chime() {
    [ -t 0 ] || return 0
    local ans cur
    cur=$(current_config_value chime)
    read -r -p "  Chime through the speaker when your 5h session limit resets? [y/N] " ans || ans=""
    if [[ "$ans" =~ ^[Yy]$ ]]; then
        upsert_config_key chime on
        echo "  Set: chime = on"
    elif [ "$cur" = "on" ]; then
        upsert_config_key chime off
        echo "  Set: chime = off"
    else
        echo "  Chime off (default)."
    fi
}

# Record the board's Bluetooth name so the daemon's HID fallback and stale-bond
# repair match the right device. The name itself lives on the board (set by
# flash-mac.sh or the `name <text>` serial command); this only stores it in the
# config. Defaults to the saved value, else "TokenMon".
configure_device_name() {
    [ -t 0 ] || return 0
    local ans cur def
    cur=$(current_config_value device_name)
    def="${cur:-TokenMon}"
    read -r -p "  Device Bluetooth name (as set when flashing) [$def]: " ans || ans=""
    [ -z "$ans" ] && ans="$def"
    if ! ans=$(valid_device_name "$ans"); then
        echo "  Invalid name (1-18 printable ASCII characters, no '#'; surrounding whitespace is trimmed) — leaving device_name unchanged."
        return 0
    fi
    if [ "$ans" = "$cur" ]; then
        echo "  device_name = $ans (unchanged)."
        return 0
    fi
    if [ "$ans" = "TokenMon" ] && [ -z "$cur" ]; then
        echo "  device_name = TokenMon (default)."
        return 0
    fi
    upsert_config_key device_name "$ans"
    echo "  Set: device_name = $ans"
}

# Pick which providers the daemon polls (`providers` key). Detects Codex and
# Kimi Code installs to suggest a default; Claude is always suggested.
configure_providers() {
    [ -t 0 ] || return 0
    local ans cur suggested="claude" detected=""
    cur=$(current_config_value providers)
    [ -d "$HOME/.codex/sessions" ] && { suggested="$suggested,codex"; detected="$detected Codex"; }
    [ -d "$HOME/.kimi-code/credentials" ] && { suggested="$suggested,kimi"; detected="$detected Kimi"; }
    [ -n "$cur" ] && suggested=$(echo "$cur" | tr -d ' ')
    echo "  The device can cycle through several providers (claude, codex, kimi)."
    [ -n "$detected" ] && echo "  Detected on this Mac:$detected"
    read -r -p "  Providers to monitor [claude,codex,kimi] (default $suggested): " ans || ans=""
    ans=$(echo "${ans:-$suggested}" | tr 'A-Z' 'a-z' | tr -d ' ')
    local p valid=""
    IFS=',' read -r -a parts <<< "$ans"
    for p in "${parts[@]}"; do
        case "$p" in
            claude|codex|kimi) valid="${valid:+$valid, }$p" ;;
            "") ;;
            *) echo "  Unknown provider '$p' — ignoring." ;;
        esac
    done
    if [ -z "$valid" ] || [ "$valid" = "claude" ]; then
        if [ -n "$cur" ]; then
            upsert_config_key providers claude
            echo "  Set: providers = claude"
        else
            echo "  Claude only (default) — no config change needed."
        fi
        return 0
    fi
    upsert_config_key providers "$valid"
    echo "  Set: providers = $valid"
}

# Offer the optional attention beep (Claude Code hooks, see the README).
configure_beep() {
    [ -t 0 ] || return 0
    local ans cur
    cur=$(current_config_value beep)
    read -r -p "  Beep through the speaker when Claude Code needs your attention? [y/N] " ans || ans=""
    if [[ "$ans" =~ ^[Yy]$ ]]; then
        upsert_config_key beep on
        echo "  Set: beep = on"
    elif [ "$cur" = "on" ]; then
        upsert_config_key beep off
        echo "  Set: beep = off"
    else
        echo "  Beep off (default)."
    fi
}

echo "=== Clawdmeter macOS install ==="
echo ""

echo "[1/6] Checking prerequisites..."
command -v curl >/dev/null || { echo "Error: curl is required"; exit 1; }

# The daemon uses Python 3.10+ syntax (PEP 604 `X | None`). macOS ships an
# older system python3 (3.9), so prefer a newer interpreter — Homebrew's if
# present — and fall back to anything on PATH that is >= 3.10.
py_ge_310() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }
PYTHON3=""
for cand in \
    "$(command -v python3.13)" "$(command -v python3.12)" \
    "$(command -v python3.11)" "$(command -v python3.10)" \
    /opt/homebrew/bin/python3 /usr/local/bin/python3 \
    "$(command -v python3)"; do
    [ -n "$cand" ] && [ -x "$cand" ] || continue
    if py_ge_310 "$cand"; then PYTHON3="$cand"; break; fi
done
if [ -z "$PYTHON3" ]; then
    echo "Error: need Python >= 3.10. Install with: brew install python"
    exit 1
fi
echo "  Using $($PYTHON3 --version) at $PYTHON3"
# blueutil lets the daemon auto-recover from a stale BLE bond (CoreBluetooth
# Code=15 "failed to encrypt") after a firmware reflash, without you having to
# manually "Forget This Device". Best-effort: install via Homebrew if present,
# otherwise warn — the daemon degrades gracefully (logs a manual-fix hint).
if ! command -v blueutil >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
        echo "  Installing blueutil (for BLE bond auto-recovery)..."
        brew install blueutil >/dev/null 2>&1 || echo "  Warning: 'brew install blueutil' failed; auto-recovery disabled."
    else
        echo "  Note: blueutil not found and Homebrew is absent. Install blueutil"
        echo "        ('brew install blueutil') to enable automatic recovery from"
        echo "        stale BLE bonds; otherwise you'll forget the device manually."
    fi
fi
if ! security find-generic-password -s "Claude Code-credentials" -a "$USER" -w >/dev/null 2>&1; then
    echo "Warning: Claude Code OAuth token not found in Keychain (service 'Claude Code-credentials')."
    echo "  Sign in via Claude Code first, then re-run this installer."
    echo "  Continuing anyway — the daemon will retry on each poll."
fi
echo "  OK"
echo ""

echo "[2/6] Creating Python virtualenv at daemon/.venv ..."
# Recreate the venv if it's missing or was built with an interpreter older
# than 3.10 (e.g. a previous run that picked the system python3).
if [ -d "$VENV_DIR" ] && ! py_ge_310 "$VENV_DIR/bin/python"; then
    echo "  Existing venv is too old; recreating with $PYTHON3"
    rm -rf "$VENV_DIR"
fi
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON3" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet "bleak>=0.22" "httpx>=0.27"
PYTHON_BIN="$VENV_DIR/bin/python"
echo "  OK ($PYTHON_BIN)"
echo ""

echo "[3/6] Rendering launchd plist..."
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
sed \
    -e "s|__PYTHON_BIN__|${PYTHON_BIN}|g" \
    -e "s|__DAEMON_PATH__|${DAEMON_PY}|g" \
    -e "s|__REPO_DIR__|${SCRIPT_DIR}|g" \
    -e "s|__LOG_OUT__|${LOG_OUT}|g" \
    -e "s|__LOG_ERR__|${LOG_ERR}|g" \
    -e "s|__HOME__|${HOME}|g" \
    "$PLIST_SRC" > "$PLIST_DST"
echo "  Installed: $PLIST_DST"
echo ""

# Interactive daemon configuration: the board's Bluetooth name, which plans and
# providers to poll, plus the optional clock display, session-reset chime and
# attention beep. All re-read by the daemon each poll.
echo "[4/6] Configuring the daemon..."
configure_device_name
configure_config_dirs
configure_providers
configure_clock
configure_chime
configure_beep
echo ""

echo "[5/6] Bluetooth permission check..."
echo "  On first run the daemon will trigger a Bluetooth permission prompt."
echo "  macOS only prompts for foreground processes — so we'll run it"
echo "  interactively once below. Press Ctrl+C after you see 'Scanning...'"
echo "  and grant permission when prompted. Then re-run this installer"
echo "  (or just continue) to enable launchd autostart."
echo ""
read -r -p "Run a permission-priming scan now? [Y/n] " ans
if [[ ! "$ans" =~ ^[Nn]$ ]]; then
    "$PYTHON_BIN" "$DAEMON_PY" || true
fi
echo ""

# blueutil needs its OWN Bluetooth permission (separate identity from the
# Python daemon) to auto-recover from a stale bond. It BLOCKS instead of
# erroring when unauthorized, so prime it now behind a bounded wait: this
# returns instantly if already authorized, or triggers the one-time Bluetooth
# permission prompt (the grant sticks even if we time out before you click).
if command -v blueutil >/dev/null 2>&1; then
    echo "  Priming blueutil's Bluetooth permission (grant if prompted)..."
    blueutil --paired >/dev/null 2>&1 &
    bu_pid=$!
    ( sleep 20; kill "$bu_pid" 2>/dev/null ) >/dev/null 2>&1 &
    bu_killer=$!
    if wait "$bu_pid" 2>/dev/null; then
        echo "  blueutil authorized — stale-bond auto-recovery enabled."
    else
        echo "  blueutil could not access Bluetooth yet. If auto-recovery"
        echo "  fails later, grant it under System Settings > Privacy &"
        echo "  Security > Bluetooth, then re-run: blueutil --paired"
    fi
    kill "$bu_killer" 2>/dev/null || true
fi
echo ""

echo "[6/6] Loading launchd service..."
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load -w "$PLIST_DST"
echo "  Loaded."
echo ""

echo "=== Done ==="
echo ""
echo "First-time Bluetooth pairing (after firmware is flashed):"
echo "  1. Power on the device."
echo "  2. Open System Settings → Bluetooth."
echo "  3. Click 'Connect' next to 'Clawdmeter'."
echo "  4. The daemon will discover it within ~30 s and start polling."
echo ""
echo "Useful commands:"
echo "  launchctl list | grep claude-usage     # check it's running"
echo "  tail -F $LOG_OUT                       # live logs"
echo "  launchctl unload $PLIST_DST            # stop"
echo "  launchctl load -w $PLIST_DST           # start"
