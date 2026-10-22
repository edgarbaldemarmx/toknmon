# ToknMon — H12 App center and Focus timer

Objective: the side button opens an app center (Meter, Focus); Focus is a block timer in 5-minute steps with a bell at the end and a daily block counter; the host can enable apps and rename the device over BLE. Branch `feat/suite-h11-h13` (after H11 T2), runners: `pio run -d firmware -e sim|waveshare_amoled_216`, `daemon/.venv/bin/python -m pytest daemon/tests -q`.

## Specs

- **S1** — User (verbatim, L1 in `toknmon-h11-codex-credits-pets.md`): "De alguna forma que aprovechemos más el dispositivo y podamos hacer que con uno de los botones nos lleve a un centro de apps se muéstren ícono de clawd meter y otro de tipo pomodoro para poder poner timers en bloques de 5 en 5 minutos (con el objetivo de tener una sesión de trabajo de enfoque) el usuario puede ir incrementando de 5 en 5 o decrementando para tener un bloque de 5,10,15,20,25,30.... minutos (a la app le podemos llamar focus) y al finalizar que tenga un timbre de finalizado y poder empezar un nuevo bloque de enfoque. En el display muestra el tiempo del bloque y cuántos bloques llevas en el día."
  - **S1.1** App center: new `SCREEN_APPS`. Short press of the side button (GPIO18, `BTN_FWD_GPIO`) toggles between the app center and the last app. The app center shows one icon per enabled app with its name: "Meter" (ToknMon logo/Clawd still) and "Focus" (timer glyph); tap launches. Boards without a secondary button (`BOARD_HAS_SECONDARY_BUTTON 0`) open it with PWR long-tap? No: they get a swipe-down from the usage header as the entry; the 2.16 keeps the side button. The side button's HID Shift+Tab becomes opt-in: NVS `clawdmeter/side_btn` = `apps` (default) | `hid`, serial `sidebtn apps|hid`.
  - **S1.2** Focus app, three states. *Setup*: block length in minutes as a big `MM:00`, default 25, range 5–120 in steps of 5; tap on the right half or swipe up = +5, left half or swipe down = −5; the start button (bottom) or PWR short press starts. *Running*: big `MM:SS` countdown, a ring that empties, "Block N today" line, tap = pause/resume, long press = cancel back to setup (no count). *Done*: the bell plays (existing clip, three times with 400 ms gaps), screen shows "Done · Block N today" and a "Start next" button that starts a new block with the same length; PWR short press does the same.
  - **S1.3** Blocks today: `clawdmeter/fx_cnt` (uint8) and `clawdmeter/fx_day` (YYYYMMDD from the daemon clock `t` when known; `0` when unknown). On a finished block: if the day differs from `fx_day`, reset to 1 and store the day; else increment. Without a clock the counter keeps counting until a clock arrives and the day changes.
  - **S1.4** Timing uses `millis()` deltas, independent of BLE; while Focus runs the idle dimming/sleep is held off and the screen stays on; usage payloads keep updating slots in the background but do not switch screens; alerts (`m`) still show on top.
  - **S1.5** Host control: payload `ap` = comma list of enabled apps (`meter` always; `focus` optional) stored in NVS `clawdmeter/apps`; disabled apps are hidden from the app center, and with only `meter` the side button does nothing (unless `side_btn = hid`). Payload `n` = new device name (1–18 printable ASCII, no `#`): stored in `dev_name` and the board restarts BLE advertising with the new name (restart is acceptable). Both keys are sent by the daemon only when the config value changes (H13 T1). Serial: `apps <list>`, `apps` (print).
  - **S1.6** Sim: `screen apps|focus` and `SIM_SCREEN=apps|focus` for the gallery; docs: `docs/apps.md` (new), `docs/controls.md`, README "Apps" section, CLAUDE.md buttons line.

## Tasks

| ID | Specs | Route | Status | Commit |
| --- | --- | --- | --- | --- |
| T1 | S1.1–S1.4, S1.6 (firmware apps + Focus) | inline or one writer after H11 T2 lands (same `ui.cpp`/`main.cpp`) | open | |
| T2 | S1.5 (`ap`/`n` firmware side) | same unit as T1 | open | |
| T3 | hardware flash, bell test, screenshots, docs | inline (parent) | open | |

## Log

- **L1** See `toknmon-h11-codex-credits-pets.md` L1–L3 (request, research, authorization).
- **L2** Hardware facts (explorer, 2026-10-21): buttons BOOT GPIO0 (HID Space PTT), GPIO18 (HID Shift+Tab), PWR via AXP2101 PKEY (short = next anim / brightness, 3 s hold = pairing); ES8311 codec, one bell clip in `chime.cpp` (`chime_play()` ignores calls while playing); no RTC, wall clock from `t`/`tf` advanced with `lv_tick` (`ui.cpp:1486-1500`); NVS ns `clawdmeter` keys `dev_name`, `brt_idx`, `slot`.
