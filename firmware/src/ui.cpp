#include "ui.h"
#include "splash.h"
#include <lvgl.h>
#include <time.h>
#include <esp_heap_caps.h>
#include "logo.h"
#include "clawd_still.h"
#include "icons.h"
#include "hal/board_caps.h"
#include <Preferences.h>

// Custom fonts (scaled for 314 PPI, ~1.9x from original 165 PPI)
LV_FONT_DECLARE(font_tiempos_56);
LV_FONT_DECLARE(font_tiempos_34);
LV_FONT_DECLARE(font_styrene_48);
LV_FONT_DECLARE(font_styrene_28);
LV_FONT_DECLARE(font_styrene_24);
LV_FONT_DECLARE(font_styrene_20);
LV_FONT_DECLARE(font_styrene_16);
LV_FONT_DECLARE(font_styrene_14);
LV_FONT_DECLARE(font_styrene_12);
LV_FONT_DECLARE(font_mono_32);
LV_FONT_DECLARE(font_mono_18);

// Layout values computed from the active board's geometry. Populated once
// in ui_init() and treated as const for the rest of the program. Adding a
// new display size means extending compute_layout() with another
// breakpoint — never editing the screen-builder functions below.
struct Layout {
    int16_t scr_w, scr_h;
    int16_t margin;
    int16_t title_y;
    int16_t content_y;
    int16_t content_w;

    // Usage screen
    int16_t usage_panel_h;
    int16_t usage_panel_gap;
    int16_t usage_bar_y;
    int16_t usage_reset_y;
    int16_t bar_h;
    int16_t panel_pad_x, panel_pad_y;
    int16_t pill_pad_x, pill_pad_y;
    // Dense variant: three stacked panels (session, weekly, scoped weekly)
    // in the same vertical budget as the two normal ones.
    int16_t dense_panel_h;
    int16_t dense_panel_gap;
    int16_t dense_bar_y;
    int16_t dense_reset_y;
    int16_t dense_bar_h;
    int16_t dense_pad_y;
    int16_t dense_pill_pad_x, dense_pill_pad_y;
    const lv_font_t* dense_pct_font;
    const lv_font_t* dense_pill_font;
    const lv_font_t* dense_reset_font;
    // Provider pill shown right of the clock in the title area.
    const lv_font_t* prov_font;
    int16_t prov_pad_x, prov_pad_y;
    int16_t prov_gap;                // gap between the clock and the pill
    const lv_font_t* title_font;     // screen title / clock
    const lv_font_t* pct_font;       // big percentage number
    const lv_font_t* ent_pct_font;   // enterprise spending number
    const lv_font_t* pill_font;      // "Current" / "Weekly" pill
    const lv_font_t* reset_font;     // "Resets in ..." line
    const lv_font_t* pace_font;      // enterprise "Under/On/Over pace" line
    const lv_font_t* anim_font;      // animated status line
    int16_t anim_y;                  // status line offset from bottom
    bool    small_icons;             // 40px logo + 24px battery (vs 80/48) on small screens
    int16_t title_nudge;             // title x-shift balancing the corner logo
    int16_t logo_y;                  // logo top edge
    int16_t batt_y;                  // battery icon top edge
    int16_t batt_w;                  // battery icon width, for position math

    // Pairing hint / idle screen
    int16_t pair_y1, pair_y2, pair_y3;
    int16_t idle_px;                 // sleeping-creature size on the idle screen

    // Bluetooth screen
    int16_t bt_info_panel_h;
    int16_t bt_reset_zone_h;
    const lv_font_t* bt_title_font;
    const lv_font_t* bt_status_font;
    const lv_font_t* bt_device_font;
    const lv_font_t* bt_credit_1_font;
    const lv_font_t* bt_credit_2_font;
};
static Layout L = {};

// Pick layout values from the active board's pixel dimensions. The two
// existing boards happen to land on the two breakpoints below; new ports
// inherit the closer one — visually OK, may need a polish pass for
// pixel-perfect alignment but never blocks the port from booting.
static void compute_layout(const BoardCaps& c) {
    L.scr_w = c.width;
    L.scr_h = c.height;
    L.margin = 20;
    L.title_y = 30;

    // Values shared by the two original breakpoints; the small branch below
    // overrides them wholesale.
    L.bar_h = 24;
    L.panel_pad_x = 16;
    L.panel_pad_y = 12;
    L.pill_pad_x = 18;
    L.pill_pad_y = 6;
    L.title_font   = &font_tiempos_56;
    L.pct_font     = &font_styrene_48;
    L.ent_pct_font = &font_tiempos_56;
    L.pill_font    = &font_styrene_28;
    L.reset_font   = &font_styrene_28;
    L.pace_font    = &font_styrene_16;
    L.anim_font    = &font_mono_32;
    L.anim_y = -15;
    L.small_icons = false;
    L.title_nudge = 16;
    L.logo_y = L.title_y - 10;
    L.batt_y = L.title_y;
    L.batt_w = ICON_BATTERY_W;
    L.pair_y1 = 40;
    L.pair_y2 = 120;
    L.pair_y3 = 160;
    L.idle_px = 160;

    if (c.height >= 460) {
        // Large layout — tuned for 480x480 (AMOLED-2.16).
        L.content_y = 100;
        L.usage_panel_h = 150;
        L.usage_panel_gap = 16;
        L.usage_bar_y = 56;
        L.usage_reset_y = 94;
        // 3 × 100 + 2 × 8 = 316 → panels end at 416, same as the normal pair.
        L.dense_panel_h = 100;
        L.dense_panel_gap = 8;
        L.dense_bar_y = 38;
        L.dense_reset_y = 58;
        L.dense_bar_h = 14;
        L.dense_pad_y = 10;
        L.dense_pill_pad_x = 12;
        L.dense_pill_pad_y = 4;
        L.dense_pct_font   = &font_styrene_28;
        L.dense_pill_font  = &font_styrene_20;
        L.dense_reset_font = &font_styrene_20;
        L.prov_font  = &font_styrene_20;
        L.prov_pad_x = 10;
        L.prov_pad_y = 3;
        L.prov_gap   = 10;
        L.bt_info_panel_h = 160;
        L.bt_reset_zone_h = 110;
        L.bt_title_font    = &font_tiempos_56;
        L.bt_status_font   = &font_styrene_48;
        L.bt_device_font   = &font_styrene_28;
        L.bt_credit_1_font = &font_styrene_24;
        L.bt_credit_2_font = &font_styrene_20;
    } else if (c.height >= 300) {
        // Compact layout — tuned for 368x448 (AMOLED-1.8).
        L.content_y = 85;
        L.usage_panel_h = 130;
        L.usage_panel_gap = 12;
        L.usage_bar_y = 48;
        L.usage_reset_y = 78;
        // 3 × 94 + 2 × 8 = 298 → panels end at 383, clear of the status line.
        L.dense_panel_h = 94;
        L.dense_panel_gap = 8;
        L.dense_bar_y = 36;
        L.dense_reset_y = 54;
        L.dense_bar_h = 12;
        L.dense_pad_y = 8;
        L.dense_pill_pad_x = 10;
        L.dense_pill_pad_y = 3;
        L.dense_pct_font   = &font_styrene_28;
        L.dense_pill_font  = &font_styrene_20;
        L.dense_reset_font = &font_styrene_20;
        L.prov_font  = &font_styrene_16;
        L.prov_pad_x = 8;
        L.prov_pad_y = 2;
        L.prov_gap   = 8;
        L.bt_info_panel_h = 140;
        L.bt_reset_zone_h = 90;
        L.bt_title_font    = &font_tiempos_34;
        L.bt_status_font   = &font_styrene_28;
        L.bt_device_font   = &font_styrene_20;
        L.bt_credit_1_font = &font_styrene_16;
        L.bt_credit_2_font = &font_styrene_14;
    } else {
        // Small layout — tuned for 240x240 (LCD-1.54 and similar square TFTs).
        // Everything shrinks: fonts two steps down, panels ~half height, and
        // the corner logo/battery switch to the 40px/24px small assets.
        L.margin = 8;
        L.title_y = 4;
        L.content_y = 44;
        L.usage_panel_h = 74;
        L.usage_panel_gap = 6;
        L.usage_bar_y = 30;
        L.usage_reset_y = 46;
        // 3 × 50 + 2 × 4 = 158 → panels end at 202, above the status line.
        L.dense_panel_h = 50;
        L.dense_panel_gap = 4;
        L.dense_bar_y = 18;
        L.dense_reset_y = 29;
        L.dense_bar_h = 8;
        L.dense_pad_y = 4;
        L.dense_pill_pad_x = 6;
        L.dense_pill_pad_y = 1;
        L.dense_pct_font   = &font_styrene_14;
        L.dense_pill_font  = &font_styrene_12;
        L.dense_reset_font = &font_styrene_12;
        L.prov_font  = &font_styrene_12;
        L.prov_pad_x = 5;
        L.prov_pad_y = 1;
        L.prov_gap   = 4;
        L.bar_h = 12;
        L.panel_pad_x = 10;
        L.panel_pad_y = 6;
        L.pill_pad_x = 8;
        L.pill_pad_y = 2;
        L.title_font   = &font_tiempos_34;
        L.pct_font     = &font_styrene_24;
        L.ent_pct_font = &font_tiempos_34;
        L.pill_font    = &font_styrene_14;
        L.reset_font   = &font_styrene_14;
        L.pace_font    = &font_styrene_12;
        L.anim_font    = &font_mono_18;
        // Center the status line in the strip below the weekly panel; flush
        // against the bottom edge it reads as unevenly spaced.
        L.anim_y = -10;
        L.small_icons = true;
        L.title_nudge = 8;
        L.logo_y = 2;
        L.batt_y = 10;
        L.batt_w = ICON_BATTERY_SMALL_W;
        L.pair_y1 = 12;
        L.pair_y2 = 56;
        L.pair_y3 = 80;
        L.idle_px = 96;
        L.bt_info_panel_h = 90;
        L.bt_reset_zone_h = 60;
        L.bt_title_font    = &font_tiempos_34;
        L.bt_status_font   = &font_styrene_20;
        L.bt_device_font   = &font_styrene_14;
        L.bt_credit_1_font = &font_styrene_12;
        L.bt_credit_2_font = &font_styrene_12;
    }

    L.content_w = L.scr_w - 2 * L.margin;
}

// Anthropic brand palette — design tokens live in theme.h
#include "theme.h"
#define COL_BG        THEME_BG
#define COL_PANEL     THEME_PANEL
#define COL_TEXT      THEME_TEXT
#define COL_DIM       THEME_DIM
#define COL_ACCENT    THEME_ACCENT
#define COL_GREEN     THEME_GREEN
#define COL_AMBER     THEME_AMBER
#define COL_RED       THEME_RED
#define COL_BAR_BG    THEME_BAR_BG

// ---- Usage screen widgets (single non-splash view) ----
static lv_obj_t* usage_container;
static lv_obj_t* lbl_title;
static lv_obj_t* lbl_provider_pill;   // provider name beside the clock (hidden while the clock is off)
// Clock fed by the daemon: base epoch (local wall-clock seconds) + the lv_tick at
// which it landed, so the title ticks forward locally between 60s payloads.
static long     clock_base_epoch = 0;
static uint32_t clock_base_ms = 0;
static int      clock_fmt = 24;   // 12 or 24, set from the daemon payload
static int      clock_last_min = -1;   // last rendered minute; avoids redrawing the title every tick
static lv_obj_t* usage_group;   // the two usage panels — shown when connected
static lv_obj_t* pair_group;    // pairing hint — shown when disconnected
static lv_obj_t* bar_session;
static lv_obj_t* lbl_session_pct;
static lv_obj_t* lbl_session_label;
static lv_obj_t* lbl_session_reset;
static lv_obj_t* bar_weekly;
static lv_obj_t* lbl_weekly_pct;
static lv_obj_t* lbl_weekly_label;
static lv_obj_t* lbl_weekly_reset;
// Optional third panel: a model-scoped weekly limit (e.g. "Fable"). Shown
// only while the visible slot carries one; the layout goes dense to fit.
static lv_obj_t* bar_third;
static lv_obj_t* lbl_third_pct;
static lv_obj_t* lbl_third_label;
static lv_obj_t* lbl_third_reset;
static lv_obj_t* panel_session = nullptr;
static lv_obj_t* panel_weekly = nullptr;
static lv_obj_t* panel_third = nullptr;
// Usage layouts. BARS is the historical two-panel view, DENSE stacks three
// panels when Claude carries a third bar on a board without the dot canvas,
// DOTS is the Codex and Grok view (a 10×10 dot grid for the weekly window plus
// an optional compact 5h bar) and the Fable view (the same grid drawn as small
// Clawds). See apply_usage_layout().
enum usage_layout_t { LAYOUT_BARS, LAYOUT_DENSE, LAYOUT_DOTS };
static usage_layout_t layout_mode = LAYOUT_BARS;
// Dot grid (LAYOUT_DOTS). The 10×10 dots are drawn into one canvas whose
// pixel buffer lives in PSRAM (100 separate objects would overflow the
// 64 KB LVGL pool through their draw tasks alone). The C6 boards have no
// PSRAM to spare for the buffer, so there Codex and Grok keep the bar layout.
#ifdef BOARD_HAS_PSRAM
static const bool DOTS_AVAILABLE = true;
#else
static const bool DOTS_AVAILABLE = false;
#endif
#define DOT_COUNT 100
#define DOT_COLS  10
static lv_obj_t* dots_group = nullptr;        // transparent container for the whole dots view
static lv_obj_t* dots_canvas = nullptr;       // the grid itself
static uint16_t* dots_buf = nullptr;          // RGB565 pixels, sized for the largest grid
static int       dots_pitch = 0, dots_dia = 0, dots_grid = 0;   // current grid geometry (px)
static int       dots_filled = -1;            // dots currently drawn in the accent color
static int       dots_view = -1;              // view the grid was last drawn for
static lv_obj_t* lbl_dots_pct;                // big weekly percentage
static lv_obj_t* lbl_dots_pill;               // "Weekly" pill
static lv_obj_t* lbl_dots_reset;              // "Resets in …" for the weekly window
static lv_obj_t* bar_dots_session;            // compact 5h bar under the grid
static lv_obj_t* lbl_dots_session;            // "5h - 12% - Resets in …" beside the bar
static bool      dots_with_session = false;   // geometry currently laid out for the 5h row
// Enterprise-only widgets inside panel_session
static lv_obj_t* lbl_session_pct_sym = nullptr;  // "%" in smaller font
static lv_obj_t* lbl_spending_desc = nullptr;     // "of your monthly budget"
static lv_obj_t* lbl_spending_status = nullptr;   // "Under pace" / "On pace" / "Over pace"
static lv_obj_t* lbl_anim;      // status line: connection state + whimsical idle

// ---- Battery indicator (shared, on top) ----
static lv_obj_t* battery_img;
static lv_obj_t* logo_img;
static lv_image_dsc_t battery_dscs[6];  // empty, low, medium, full, charging, plug-zap (no battery)

// ---- Live-data freshness → which usage sub-view to show ----
// usage panels when data is flowing, an idle "Zzz" screen when the host is
// connected but no usage update landed within DATA_FRESH_MS, the pairing hint
// when BLE is down. Re-evaluated every loop in ui_tick_anim().
static lv_obj_t* idle_group;            // the "Zzz" idle screen
static int       view_state = -1;       // -1 unknown / 0 pair / 1 idle / 2 usage
static const uint32_t DATA_FRESH_MS = 90000;  // usage counts as "live" within this window (daemon sends ~60s)

// ---- Provider slots (carousel) ----
// Freshness is tracked per provider: a {"ok":false} beat or a lapsed window on
// one provider only drops that provider out of the rotation. The screen goes
// idle only when no slot is fresh. The carousel shows one slot at a time and
// only moves on a user action (tap, horizontal swipe, serial `next`/`slot`);
// the slot the user picked is stored in NVS and stays on screen even when its
// data lapses. At boot, until the picked slot has data, the first slot that
// receives data stands in for it.
struct SlotState {
    UsageData data;
    uint32_t  last_ms;    // lv_tick when the last ok payload landed
    bool      received;   // any ok payload since boot
    bool      ok;         // last payload's ok flag
};
static SlotState  slots[PROVIDER_COUNT] = {};
static int        visible_view = PROVIDER_CLAUDE;
static bool       data_received = false;     // any ok payload on any slot since boot
static int        picked_view = PROVIDER_CLAUDE;   // the user's choice (NVS)
static bool       fable_seen = false;        // a Claude payload carried the model limit since boot

// ---- Views ----
// The carousel pages views, not providers: one per provider slot plus the
// Fable view (Claude's model-scoped weekly limit as a grid of small Clawds).
// It follows Claude in paging order and exists only while Claude's payload
// carries that limit and the board has the dot canvas. Naming: a slot is a
// provider's stored payload (slots[], ui_update_slot()); a view is a page of
// the carousel. visible_view and picked_view hold view ids
// (UI_VIEW_FABLE = PROVIDER_COUNT); view_provider() maps one to its slot.
static const int VIEW_ORDER[UI_VIEW_COUNT] = {
    PROVIDER_CLAUDE, UI_VIEW_FABLE, PROVIDER_CODEX, PROVIDER_KIMI, PROVIDER_GROK };

static int view_provider(int v) { return v == UI_VIEW_FABLE ? PROVIDER_CLAUDE : v; }

// ---- Parade ----
// The splash parades the full-size mascots of every fresh provider. It never
// starts on its own: the meter stays on screen until the user touches it
// (serial `parade on` starts it for QA). A vertical swipe on the splash ends
// the parade (taps step the animation and leave the rotation running).

static bool slot_fresh(int i) {
    return slots[i].received && slots[i].ok &&
           (lv_tick_get() - slots[i].last_ms) < DATA_FRESH_MS;
}

static int fresh_count(void) {
    int n = 0;
    for (int i = 0; i < PROVIDER_COUNT; i++) if (slot_fresh(i)) n++;
    return n;
}

static bool fable_available(void) {
    return DOTS_AVAILABLE && dots_canvas && slots[PROVIDER_CLAUDE].data.has_third;
}

static bool view_fresh(int v) {
    if (v == UI_VIEW_FABLE) return fable_available() && slot_fresh(PROVIDER_CLAUDE);
    return slot_fresh(v);
}

// Whether the view had data since boot (the boot stand-in ends when it does).
static bool view_received(int v) {
    if (v == UI_VIEW_FABLE) return fable_seen;
    return slots[v].received;
}

static int view_pos(int v) {
    for (int i = 0; i < UI_VIEW_COUNT; i++) if (VIEW_ORDER[i] == v) return i;
    return 0;
}

// Next fresh view after `from` in paging order, or -1 when none is fresh.
static int next_fresh_view(int from) {
    const int pos = view_pos(from);
    for (int k = 1; k <= UI_VIEW_COUNT; k++) {
        int v = VIEW_ORDER[(pos + k) % UI_VIEW_COUNT];
        if (view_fresh(v)) return v;
    }
    return -1;
}

// Previous fresh view before `from` in paging order, or -1 when none is fresh.
static int prev_fresh_view(int from) {
    const int pos = view_pos(from);
    for (int k = 1; k <= UI_VIEW_COUNT; k++) {
        int v = VIEW_ORDER[(pos + UI_VIEW_COUNT - k) % UI_VIEW_COUNT];
        if (view_fresh(v)) return v;
    }
    return -1;
}

// True when a fresh view other than the one on screen exists. The picked
// view stays up after it goes stale, so a stale pick with a single live view
// elsewhere must still page; counting fresh views would block it.
static bool can_page(void) {
    int nxt = next_fresh_view(visible_view);
    return nxt >= 0 && nxt != visible_view;
}

static lv_color_t provider_color(int i) {
    return provider_theme(i).accent;
}

// ---- Shared ----
static lv_image_dsc_t logo_dsc;
static screen_t current_screen = SCREEN_USAGE;
static bool     s_ble_connected = false;   // cached BLE connection state
static uint32_t connected_at_ms = 0;       // when we last entered CONNECTED ("Connected" dwell)

// Animation state
static uint32_t anim_last_ms = 0;
static uint8_t anim_spinner_idx = 0;
static uint8_t anim_phase = 0;
static uint8_t anim_msg_idx = 0;
static uint32_t anim_msg_start = 0;
#define ANIM_MSG_MS     4000

static const char* const spinner_frames[] = {
    "\xC2\xB7", "\xE2\x9C\xBB", "\xE2\x9C\xBD",
    "\xE2\x9C\xB6", "\xE2\x9C\xB3", "\xE2\x9C\xA2",
};
#define SPINNER_COUNT 6
#define SPINNER_PHASES (2 * (SPINNER_COUNT - 1))  // 10: ping-pong 0..5..0

static const uint16_t spinner_ms[SPINNER_COUNT] = {
    260, 130, 130, 130, 130, 260,
};

static const char* const anim_messages[] = {
    "Accomplishing", "Elucidating", "Perusing",
    "Actioning", "Enchanting", "Philosophising",
    "Actualizing", "Envisioning", "Pondering",
    "Baking", "Finagling", "Pontificating",
    "Booping", "Flibbertigibbeting", "Processing",
    "Brewing", "Forging", "Puttering",
    "Calculating", "Forming", "Puzzling",
    "Cerebrating", "Frolicking", "Reticulating",
    "Channelling", "Generating", "Ruminating",
    "Churning", "Germinating", "Scheming",
    "Clauding", "Hatching", "Schlepping",
    "Coalescing", "Herding", "Shimmying",
    "Cogitating", "Honking", "Shucking",
    "Combobulating", "Hustling", "Simmering",
    "Computing", "Ideating", "Smooshing",
    "Concocting", "Imagining", "Spelunking",
    "Conjuring", "Incubating", "Spinning",
    "Considering", "Inferring", "Stewing",
    "Contemplating", "Jiving", "Sussing",
    "Cooking", "Manifesting", "Synthesizing",
    "Crafting", "Marinating", "Thinking",
    "Creating", "Meandering", "Tinkering",
    "Crunching", "Moseying", "Transmuting",
    "Deciphering", "Mulling", "Unfurling",
    "Deliberating", "Mustering", "Unravelling",
    "Determining", "Musing", "Vibing",
    "Discombobulating", "Noodling", "Wandering",
    "Divining", "Percolating", "Whirring",
    "Doing", "Wibbling",
    "Effecting", "Wizarding",
    "Working", "Wrangling",
};
#define ANIM_MSG_COUNT (sizeof(anim_messages) / sizeof(anim_messages[0]))

// Bar fill tier for a percentage, in the given provider's palette.
static lv_color_t pct_color(float pct, int provider) {
    const ProviderTheme th = provider_theme(provider);
    if (pct >= 80.0f) return th.bar_danger;
    if (pct >= 50.0f) return th.bar_warn;
    return th.bar_ok;
}

static void format_reset_time(int mins, char* buf, size_t len) {
    if (mins < 0) {
        snprintf(buf, len, "---");
    } else if (mins < 60) {
        snprintf(buf, len, "Resets in %dm", mins);
    } else if (mins < 1440) {
        snprintf(buf, len, "Resets in %dh %dm", mins / 60, mins % 60);
    } else {
        snprintf(buf, len, "Resets in %dd %dh", mins / 1440, (mins % 1440) / 60);
    }
}

// Forward decls — callbacks defined near ui_show_screen below
static void global_click_cb(lv_event_t* e);
static void usage_tap_cb(lv_event_t* e);
static void usage_long_press_cb(lv_event_t* e);
static void gesture_cb(lv_event_t* e);
static void apply_usage_layout(usage_layout_t mode);
static void layout_dots(bool with_session);
static void dots_geometry(bool with_session, int* pitch, int* dia, int* grid);
static void style_pill_geometry(lv_obj_t* pill, const lv_font_t* font, int16_t px, int16_t py);

static lv_obj_t* make_panel(lv_obj_t* parent, int x, int y, int w, int h) {
    lv_obj_t* panel = lv_obj_create(parent);
    lv_obj_set_pos(panel, x, y);
    lv_obj_set_size(panel, w, h);
    lv_obj_set_style_bg_color(panel, COL_PANEL, 0);
    lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(panel, 8, 0);
    lv_obj_set_style_border_width(panel, 0, 0);
    lv_obj_set_style_pad_left(panel, L.panel_pad_x, 0);
    lv_obj_set_style_pad_right(panel, L.panel_pad_x, 0);
    lv_obj_set_style_pad_top(panel, L.panel_pad_y, 0);
    lv_obj_set_style_pad_bottom(panel, L.panel_pad_y, 0);
    lv_obj_clear_flag(panel, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(panel, LV_OBJ_FLAG_EVENT_BUBBLE);
    return panel;
}

static lv_obj_t* make_bar(lv_obj_t* parent, int x, int y, int w, int h) {
    lv_obj_t* bar = lv_bar_create(parent);
    lv_obj_set_pos(bar, x, y);
    lv_obj_set_size(bar, w, h);
    lv_bar_set_range(bar, 0, 100);
    lv_bar_set_value(bar, 0, LV_ANIM_OFF);
    lv_obj_set_style_bg_color(bar, COL_BAR_BG, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_radius(bar, 6, LV_PART_MAIN);
    lv_obj_set_style_bg_color(bar, COL_GREEN, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_radius(bar, 6, LV_PART_INDICATOR);
    return bar;
}

static void init_icon_dsc_rgb565a8(lv_image_dsc_t* dsc, int w, int h, const uint8_t* data) {
    dsc->header.w = w;
    dsc->header.h = h;
    dsc->header.cf = LV_COLOR_FORMAT_RGB565A8;
    dsc->header.stride = w * 2;
    dsc->data = data;
    dsc->data_size = w * h * 3;
}

static lv_obj_t* make_pill(lv_obj_t* parent, const char* text) {
    lv_obj_t* lbl = lv_label_create(parent);
    lv_label_set_text(lbl, text);
    lv_obj_set_style_text_font(lbl, L.pill_font, 0);
    lv_obj_set_style_text_color(lbl, COL_TEXT, 0);
    lv_obj_set_style_bg_color(lbl, COL_BAR_BG, 0);
    lv_obj_set_style_bg_opa(lbl, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(lbl, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_pad_left(lbl, L.pill_pad_x, 0);
    lv_obj_set_style_pad_right(lbl, L.pill_pad_x, 0);
    lv_obj_set_style_pad_top(lbl, L.pill_pad_y, 0);
    lv_obj_set_style_pad_bottom(lbl, L.pill_pad_y, 0);
    return lbl;
}

static void init_battery_icons(void) {
    if (L.small_icons) {
        init_icon_dsc_rgb565a8(&battery_dscs[0], ICON_BATTERY_SMALL_W, ICON_BATTERY_SMALL_H, icon_battery_small_data);
        init_icon_dsc_rgb565a8(&battery_dscs[1], ICON_BATTERY_LOW_SMALL_W, ICON_BATTERY_LOW_SMALL_H, icon_battery_low_small_data);
        init_icon_dsc_rgb565a8(&battery_dscs[2], ICON_BATTERY_MEDIUM_SMALL_W, ICON_BATTERY_MEDIUM_SMALL_H, icon_battery_medium_small_data);
        init_icon_dsc_rgb565a8(&battery_dscs[3], ICON_BATTERY_FULL_SMALL_W, ICON_BATTERY_FULL_SMALL_H, icon_battery_full_small_data);
        init_icon_dsc_rgb565a8(&battery_dscs[4], ICON_BATTERY_CHARGING_SMALL_W, ICON_BATTERY_CHARGING_SMALL_H, icon_battery_charging_small_data);
        init_icon_dsc_rgb565a8(&battery_dscs[5], ICON_PLUG_ZAP_SMALL_W, ICON_PLUG_ZAP_SMALL_H, icon_plug_zap_small_data);
        return;
    }
    init_icon_dsc_rgb565a8(&battery_dscs[0], ICON_BATTERY_W, ICON_BATTERY_H, icon_battery_data);
    init_icon_dsc_rgb565a8(&battery_dscs[1], ICON_BATTERY_LOW_W, ICON_BATTERY_LOW_H, icon_battery_low_data);
    init_icon_dsc_rgb565a8(&battery_dscs[2], ICON_BATTERY_MEDIUM_W, ICON_BATTERY_MEDIUM_H, icon_battery_medium_data);
    init_icon_dsc_rgb565a8(&battery_dscs[3], ICON_BATTERY_FULL_W, ICON_BATTERY_FULL_H, icon_battery_full_data);
    init_icon_dsc_rgb565a8(&battery_dscs[4], ICON_BATTERY_CHARGING_W, ICON_BATTERY_CHARGING_H, icon_battery_charging_data);
    init_icon_dsc_rgb565a8(&battery_dscs[5], ICON_PLUG_ZAP_W, ICON_PLUG_ZAP_H, icon_plug_zap_data);
}

// ======== Usage Screen ========

static lv_obj_t* make_usage_panel(lv_obj_t* parent, int y, const char* pill_text,
                                  lv_obj_t** out_pct, lv_obj_t** out_pill,
                                  lv_obj_t** out_bar, lv_obj_t** out_reset) {
    lv_obj_t* panel = make_panel(parent, L.margin, y, L.content_w, L.usage_panel_h);

    *out_pct = lv_label_create(panel);
    lv_label_set_text(*out_pct, "---%");
    lv_obj_set_style_text_font(*out_pct, L.pct_font, 0);
    lv_obj_set_style_text_color(*out_pct, COL_TEXT, 0);
    lv_obj_set_pos(*out_pct, 0, 0);

    *out_pill = make_pill(panel, pill_text);
    lv_obj_align(*out_pill, LV_ALIGN_TOP_RIGHT, 0, 1);

    *out_bar = make_bar(panel, 0, L.usage_bar_y,
                        L.content_w - 2 * L.panel_pad_x, L.bar_h);

    *out_reset = lv_label_create(panel);
    lv_label_set_text(*out_reset, "---");
    lv_obj_set_style_text_font(*out_reset, L.reset_font, 0);
    lv_obj_set_style_text_color(*out_reset, COL_DIM, 0);
    lv_obj_set_pos(*out_reset, 0, L.usage_reset_y);

    return panel;
}

// Pairing hint — shown when disconnected so the screen isn't empty and the
// user knows how to (re)pair. Wording matches the 3-second release gesture.
static void build_pair_group(lv_obj_t* parent) {
    pair_group = lv_obj_create(parent);
    lv_obj_set_size(pair_group, L.scr_w, L.scr_h - L.content_y);
    lv_obj_set_pos(pair_group, 0, L.content_y);
    lv_obj_set_style_bg_opa(pair_group, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(pair_group, 0, 0);
    lv_obj_set_style_pad_all(pair_group, 0, 0);
    lv_obj_clear_flag(pair_group, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(pair_group, LV_OBJ_FLAG_EVENT_BUBBLE);

    lv_obj_t* l1 = lv_label_create(pair_group);
    lv_label_set_text(l1, "To pair");
    lv_obj_set_style_text_font(l1, L.bt_status_font, 0);
    lv_obj_set_style_text_color(l1, COL_TEXT, 0);
    lv_obj_align(l1, LV_ALIGN_TOP_MID, 0, L.pair_y1);

    lv_obj_t* l2 = lv_label_create(pair_group);
    lv_label_set_text(l2, "hold the power button");
    lv_obj_set_style_text_font(l2, L.bt_device_font, 0);
    lv_obj_set_style_text_color(l2, COL_DIM, 0);
    lv_obj_align(l2, LV_ALIGN_TOP_MID, 0, L.pair_y2);

    lv_obj_t* l3 = lv_label_create(pair_group);
    lv_label_set_text(l3, "for 3 seconds, then release");
    lv_obj_set_style_text_font(l3, L.bt_device_font, 0);
    lv_obj_set_style_text_color(l3, COL_DIM, 0);
    lv_obj_align(l3, LV_ALIGN_TOP_MID, 0, L.pair_y3);

    lv_obj_add_flag(pair_group, LV_OBJ_FLAG_HIDDEN);  // ui_update_ble_status decides
}

// Idle "Zzz" screen — shown when the host is connected but no usage update has
// landed recently (token expired, daemon down, host asleep…). Full-screen, like
// the pairing hint, so we never render hours-old numbers as if they were live.
static void build_idle_group(lv_obj_t* parent) {
    idle_group = lv_obj_create(parent);
    lv_obj_set_size(idle_group, L.scr_w, L.scr_h - L.content_y);
    lv_obj_set_pos(idle_group, 0, L.content_y);
    lv_obj_set_style_bg_opa(idle_group, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(idle_group, 0, 0);
    lv_obj_set_style_pad_all(idle_group, 0, 0);
    lv_obj_clear_flag(idle_group, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(idle_group, LV_OBJ_FLAG_EVENT_BUBBLE);

    // A shrunk-down resting creature (the official cloud-ride animation)
    // sits between the header and the status line; the animated "Listening…"
    // status line carries the words, so no extra text is needed here.
    lv_obj_t* creature = splash_mini_create(idle_group, "cloud", L.idle_px);
    if (creature) lv_obj_align(creature, LV_ALIGN_CENTER, 0, -20);

    lv_obj_add_flag(idle_group, LV_OBJ_FLAG_HIDDEN);  // update_view_state decides
}

// Codex / Grok dot grid (LAYOUT_DOTS). Everything lives in one transparent container
// so the layout switch is a single show/hide. Objects are created once here;
// layout_dots() places them and show_view() recolors the dots.
static void build_dots_group(lv_obj_t* parent) {
    dots_group = lv_obj_create(parent);
    lv_obj_set_size(dots_group, L.scr_w, L.scr_h);
    lv_obj_set_pos(dots_group, 0, 0);
    lv_obj_set_style_bg_opa(dots_group, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(dots_group, 0, 0);
    lv_obj_set_style_pad_all(dots_group, 0, 0);
    lv_obj_clear_flag(dots_group, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(dots_group, LV_OBJ_FLAG_EVENT_BUBBLE);

    lbl_dots_pct = lv_label_create(dots_group);
    lv_label_set_text(lbl_dots_pct, "---%");
    lv_obj_set_style_text_font(lbl_dots_pct, L.pct_font, 0);
    lv_obj_set_style_text_color(lbl_dots_pct, COL_TEXT, 0);

    lbl_dots_pill = make_pill(dots_group, "Weekly");
    style_pill_geometry(lbl_dots_pill, L.dense_pill_font, L.dense_pill_pad_x, L.dense_pill_pad_y);

    lbl_dots_reset = lv_label_create(dots_group);
    lv_label_set_text(lbl_dots_reset, "---");
    lv_obj_set_style_text_font(lbl_dots_reset, L.dense_reset_font, 0);
    lv_obj_set_style_text_color(lbl_dots_reset, COL_DIM, 0);

    // The buffer is sized for the largest grid (no 5h row) and reused, with a
    // smaller canvas size, when the row is present.
    int pitch, dia, grid;
    dots_geometry(false, &pitch, &dia, &grid);
    dots_buf = (uint16_t*)heap_caps_malloc((size_t)grid * grid * 2, MALLOC_CAP_SPIRAM);
    if (dots_buf) {
        dots_canvas = lv_canvas_create(dots_group);
        lv_canvas_set_buffer(dots_canvas, dots_buf, grid, grid, LV_COLOR_FORMAT_RGB565);
        lv_obj_clear_flag(dots_canvas, LV_OBJ_FLAG_CLICKABLE);   // taps go to the carousel
    }

    bar_dots_session = make_bar(dots_group, 0, 0, 10, L.dense_bar_h);
    lbl_dots_session = lv_label_create(dots_group);
    lv_label_set_text(lbl_dots_session, "");
    lv_obj_set_style_text_font(lbl_dots_session, L.dense_reset_font, 0);
    lv_obj_set_style_text_color(lbl_dots_session, COL_DIM, 0);

    layout_dots(false);
    lv_obj_add_flag(dots_group, LV_OBJ_FLAG_HIDDEN);   // apply_usage_layout decides
}

// Vertical budget of the dots view: from the top of the percentage row to
// just above the status line (which is bottom-aligned at L.anim_y).
static int dots_row_top(void)  { return L.content_y; }
static int dots_grid_top(void) { return L.content_y + lv_font_get_line_height(L.pct_font) + L.usage_panel_gap / 2; }
static int dots_bottom(void)   { return L.scr_h + L.anim_y - lv_font_get_line_height(L.anim_font) - L.panel_pad_y; }

// Grid geometry for the available height: the largest 10×10 square that fits
// between the percentage row and the status line, less the compact 5h row
// when the slot has a session window. Dots are 3/4 of the pitch.
static void dots_geometry(bool with_session, int* pitch, int* dia, int* grid) {
    const int reset_h = lv_font_get_line_height(L.dense_reset_font);
    const int sess_h  = with_session ? (reset_h + L.usage_panel_gap / 2) : 0;
    int avail = dots_bottom() - dots_grid_top() - sess_h;
    if (avail > L.content_w) avail = L.content_w;
    if (avail < DOT_COLS) avail = DOT_COLS;
    *pitch = avail / DOT_COLS;
    *dia   = (*pitch * 3 + 2) / 4;
    *grid  = (DOT_COLS - 1) * *pitch + *dia;
}

// Draw the grid: `filled` dots in the accent, the rest in dot_empty, left to
// right then top to bottom. Drawn one row per layer so the transient draw
// tasks stay small on the LVGL pool.
static void draw_dots(int filled, const ProviderTheme& th) {
    if (!dots_canvas) return;
    lv_canvas_fill_bg(dots_canvas, COL_BG, LV_OPA_COVER);
    lv_draw_rect_dsc_t dsc;
    lv_draw_rect_dsc_init(&dsc);
    dsc.bg_opa = LV_OPA_COVER;
    dsc.radius = LV_RADIUS_CIRCLE;
    dsc.border_width = 0;
    for (int row = 0; row < DOT_COLS; row++) {
        lv_layer_t layer;
        lv_canvas_init_layer(dots_canvas, &layer);
        for (int col = 0; col < DOT_COLS; col++) {
            const int i = row * DOT_COLS + col;
            dsc.bg_color = (i < filled) ? th.accent : th.dot_empty;
            lv_area_t a;
            a.x1 = col * dots_pitch;
            a.y1 = row * dots_pitch;
            a.x2 = a.x1 + dots_dia - 1;
            a.y2 = a.y1 + dots_dia - 1;
            lv_draw_rect(&layer, &dsc, &a);
        }
        lv_canvas_finish_layer(dots_canvas, &layer);
    }
    dots_filled = filled;
    dots_view = visible_view;
}

// Fable view: the same canvas drawn as a 10×10 grid of small Clawds, `filled`
// in Claude's accent and the rest dim. The pixels go straight into the
// canvas buffer (a few thousand rects would flood the LVGL draw pool).
#define CLAWD_GLYPH_W 12
#define CLAWD_GLYPH_H 8
static const char* const CLAWD_GLYPH[CLAWD_GLYPH_H] = {
    "..XXXXXXXX..",
    "..X.XXXX.X..",   // eyes are holes, so they read as ink on black
    "..X.XXXX.X..",
    "XXXXXXXXXXXX",   // arms
    "XXXXXXXXXXXX",
    "..XXXXXXXX..",
    "..X.X..X.X..",   // four legs
    "..X.X..X.X..",
};

static void draw_clawds(int filled, const ProviderTheme& th) {
    if (!dots_canvas) return;
    lv_canvas_fill_bg(dots_canvas, COL_BG, LV_OPA_COVER);
    lv_draw_buf_t* db = lv_canvas_get_draw_buf(dots_canvas);
    const int cell = dots_grid / DOT_COLS;
    int s = cell / CLAWD_GLYPH_W;
    if (s < 1) s = 1;
    const uint16_t on  = lv_color_to_u16(th.accent);
    const uint16_t off = lv_color_to_u16(th.dot_empty);
    for (int i = 0; i < DOT_COUNT; i++) {
        const uint16_t px = (i < filled) ? on : off;
        const int x0 = (i % DOT_COLS) * cell + (cell - CLAWD_GLYPH_W * s) / 2;
        const int y0 = (i / DOT_COLS) * cell + (cell - CLAWD_GLYPH_H * s) / 2;
        for (int gy = 0; gy < CLAWD_GLYPH_H * s; gy++) {
            const int y = y0 + gy;
            if (y < 0 || y >= dots_grid) continue;
            uint16_t* row = (uint16_t*)(db->data + (size_t)y * db->header.stride);
            const char* g = CLAWD_GLYPH[gy / s];
            for (int gx = 0; gx < CLAWD_GLYPH_W * s; gx++) {
                const int x = x0 + gx;
                if (x >= 0 && x < dots_grid && g[gx / s] == 'X') row[x] = px;
            }
        }
    }
    lv_obj_invalidate(dots_canvas);
    dots_filled = filled;
    dots_view = UI_VIEW_FABLE;
}

// The compact 5h bar sits right of its label and takes the rest of the row,
// so it is re-placed whenever the label text changes.
static void place_dots_session_bar(void) {
    const int reset_h = lv_font_get_line_height(L.dense_reset_font);
    const int sess_y  = dots_bottom() - reset_h;
    lv_obj_update_layout(lbl_dots_session);
    const int gap   = L.panel_pad_x;
    int bar_x = L.margin + lv_obj_get_width(lbl_dots_session) + gap;
    int bar_w = L.margin + L.content_w - bar_x;
    if (bar_w < L.content_w / 5) {   // label too long for the row: keep a minimum bar
        bar_w = L.content_w / 5;
        bar_x = L.margin + L.content_w - bar_w;
    }
    lv_obj_set_size(bar_dots_session, bar_w, L.dense_bar_h);
    lv_obj_set_pos(bar_dots_session, bar_x, sess_y + (reset_h - L.dense_bar_h) / 2);
}

// Place the dots view. Top row: big weekly percentage left, "Weekly" pill +
// reset time right. Grid centered in the remaining height; 5h row at the bottom.
static void layout_dots(bool with_session) {
    if (!dots_group) return;
    dots_with_session = with_session;
    const int row_gap = L.usage_panel_gap / 2;
    const int pill_h  = lv_font_get_line_height(L.dense_pill_font) + 2 * L.dense_pill_pad_y;
    const int reset_h = lv_font_get_line_height(L.dense_reset_font);
    const int bottom  = dots_bottom();
    const int grid_top = dots_grid_top();

    lv_obj_set_pos(lbl_dots_pct, L.margin, dots_row_top());
    lv_obj_align(lbl_dots_pill, LV_ALIGN_TOP_RIGHT, -L.margin, dots_row_top());
    lv_obj_align(lbl_dots_reset, LV_ALIGN_TOP_RIGHT, -L.margin, dots_row_top() + pill_h + 4);

    const int sess_h = with_session ? (reset_h + row_gap) : 0;
    const int avail  = bottom - grid_top - sess_h;
    dots_geometry(with_session, &dots_pitch, &dots_dia, &dots_grid);
    if (dots_canvas) {
        // Same buffer, possibly a smaller canvas: the buffer was sized for
        // the no-session grid, which is the larger of the two.
        lv_canvas_set_buffer(dots_canvas, dots_buf, dots_grid, dots_grid, LV_COLOR_FORMAT_RGB565);
        lv_obj_set_pos(dots_canvas, L.margin + (L.content_w - dots_grid) / 2,
                       grid_top + (avail - dots_grid) / 2);
        dots_filled = -1;   // geometry changed → redraw on the next render
    }

    // 5h row: label left, bar filling the rest of the row; see
    // place_dots_session_bar() for the bar, which follows the label width.
    lv_obj_set_pos(lbl_dots_session, L.margin, bottom - reset_h);
    place_dots_session_bar();
    if (with_session) {
        lv_obj_clear_flag(bar_dots_session, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(lbl_dots_session, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(bar_dots_session, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lbl_dots_session, LV_OBJ_FLAG_HIDDEN);
    }
}

static void init_usage_screen(lv_obj_t* scr) {
    usage_container = lv_obj_create(scr);
    lv_obj_set_size(usage_container, L.scr_w, L.scr_h);
    lv_obj_set_pos(usage_container, 0, 0);
    lv_obj_set_style_bg_opa(usage_container, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(usage_container, 0, 0);
    lv_obj_set_style_pad_all(usage_container, 0, 0);
    lv_obj_clear_flag(usage_container, LV_OBJ_FLAG_SCROLLABLE);
    // Tap = next provider (or splash when only one is live); long press =
    // splash always. SHORT_CLICKED, not CLICKED: LVGL also fires CLICKED on
    // the release after a long press, which would double-act.
    lv_obj_add_event_cb(usage_container, usage_tap_cb, LV_EVENT_SHORT_CLICKED, NULL);
    lv_obj_add_event_cb(usage_container, usage_long_press_cb, LV_EVENT_LONG_PRESSED, NULL);

    lbl_title = lv_label_create(usage_container);
    lv_label_set_text(lbl_title, "Usage");
    lv_obj_set_style_text_font(lbl_title, L.title_font, 0);
    lv_obj_set_style_text_color(lbl_title, COL_TEXT, 0);
    // The nudge balances the corner logo on the left; smaller on small
    // screens where the logo is 40px and the battery icon sits closer.
    lv_obj_align(lbl_title, LV_ALIGN_TOP_MID, L.title_nudge, L.title_y);

    // Provider pill: sits right of the clock once the daemon drives the title
    // clock; while the clock is off the title text itself names the provider.
    lbl_provider_pill = lv_label_create(usage_container);
    lv_label_set_text(lbl_provider_pill, provider_name(PROVIDER_CLAUDE));
    lv_obj_set_style_text_font(lbl_provider_pill, L.prov_font, 0);
    lv_obj_set_style_text_color(lbl_provider_pill, COL_TEXT, 0);
    lv_obj_set_style_bg_color(lbl_provider_pill, provider_color(PROVIDER_CLAUDE), 0);
    lv_obj_set_style_bg_opa(lbl_provider_pill, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(lbl_provider_pill, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_pad_left(lbl_provider_pill, L.prov_pad_x, 0);
    lv_obj_set_style_pad_right(lbl_provider_pill, L.prov_pad_x, 0);
    lv_obj_set_style_pad_top(lbl_provider_pill, L.prov_pad_y, 0);
    lv_obj_set_style_pad_bottom(lbl_provider_pill, L.prov_pad_y, 0);
    lv_obj_add_flag(lbl_provider_pill, LV_OBJ_FLAG_HIDDEN);

    // Usage panels (shown when connected) live in a transparent full-size group
    // so they can be toggled against the pairing hint as one unit.
    usage_group = lv_obj_create(usage_container);
    lv_obj_set_size(usage_group, L.scr_w, L.scr_h);
    lv_obj_set_pos(usage_group, 0, 0);
    lv_obj_set_style_bg_opa(usage_group, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(usage_group, 0, 0);
    lv_obj_set_style_pad_all(usage_group, 0, 0);
    lv_obj_clear_flag(usage_group, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(usage_group, LV_OBJ_FLAG_EVENT_BUBBLE);

    panel_session = make_usage_panel(usage_group, L.content_y, "Current",
                     &lbl_session_pct, &lbl_session_label,
                     &bar_session, &lbl_session_reset);

    // Enterprise-only overlays inside panel_session — hidden until enterprise data arrives
    lbl_session_pct_sym = lv_label_create(panel_session);
    lv_label_set_text(lbl_session_pct_sym, "%");
    lv_obj_set_style_text_font(lbl_session_pct_sym, L.reset_font, 0);
    lv_obj_set_style_text_color(lbl_session_pct_sym, COL_TEXT, 0);
    lv_obj_add_flag(lbl_session_pct_sym, LV_OBJ_FLAG_HIDDEN);

    lbl_spending_desc = lv_label_create(panel_session);
    lv_label_set_text(lbl_spending_desc, "of your monthly budget");
    lv_obj_set_style_text_font(lbl_spending_desc, L.reset_font, 0);
    lv_obj_set_style_text_color(lbl_spending_desc, COL_DIM, 0);
    lv_obj_set_pos(lbl_spending_desc, 0, L.usage_reset_y);
    lv_obj_add_flag(lbl_spending_desc, LV_OBJ_FLAG_HIDDEN);

    lbl_spending_status = lv_label_create(panel_session);
    lv_label_set_text(lbl_spending_status, "");
    lv_obj_set_style_text_font(lbl_spending_status, L.pace_font, 0);
    lv_obj_set_pos(lbl_spending_status, 0, L.usage_reset_y + 20);
    lv_obj_add_flag(lbl_spending_status, LV_OBJ_FLAG_HIDDEN);

    panel_weekly = make_usage_panel(usage_group,
                     L.content_y + L.usage_panel_h + L.usage_panel_gap, "Weekly",
                     &lbl_weekly_pct, &lbl_weekly_label,
                     &bar_weekly, &lbl_weekly_reset);
    // Recolor enabled so enterprise period box can color pace and reset separately
    lv_label_set_recolor(lbl_weekly_reset, true);

    // Third panel (scoped weekly limit). Positioned by apply_usage_layout();
    // hidden until a payload with has_third is visible.
    panel_third = make_usage_panel(usage_group,
                     L.content_y + 2 * (L.usage_panel_h + L.usage_panel_gap), "Fable",
                     &lbl_third_pct, &lbl_third_label,
                     &bar_third, &lbl_third_reset);
    lv_obj_add_flag(panel_third, LV_OBJ_FLAG_HIDDEN);

    if (DOTS_AVAILABLE) build_dots_group(usage_group);

    build_pair_group(usage_container);
    build_idle_group(usage_container);

    // Status line — always visible on the usage view. Driven by ui_tick_anim().
    lbl_anim = lv_label_create(usage_container);
    lv_label_set_text(lbl_anim, "");
    lv_obj_set_style_text_font(lbl_anim, L.anim_font, 0);
    lv_obj_set_style_text_color(lbl_anim, COL_ACCENT, 0);
    lv_obj_align(lbl_anim, LV_ALIGN_BOTTOM_MID, 0, L.anim_y);
}

// ---- Attention: the mascot walk-on (splash_mascot_attention) plus the
// message on the status line. Ends on a tap, after 2 minutes, or ui_hide_alert().
static const uint32_t ALERT_TIMEOUT_MS = 120000;
static bool        alert_active = false;
static lv_timer_t* alert_timer;

static void alert_timer_cb(lv_timer_t* t) { (void)t; ui_hide_alert(); }

// Registered on the input device, so it sees every tap. A tap that dismisses
// does nothing else.
static void alert_tap_cb(lv_event_t* e) {
    if (!alert_active) return;
    ui_hide_alert();
    lv_indev_stop_processing((lv_indev_t*)lv_event_get_user_data(e));
}

// Swipe bookkeeping. LVGL 9 keeps sending RELEASED → SHORT_CLICKED → CLICKED
// after a GESTURE (pointer.pressed only records that the press began on the
// object), so a swipe would also count as a tap. The gesture handler raises
// this flag and the tap handlers skip the press; a new press clears it.
static bool gesture_seen = false;

// A new press, on any screen, clears the swipe flag.
static void activity_press_cb(lv_event_t* e) {
    (void)e;
    gesture_seen = false;
}

static void init_alert(void) {
    alert_timer = lv_timer_create(alert_timer_cb, ALERT_TIMEOUT_MS, NULL);
    lv_timer_pause(alert_timer);
    lv_indev_t* indev = lv_indev_get_next(NULL);
    if (indev) lv_indev_add_event_cb(indev, alert_tap_cb, LV_EVENT_CLICKED, indev);
    if (indev) lv_indev_add_event_cb(indev, activity_press_cb, LV_EVENT_PRESSED, NULL);
    lv_obj_set_style_text_align(lbl_anim, LV_TEXT_ALIGN_CENTER, 0);
}

// ======== Public API ========

static int load_picked_view(void);

void ui_init(void) {
    compute_layout(board_caps());

    lv_obj_t* scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, COL_BG, 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);

#ifndef BOARD_HAS_PSRAM
    // Static corner mascot (see clawd_still.h) — the animated one needs PSRAM.
    if (L.small_icons) init_icon_dsc_rgb565a8(&logo_dsc, CLAWD_STILL_SMALL_W, CLAWD_STILL_SMALL_H, clawd_still_small_data);
    else               init_icon_dsc_rgb565a8(&logo_dsc, CLAWD_STILL_W, CLAWD_STILL_H, clawd_still_data);
#endif
    init_battery_icons();

    init_usage_screen(scr);
    splash_init(scr);

    if (splash_get_root()) {
        lv_obj_add_event_cb(splash_get_root(), global_click_cb, LV_EVENT_CLICKED, NULL);
    }
    // Gestures bubble (LV_OBJ_FLAG_GESTURE_BUBBLE, default on) from the splash
    // root and the usage container up to the screen, so one handler there
    // covers both views; it dispatches on current_screen.
    lv_obj_add_event_cb(scr, gesture_cb, LV_EVENT_GESTURE, NULL);

    // Corner mascot in the old logo slot. The still Clawd is shorter than the
    // 80/40 px slot the spark logo used; center it vertically in that slot.
    {
        const int slot  = L.small_icons ? LOGO_SMALL_HEIGHT : LOGO_HEIGHT;
        const int art_h = L.small_icons ? CLAWD_STILL_SMALL_H : CLAWD_STILL_H;
        const int top   = L.logo_y + (slot - art_h) / 2;
#ifdef BOARD_HAS_PSRAM
        // Animated: idles, does acts, and takes walk-off/lurk trips.
        splash_mascot_create(scr, L.margin, top + art_h, L.small_icons ? 2 : 3);
#else
        logo_img = lv_image_create(scr);
        lv_image_set_src(logo_img, &logo_dsc);
        lv_obj_set_pos(logo_img, L.margin, top);
#endif
    }

    battery_img = lv_image_create(scr);
    lv_image_set_src(battery_img, &battery_dscs[0]);
    lv_obj_set_pos(battery_img, L.scr_w - L.batt_w - L.margin, L.batt_y);
    // Boards without battery telemetry never show the indicator (per the HAL
    // contract; previously every board drew the empty-battery glyph).
    if (!board_caps().has_battery) {
        lv_obj_del(battery_img);
        battery_img = nullptr;
    }

    init_alert();
    apply_usage_layout(LAYOUT_BARS);
    picked_view = load_picked_view();
    visible_view = picked_view;
}

// ---- Title area: clock + provider ----
// With the clock off, the title text is the provider name in its accent color
// ("Usage" until the first payload). With the clock on, the title is the time
// and the provider rides in a small accent pill to its right; both are
// re-centered as one unit so the pair stays balanced against the corner logo.
static void layout_title(void) {
    bool pill = (clock_base_epoch > 0) && data_received;
    if (!pill) {
        lv_obj_add_flag(lbl_provider_pill, LV_OBJ_FLAG_HIDDEN);
        lv_obj_align(lbl_title, LV_ALIGN_TOP_MID, L.title_nudge, L.title_y);
        return;
    }
    lv_obj_clear_flag(lbl_provider_pill, LV_OBJ_FLAG_HIDDEN);
    lv_obj_update_layout(lbl_provider_pill);
    int32_t pw = lv_obj_get_width(lbl_provider_pill);
    lv_obj_align(lbl_title, LV_ALIGN_TOP_MID, L.title_nudge - (pw + L.prov_gap) / 2, L.title_y);
    lv_obj_update_layout(lbl_title);
    lv_obj_align_to(lbl_provider_pill, lbl_title, LV_ALIGN_OUT_RIGHT_MID, L.prov_gap, 0);
}

// Title of the visible view: the provider name, or the model label on the
// Fable view.
static const char* view_title(int v) {
    if (v != UI_VIEW_FABLE) return provider_name(v);
    const char* label = slots[PROVIDER_CLAUDE].data.third_label;
    return label[0] ? label : "Fable";
}

static void refresh_title(void) {
    const int prov = view_provider(visible_view);
    if (clock_base_epoch > 0) {
        lv_obj_set_style_text_color(lbl_title, COL_TEXT, 0);
        lv_label_set_text(lbl_provider_pill, view_title(visible_view));
        lv_obj_set_style_bg_color(lbl_provider_pill, provider_color(prov), 0);
        lv_obj_set_style_text_color(lbl_provider_pill, provider_theme(prov).pill_text, 0);
        clock_last_min = -1;   // force the clock tick to rewrite + re-layout the title
    } else if (data_received) {
        lv_label_set_text(lbl_title, view_title(visible_view));
        lv_obj_set_style_text_color(lbl_title, provider_color(prov), 0);
    } else {
        lv_label_set_text(lbl_title, "Usage");
        lv_obj_set_style_text_color(lbl_title, COL_TEXT, 0);
    }
    layout_title();
}

// ---- Panel layout: normal (2 panels) vs dense (3 panels) ----
static void style_pill_geometry(lv_obj_t* pill, const lv_font_t* font, int16_t px, int16_t py) {
    lv_obj_set_style_text_font(pill, font, 0);
    lv_obj_set_style_pad_left(pill, px, 0);
    lv_obj_set_style_pad_right(pill, px, 0);
    lv_obj_set_style_pad_top(pill, py, 0);
    lv_obj_set_style_pad_bottom(pill, py, 0);
}

static void apply_usage_layout(usage_layout_t mode) {
    layout_mode = mode;
    const bool dense = (mode == LAYOUT_DENSE);
    const bool dots  = (mode == LAYOUT_DOTS);
    lv_obj_t* bar_panels[2] = { panel_session, panel_weekly };
    for (lv_obj_t* p : bar_panels) {
        if (dots) lv_obj_add_flag(p, LV_OBJ_FLAG_HIDDEN);
        else      lv_obj_clear_flag(p, LV_OBJ_FLAG_HIDDEN);
    }
    if (dots_group) {
        if (dots) lv_obj_clear_flag(dots_group, LV_OBJ_FLAG_HIDDEN);
        else      lv_obj_add_flag(dots_group, LV_OBJ_FLAG_HIDDEN);
    }
    const int16_t ph      = dense ? L.dense_panel_h   : L.usage_panel_h;
    const int16_t gap     = dense ? L.dense_panel_gap : L.usage_panel_gap;
    const int16_t bar_y   = dense ? L.dense_bar_y     : L.usage_bar_y;
    const int16_t reset_y = dense ? L.dense_reset_y   : L.usage_reset_y;
    const int16_t bar_h   = dense ? L.dense_bar_h     : L.bar_h;
    const int16_t pad_y   = dense ? L.dense_pad_y     : L.panel_pad_y;
    const lv_font_t* pct_font   = dense ? L.dense_pct_font   : L.pct_font;
    const lv_font_t* pill_font  = dense ? L.dense_pill_font  : L.pill_font;
    const lv_font_t* reset_font = dense ? L.dense_reset_font : L.reset_font;
    const int16_t pill_px = dense ? L.dense_pill_pad_x : L.pill_pad_x;
    const int16_t pill_py = dense ? L.dense_pill_pad_y : L.pill_pad_y;

    lv_obj_t* panels[3] = { panel_session, panel_weekly, panel_third };
    lv_obj_t* pcts[3]   = { lbl_session_pct, lbl_weekly_pct, lbl_third_pct };
    lv_obj_t* pills[3]  = { lbl_session_label, lbl_weekly_label, lbl_third_label };
    lv_obj_t* bars[3]   = { bar_session, bar_weekly, bar_third };
    lv_obj_t* resets[3] = { lbl_session_reset, lbl_weekly_reset, lbl_third_reset };
    for (int i = 0; i < 3; i++) {
        lv_obj_set_pos(panels[i], L.margin, L.content_y + i * (ph + gap));
        lv_obj_set_height(panels[i], ph);
        lv_obj_set_style_pad_top(panels[i], pad_y, 0);
        lv_obj_set_style_pad_bottom(panels[i], pad_y, 0);
        lv_obj_set_style_text_font(pcts[i], pct_font, 0);
        style_pill_geometry(pills[i], pill_font, pill_px, pill_py);
        lv_obj_align(pills[i], LV_ALIGN_TOP_RIGHT, 0, 1);
        lv_obj_set_y(bars[i], bar_y);
        lv_obj_set_height(bars[i], bar_h);
        lv_obj_set_style_text_font(resets[i], reset_font, 0);
        lv_obj_set_y(resets[i], reset_y);
    }
    // Enterprise overlays follow the session panel's reset line.
    lv_obj_set_style_text_font(lbl_spending_desc, reset_font, 0);
    lv_obj_set_y(lbl_spending_desc, reset_y);
    lv_obj_set_y(lbl_spending_status, reset_y + (dense ? 16 : 20));

    if (dense) lv_obj_clear_flag(panel_third, LV_OBJ_FLAG_HIDDEN);
    else       lv_obj_add_flag(panel_third, LV_OBJ_FLAG_HIDDEN);
    // The mascot's full-size lurk peeks in over the lower panel area, which
    // the dense layout fills with the third panel and the dots layout with
    // the grid: pause trips on both.
    splash_mascot_set_trips(mode == LAYOUT_BARS);
}

// Which layout a view wants. Dots is for Codex and Grok (weekly-first plans)
// and the Fable view, and needs the dot objects. Claude's third, model-scoped
// bar has its own Fable view when the grid exists; only boards without it
// fall back to the dense three-panel layout.
static usage_layout_t layout_for(int idx, const UsageData* data) {
    const bool dots_ok = DOTS_AVAILABLE && dots_group;
    const bool dots_view_id = (idx == PROVIDER_CODEX || idx == PROVIDER_GROK || idx == UI_VIEW_FABLE);
    if (dots_view_id && dots_ok) return LAYOUT_DOTS;
    if (data->has_third && !dots_ok) return LAYOUT_DENSE;
    return LAYOUT_BARS;
}

// Render Claude's model-scoped weekly limit into the dots view as Clawds.
static void render_fable(const UsageData* data) {
    const ProviderTheme th = provider_theme(PROVIDER_CLAUDE);
    if (dots_with_session) layout_dots(false);
    int f_pct = (int)(data->third_pct + 0.5f);
    if (f_pct < 0) f_pct = 0;
    if (f_pct > 100) f_pct = 100;
    lv_label_set_text_fmt(lbl_dots_pct, "%d%%", f_pct);
    char buf[48];
    format_reset_time(data->third_reset_mins, buf, sizeof(buf));
    lv_label_set_text(lbl_dots_reset, buf);
    lv_obj_align(lbl_dots_pill, LV_ALIGN_TOP_RIGHT, -L.margin, dots_row_top());
    if (f_pct != dots_filled || dots_view != UI_VIEW_FABLE) draw_clawds(f_pct, th);
}

// Render a Codex or Grok payload into the dots view: weekly % as filled dots (one
// per percent, left→right then top→bottom), plus the compact 5h row when
// the plan has a session window.
static void render_dots(int idx, const UsageData* data) {
    const ProviderTheme th = provider_theme(idx);
    if (dots_with_session != data->has_session) layout_dots(data->has_session);

    int w_pct = (int)(data->weekly_pct + 0.5f);
    if (w_pct < 0) w_pct = 0;
    if (w_pct > 100) w_pct = 100;
    lv_label_set_text_fmt(lbl_dots_pct, "%d%%", w_pct);
    char buf[48];
    format_reset_time(data->weekly_reset_mins, buf, sizeof(buf));
    lv_label_set_text(lbl_dots_reset, buf);
    lv_obj_align(lbl_dots_pill, LV_ALIGN_TOP_RIGHT, -L.margin, dots_row_top());
    if (w_pct != dots_filled || dots_view != idx) draw_dots(w_pct, th);

    if (data->has_session) {
        int s_pct = (int)(data->session_pct + 0.5f);
        char when[32];
        format_reset_time(data->session_reset_mins, when, sizeof(when));
        lv_label_set_text_fmt(lbl_dots_session, "5h - %d%% - %s", s_pct, when);
        place_dots_session_bar();
        lv_bar_set_value(bar_dots_session, s_pct, LV_ANIM_ON);
        lv_obj_set_style_bg_color(bar_dots_session, pct_color(data->session_pct, idx), LV_PART_INDICATOR);
    }
}

// ---- Carousel ----
static void show_view(int idx);

// The user picked `idx`: show it and remember it across reboots.
static void pick_view(int idx) {
    show_view(idx);
    if (picked_view == idx) return;
    picked_view = idx;
    Preferences prefs;
    prefs.begin(UI_SLOT_NVS_NAMESPACE, false);
    prefs.putUChar(UI_SLOT_NVS_KEY, (uint8_t)idx);
    prefs.end();
    Serial.printf("UI: picked view %d\n", idx);
}

static int load_picked_view(void) {
    Preferences prefs;
    prefs.begin(UI_SLOT_NVS_NAMESPACE, true);
    int idx = prefs.getUChar(UI_SLOT_NVS_KEY, PROVIDER_CLAUDE);
    prefs.end();
    Serial.printf("UI: restored picked view %d\n", idx);
    return (idx >= 0 && idx < UI_VIEW_COUNT) ? idx : PROVIDER_CLAUDE;
}

// Move to the next fresh view (if there is another one).
static void carousel_advance(void) {
    int nxt = next_fresh_view(visible_view);
    if (nxt < 0 || nxt == visible_view) return;
    pick_view(nxt);
}

bool ui_carousel_next(void) {
    if (current_screen != SCREEN_USAGE || view_state != 2 || !can_page()) return false;
    carousel_advance();
    return true;
}

bool ui_carousel_prev(void) {
    if (current_screen != SCREEN_USAGE || view_state != 2 || !can_page()) return false;
    int prv = prev_fresh_view(visible_view);
    if (prv < 0 || prv == visible_view) return false;
    pick_view(prv);
    return true;
}

bool ui_show_slot(int idx) {
    if (idx < 0 || idx >= UI_VIEW_COUNT || !view_fresh(idx)) return false;
    pick_view(idx);
    return true;
}

void ui_update(const UsageData* data) {
    if (!data) return;
    ui_update_slot(data->provider < PROVIDER_COUNT ? data->provider : PROVIDER_CLAUDE, data);
}

void ui_update_slot(int idx, const UsageData* data) {
    if (idx < 0 || idx >= PROVIDER_COUNT || !data || !data->valid) return;
    SlotState& st = slots[idx];
    st.ok = data->ok;
    if (!data->ok) {
        // {"ok":false} beat: the slot keeps its last numbers (last_ms
        // untouched) and drops out of paging until a good payload lands. If
        // it is on screen it stays there: only the user changes the slot.
        return;
    }
    st.data = *data;
    if (idx == PROVIDER_CLAUDE && data->has_third) fable_seen = true;
    st.last_ms = lv_tick_get();   // a real usage update just landed
    st.received = true;
    bool first = !data_received;
    data_received = true;

    if (data->clock_epoch > 0) {    // daemon supplied wall-clock time → drive the title clock
        bool was_off = (clock_base_epoch == 0);
        clock_base_epoch = data->clock_epoch;
        clock_base_ms = st.last_ms;
        clock_fmt = data->clock_fmt;
        if (was_off) refresh_title();
    } else if (idx == PROVIDER_CLAUDE && clock_base_epoch != 0) {
        // Clock turned off daemon-side (judged on the Claude payload, which
        // carries the daemon's clock config) → title reverts to the provider name.
        clock_base_epoch = 0;
        clock_last_min = -1;
        refresh_title();
    }

    // The picked view always comes (back) on screen. Until it has data since
    // boot, the first view with data stands in for it; otherwise only the
    // view on screen re-renders.
    if (view_provider(picked_view) == idx && view_fresh(picked_view)) {
        show_view(picked_view);
    } else if (!view_received(picked_view) && (first || !view_fresh(visible_view))) {
        show_view(idx);
    } else if (view_provider(visible_view) == idx) {
        show_view(visible_view);
    }
}

// Render one view's data into the panels and make it the visible view.
static void show_view(int idx) {
    if (idx == UI_VIEW_FABLE && !fable_available()) idx = PROVIDER_CLAUDE;   // the limit went away
    // Logged only on a change; tools/test/shell/test_sim_sticky_view.sh reads it.
    if (idx != visible_view) Serial.printf("UI: showing view %d\n", idx);
    visible_view = idx;
    const int prov = view_provider(idx);
    const UsageData* data = &slots[prov].data;
    refresh_title();
    splash_mascot_set_provider(prov);   // corner mascot follows the visible provider

    // Everything colored on this screen follows the provider's palette.
    const ProviderTheme th = provider_theme(prov);
    lv_obj_set_style_text_color(lbl_anim, th.status_text, 0);

    const usage_layout_t mode = layout_for(idx, data);
    if (layout_mode != mode) apply_usage_layout(mode);
    if (mode == LAYOUT_DOTS) {
        if (idx == UI_VIEW_FABLE) render_fable(data);
        else                      render_dots(idx, data);
        return;
    }
    const bool layout_dense = (mode == LAYOUT_DENSE);

    int s_pct = (int)(data->session_pct + 0.5f);

    if (data->enterprise) {
        // Spending box: big number-only label + small "%" symbol + desc + pace
        lv_obj_set_style_text_font(lbl_session_pct, layout_dense ? L.dense_pct_font : L.ent_pct_font, 0);
        lv_label_set_text(lbl_session_label, "Spending");
        lv_obj_add_flag(lbl_session_reset, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(lbl_session_pct_sym, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(lbl_spending_desc,   LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lbl_spending_status,   LV_OBJ_FLAG_HIDDEN);
        if (panel_weekly) lv_obj_clear_flag(panel_weekly, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_set_style_text_font(lbl_session_pct, layout_dense ? L.dense_pct_font : L.pct_font, 0);
        lv_label_set_text(lbl_session_label, "Current");
        lv_label_set_text(lbl_weekly_label, "Weekly");   // undo the enterprise "Period" pill
        lv_obj_clear_flag(lbl_session_reset, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lbl_session_pct_sym, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lbl_spending_desc,   LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lbl_spending_status, LV_OBJ_FLAG_HIDDEN);
        if (panel_weekly) lv_obj_clear_flag(panel_weekly, LV_OBJ_FLAG_HIDDEN);
    }

    char buf[48];

    // Pace vars used in both enterprise blocks below. Enterprise accounts are
    // Claude-only, so the recolor hex strings match the Claude tiers.
    const char* pace_text = "Under pace";
    lv_color_t  pace_color = th.bar_ok;
    const char* pace_hex   = "788c5d";   // matches THEME_GREEN
    if (data->session_pct > (float)data->time_pct + 15.0f) {
        pace_text = "Over pace";  pace_color = th.bar_danger; pace_hex = "c0392b";
    } else if (data->session_pct > (float)data->time_pct - 15.0f) {
        pace_text = "On pace";    pace_color = th.bar_warn;   pace_hex = "d97757";
    }

    if (data->enterprise) {
        lv_label_set_text_fmt(lbl_session_pct, "%d", s_pct);
        lv_obj_align_to(lbl_session_pct_sym, lbl_session_pct,
                        LV_ALIGN_OUT_RIGHT_TOP, 4, 12);
    } else {
        lv_label_set_text_fmt(lbl_session_pct, "%d%%", s_pct);
        format_reset_time(data->session_reset_mins, buf, sizeof(buf));
        lv_label_set_text(lbl_session_reset, buf);
    }

    lv_bar_set_value(bar_session, s_pct, LV_ANIM_ON);
    lv_obj_set_style_bg_color(bar_session, pct_color(data->session_pct, idx), LV_PART_INDICATOR);

    if (data->enterprise) {
        // Period box: time % + dynamic pace color + "Resets <date>" label
        lv_label_set_text(lbl_weekly_label, "Period");
        lv_label_set_text_fmt(lbl_weekly_pct, "%d%%", data->time_pct);
        lv_bar_set_value(bar_weekly, data->time_pct, LV_ANIM_ON);
        lv_color_t bar_pace = (data->session_pct <= (float)data->time_pct) ? th.bar_ok :
                              (data->session_pct <= (float)data->time_pct + 15.0f) ? th.bar_warn :
                              th.bar_danger;
        lv_obj_set_style_bg_color(bar_weekly, bar_pace, LV_PART_INDICATOR);
        snprintf(buf, sizeof(buf), "#%s %s# - #faf9f5 Resets %s#",
                 pace_hex, pace_text, data->reset_date);
        lv_label_set_text(lbl_weekly_reset, buf);
    } else {
        int w_pct = (int)(data->weekly_pct + 0.5f);
        lv_label_set_text_fmt(lbl_weekly_pct, "%d%%", w_pct);
        lv_bar_set_value(bar_weekly, w_pct, LV_ANIM_ON);
        lv_obj_set_style_bg_color(bar_weekly, pct_color(data->weekly_pct, idx), LV_PART_INDICATOR);
        format_reset_time(data->weekly_reset_mins, buf, sizeof(buf));
        lv_label_set_text(lbl_weekly_reset, buf);
    }

    if (layout_dense) {
        int t_pct = (int)(data->third_pct + 0.5f);
        lv_label_set_text(lbl_third_label, data->third_label[0] ? data->third_label : "Fable");
        lv_obj_align(lbl_third_label, LV_ALIGN_TOP_RIGHT, 0, 1);
        lv_label_set_text_fmt(lbl_third_pct, "%d%%", t_pct);
        lv_bar_set_value(bar_third, t_pct, LV_ANIM_ON);
        lv_obj_set_style_bg_color(bar_third, pct_color(data->third_pct, idx), LV_PART_INDICATOR);
        format_reset_time(data->third_reset_mins, buf, sizeof(buf));
        lv_label_set_text(lbl_third_reset, buf);
    }
}

// Pick the usage-view sub-screen: pairing hint (BLE down), the idle "Zzz" screen
// (connected but data has gone stale), or the live usage panels. Only re-lays-out
// on an actual change. The animated status line stays visible everywhere — it
// reads "Listening…" on the idle screen, keeping it alive rather than frozen.
static void update_view_state(void) {
    if (!usage_group || !pair_group || !idle_group) return;
    int v;
    if (!s_ble_connected) {
        v = 0;  // pairing hint
    } else if (fresh_count() > 0) {
        v = 2;  // live usage (at least one provider is fresh)
    } else {
        v = 1;  // idle / Zzz
    }
    if (v == view_state) return;
    view_state = v;
    lv_obj_add_flag(pair_group, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(idle_group, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(usage_group, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(v == 0 ? pair_group : v == 1 ? idle_group : usage_group,
                      LV_OBJ_FLAG_HIDDEN);
}

void ui_tick_anim(void) {
    if (current_screen != SCREEN_USAGE) return;
    update_view_state();
    if (view_state == 1) splash_mini_tick();   // animate the sleeping creature on the idle screen

    uint32_t now = lv_tick_get();

    // Title clock: once the daemon has sent wall-clock time, replace "Usage" with
    // the live time, advanced locally so it ticks every minute between payloads.
    if (clock_base_epoch > 0) {
        time_t cur = (time_t)(clock_base_epoch + (now - clock_base_ms) / 1000);
        struct tm tmv;
        gmtime_r(&cur, &tmv);   // epoch is already local wall-clock → gmtime keeps it as-is
        if (tmv.tm_min != clock_last_min) {   // only rewrite the title when the minute changes
            clock_last_min = tmv.tm_min;
            char tbuf[12];
            if (clock_fmt == 12) {
                int h12 = tmv.tm_hour % 12;
                if (h12 == 0) h12 = 12;
                snprintf(tbuf, sizeof(tbuf), "%d:%02d %s", h12, tmv.tm_min,
                         tmv.tm_hour < 12 ? "AM" : "PM");
            } else {
                snprintf(tbuf, sizeof(tbuf), "%02d:%02d", tmv.tm_hour, tmv.tm_min);
            }
            lv_label_set_text(lbl_title, tbuf);
            layout_title();   // the clock width changed → re-center clock + provider pill
        }
    }

    if (alert_active) return;          // the status line holds the alert message

    if (now - anim_msg_start >= ANIM_MSG_MS) {
        anim_msg_idx = (anim_msg_idx + 1) % ANIM_MSG_COUNT;
        anim_msg_start = now;
    }

    if (now - anim_last_ms < spinner_ms[anim_spinner_idx]) return;
    anim_last_ms = now;
    anim_phase = (anim_phase + 1) % SPINNER_PHASES;
    anim_spinner_idx = (anim_phase < SPINNER_COUNT) ? anim_phase
                                                    : (SPINNER_PHASES - anim_phase);

    // Status text by priority. Whimsical messages only when connected & settled.
    const char* text;
    if (!s_ble_connected) {
        text = "Waiting";              // advertising / waiting for a host connection
    } else if (view_state == 1) {      // idle — alternate so it reads as alive AND data-less
        text = (anim_msg_idx & 1) ? "No data" : "Listening";
    } else if (now - connected_at_ms < 5000) {
        text = "Connected";
    } else {
        text = anim_messages[anim_msg_idx];
    }

    // All states share the whimsical style: "<glyph> <Title-case word>…"
    static char buf[80];
    snprintf(buf, sizeof(buf), "%s %s\xE2\x80\xA6",
             spinner_frames[anim_spinner_idx], text);
    lv_label_set_text(lbl_anim, buf);
}

static screen_t prev_non_splash_screen = SCREEN_USAGE;
static void apply_battery_visibility(void) {
    if (!battery_img) return;
    if (current_screen == SCREEN_SPLASH) lv_obj_add_flag(battery_img, LV_OBJ_FLAG_HIDDEN);
    else                                  lv_obj_clear_flag(battery_img, LV_OBJ_FLAG_HIDDEN);
}

// Splash tap: next animation (within the set in mascot mode and the parade,
// through the catalog on the default splash). A vertical swipe leaves.
static void global_click_cb(lv_event_t* e) {
    (void)e;
    if (gesture_seen) return;
    if (current_screen == SCREEN_SPLASH) splash_next();
    else                                  ui_show_screen(SCREEN_SPLASH);
}

// Usage view tap: when another view is live it pages the carousel;
// otherwise it keeps the historical behavior (toggle to the splash).
// LVGL delivers the object's SHORT_CLICKED before the indev CLICKED that
// alert_tap_cb vetoes, so a tap that dismisses an alert must do nothing here.
static void usage_tap_cb(lv_event_t* e) {
    (void)e;
    if (gesture_seen || alert_active) return;
    if (current_screen == SCREEN_USAGE && view_state == 2 && can_page()) {
        carousel_advance();
        return;
    }
    ui_show_screen(SCREEN_SPLASH);
}

// Long press on the usage view: mascot mode for the provider on screen.
static void usage_long_press_cb(lv_event_t* e) {
    (void)e;
    if (gesture_seen || alert_active) return;
    if (current_screen == SCREEN_USAGE) ui_show_mascot(view_provider(visible_view));
}

// Swipe on either view (fires once per press, when the finger has travelled
// LV_INDEV_DEF_GESTURE_LIMIT). Vertical toggles splash ↔ usage; horizontal
// steps the item: animation on the splash, provider on the usage view.
static void gesture_cb(lv_event_t* e) {
    (void)e;
    gesture_seen = true;
    ui_handle_swipe(lv_indev_get_gesture_dir(lv_indev_active()));
}

bool ui_handle_swipe(lv_dir_t dir) {
    if (alert_active) return false;            // the alert owns the touch
    const bool vertical = (dir == LV_DIR_TOP || dir == LV_DIR_BOTTOM);
    switch (current_screen) {
    case SCREEN_SPLASH:
        // ui_show_screen() ends the parade and resets the provider.
        if (vertical)                 { ui_show_screen(prev_non_splash_screen); return true; }
        if (dir == LV_DIR_LEFT)       { splash_next(); return true; }
        if (dir == LV_DIR_RIGHT)      { splash_prev(); return true; }
        return false;
    case SCREEN_USAGE:
        if (vertical)                 { ui_show_screen(SCREEN_SPLASH); return true; }
        if (dir == LV_DIR_LEFT)       return ui_carousel_next();
        if (dir == LV_DIR_RIGHT)      return ui_carousel_prev();
        return false;
    default:
        return false;
    }
}

void ui_show_screen(screen_t screen) {
    lv_obj_add_flag(usage_container, LV_OBJ_FLAG_HIDDEN);
    splash_hide();
    if (screen != SCREEN_SPLASH) {
        // Leaving the splash ends mascot mode and the parade: the next plain
        // splash is Claude's default again.
        splash_parade_stop();
        splash_set_provider(-1);
    }

    switch (screen) {
    case SCREEN_SPLASH:  splash_show(); break;
    case SCREEN_USAGE:   lv_obj_clear_flag(usage_container, LV_OBJ_FLAG_HIDDEN); break;
    default: break;
    }

    splash_mascot_set_visible(screen != SCREEN_SPLASH);
    if (logo_img) {
        if (screen == SCREEN_SPLASH) lv_obj_add_flag(logo_img, LV_OBJ_FLAG_HIDDEN);
        else                          lv_obj_clear_flag(logo_img, LV_OBJ_FLAG_HIDDEN);
    }

    if (screen != SCREEN_SPLASH) prev_non_splash_screen = screen;
    current_screen = screen;
    apply_battery_visibility();
}

void ui_toggle_splash(void) {
    if (current_screen == SCREEN_SPLASH) ui_show_screen(prev_non_splash_screen);
    else                                  ui_show_screen(SCREEN_SPLASH);
}

void ui_show_mascot(int slot) {
    splash_parade_stop();
    splash_set_provider(slot);
    ui_show_screen(SCREEN_SPLASH);
}

bool ui_parade_start(void) {
    bool fresh[PROVIDER_COUNT];
    bool any = false;
    for (int i = 0; i < PROVIDER_COUNT; i++) {
        fresh[i] = slot_fresh(i);
        any = any || fresh[i];
    }
    if (!any) return false;
    splash_parade_start(fresh);
    ui_show_screen(SCREEN_SPLASH);
    return true;
}

screen_t ui_get_current_screen(void) {
    return current_screen;
}

void ui_update_ble_status(ble_state_t state, const char* name, const char* mac) {
    (void)name; (void)mac;
    bool was_connected = s_ble_connected;
    s_ble_connected = (state == BLE_STATE_CONNECTED);

    if (s_ble_connected && !was_connected) connected_at_ms = lv_tick_get();
    // pair / idle / usage — picked from connection + data freshness.
    update_view_state();
}

void ui_update_battery(int percent, bool charging, bool usb_power) {
    if (!battery_img) return;
    int idx;
    if (percent < 0 && usb_power) {
        idx = 5;   // no battery, running on USB: show the plug-zap glyph, not an empty battery
    } else if (charging) {
        idx = 4;
    } else if (percent < 0) {
        idx = 0;
    } else if (percent <= 10) {
        idx = 0;
    } else if (percent <= 35) {
        idx = 1;
    } else if (percent <= 75) {
        idx = 2;
    } else {
        idx = 3;
    }
    lv_image_set_src(battery_img, &battery_dscs[idx]);
    apply_battery_visibility();
}

void ui_show_alert(const char* message) {
    alert_active = true;
    if (current_screen == SCREEN_SPLASH) ui_show_screen(SCREEN_USAGE);
    splash_mascot_attention(true);
    lv_label_set_long_mode(lbl_anim, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_width(lbl_anim, L.content_w);
    lv_label_set_text(lbl_anim, message);
    lv_timer_reset(alert_timer);
    lv_timer_resume(alert_timer);
}

void ui_hide_alert(void) {
    if (!alert_active) return;
    alert_active = false;
    splash_mascot_attention(false);
    lv_label_set_long_mode(lbl_anim, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(lbl_anim, LV_SIZE_CONTENT);
    lv_timer_pause(alert_timer);
}
