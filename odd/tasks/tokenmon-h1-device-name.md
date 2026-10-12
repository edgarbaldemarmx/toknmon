# TokenMon — H1 Configurable BLE device name

## Objective
Let each user give their device its own Bluetooth name (e.g. "ToknMon Desk One") during setup, so several devices in one office do not all advertise as "Clawdmeter".

## Problem / Why
`DEVICE_NAME` is a compile-time `#define` (`firmware/src/ble.cpp:7`). Teammates flashing the same binary get identical names; macOS shows them indistinguishably. The daemon mostly finds the device by service UUID, but the HID fallback and `blueutil` unpair paths match by name.

## Scope
- Firmware: name stored in NVS (namespace `clawdmeter`, key `dev_name`), default `TokenMon`; read at BLE init; settable via the existing USB serial command parser (`name <string>`), max 18 chars (advertising budget), reboot or re-advertise after set. `name` with no argument prints the current name. Works in `sim` (in-memory Preferences shim).
- Host: `flash-mac.sh` prompts for the name after a successful upload (skippable, remembers last value in `~/.config/claude-usage-monitor/config` as `device_name`) and sends the serial command. `install-mac.sh` prompts for `device_name` and upserts it into config. Daemon reads `device_name` from config (default `TokenMon`, legacy fallback also accepts `Clawdmeter`) for the HID fallback and blueutil matching.
- Tests: daemon config parsing + name matching (pytest). Firmware: sim build + hardware flash + serial round-trip.
- Docs: README section "Naming your device".
- Out of scope: BLE-side name write characteristic; Linux/Windows daemons (note only).

## Constraints
- Branch `feat/tokenmon-h1-device-name` from `feat/tokenmon-h0-baseline`.
- No `#ifdef BOARD_*` in shared code (project rule).
- Name length ≤ 18 bytes ASCII; reject longer with a serial error message.
- The installed upstream daemon runs from `~/Downloads/Clawdmeter` (separate copy); do not touch it.

## Delivery strategy
`ask-on-risk`. Forecast ~250 authored changed lines. Actual: 408+/31- on tracked files plus a 141-line new test file (~580). Over the ~400 heuristic because the flash script gained a self-contained pyserial round-trip (port re-enumeration after `ESP.restart()`), the daemon gained 13 behavior tests, and the README section documents the new flow; none of it is padding and splitting it would separate behavior from its tests/docs.

## Design notes (accepted)
- Name constants live in `firmware/src/ble.h` (`BLE_NAME_NVS_NAMESPACE`, `BLE_NAME_NVS_KEY`, `BLE_DEFAULT_DEVICE_NAME`, `BLE_DEVICE_NAME_MAX_LEN`) so `ble.cpp` (reader) and `main.cpp` (serial writer) share them without touching the sim's `ble_sim.cpp`.
- `name <text>` persists to NVS and calls `ESP.restart()` — chosen over re-advertising because NimBLE fixes the GAP name at `init` and a reboot also drops clients holding the old name. The sim shim provides a no-op `ESP.restart()` (`boards/sim/shim/Arduino.h`), keeping `main.cpp` free of board ifdefs.
- Uses the C-buffer `Preferences::getString(key, char*, size_t)` / `putString(key, const char*)` API so the header-only sim shim does not need an Arduino `String` class.
- Daemon: `DEVICE_NAME` constant replaced by `DEFAULT_DEVICE_NAME="TokenMon"`, `LEGACY_DEVICE_NAMES=("Clawdmeter",)`, `read_device_name()`, `accepted_device_names()`, `is_device_name()`; the generic `read_config_value(key)` helper backs the new key. HID fallback and `unpair_macos` match any accepted name.

## Tasks
- [x] T1 — Firmware: NVS-backed name + serial `name` command + advertising uses it. Route: delegated writer (multi-file). Evidence: `pio run -e sim` SUCCESS, `pio run -e waveshare_amoled_216` SUCCESS (Flash 65.0%), hardware boot log `BLE: name=ToknMon Desk One`, over-long / non-ASCII names answered with `BLE: name rejected (need 1-18 printable ASCII chars)`.
- [x] T2 — Host scripts + daemon `device_name` config + tests. Route: same writer. Evidence: `daemon/tests/test_device_name.py` RED (collection ImportError) → GREEN (13 passed); full suite 137 passed, 2 skipped; `bash -n` clean on both scripts; `flash-mac.sh` non-interactive run wrote `device_name = ToknMon Desk One` to `~/.config/claude-usage-monitor/config`.
- [x] T3 — Verify: `pio run -e sim`, `pio run -e waveshare_amoled_216`, pytest, flash board, set name over serial, confirm advertising name in boot log. Route: writer self-verification + parent spot check. Evidence: see Verification evidence.
- [ ] T4 — README docs + commit. README section "Naming your device" written (`README.md`, macOS installation); commit pending (parent commits).

## Verification
- `pio run -d firmware -e sim`
- `pio run -d firmware -e waveshare_amoled_216`
- `daemon/.venv/bin/python -m pytest daemon/tests -q`
- Flash + serial: `name ToknMon Desk One` → boot log shows `BLE: name=ToknMon Desk One`

## Verification evidence
- `daemon/.venv/bin/python -m pytest daemon/tests/test_device_name.py -q` (before implementation): `1 error during collection` (ImportError on the new symbols) — RED observed.
- `daemon/.venv/bin/python -m pytest daemon/tests -q 2>&1 | tail -5`: `137 passed, 2 skipped, 2 warnings in 0.17s` (13 of them new).
- `~/.platformio/penv/bin/pio run -d firmware -e sim 2>&1 | tail -3`: `sim SUCCESS 00:00:01.147`; `strings .pio/build/sim/program` contains `BLE: name=%s`, `BLE: name rejected…`, `sim: ESP.restart() requested (ignored)`.
- `~/.platformio/penv/bin/pio run -d firmware -e waveshare_amoled_216 2>&1 | tail -4`: `waveshare_amoled_216 SUCCESS`; RAM 32.8%, Flash 65.0%.
- `PATH=~/.platformio/penv/bin:$PATH DEVICE_NAME="ToknMon Desk One" ./flash-mac.sh waveshare_amoled_216 /dev/cu.usbmodem214201`: upload SUCCESS (22.8 s), then
  `board> BLE: name set to "ToknMon Desk One", restarting` / `board> BLE: name=ToknMon Desk One` / `Saved: device_name = ToknMon Desk One -> ~/.config/claude-usage-monitor/config`.
- Boot log after RTS reset (8 s, scratchpad `bootlog_h1.py`): `BLE: name=ToknMon Desk One` precedes `BLE: owner loaded`; upstream daemon (peer `AA:BB:CC:DD:EE:02`, `~/Downloads/Clawdmeter`) reconnected by service UUID and subscribed — name independence confirmed. `name` over serial → `BLE: name=ToknMon Desk One`.
- Rejection on hardware: `name` + 19×`X` and `name Tokén` → `BLE: name rejected (need 1-18 printable ASCII chars)`; stored name unchanged.
- Observed but unrelated: one transient `i2cWrite(): i2c_master_transmit failed: [259] ESP_ERR_INVALID_STATE` during QMI8658 init in that boot (no I2C code touched; QMI8658 still reported `init OK`).
- Not run: interactive prompt paths of `flash-mac.sh` / `install-mac.sh` (only syntax-checked and the validator exercised); the Bluetooth screen's rendering of the longer name on the display was not screenshot-checked.

## Open questions
- `firmware/src/boards/sim/ble_sim.cpp` still returns `"Clawdmeter (sim)"` from `ble_get_device_name()` (outside this task's edit surface); harmless, revisit when renaming the rest of the project.
- Windows/Linux daemons still hardcode "Clawdmeter" (noted as out of scope).

## Next step
Parent: spot-check, commit T1–T3 + README as one work unit (`feat(ble): configurable device name via NVS and serial`), then run `gentle-ai review assess` per the ODD flow.
