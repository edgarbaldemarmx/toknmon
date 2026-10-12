#!/bin/bash
# Build and flash TokenMon firmware on macOS, then (optionally) give the board
# its Bluetooth name.
# Usage:
#   ./flash-mac.sh <board>                             # auto-detect /dev/cu.usbmodem*
#   ./flash-mac.sh <board> /dev/cu.usbmodem1101        # explicit USB serial port
#   ./flash-mac.sh <board> --name "ToknMon Desk One"  # non-interactive name
#   DEVICE_NAME="Desk 2" ./flash-mac.sh <board>        # same, via environment
#
# <board> is the PlatformIO env name, e.g. waveshare_amoled_216 or waveshare_amoled_18.
#
# After a successful upload the script asks for the device's Bluetooth name
# (default: the last one saved in ~/.config/claude-usage-monitor/config, else
# "TokenMon"), sends `name <text>` to the firmware over USB serial, echoes the
# board's reply, and records the name as `device_name` in the daemon config.
# Press Enter to keep the default; leave DEVICE_NAME unset in a non-interactive
# shell to skip the naming step entirely.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$HOME/.config/claude-usage-monitor/config"
DEFAULT_NAME="TokenMon"
NAME_MAX_LEN=18

BOARD=""
PORT=""
NAME_ARG="${DEVICE_NAME:-}"
while [ $# -gt 0 ]; do
    case "$1" in
        --name)   NAME_ARG="$2"; shift 2 ;;
        --name=*) NAME_ARG="${1#--name=}"; shift ;;
        *)
            if [ -z "$BOARD" ]; then BOARD="$1"
            elif [ -z "$PORT" ]; then PORT="$1"
            else echo "Error: unexpected argument '$1'"; exit 1; fi
            shift ;;
    esac
done

if [ -z "$BOARD" ]; then
    echo "Error: board env name is required."
    echo "Usage: $0 <board> [port] [--name <bluetooth name>]"
    echo "Available boards:"
    grep -E '^\[env:' "$SCRIPT_DIR/firmware/platformio.ini" | sed 's/\[env:/  /;s/\]//'
    exit 1
fi

if [ -z "$PORT" ]; then
    PORT=$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)
    if [ -z "$PORT" ]; then
        echo "Error: no /dev/cu.usbmodem* device found. Plug in via USB-C."
        exit 1
    fi
fi

if ! command -v pio >/dev/null; then
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

# 1..18 printable ASCII characters (the firmware enforces the same rule).
valid_device_name() {
    local n="$1"
    [ -n "$n" ] || return 1
    [ ${#n} -le $NAME_MAX_LEN ] || return 1
    LC_ALL=C grep -qE '^[ -~]+$' <<< "$n"
}

# Send `name <text>` to the board over serial and echo its replies. Uses pio's
# bundled Python when pyserial isn't on the system python (same as screenshot.sh).
send_device_name() {
    local name="$1"
    local py="python3"
    if ! python3 -c "import serial" 2>/dev/null; then
        if [ -x "$HOME/.platformio/penv/bin/python" ]; then
            py="$HOME/.platformio/penv/bin/python"
        else
            echo "  Warning: pyserial not available; set the name later with:"
            echo "    pio device monitor -p $PORT -b 115200   then type:  name $name"
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
# Echo the firmware's reply, then the first lines of the reboot so the new
# `BLE: name=...` line is visible.
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
        if line == f"BLE: name={name}":
            ok = True
            break
        if "rejected" in line:
            break
sys.exit(0 if ok else 2)
PYEOF
}

echo "=== Flashing TokenMon ==="
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
    echo "Each board can advertise its own Bluetooth name (max $NAME_MAX_LEN ASCII chars),"
    echo "handy when several TokenMons share an office. Press Enter to keep the default."
    read -r -p "Device Bluetooth name [$default_name]: " chosen || chosen=""
    [ -z "$chosen" ] && chosen="$default_name"
else
    echo "Non-interactive shell and DEVICE_NAME unset — keeping the board's current name."
fi

if [ -n "$chosen" ]; then
    if ! valid_device_name "$chosen"; then
        echo "Error: '$chosen' is not a valid name (1-$NAME_MAX_LEN printable ASCII characters)."
        exit 1
    fi
    echo "Setting device name to \"$chosen\"..."
    if send_device_name "$chosen"; then
        upsert_config_key device_name "$chosen"
        echo "  Saved: device_name = $chosen  -> $CONFIG_FILE"
    else
        echo "  Could not confirm the new name over serial; set it manually with:"
        echo "    pio device monitor -p $PORT -b 115200   then type:  name $chosen"
    fi
fi

echo ""
echo "=== Done ==="
echo "Monitor with: pio device monitor -p $PORT -b 115200"
