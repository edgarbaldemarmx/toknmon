# ToknMon — H13 macOS menu-bar app and suite installer

Objective: a native-feeling macOS menu-bar app (Python, rumps + pyobjc) configures the daemon, renames the device and enables apps; the installer lets the user pick "meter only" or the full suite. Branch `feat/suite-h11-h13`, runner: `daemon/.venv/bin/python -m pytest daemon/tests -q`, `bash -n`, shell tests in `tools/test/shell/`.

## Specs

- **S1** — User (verbatim): "1. Me gusta la interfaz para mac tipo app para que la configuración sea en una GUI como en este fork (https://github.com/HermannBjorgvin/Clawdmeter). 2. Que en la GUI tengas la posibilidad de hacer configuraicones que tu quieras como nombrar el device." and "La ventaja o beneficio es que el usuario pueda seleccionar cuando isntale si solo quiere el meter o todo el sutie app completa o que en la GUI pueda seleccionar lo que quiere activar en el device". Decision (2026-10-21, user): "Python menubar" (rumps + pyobjc over the existing daemon, packaged with py2app, DMG in CI).
  - **S1.1** Daemon: new config key `apps = meter` | `meter,focus` (default `meter,focus`), new key `device_name` already exists. On every poll the daemon compares `apps` and `device_name` with the values it last sent (persisted in `~/.config/toknmon/state.json`) and, when different, sends a config payload `{"ap": "...", "n": "..."}` (only the changed keys) before the provider payloads. The daemon also writes `~/.config/toknmon/status.json` after each cycle: timestamp, device connected (bool), per-provider last result (`ok`, `s`, `w`, `f`, `rc`) so the GUI can show status without BLE.
  - **S1.2** Menu-bar app `daemon/gui/menubar.py` (`rumps`): title icon (monochrome template PNG from the Clawd still), menu: per-provider line "Claude · 5h 32 % · week 61 %" (from status.json, "no data" fallback), "Device: <name> · connected/offline", separator, "Device name…" (text dialog, validated 1–18 printable ASCII without `#`, writes `device_name`), "Apps" submenu with checkable "Meter" (always on, disabled) and "Focus", "Providers" submenu (Auto + one checkable per provider), "Sound" submenu (Chime, Beep), "Clock" submenu (Off/Auto/12h/24h), separator, "Restart daemon" (`launchctl kickstart -k`), "Open config file", "Open logs", "About ToknMon", "Quit". All edits go through a small `daemon/gui/config_store.py` that rewrites `key = value` lines in place and preserves comments; the daemon re-reads the config on the next poll so no restart is needed except for providers.
  - **S1.3** Packaging: `tools/build_mac_app.sh` creates `dist/ToknMon.app` with py2app from the venv (Info.plist: `LSUIElement` true, `NSBluetoothAlwaysUsageDescription` not needed because the GUI never opens BLE), ad-hoc `codesign --sign -`, then `dist/ToknMon-<version>.dmg` via `hdiutil`. `install-mac.sh --gui` (default on when py2app builds; `--no-gui` skips) builds and copies the app to `~/Applications/ToknMon.app` and registers `~/Library/LaunchAgents/com.toknmon.menubar.plist` (RunAtLoad). CI: new job `mac-app` on `macos-latest` builds the app and uploads the DMG artifact; failures there do not block the other jobs (`continue-on-error: false` but separate job).
  - **S1.4** Installer: `--apps meter|suite` flag and an interactive question ("Install the meter only or the full suite (meter + Focus timer)?") writing `apps`; `--yes` picks suite. Detection box unchanged.
  - **S1.5** Docs: `docs/gui.md` (new, with a screenshot of the menu), `docs/install-macos.md` (GUI step, `--apps`, `--no-gui`), README (Features bullet + screenshot), CHANGELOG.

## Tasks

| ID | Specs | Route | Status | Commit |
| --- | --- | --- | --- | --- |
| T1 | S1.1 (daemon config payload + status.json) | writer D after H11 T1 (same `claude_usage_daemon.py`) | open | |
| T2 | S1.2, S1.3 (menubar app + packaging) | writer D, same unit (new `daemon/gui/`, `tools/build_mac_app.sh`, `daemon/requirements-macos.txt`, plist) | open | |
| T3 | S1.4, S1.5 (installer, CI, docs) | inline (parent) | open | |
| T4 | first launch with the user (Bluetooth permission is on the daemon, not the GUI; the GUI needs the Accessibility/Automation nothing) and screenshots | parent + user | open | |

## Log

- **L1** See `toknmon-h11-codex-credits-pets.md` L1–L3.
- **L2** Research (2026-10-21): upstream Clawdmeter replaced its Python daemon with a Rust GPUI tray app (`desktop/` crates, btleplug, espflash; DMG ad-hoc signed in CI; config `~/.config/clawdmeter/config` with keys `config_dirs`, `poll_interval`, `reset_chime`, `alert_chime`, `desktop_chime`, `clock`, `liveliness`, `attention_anim`, `pace_marker`, …; no device-name setting). Host: no `cargo`; `swift`/`xcodebuild` only via CommandLineTools; `rumps` not installed. User chose the Python menu-bar route.
