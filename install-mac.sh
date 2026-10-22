#!/bin/bash
# macOS installer for the ToknMon daemon (Python + bleak + launchd).
# Mirrors install.sh but uses LaunchAgents instead of systemd user units.
#
# Usage:
#   ./install-mac.sh                       # interactive (prompts for each setting)
#   ./install-mac.sh --yes --no-prime      # non-interactive, defaults everywhere
#   ./install-mac.sh --yes --providers auto --device-name "Desk 2"
#   ./install-mac.sh --yes --providers claude,codex  # pin an explicit list
#   ./install-mac.sh --yes --apps meter            # meter only, no Focus timer
#
# Options:
#   --yes, -y             Accept the default answer for every prompt. Existing
#                         config values are kept; the permission-priming run is
#                         bounded to a few seconds instead of waiting for Ctrl+C.
#   --providers auto|<list>
#                         'auto' (default) polls every provider whose CLI is
#                         installed and logged in on this Mac, re-checked by the
#                         daemon on every poll (install a CLI later and it shows
#                         up by itself). Or a comma-separated list to pin
#                         (claude, codex, kimi, grok); a listed provider that is not
#                         installed shows "no data" on the device.
#   --device-name <name>  Bluetooth name of the board, as set when flashing
#                         (1-18 printable ASCII characters, no '#').
#   --apps meter|suite    What the device offers: 'suite' (default) is the
#                         usage meter plus the Focus timer in the app center;
#                         'meter' hides Focus and the app center. Stored as the
#                         `apps` config key and pushed to the board over BLE.
#   --no-prime            Skip the Bluetooth permission-priming daemon run.
#   -h, --help            Show this help and exit.
#
# Upgrading from Clawdmeter: the legacy launch agent (com.user.claude-usage-daemon)
# is stopped and its plist moved to ~/.config/toknmon/legacy/, and the legacy
# config under ~/.config/claude-usage-monitor is copied to ~/.config/toknmon
# (never deleted).
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_LABEL="com.toknmon.daemon"
PLIST_SRC="$SCRIPT_DIR/daemon/$SERVICE_LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$SERVICE_LABEL.plist"
LEGACY_LABEL="com.user.claude-usage-daemon"
LEGACY_PLIST="$HOME/Library/LaunchAgents/$LEGACY_LABEL.plist"
VENV_DIR="$SCRIPT_DIR/daemon/.venv"
DAEMON_PY="$SCRIPT_DIR/daemon/claude_usage_daemon.py"
REQUIREMENTS="$SCRIPT_DIR/daemon/requirements-macos.txt"
LOG_DIR="$HOME/Library/Logs"
LOG_OUT="$LOG_DIR/toknmon.out.log"
LOG_ERR="$LOG_DIR/toknmon.err.log"
CONFIG_DIR="$HOME/.config/toknmon"
CONFIG_FILE="$CONFIG_DIR/config"
LEGACY_CONFIG_DIR="$HOME/.config/claude-usage-monitor"
LEGACY_KEEP_DIR="$CONFIG_DIR/legacy"
DEFAULT_DEVICE_NAME="ToknMon"
PRIME_SECONDS=25   # bounded priming run under --yes

usage() {
    sed -n '/^# Usage:/,/^set -e/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

ASSUME_YES=0
NO_PRIME=0
OPT_PROVIDERS=""
OPT_DEVICE_NAME=""
OPT_APPS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1 ;;
        --no-prime) NO_PRIME=1 ;;
        --providers)
            shift
            [ -n "${1:-}" ] || { echo "Error: --providers needs a value (auto, or e.g. claude,codex,kimi,grok)" >&2; exit 2; }
            OPT_PROVIDERS="$1" ;;
        --providers=*) OPT_PROVIDERS="${1#*=}" ;;
        --device-name)
            shift
            [ -n "${1:-}" ] || { echo "Error: --device-name needs a value" >&2; exit 2; }
            OPT_DEVICE_NAME="$1" ;;
        --device-name=*) OPT_DEVICE_NAME="${1#*=}" ;;
        --apps)
            shift
            [ -n "${1:-}" ] || { echo "Error: --apps needs a value (meter or suite)" >&2; exit 2; }
            OPT_APPS="$1" ;;
        --apps=*) OPT_APPS="${1#*=}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; echo "" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# True when we may ask the user questions: a terminal on stdin and no --yes.
interactive() { [ -t 0 ] && [ "$ASSUME_YES" = 0 ]; }

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
    if ! interactive; then
        local list=""
        for d in "${candidates[@]}"; do list="${list:+$list, }$(_tilde "$d")"; done
        echo "  Non-interactive — keeping the default (~/.claude). To poll several, add to $CONFIG_FILE:"
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
    local ans cur
    cur=$(current_config_value clock)
    if ! interactive; then
        if [ -n "$cur" ]; then
            echo "  Clock: $cur (kept)."
        else
            echo "  Clock: off (default)."
        fi
        return 0
    fi
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
    local ans cur
    cur=$(current_config_value chime)
    if ! interactive; then
        if [ -n "$cur" ]; then
            echo "  Chime: $cur (kept)."
        else
            echo "  Chime: off (default)."
        fi
        return 0
    fi
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
# config. Defaults to the saved value, else "ToknMon". `--device-name` sets it
# without asking (an invalid value is an error); `--yes` keeps the default.
configure_device_name() {
    local ans cur def
    cur=$(current_config_value device_name)
    def="${cur:-$DEFAULT_DEVICE_NAME}"
    if [ -n "$OPT_DEVICE_NAME" ]; then
        ans="$OPT_DEVICE_NAME"
        if ! ans=$(valid_device_name "$ans"); then
            echo "Error: --device-name '$OPT_DEVICE_NAME' is invalid (1-18 printable ASCII characters, no '#')." >&2
            exit 2
        fi
    elif ! interactive; then
        ans="$def"
    else
        read -r -p "  Device Bluetooth name (as set when flashing) [$def]: " ans || ans=""
        [ -z "$ans" ] && ans="$def"
        if ! ans=$(valid_device_name "$ans"); then
            echo "  Invalid name (1-18 printable ASCII characters, no '#'; surrounding whitespace is trimmed) — leaving device_name unchanged."
            return 0
        fi
    fi
    if [ "$ans" = "$cur" ]; then
        echo "  device_name = $ans (unchanged)."
        return 0
    fi
    if [ "$ans" = "$DEFAULT_DEVICE_NAME" ] && [ -z "$cur" ]; then
        echo "  device_name = $DEFAULT_DEVICE_NAME (default)."
        return 0
    fi
    upsert_config_key device_name "$ans"
    echo "  Set: device_name = $ans"
}

# Pick which providers the daemon polls (`providers` key). Runs the daemon's
# own detection (`claude_usage_daemon.py --detect`: local files only, no
# network, no Bluetooth) and prints what it found. The default `auto` makes the
# daemon repeat that detection on every poll, so a CLI installed later appears
# on the device without a reinstall. `--providers auto|<list>` sets the key
# without asking (an unknown provider is an error); `--yes` keeps an existing
# value, else `auto`.
configure_providers() {
    local ans cur suggested="auto" explicit=0 detected=0
    local -a found=() missing=() reasons=()
    cur=$(current_config_value providers)

    local line name state
    while IFS= read -r line; do
        name="${line%%:*}"
        state="${line#*: }"
        case "$state" in
            available) found+=("$name"); detected=1 ;;
            "unavailable — "*) missing+=("$name"); reasons+=("${state#unavailable — }"); detected=1 ;;
        esac
    done < <("$PYTHON_BIN" "$DAEMON_PY" --detect 2>/dev/null || true)

    if [ "$detected" = 0 ]; then
        echo "  Provider detection did not answer; choose the providers by hand below."
    else
        echo "  +-- Provider detection (this Mac) -----------------------------------"
        local i
        for name in "${found[@]}"; do
            echo "  | $name: found"
        done
        for i in "${!missing[@]}"; do
            echo "  | ${missing[$i]}: not found"
            echo "  |   ${reasons[$i]}"
            echo "  |   Once it is installed and logged in, 'auto' picks it up on the next"
            echo "  |   poll — no reinstall, no restart."
        done
        echo "  +--------------------------------------------------------------------"
        if [ ${#found[@]} -eq 0 ]; then
            echo "  WARNING: no provider detected. The daemon will install and connect, but the"
            echo "  device stays on its splash screen until a supported CLI (claude, codex,"
            echo "  kimi or grok) is installed and logged in; it is then picked up automatically."
        fi
    fi

    [ -n "$cur" ] && suggested=$(echo "$cur" | tr -d ' ')
    if [ -n "$OPT_PROVIDERS" ]; then
        ans="$OPT_PROVIDERS"; explicit=1
    elif ! interactive; then
        ans="$suggested"
        if [ -n "$cur" ]; then
            echo "  Providers: $ans (kept from config)."
        else
            echo "  Providers: $ans (default)."
        fi
    else
        echo "  'auto' (default) polls whatever is detected above and re-checks on every"
        echo "  poll, so a CLI you install later shows up on the device by itself. Type"
        echo "  an explicit list (e.g. claude,codex) to pin the set instead; a listed"
        echo "  provider that is not installed shows 'no data' on the device."
        read -r -p "  Providers to monitor [auto | claude,codex,kimi,grok] (default $suggested): " ans || ans=""
    fi
    ans=$(echo "${ans:-$suggested}" | tr 'A-Z' 'a-z' | tr -d ' ')
    local p valid=""
    if [ "$ans" = "auto" ]; then
        valid="auto"
    else
        IFS=',' read -r -a parts <<< "$ans"
        for p in "${parts[@]}"; do
            case "$p" in
                claude|codex|kimi|grok) valid="${valid:+$valid, }$p" ;;
                "") ;;
                auto)
                    if [ "$explicit" = 1 ]; then
                        echo "Error: --providers: 'auto' cannot be combined with a list." >&2
                        exit 2
                    fi
                    echo "  'auto' cannot be combined with a list — using auto."
                    valid="auto"; break ;;
                *)
                    if [ "$explicit" = 1 ]; then
                        echo "Error: --providers: unknown provider '$p' (use auto, or claude, codex, kimi, grok)." >&2
                        exit 2
                    fi
                    echo "  Unknown provider '$p' — ignoring." ;;
            esac
        done
    fi
    if [ -n "$cur" ] && [ "$(echo "$valid" | tr -d ' ')" = "$(echo "$cur" | tr -d ' ')" ]; then
        echo "  providers = $valid (unchanged)."
        return 0
    fi
    if [ -z "$valid" ] || [ "$valid" = "auto" ]; then
        if [ -n "$cur" ]; then
            upsert_config_key providers auto
            echo "  Set: providers = auto"
        else
            echo "  Automatic detection (default) — no config change needed."
        fi
        return 0
    fi
    upsert_config_key providers "$valid"
    echo "  Set: providers = $valid"
}

# Pick what the device offers (`apps` key): `suite` = the usage meter plus the
# Focus timer behind the app center (the daemon default when the key is unset),
# `meter` = the meter alone (no app center). The daemon pushes the value to the
# board over BLE whenever it changes. `--apps meter|suite` sets it without
# asking (anything else is an error); `--yes` keeps an existing value, else
# the default.
configure_apps() {
    local ans cur def_label="suite" value
    cur=$(current_config_value apps)
    if [ -n "$OPT_APPS" ]; then
        ans="$OPT_APPS"
    elif ! interactive; then
        ans=""
    else
        local cur_label="$def_label"
        case "$(echo "$cur" | tr -d ' ')" in
            meter) cur_label="meter" ;;
        esac
        echo "  The board can run the usage meter alone, or the full suite:"
        echo "  the meter plus a Focus timer (5-minute blocks) in an app center."
        read -r -p "  Install meter only or the full suite? [suite/meter] [$cur_label]: " ans || ans=""
        [ -z "$ans" ] && ans="$cur_label"
    fi
    case "$(echo "$ans" | tr '[:upper:]' '[:lower:]' | tr -d ' ')" in
        "")      value="" ;;
        suite)   value="meter,focus" ;;
        meter)   value="meter" ;;
        *)
            echo "Error: --apps: unknown value '$ans' (use meter or suite)." >&2
            if [ -n "$OPT_APPS" ]; then exit 2; fi
            echo "  Leaving apps unchanged."
            return 0 ;;
    esac
    if [ -z "$value" ]; then
        if [ -n "$cur" ]; then
            echo "  apps = $cur (unchanged)."
        else
            echo "  apps = meter,focus (default) — no config change needed."
        fi
        return 0
    fi
    if [ "$(echo "$cur" | tr -d ' ')" = "$value" ]; then
        echo "  apps = $value (unchanged)."
        return 0
    fi
    upsert_config_key apps "$value"
    echo "  Set: apps = $value"
}

# Offer the optional attention beep (Claude Code hooks, see the README).
configure_beep() {
    local ans cur
    cur=$(current_config_value beep)
    if ! interactive; then
        if [ -n "$cur" ]; then
            echo "  Beep: $cur (kept)."
        else
            echo "  Beep: off (default)."
        fi
        return 0
    fi
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

# Mirror of the daemon's migrate_legacy_config(): copy the Clawdmeter-era
# config and cached BLE address into ~/.config/toknmon when the new files are
# absent, so the prompts below start from the user's existing settings. The
# legacy files are never deleted.
migrate_legacy_config() {
    [ -d "$LEGACY_CONFIG_DIR" ] || return 0
    local f
    for f in config ble-address; do
        if [ -f "$LEGACY_CONFIG_DIR/$f" ] && [ ! -e "$CONFIG_DIR/$f" ]; then
            mkdir -p "$CONFIG_DIR"
            cp -p "$LEGACY_CONFIG_DIR/$f" "$CONFIG_DIR/$f"
            echo "  Migrated $(_tilde "$LEGACY_CONFIG_DIR/$f") -> $(_tilde "$CONFIG_DIR/$f") (legacy file kept)."
        fi
    done
}

# Stop and park the Clawdmeter-era launch agent so two daemons never fight over
# the board. Its plist is moved (not deleted) to ~/.config/toknmon/legacy/.
retire_legacy_agent() {
    [ -f "$LEGACY_PLIST" ] || return 0
    echo "  Legacy launch agent found: $LEGACY_LABEL"
    if launchctl bootout "gui/$(id -u)/$LEGACY_LABEL" 2>/dev/null; then
        echo "  Stopped $LEGACY_LABEL."
    else
        echo "  $LEGACY_LABEL was not running (bootout skipped)."
    fi
    mkdir -p "$LEGACY_KEEP_DIR"
    mv "$LEGACY_PLIST" "$LEGACY_KEEP_DIR/"
    echo "  Moved $(_tilde "$LEGACY_PLIST") -> $(_tilde "$LEGACY_KEEP_DIR")/"
}

echo "=== ToknMon macOS install ==="
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
"$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS"
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
# providers to poll, which apps the board offers, plus the optional clock
# display, session-reset chime and attention beep. All re-read by the daemon
# each poll.
echo "[4/6] Configuring the daemon..."
migrate_legacy_config
configure_device_name
configure_config_dirs
configure_providers
configure_apps
configure_clock
configure_chime
configure_beep
echo ""

echo "[5/6] Bluetooth permission check..."
if [ "$NO_PRIME" = 1 ]; then
    echo "  Skipped (--no-prime). If macOS never asked for Bluetooth access, run"
    echo "  once in a terminal and grant it when prompted:  $PYTHON_BIN $DAEMON_PY"
elif ! interactive; then
    echo "  On first run the daemon triggers a Bluetooth permission prompt, and"
    echo "  macOS only prompts for foreground processes. Running it for"
    echo "  ${PRIME_SECONDS}s — grant access if prompted."
    "$PYTHON_BIN" "$DAEMON_PY" &
    prime_pid=$!
    ( sleep "$PRIME_SECONDS"; kill "$prime_pid" 2>/dev/null ) >/dev/null 2>&1 &
    prime_killer=$!
    wait "$prime_pid" 2>/dev/null || true
    kill "$prime_killer" 2>/dev/null || true
else
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
    # Watchdog kills a blocked blueutil after 20 s; it is disowned so the
    # shell never prints a "Terminated: 15" job notice for it.
    ( sleep 20; kill "$bu_pid" 2>/dev/null ) >/dev/null 2>&1 &
    bu_killer=$!
    disown "$bu_killer" 2>/dev/null || true
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
retire_legacy_agent
# Modern launchctl vocabulary (bootout/bootstrap, macOS 10.11+); fall back to
# the legacy load/unload pair only if bootstrap is refused on this system.
launchctl bootout "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null || true
if launchctl bootstrap "gui/$(id -u)" "$PLIST_DST" 2>/dev/null; then
    echo "  Loaded (launchctl bootstrap)."
else
    echo "  bootstrap refused; falling back to launchctl load -w."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load -w "$PLIST_DST"
    echo "  Loaded (launchctl load -w)."
fi
echo ""

echo "=== Done ==="
echo ""
echo "First-time Bluetooth pairing (after firmware is flashed):"
echo "  1. Power on the device."
echo "  2. Open System Settings → Bluetooth."
final_name=$(current_config_value device_name)
echo "  3. Click 'Connect' next to '${final_name:-$DEFAULT_DEVICE_NAME}'."
echo "  4. The daemon will discover it within ~30 s and start polling."
echo ""
echo "Useful commands:"
echo "  launchctl list | grep toknmon                          # check it's running"
echo "  tail -F $(_tilde "$LOG_OUT")                       # live logs"
echo "  launchctl kickstart -k gui/\$(id -u)/$SERVICE_LABEL    # restart now"
echo "  launchctl bootout gui/\$(id -u)/$SERVICE_LABEL         # stop and unload"
echo "  launchctl bootstrap gui/\$(id -u) $(_tilde "$PLIST_DST")   # load again"
