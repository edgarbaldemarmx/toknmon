#!/bin/bash
# Build and flash ToknMon firmware on macOS, then (optionally) give the board
# its Bluetooth name.
# Usage:
#   ./flash-mac.sh <board>                             # auto-detect /dev/cu.usbmodem*
#   ./flash-mac.sh <board> /dev/cu.usbmodem1101        # explicit USB serial port
#   ./flash-mac.sh <board> --name "Desk 2"             # non-interactive name
#   DEVICE_NAME="Desk 2" ./flash-mac.sh <board>        # same, via environment
#   ./flash-mac.sh --rename "Desk 2" [port]            # rename an already-flashed
#                                                      # board, no build/upload
#
# <board> is the PlatformIO env name, e.g. waveshare_amoled_216 or waveshare_amoled_18.
#
# After a successful upload the script asks for the device's Bluetooth name
# (default: the last one saved in ~/.config/toknmon/config, else
# "ToknMon"), sends `name <text>` to the firmware over USB serial, echoes the
# board's reply, and records the name as `device_name` in the daemon config.
# Press Enter to keep the default; leave DEVICE_NAME unset in a non-interactive
# shell to skip the naming step entirely.
#
# `--rename` skips the build and upload: it only sends `name <text>` to the board
# that is already running ToknMon firmware and updates the daemon config.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$HOME/.config/toknmon/config"
DEFAULT_NAME="ToknMon"
NAME_MAX_LEN=18
NAME_RULES="1-$NAME_MAX_LEN printable ASCII characters, no '#'; surrounding whitespace is trimmed"

usage() {
    echo "Usage: $0 <board> [port] [--name <bluetooth name>]"
    echo "       $0 --rename <bluetooth name> [port]"
}

BOARD=""
PORT=""
RENAME=""
NAME_ARG="${DEVICE_NAME:-}"
while [ $# -gt 0 ]; do
    case "$1" in
        --name|--rename)
            if [ $# -lt 2 ]; then
                echo "Error: $1 requires a value."
                usage
                exit 1
            fi
            if [ "$1" = "--name" ]; then NAME_ARG="$2"; else RENAME="$2"; fi
            shift 2 ;;
        --name=*)   NAME_ARG="${1#--name=}"; shift ;;
        --rename=*) RENAME="${1#--rename=}"; shift ;;
        -h|--help)  usage; exit 0 ;;
        *)
            if [ -n "$RENAME" ] && [ -z "$PORT" ]; then PORT="$1"
            elif [ -n "$RENAME" ]; then echo "Error: unexpected argument '$1'"; usage; exit 1
            elif [ -z "$BOARD" ]; then BOARD="$1"
            elif [ -z "$PORT" ]; then PORT="$1"
            else echo "Error: unexpected argument '$1'"; usage; exit 1; fi
            shift ;;
    esac
done

if [ -n "$RENAME" ] && [ -n "$BOARD" ]; then
    # `--rename` came after a positional: the positional was the port, not a board.
    if [ -n "$PORT" ]; then echo "Error: unexpected argument '$BOARD'"; usage; exit 1; fi
    PORT="$BOARD"
    BOARD=""
fi

if [ -z "$RENAME" ] && [ -z "$BOARD" ]; then
    # No arguments reads as help: usage, the board list, then a one-line hint.
    usage
    echo ""
    echo "Available boards (PlatformIO env names):"
    grep -E '^\[env:' "$SCRIPT_DIR/firmware/platformio.ini" | sed 's/\[env:/  /;s/\]//'
    echo ""
    echo "Hint: pass a board env name, e.g. $0 waveshare_amoled_216 --name \"Desk\""
    exit 2
fi

if [ -z "$PORT" ]; then
    PORT=$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)
    if [ -z "$PORT" ]; then
        echo "Error: no /dev/cu.usbmodem* device found. Plug in via USB-C."
        exit 1
    fi
fi

if [ -z "$RENAME" ] && ! command -v pio >/dev/null; then
    echo "Error: 'pio' not found. Install with:"
    echo "  brew install platformio"
    exit 1
fi

# --- config helpers (same semantics as install-mac.sh) ---------------------
current_config_value() {
    [ -f "$CONFIG_FILE" ] || return 0
    grep -E "^[[:space:]]*$1[[:space:]]*=" "$CONFIG_FILE" | tail -1 \
        | tr -d '\r' \
        | sed -E "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//; s/[[:space:]]*(#.*)?$//"
}

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

# Send `name <text>` to the board over serial and echo its replies. Uses pio's
# bundled Python when pyserial isn't on the system python (same as screenshot.sh).
# Returns 1 without printing manual instructions (the caller does that once).
send_device_name() {
    local name="$1"
    local py="python3"
    if ! python3 -c "import serial" 2>/dev/null; then
        if [ -x "$HOME/.platformio/penv/bin/python" ]; then
            py="$HOME/.platformio/penv/bin/python"
        else
            echo "  Warning: pyserial not available (neither system python3 nor ~/.platformio/penv)."
            return 1
        fi
    fi
    "$py" - "$PORT" "$name" << 'PYEOF'
import sys, time
import serial

port_path, name = sys.argv[1], sys.argv[2]


def open_port(seconds):
    # The board re-enumerates its USB-JTAG port after flashing and after
    # ESP.restart(); retry until it is back.
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return serial.Serial(port_path, 115200, timeout=0.5)
        except (OSError, serial.SerialException):
            time.sleep(0.5)
    return None


port = open_port(8)
if port is None:
    print(f"  Could not open {port_path}", file=sys.stderr)
    sys.exit(1)
time.sleep(3)  # let the firmware finish booting
port.reset_input_buffer()
port.write(f"name {name}\n".encode("ascii"))
port.flush()
# The firmware confirms with `BLE: name set to "<name>", restarting` BEFORE it
# reboots; that line is the proof the name was persisted. The post-reboot
# `BLE: name=<name>` line is only a bonus: the USB-JTAG port may re-enumerate
# too slowly for us to catch it, so never require it.
end = time.time() + 12
ok = False
while time.time() < end:
    try:
        line = port.readline().decode("utf-8", errors="replace").rstrip()
    except (OSError, serial.SerialException):
        port.close()
        port = open_port(max(1, int(end - time.time())))
        if port is None:
            break
        continue
    if not line:
        continue
    if line.startswith("BLE: name"):
        print(f"  board> {line}")
        if line == f'BLE: name set to "{name}", restarting':
            ok = True
            end = min(end, time.time() + 8)  # wait briefly for the boot line
            continue
        if line == f"BLE: name={name}":
            ok = True
            break
        if "rejected" in line:
            break
if port is not None:
    port.close()
sys.exit(0 if ok else 2)
PYEOF
}

# Validate `$1`, send it to the board and record it in the daemon config.
# Prints the manual fallback exactly once when the serial round-trip fails.
apply_device_name() {
    local chosen
    if ! chosen=$(valid_device_name "$1"); then
        echo "Error: '$1' is not a valid name ($NAME_RULES)."
        exit 1
    fi
    echo "Setting device name to \"$chosen\"..."
    if send_device_name "$chosen"; then
        upsert_config_key device_name "$chosen"
        echo "  Saved: device_name = $chosen  -> $CONFIG_FILE"
    else
        echo "  Could not confirm the new name over serial; set it manually with:"
        echo "    pio device monitor -p $PORT -b 115200   then type:  name $chosen"
        return 1
    fi
}

# --- rename-only mode ------------------------------------------------------
if [ -n "$RENAME" ]; then
    echo "=== Renaming ToknMon ==="
    echo "Port:  $PORT"
    echo ""
    apply_device_name "$RENAME"
    echo ""
    echo "=== Done ==="
    exit 0
fi

echo "=== Flashing ToknMon ==="
echo "Board: $BOARD"
echo "Port:  $PORT"
echo ""

cd "$SCRIPT_DIR/firmware"
pio run -e "$BOARD" -t upload --upload-port "$PORT"

echo ""
echo "=== Upload done ==="

# --- Bluetooth device name -------------------------------------------------
saved_name=$(current_config_value device_name)
default_name="${saved_name:-$DEFAULT_NAME}"
chosen=""
if [ -n "$NAME_ARG" ]; then
    chosen="$NAME_ARG"
elif [ -t 0 ]; then
    echo "Each board can advertise its own Bluetooth name ($NAME_RULES),"
    echo "handy when several ToknMon boards share an office. Press Enter to keep the default."
    read -r -p "Device Bluetooth name [$default_name]: " chosen || chosen=""
    [ -z "$chosen" ] && chosen="$default_name"
else
    echo "Non-interactive shell and DEVICE_NAME unset — keeping the board's current name."
fi

if [ -n "$chosen" ]; then
    apply_device_name "$chosen" || true
fi

echo ""
echo "=== Done ==="
echo "Monitor with: pio device monitor -p $PORT -b 115200"
