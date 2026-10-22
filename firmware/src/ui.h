#pragma once
#include <lvgl.h>
#include "data.h"
#include "ble.h"

enum screen_t {
    SCREEN_SPLASH,
    SCREEN_USAGE,
    SCREEN_APPS,     // app center (H12): one tile per enabled app
    SCREEN_FOCUS,    // Focus block timer (H12)
    SCREEN_COUNT,
};

void ui_init(void);
// Store a provider's payload in its carousel slot and re-render when that
// slot is the visible one. ui_update() is the legacy single-provider entry
// point: it routes to the slot named by data->provider.
void ui_update_slot(int idx, const UsageData* data);
void ui_update(const UsageData* data);
void ui_tick_anim(void);
// Serial QA hooks. ui_carousel_next() / ui_carousel_prev() page like a tap or
// a horizontal swipe (false unless the live usage view is up and another view
// is fresh); ui_show_slot() brings view `idx` (0..UI_VIEW_COUNT-1) on screen
// (false when out of range or stale). Each of them makes that view the picked
// one: it stays on screen until the next user action and survives a reboot.
bool ui_carousel_next(void);
bool ui_carousel_prev(void);
bool ui_show_slot(int idx);
// Views the carousel pages: 0..PROVIDER_COUNT-1 are the provider slots,
// UI_VIEW_FABLE is Claude's model-scoped weekly limit drawn as Clawds.
#define UI_VIEW_FABLE PROVIDER_COUNT
#define UI_VIEW_COUNT (PROVIDER_COUNT + 1)
// NVS location of the view the user picked (restored at boot).
#define UI_SLOT_NVS_NAMESPACE "clawdmeter"
#define UI_SLOT_NVS_KEY       "slot"
// Swipe handler shared by the LVGL gesture event and serial `swipe <dir>`:
// vertical (LV_DIR_TOP/BOTTOM) toggles splash ↔ usage; LV_DIR_LEFT/RIGHT is
// next/prev animation on the splash, next/prev provider on the usage view.
// False when nothing changed (alert on screen, single provider, ...).
bool ui_handle_swipe(lv_dir_t dir);
void ui_show_screen(screen_t screen);
void ui_toggle_splash(void);
// Mascot mode: the splash pinned to one provider's play-list (long-press on
// the usage view; serial `screen splash <provider>`). Taps and horizontal
// swipes step the set; a vertical swipe returns to usage, which also restores
// the default Claude splash.
void ui_show_mascot(int slot);
// Parade: the splash cycles every fresh provider's mascot, 20 s each. Never
// starts on its own; serial `parade on` starts it. False when no slot is
// fresh. A vertical swipe ends it.
bool ui_parade_start(void);
screen_t ui_get_current_screen(void);
void ui_update_ble_status(ble_state_t state, const char* name, const char* mac);
void ui_update_battery(int percent, bool charging, bool usb_power);  // percent < 0 = no battery
// Attention: mascot walk-on plus the message on the status line. Ends on a
// tap, after 2 minutes, or ui_hide_alert() when the session moves on.
void ui_show_alert(const char* message);
void ui_hide_alert(void);
// ---- App center and Focus (H12, see docs/apps.md) ----
// Side-button action: app center ↔ the last app (usage or Focus); from the
// splash it opens the app center. False (nothing happens) when only Meter is
// enabled (`apps` config) — the caller keeps the button inert then.
bool ui_apps_toggle(void);
// Re-lay the app tiles after apps_set_list() changed the enabled set.
void ui_apps_refresh(void);
// True while a Focus block is counting down (the main loop keeps the panel
// awake, S1.4). Paused and done blocks do not hold the screen.
bool ui_focus_running(void);
// PWR short press while the Focus screen is up mirrors the action button:
// setup → start, running → pause, paused → resume, done → back to setup with
// the same length. False when the press was not consumed (other screens), so
// the caller falls through to its default action.
bool ui_focus_pwr_press(void);
// Serial / sim QA: `focus start|pause|cancel|next|finish|plus|minus` drive
// the same state machine as touch and PWR. `start` starts a block from setup
// or done; `next` is the done screen's "Start next" (back to setup, same
// length); `finish` ends a running block now (counts it, rings the bell).
// False when the action does not apply.
bool ui_focus_command(const char* action);
