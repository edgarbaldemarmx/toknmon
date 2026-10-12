# Flashing and naming the board

ToknMon firmware is built and uploaded with PlatformIO. On macOS the
`flash-mac.sh` wrapper builds, uploads, then gives the board its Bluetooth
name over USB serial in one go.

## Supported hardware

| Board | PlatformIO env | Status |
| --- | --- | --- |
| [Waveshare ESP32-S3-Touch-AMOLED-2.16](https://www.waveshare.com/esp32-s3-touch-amoled-2.16.htm) (480×480 CO5300, CST9220 touch, AXP2101 PMU, QMI8658 IMU, ES8311 codec) | `waveshare_amoled_216` | ✅ verified with ToknMon |
| Waveshare ESP32-S3-Touch-AMOLED-1.8 | `waveshare_amoled_18` | ⚠️ inherited from Clawdmeter, builds, untested with ToknMon |
| Waveshare ESP32-C6-Touch-AMOLED-2.16 | `waveshare_amoled_216_c6` | ⚠️ inherited, untested; no PSRAM: no corner mascots, no `screenshot` command |
| Waveshare ESP32-C6-Touch-AMOLED-1.8 | `waveshare_amoled_18_c6` | ⚠️ inherited, untested; no PSRAM |
| Waveshare ESP32-S3-Touch-AMOLED-2.06 | `waveshare_amoled_206` | ⚠️ inherited, untested |
| Waveshare ESP32-S3-Touch-LCD-1.54 | `waveshare_lcd_154` | ⚠️ inherited, untested (240×240) |
| Waveshare ESP32-S3-Touch-LCD-4 | `waveshare_lcd_4` | ⚠️ inherited, untested; one button only |
| Desktop simulator (SDL2) | `sim` | development only, see [`simulator.md`](simulator.md) |

The inherited ports compile in CI but nobody has run ToknMon's multi-provider
UI, mascots or gestures on them since the fork. Reports are welcome
([CONTRIBUTING](../CONTRIBUTING.md)). Pin maps and bring-up notes for every
board are in `CLAUDE.md`.

## Requirements

- **PlatformIO CLI**: `brew install platformio` or `pip install platformio`
  (the scripts also find `~/.platformio/penv/bin/pio`). The first build
  downloads the pioarduino ESP32 platform (Arduino core 3.x) and the library
  dependencies; expect a few minutes.
- A **USB-C data cable**. The boards expose the ESP32-S3 native USB-JTAG, so no
  boot-button dance is needed; the port appears as `/dev/cu.usbmodem*` on macOS
  (`/dev/ttyACM0` on Linux).
- `flash-mac.sh` needs Python with `pyserial` for the naming step; it falls
  back to PlatformIO's bundled interpreter, so nothing extra to install.

## Flash on macOS

```bash
./flash-mac.sh waveshare_amoled_216                              # auto-detects /dev/cu.usbmodem*
./flash-mac.sh waveshare_amoled_216 /dev/cu.usbmodem1101         # explicit port
./flash-mac.sh waveshare_amoled_216 --name "<Your name>"         # non-interactive name
DEVICE_NAME="<Your name>" ./flash-mac.sh waveshare_amoled_216    # same, via environment
./flash-mac.sh                                                   # list the available envs
```

The script runs `pio run -e <env> -t upload`, waits for the board to
re-enumerate, then asks for the Bluetooth name (Enter keeps the default: the
last name saved in `~/.config/toknmon/config`, else `ToknMon`), sends
`name <text>` to the firmware, prints the board's reply and records the name as
`device_name` in `~/.config/toknmon/config` so `install-mac.sh` picks it up.

```text
Device Bluetooth name [ToknMon]: <Your name>
  board> BLE: name set to "<Your name>", restarting
  board> BLE: name=<Your name>
  Saved: device_name = <Your name>  -> ~/.config/toknmon/config
```

Leave `DEVICE_NAME` unset in a non-interactive shell to skip the naming step
entirely.

### Name rules

- 1 to 18 printable ASCII characters (the BLE advertising budget), no `#`
  (it would start a comment in the config file). Surrounding whitespace is
  trimmed. The firmware answers `BLE: name rejected (need 1-18 printable ASCII
  chars, no '#')` otherwise and keeps the old name.
- Stored in the board's flash (NVS), so it survives reflashing. The default
  is `ToknMon`.
- The daemon finds the board by its **service UUID**, not by name. The name
  is what you see in Bluetooth settings and what the HID fallback and
  stale-bond repair match against (`device_name` in the config; the legacy
  names `TokenMon` and `Clawdmeter` are always accepted too).
- **After renaming a paired board, unpair it and pair again**: macOS caches
  the name with the bond.

### Rename without reflashing

```bash
./flash-mac.sh --rename "<New name>" [port]
```

Or open a serial monitor at 115200 baud (`pio device monitor -p /dev/cu.usbmodem* -b 115200`)
and type `name <new name>`; `name` alone prints the current one. The board
reboots to apply it.

## Flash with PlatformIO directly

```bash
pio run -d firmware -e waveshare_amoled_216                                          # build only
pio run -d firmware -e waveshare_amoled_216 -t upload --upload-port /dev/cu.usbmodem101
pio device monitor -p /dev/cu.usbmodem101 -b 115200                                  # serial console
```

The compiled image is `firmware/.pio/build/waveshare_amoled_216/firmware.bin`;
CI uploads the same file as a build artifact on every push.

Linux users can use the inherited `./flash.sh <env> [port]` (defaults to
`/dev/ttyACM0`); it builds and uploads but does not do the naming step, so
set the name over serial afterwards. Windows: `pio run ... -t upload
--upload-port COM5`.

## First boot

The board boots on the splash (Clawd animations), advertises as the name you
chose and waits for the daemon. A fresh flash prints a few benign lines on the
serial console (a core-dump partition size notice and `NVS … NOT_FOUND` for
keys that have never been written). Bonds, the device name and the brightness
level live in NVS namespaces that are unchanged since Clawdmeter, so
upgrading an existing board keeps all three.

Continue with [`install-macos.md`](install-macos.md) to pair and install the
daemon.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No /dev/cu.usbmodem* found` | Use a data cable (not charge-only), try the other USB-C port on the board, or pass the port explicitly. `ls /dev/cu.*` lists candidates. |
| `This chip is ESP32-C6, not ESP32-S3` | You picked an S3 env for a C6 board (or the reverse); use the matching `*_c6` env. |
| Upload succeeds but the naming step times out | The board re-enumerates with a new port number after reset. Re-run `./flash-mac.sh --rename "<name>" <new port>`, or set the name from the serial monitor. |
| `pio: command not found` | `brew install platformio`, or add `~/.platformio/penv/bin` to `PATH`. |
| Screen stays black after flashing | Make sure you flashed the env that matches the board; on the 2.16 a black screen after a successful upload usually means a wrong env. Power-cycle once. |
| Build fails fetching the platform | The pioarduino platform is downloaded from GitHub on first build; retry on a stable connection, or set `PLATFORMIO_CORE_DIR` outside a synced folder. |

More in [`troubleshooting.md`](troubleshooting.md).
