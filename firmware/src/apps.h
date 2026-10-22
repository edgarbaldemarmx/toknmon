#pragma once
#include <stdint.h>
#include <stddef.h>

// App center configuration (H12), persisted in the `clawdmeter` NVS namespace:
//   apps      comma list of enabled apps ("meter" always, "focus" optional)
//   side_btn  "apps" (default: the side button toggles the app center) or
//             "hid" (legacy: the side button sends Shift+Tab over HID)
//   fx_cnt    Focus blocks finished on fx_day (uint8)
//   fx_day    YYYYMMDD that fx_cnt belongs to (uint32), 0 = no clock yet
// The host sets the first two through a {"p":"cfg", ...} payload; the serial
// `apps` / `sidebtn` commands do the same by hand.

#define APPS_NVS_NAMESPACE "clawdmeter"
#define APPS_NVS_KEY_APPS  "apps"
#define APPS_NVS_KEY_SIDE  "side_btn"
#define APPS_NVS_KEY_FXCNT "fx_cnt"
#define APPS_NVS_KEY_FXDAY "fx_day"

enum app_id_t { APP_METER = 0, APP_FOCUS = 1, APP_COUNT };

void        apps_init(void);                      // load NVS (call once before ui_init)
bool        apps_enabled(app_id_t app);
int         apps_enabled_count(void);
const char* apps_name(app_id_t app);              // "Meter" / "Focus" (tile label)
const char* apps_short(app_id_t app);             // "meter" / "focus" (wire / NVS id)
// Parse "meter,focus": unknown names are ignored, "meter" is always kept,
// spaces around names are tolerated. Stores the result; returns true when the
// stored set changed.
bool        apps_set_list(const char* csv);
void        apps_list_string(char* buf, size_t len);   // "meter,focus"

bool        apps_side_button_hid(void);           // side_btn == "hid"
bool        apps_set_side_button(const char* mode);    // "apps" | "hid"; false on anything else
const char* apps_side_button_mode(void);          // "apps" / "hid"

void        apps_focus_counter_load(uint8_t* blocks, uint32_t* day);
void        apps_focus_counter_store(uint8_t blocks, uint32_t day);
