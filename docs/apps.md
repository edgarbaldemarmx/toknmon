# Apps: the app center and Focus

Since H12 the board runs more than the meter. The **app center** lists the
enabled apps as tiles; **Meter** is the usage view described in
[`controls.md`](controls.md) and **Focus** is a block timer for focused work
sessions. The host enables apps and renames the board through its config
(see "Host control" below).

## App center

Open it with the **side button** (the secondary button, GPIO 18 on the
Waveshare AMOLED 2.16): a short press toggles between the app center and the
last app you were in (the meter or Focus); from the splash it opens the app
center too. The screen follows the meter's design system (H14): an "Apps"
header with the battery and a hairline, one surface card per app with its
icon and name (Meter in primary text, Focus in its amber), and a footer dot
with "Pick an app". Tap a tile to launch that app.

| Tile | Icon | Opens |
| --- | --- | --- |
| **Meter** | the still Clawd | the usage view (carousel, mascots, alerts) |
| **Focus** | a timer ring with hands | the Focus block timer |

Boards without a secondary button (`BOARD_HAS_SECONDARY_BUTTON 0`, for
example the LCD-4) open the app center with a **swipe down that starts in the
meter's header** (the title row above the panels); a swipe down lower on the
meter still goes to the splash as before.

When only Meter is enabled (host config `apps = meter`) the app center has a
single tile and the side button does nothing. Set `side_btn = hid` to give the
side button its legacy role instead: it then sends **Shift+Tab** over
Bluetooth HID (Claude Code mode toggle) and never opens the app center.

## Focus

A block timer in 5-minute steps, laid out on the meter's design system
(H14, `DESIGN.md` §6 of the design package): the same header as the usage
pages ("Focus" in the app's amber, `TIMER` where the provider label goes,
the battery, the hairline), a ring of radius 120 centred on the panel with
the state label, the time and a supporting line stacked on its centre, one
amber action button under it, and the footer dot with the blocks line. The
screen has four states:

**Setup** (label `SET DURATION`, full amber ring as a preview) shows the
block length as `MM:00` over the word "minutes" (default 25 minutes, 5 to
120 in steps of 5), a **-5** and a **+5** card either side of the ring
(muted at the 5 / 120 bounds), the blocks finished today in the footer, and
the **Start focus** button.

| Action | Effect |
| --- | --- |
| **+5** card / tap the right half / swipe up | +5 minutes |
| **-5** card / tap the left half / swipe down | −5 minutes |
| **Start focus** button / PWR short press | start the block |

**Running** (label `IN PROGRESS`) shows the countdown as `MM:SS` over
"remaining", the ring emptying clockwise from the top in proportion to the
time left of the selected length, "Block N today" in the footer (N counts the
block that is running) with "Hold timer to cancel" at the right, and the
**Pause** button.

| Action | Effect |
| --- | --- |
| **Pause** button / tap elsewhere / PWR short press | pause: the label reads `PAUSED`, the frozen arc and the label turn muted, the button reads **Resume** |
| **Resume** button / tap elsewhere / PWR short press | resume where it left off |
| long press on the ring | cancel back to setup; the block is not counted |

**Done** (label `COMPLETE`): when the countdown reaches zero the bell rings
three times (the session-reset clip, 400 ms apart, on boards with a speaker),
the ring shows its track only, the screen reads `00:00` over "N min
completed", the footer counts the finished block, and the **Start next**
button, or a PWR short press, returns to setup with the same length selected;
the next block starts on another **Start focus**.

The design package also specifies a 1.2 s hold with visible feedback and a
confirmation dialog for cancelling; the firmware keeps the plain long press
of H12 for now.

The countdown runs from the board's own `millis()` clock, so it does not need
the daemon or BLE. While a block is running the panel never dims or sleeps.
Usage payloads keep updating the carousel slots in the background but never
pull the screen away from Focus or the app center; a leaving Focus for the
meter (side button → Meter) keeps the block counting, and the bell rings
wherever you are. Attention alerts (`m`) still show on top: the message
scrolls along the bottom of the Focus and app-center screens and a tap
dismisses it without touching the timer.

### Blocks today

The board keeps the counter in NVS: `clawdmeter/fx_cnt` (blocks finished) and
`clawdmeter/fx_day` (the day they belong to as `YYYYMMDD`, from the daemon's
clock `t`; `0` while no clock has arrived). When a block finishes:

- the day is known and differs from the stored day → the counter restarts at 1
  and the new day is stored;
- otherwise the counter increments; the first known day after a `0` is
  adopted without a reset, so blocks finished before the daemon connected
  still count for that day.

Without a clock the counter keeps growing until a clock arrives and the day
changes. On a new day the setup screen reads "0 blocks today" before the
first block finishes.

## Host control

The daemon sends a config packet, `{"p":"cfg", ...}`, when a config value
changes (H13). It is not a provider payload: it touches no carousel slot and
has no usage side effects.

| Key | Value | Effect |
| --- | --- | --- |
| `ap` | comma list of apps, e.g. `meter,focus` | stored in NVS `clawdmeter/apps`; `meter` is always kept, unknown names are ignored; disabled apps leave the app center |
| `n` | device name, 1–18 printable ASCII without `#` | stored like the serial `name <text>` command; the board restarts so the new name is advertised |

The side-button mode lives in NVS `clawdmeter/side_btn` (`apps`, the default,
or `hid`) and is set from the serial console.

## Serial commands

| Command | Effect | Reply |
| --- | --- | --- |
| `apps` | print the enabled apps | `apps: meter,focus` |
| `apps <list>` | set the enabled apps (`meter` always on) | `apps: <stored list>` |
| `sidebtn` | print the side-button mode | `sidebtn: apps` |
| `sidebtn apps\|hid` | set the side-button mode | `sidebtn: <mode>` / `err sidebtn apps\|hid` |
| `screen apps` / `screen focus` | open the app center / Focus | `ok` |
| `focus start\|pause\|cancel\|next\|finish\|plus\|minus` | drive the timer like touch and PWR would; `start` starts a block from setup or done, `next` is the done screen's **Start next** (back to setup, same length), `finish` ends the running block now (counts it, rings the bell) | `ok` / `err …` |

In the simulator the `n` key is the side button and `SIM_SCREEN=apps|focus`
plus `SIM_FOCUS=start|paused|done` capture the screens headless
([`simulator.md`](simulator.md)).
