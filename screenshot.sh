#!/bin/bash
# Take a screenshot from the Waveshare AMOLED display via LVGL snapshot.
# Usage: ./screenshot.sh [output.png] [port] [--screen <name>]
#   <name>: usage | usage:claude | usage:codex | usage:kimi | usage:grok | usage:fable
#           splash | splash:claude | splash:codex | splash:kimi | splash:grok
# Default port: /dev/cu.usbmodem101 on macOS, /dev/ttyACM0 on Linux.
# --screen sends the firmware's `screen <name>` serial command first, waits
# 300 ms for the redraw, then captures — no button press needed.
# `usage:<provider>` sends `screen usage` and then `slot 0|1|2|3` so the meter
# shows that provider (the slot must hold fresh data); `usage:fable` sends
# `slot 4`, Claude's model-scoped weekly view (needs that limit in the payload). `splash:<provider>`
# opens mascot mode for that provider; bare `splash` is the default Claude
# splash. The colon stands in for the space in the serial command, so no
# quoting is needed.
# The raw dump (460800 bytes at 480x480) can stall when the board is busy
# logging BLE traffic, so the capture is retried up to 3 times before the
# script gives up with a non-zero exit code.

MAX_ATTEMPTS=3

SCREEN=""
SLOT=""
POSITIONAL=()
while [ $# -gt 0 ]; do
    case "$1" in
        --screen)
            case "$2" in
                usage|splash|splash:claude|splash:codex|splash:kimi|splash:grok)
                    SCREEN="${2/:/ }" ;;
                usage:claude) SCREEN="usage"; SLOT=0 ;;
                usage:codex)  SCREEN="usage"; SLOT=1 ;;
                usage:kimi)   SCREEN="usage"; SLOT=2 ;;
                usage:grok)   SCREEN="usage"; SLOT=3 ;;
                usage:fable)  SCREEN="usage"; SLOT=4 ;;
                *)
                    echo "Usage: --screen usage|usage:claude|usage:codex|usage:kimi|usage:grok|usage:fable|splash|splash:claude|splash:codex|splash:kimi|splash:grok" >&2
                    exit 2 ;;
            esac
            shift 2 ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done
set -- "${POSITIONAL[@]}"

OUTPUT="${1:-screenshot.png}"
if [ -z "$2" ]; then
    case "$(uname -s)" in
        Darwin) PORT="/dev/cu.usbmodem101" ;;
        *)      PORT="/dev/ttyACM0" ;;
    esac
else
    PORT="$2"
fi

# Use pio's bundled python if pyserial isn't on the system python.
PY="python3"
if ! python3 -c "import serial" 2>/dev/null; then
    if [ -x "$HOME/.platformio/penv/bin/python" ]; then
        PY="$HOME/.platformio/penv/bin/python"
    fi
fi

TMPRAW=$(mktemp /tmp/screenshot_XXXXXX.raw)
TMPDIMS=$(mktemp /tmp/screenshot_XXXXXX.dims)
trap "rm -f '$TMPRAW' '$TMPDIMS'" EXIT

echo "Taking screenshot from $PORT..."

# One capture attempt. Exit codes: 0 ok, 1 device error / transfer timeout
# (retryable), 3 the port could not be opened (not retryable).
capture() {
"$PY" - "$PORT" "$TMPRAW" "$TMPDIMS" "$SCREEN" "$SLOT" << 'PYEOF'
import serial, sys, time

port_path, raw_path, dims_path, screen, slot = sys.argv[1:6]

# Per-read timeout: a 4 KiB chunk takes ~0.4 s at 115200 baud, so 30 s only
# fires when the board has really stopped sending (e.g. a BLE burst wedged
# the dump), not on an ordinary slow stretch.
try:
    port = serial.Serial(port_path, 115200, timeout=30)
except serial.SerialException as e:
    print(f"Cannot open {port_path}: {e}", file=sys.stderr)
    sys.exit(3)
port.reset_input_buffer()
if screen:
    port.write(f"screen {screen}\n".encode())
    port.flush()
    time.sleep(0.3)
    if slot:
        port.write(f"slot {slot}\n".encode())
        port.flush()
        time.sleep(0.3)
    port.reset_input_buffer()
port.write(b"screenshot\n")
port.flush()

deadline = time.monotonic() + 30
while True:
    line = port.readline().decode("utf-8", errors="replace").strip()
    if line.startswith("SCREENSHOT_START"):
        parts = line.split()
        w, h, raw_size = int(parts[1]), int(parts[2]), int(parts[3])
        break
    if line == "SCREENSHOT_ERR":
        print("Device reported screenshot error", file=sys.stderr)
        sys.exit(1)
    if time.monotonic() > deadline:
        print("Timeout: no SCREENSHOT_START from the device", file=sys.stderr)
        sys.exit(1)

data = b""
while len(data) < raw_size:
    chunk = port.read(min(4096, raw_size - len(data)))
    if not chunk:
        print(f"Timeout: got {len(data)} of {raw_size} bytes", file=sys.stderr)
        sys.exit(1)
    data += chunk

with open(raw_path, "wb") as f:
    f.write(data)
with open(dims_path, "w") as f:
    f.write(f"{w}x{h}\n")

for _ in range(10):
    line = port.readline().decode("utf-8", errors="replace").strip()
    if line == "SCREENSHOT_END":
        break

port.close()
print(f"Captured {w}x{h} ({len(data)} bytes)")
PYEOF
}

attempt=1
while :; do
    capture
    rc=$?
    [ "$rc" -eq 0 ] && break
    if [ "$rc" -eq 3 ] || [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
        echo "Screenshot capture failed after $attempt attempt(s)" >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    echo "Transfer failed, retrying ($attempt/$MAX_ATTEMPTS)..."
    sleep 1
done

DIMS=$(cat "$TMPDIMS")
ffmpeg -y -f rawvideo -pixel_format rgb565le -video_size "$DIMS" \
    -i "$TMPRAW" -update 1 -frames:v 1 "$OUTPUT" 2>/dev/null || true


if [ -f "$OUTPUT" ]; then
    echo "Saved: $OUTPUT ($DIMS)"
else
    echo "Error: conversion failed"
    exit 1
fi
