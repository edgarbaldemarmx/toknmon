# Using the device

ToknMon has four screens: the **splash** (full-size pixel-art animations),
the **meter** (usage view, one provider at a time), the **app center** and
**Focus** (a block timer) — the last two are described in
[`apps.md`](apps.md). The board boots on the splash and waits for the daemon;
the first payload lights up the meter.

## Touch

| Gesture | On the splash | On the meter |
| --- | --- | --- |
| **Tap** | next animation (within the active set) | next provider; with a single provider, nothing |
| **Swipe up / down** | go to the meter | go to the splash |
| **Swipe left** | next animation | next provider |
| **Swipe right** | previous animation | previous provider |
| **Long-press** | — | **mascot mode** for the provider on screen |

A swipe never counts as a tap: the gesture handler marks the press and the
tap/long-press handlers ignore it (LVGL fires both on the same release).

| Gesture | App center | Focus (setup) | Focus (running) |
| --- | --- | --- | --- |
| **Tap** | on a tile: launch it | right half +5 min, left half −5 min | pause / resume |
| **Swipe up** | — | +5 min | — |
| **Swipe down** | — | −5 min | — |
| **Long-press** | — | — | cancel back to setup |

On boards without a secondary button, a swipe down that starts in the meter's
header (the title row) opens the app center.

## Buttons (Waveshare AMOLED 2.16)

| Button | Where | Splash | Meter |
| --- | --- | --- | --- |
| **PWR** (middle) | AXP2101 power key | next animation | cycle brightness (on Focus: start / start next) |
| **BOOT** (left, GPIO 0) | side | hold: sends **Space** over Bluetooth HID (Claude Code voice-mode push-to-talk) | same |
| **Secondary** (right, GPIO 18) | side | press: open the app center | press: app center ↔ last app |

With `sidebtn hid` (NVS `side_btn = hid`) the secondary button keeps its
legacy role on every screen: it sends **Shift+Tab** over Bluetooth HID
(Claude Code mode toggle) and never opens the app center. The HID keys are
standard Bluetooth keyboard reports: they land in whatever window has focus
on the paired Mac, not only in Claude Code. Boards without a secondary
button open the app center with a swipe down from the meter's header and lack
the Shift+Tab key.

**Pairing mode**: hold PWR for about 3 seconds and release. The board clears
its saved bond and advertises again; pair it from System Settings → Bluetooth.
Holding past 6 seconds cancels the gesture (that is also the AXP2101's hard
power-off threshold at 8 s, so release in time).

## Screens and states

### Splash

Plays Anthropic's Clawd animations (intro → loop → outro) on a 60×60 stage,
picking from a mood group that follows your Claude usage rate: the busier
the pace, the busier the animation. Every 20 s it rotates within the group so
a long stay is not one loop forever. Horizontal swipes, taps and PWR step
through the whole catalog, custom animations included (`claude.bike`).

### Meter

- **Claude**: Current (5h) and Weekly bars, each with "Resets in …"; title
  in clay; a status line
  with the spinner; the clock (`clock = auto|12|24`) in place of the "Usage"
  title; the Clawd corner mascot, which walks off and back, lurks and acts
  depending on the pace.
- **Fable**: when the subscription has a model-scoped weekly limit, it gets
  its own view right after Claude: a 10×10 grid of small Clawds, one per
  percent, filled in clay; the title is the model name the daemon sends
  (`fl`, "Fable" when absent), with the "Weekly" pill and "Resets in …".
  Boards without the dot canvas (the C6 ports) keep it as a third bar on
  the Claude view.
- **Codex**: 10×10 dot grid filled to the weekly percentage, large percentage
  and reset time, a compact 5h bar only if the plan reports one; the three
  dots in the corner.
- **Kimi**: Current and Weekly bars in blue; the moon in the corner.
- **Grok**: the same 10×10 dot grid as Codex, filled to the weekly (or
  monthly) credit percentage, in silver; Grok has no 5-hour window, so there
  is never a 5h row. The white Grokbot-style ball sits in the corner.
- **Carousel**: the meter stays on the provider you picked; tap or swipe
  left/right to page through the fresh slots. The pick is stored on the
  board and restored after a reboot (until that provider's first payload
  lands, the first provider with data stands in). The provider name sits in
  the title in its accent color. A slot is fresh for 90 s after its last
  payload; paging skips stale slots, but the slot you picked stays on screen
  with its last values even when it goes stale. The status
  line reads "Waiting" while no host is connected and alternates "No data" /
  "Listening" when the connection is up but every slot has gone stale.
- **Battery / power**: battery icon with charge state top-right (USB plug
  glyph when running from USB without a battery). The 2.16 auto-rotates with
  its IMU.
- **Attention alert** (Claude Code hooks): the corner mascot leaves, a
  full-size Clawd waves and the message scrolls on the status line; tap to
  dismiss, or it clears when the session moves on.

### Mascot mode

Long-press the meter to pin the splash to the provider on screen. The
provider's full-size set plays in order: for Codex idle → dots → think → bike
→ scene *wave* → scene *rain*; for Kimi idle → glow → sleep → bike → scene
*night* → scene *orbit*; for Grok idle → look → bike → scene
*stars* → scene *build*; Claude keeps the official set. Each entry plays
intro → loop (6 s) → outro, then the next; a tap, a horizontal swipe or PWR
steps manually. The provider name shows top-center in its accent (Claude has
no label, to keep the official look). Swipe vertically to return to the meter.

### Parade

In the parade every provider with live data gets **20 s** of full-size
mascot in turn, Claude with its rate-group pick, Codex, Kimi and Grok with
their sets. Taps step the current animation; the rotation keeps going. A vertical
swipe returns to the meter and stops it. The parade never starts on its own:
the meter stays on screen until you touch it. Start it with the serial
command `parade on`.

### Brightness and idle

PWR on the meter cycles the brightness level (saved in NVS). After a while
without touch the panel dims; any touch restores it.

## Serial QA commands

Open the USB serial console at **115200 baud**
(`pio device monitor -p /dev/cu.usbmodem* -b 115200`) and type:

| Command | Effect | Reply |
| --- | --- | --- |
| `screenshot` | dump the framebuffer (use `./screenshot.sh` instead) | binary |
| `name` | print the Bluetooth name | `BLE: name=<name>` |
| `name <text>` | set the name (1–18 printable ASCII, no `#`) and reboot | `BLE: name set to "<text>", restarting` |
| `screen usage` | show the meter | `ok` |
| `screen apps` / `screen focus` | show the app center / Focus ([`apps.md`](apps.md)) | `ok` |
| `apps [list]` / `sidebtn [apps\|hid]` / `focus <action>` | app center and Focus controls, see [`apps.md`](apps.md) | see there |
| `screen splash` | show the default (Claude) splash | `ok` |
| `screen splash claude\|codex\|kimi\|grok` | mascot mode for that provider | `ok` / `err …` |
| `slot 0-4` | show that view on the meter and make it the picked one (0 Claude, 1 Codex, 2 Kimi, 3 Grok, 4 Fable) | `ok` / `err slot not fresh` |
| `next` | page the carousel | `ok` / `err need usage view and another fresh view` |
| `splash next` / `splash prev` | step the animation (splash on screen) | `ok` / `err splash not on screen` |
| `swipe up\|down\|left\|right` | inject a gesture through the same handlers as touch | `ok` |
| `parade on` / `parade off` | start the parade / back to the meter | `ok` / `err no fresh slot` |
| `buzz` | play the reset chime (boards with audio) | — |

Screenshots without touching the board:

```bash
./screenshot.sh out.png [port]                          # whatever is on screen (480×480 PNG)
./screenshot.sh out.png [port] --screen usage           # switch to the meter first
./screenshot.sh out.png [port] --screen usage:codex     # meter on the Codex slot (`slot 1`; the slot must be fresh)
./screenshot.sh out.png [port] --screen splash:codex    # mascot mode for Codex, then capture
```

`usage:claude|codex|kimi|grok` sends `screen usage` and then `slot 0|1|2|3`. The raw
dump can stall while the board logs BLE traffic, so the script retries the
whole capture up to 3 times (`retrying (n/3)`) and exits non-zero only after
the last failure.

The `screenshot` command needs PSRAM (`LV_USE_SNAPSHOT`), so it is unavailable
on the C6 boards. The simulator has the same UI with keyboard shortcuts and
headless captures: [`simulator.md`](simulator.md).
