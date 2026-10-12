#pragma once
#include "data.h"
#include "ble.h"

enum screen_t {
    SCREEN_SPLASH,
    SCREEN_USAGE,
    SCREEN_COUNT,
};

void ui_init(void);
// Store a provider's payload in its carousel slot and re-render when that
// slot is the visible one. ui_update() is the legacy single-provider entry
// point: it routes to the slot named by data->provider.
void ui_update_slot(int idx, const UsageData* data);
void ui_update(const UsageData* data);
void ui_tick_anim(void);
// Serial QA hooks. ui_carousel_next() pages like a tap (false unless the live
// usage view is up with 2+ fresh slots); ui_show_slot() brings one provider
// slot on screen (false when out of range or stale).
bool ui_carousel_next(void);
bool ui_show_slot(int idx);
void ui_show_screen(screen_t screen);
void ui_toggle_splash(void);
// Mascot mode: the splash pinned to one provider's play-list (long-press on
// the usage view; serial `screen splash <provider>`). A tap returns to usage,
// which also restores the default Claude splash.
void ui_show_mascot(int slot);
// Parade: the splash cycles every fresh provider's mascot, 20 s each. Starts
// after IDLE_PARADE_MS without input on the usage view, or via serial
// `parade on`. False when no slot is fresh. Any touch ends it.
bool ui_parade_start(void);
// Input bookkeeping for the parade timer. Touches are seen on the input
// device; main.cpp reports physical button presses through this.
void ui_note_activity(void);
screen_t ui_get_current_screen(void);
void ui_update_ble_status(ble_state_t state, const char* name, const char* mac);
void ui_update_battery(int percent, bool charging, bool usb_power);  // percent < 0 = no battery
// Attention: mascot walk-on plus the message on the status line. Ends on a
// tap, after 2 minutes, or ui_hide_alert() when the session moves on.
void ui_show_alert(const char* message);
void ui_hide_alert(void);
