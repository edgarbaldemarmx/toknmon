#include "ui.h"
#include "splash.h"
#include <lvgl.h>
#include <time.h>
#include <ctype.h>
#include <string.h>
#include <esp_heap_caps.h>
#include "logo.h"
#include "clawd_still.h"
#include "icons.h"
#include "hal/board_caps.h"
#include "hal/sound_hal.h"
#include "apps.h"
#include "focus_logic.h"
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
// Inter (H14 design system, docs/fonts.md "Inter"): the usage pages, the app
// center and the status footer.
LV_FONT_DECLARE(font_inter_92);
LV_FONT_DECLARE(font_inter_60);
LV_FONT_DECLARE(font_inter_29);
LV_FONT_DECLARE(font_inter_22);
LV_FONT_DECLARE(font_inter_17);
LV_FONT_DECLARE(font_inter_15);
LV_FONT_DECLARE(font_inter_13);

// Layout values computed from the active board's geometry. Populated once
// in ui_init() and treated as const for the rest of the program. Adding a
// new display size means extending compute_layout() with another
// breakpoint — never editing the screen-builder functions below.
struct Layout {
    int16_t scr_w, scr_h;
    int16_t margin;
    // Usage module (H14): the 480×480 design geometry (DESIGN.md §4) scales
    // by these factors, x by sx and y by sy; fonts are picked per breakpoint.
    float   sx, sy;
    int16_t inset;                   // working inset (32 px on 480)
    const lv_font_t* mod_title_font;   // screen title (29 px semibold)
    const lv_font_t* mod_value_font;   // main usage number (92 px medium, digits only)
    const lv_font_t* mod_sign_font;    // "%" after the number, remaining / 5h figures (29 px)
    const lv_font_t* mod_label_font;   // WEEKLY USAGE, provider label, clock (13 px semibold)
    const lv_font_t* mod_reset_font;   // "Resets in …", "used", "remaining" (17 px)
    const lv_font_t* mod_small_font;   // credit metadata, 5h reset (15 px)
    const lv_font_t* footer_font;      // status verb, "N blocks today", "Pick an app" (22 px; the user could not read 15 px on the panel)
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
    const lv_font_t* title_font;     // pair / idle hint title (dense breakpoints)
    const lv_font_t* pct_font;       // dense-layout percentage
    const lv_font_t* pill_font;      // "Current" / "Weekly" pill
    const lv_font_t* reset_font;     // "Resets in ..." line
    bool    small_icons;             // 40px logo + 24px battery (vs 80/48) on small screens
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

    // Focus screen (H14, DESIGN.md §6): one Inter face per element, picked per
    // breakpoint; the geometry scales from the 480×480 design in
    // init_focus_screen(). The header and footer reuse the mod_* faces.
    const lv_font_t* focus_label_font;    // SET DURATION / IN PROGRESS / PAUSED / COMPLETE (13 px semibold)
    const lv_font_t* focus_time_font;     // countdown (60 px medium)
    const lv_font_t* focus_support_font;  // "minutes" / "remaining" / "N min completed" (15 px)
    const lv_font_t* focus_ctrl_font;     // "-5" / "+5" cards and the action button (17 px)
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
    L.sx = (float)c.width / 480.0f;
    L.sy = (float)c.height / 480.0f;
    L.inset = (int16_t)(32.0f * L.sx + 0.5f);
    L.mod_title_font = &font_inter_29;
    L.mod_value_font = &font_inter_92;
    L.mod_sign_font  = &font_inter_29;
    L.mod_label_font = &font_inter_13;
    L.mod_reset_font = &font_inter_17;
    L.mod_small_font = &font_inter_15;
    L.footer_font    = &font_inter_22;

    // Values shared by the two original breakpoints; the small branch below
    // overrides them wholesale.
    L.bar_h = 24;
    L.panel_pad_x = 16;
    L.panel_pad_y = 12;
    L.pill_pad_x = 18;
    L.pill_pad_y = 6;
    L.title_font   = &font_tiempos_56;
    L.pct_font     = &font_styrene_48;
    L.pill_font    = &font_styrene_28;
    L.reset_font   = &font_styrene_28;
    L.small_icons = false;
    // Battery: right-aligned at the working inset, centred on the header's
    // y 45 (DESIGN.md §4: body y 39–52).
    L.batt_w = ICON_BATTERY_W;
    L.batt_y = (int16_t)(45.0f * L.sy + 0.5f) - L.batt_w / 2;
    L.pair_y1 = 40;
    L.pair_y2 = 120;
    L.pair_y3 = 160;
    L.idle_px = 160;
    L.focus_label_font   = &font_inter_13;
    L.focus_time_font    = &font_inter_60;
    L.focus_support_font = &font_inter_15;
    L.focus_ctrl_font    = &font_inter_17;

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
        L.bt_info_panel_h = 140;
        L.bt_reset_zone_h = 90;
        L.bt_title_font    = &font_tiempos_34;
        L.bt_status_font   = &font_styrene_28;
        L.bt_device_font   = &font_styrene_20;
        L.bt_credit_1_font = &font_styrene_16;
        L.bt_credit_2_font = &font_styrene_14;
        // The header is narrower: a 34 px title keeps clear of the pill.
        L.focus_label_font   = &font_inter_13;
        L.focus_time_font    = &font_inter_60;
        L.focus_support_font = &font_inter_15;
        L.focus_ctrl_font    = &font_inter_17;
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
        L.bar_h = 12;
        L.panel_pad_x = 10;
        L.panel_pad_y = 6;
        L.pill_pad_x = 8;
        L.pill_pad_y = 2;
        L.title_font   = &font_tiempos_34;
        L.pct_font     = &font_styrene_24;
        L.pill_font    = &font_styrene_14;
        L.reset_font   = &font_styrene_14;
        // Half-size module: the 60 px figure and the 17/13 px faces.
        L.mod_title_font = &font_inter_17;
        L.mod_value_font = &font_inter_60;
        L.mod_sign_font  = &font_inter_17;
        L.mod_label_font = &font_inter_13;
        L.mod_reset_font = &font_inter_13;
        L.mod_small_font = &font_inter_13;
        L.footer_font    = &font_inter_17;
        L.small_icons = true;
        L.batt_w = ICON_BATTERY_SMALL_W;
        L.batt_y = (int16_t)(45.0f * L.sy + 0.5f) - L.batt_w / 2;
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
        L.focus_label_font   = &font_inter_13;
        L.focus_time_font    = &font_inter_29;
        L.focus_support_font = &font_inter_13;
        L.focus_ctrl_font    = &font_inter_13;
    }

    L.content_w = L.scr_w - 2 * L.margin;
}

// Anthropic brand palette — design tokens live in theme.h
#include "theme.h"
#define COL_BG        UI_BG
#define COL_SURFACE   UI_SURFACE
#define COL_DIVIDER   UI_DIVIDER
#define COL_PANEL     THEME_PANEL
#define COL_TEXT      UI_TEXT
#define COL_DIM       UI_MUTED
#define COL_ACCENT    THEME_ACCENT
#define COL_GREEN     THEME_GREEN
#define COL_AMBER     THEME_AMBER
#define COL_RED       THEME_RED
#define COL_BAR_BG    UI_TRACK

// ---- Usage screen widgets (single non-splash view) ----
static lv_obj_t* usage_container;
// Header (H14): title in the provider accent, the corner mascot after it,
// the clock and the provider label in muted small caps, the battery at the
// right inset, and a 1 px divider under all of it.
static lv_obj_t* lbl_title;
static lv_obj_t* lbl_provider;        // "CODEX" — right-aligned at design x 390
static lv_obj_t* lbl_clock;           // "05:00" left of the provider label; hidden until the daemon sends `t`
static lv_obj_t* header_divider;
// Clock fed by the daemon: base epoch (local wall-clock seconds) + the lv_tick at
// which it landed, so the clock ticks forward locally between 60s payloads.
static long     clock_base_epoch = 0;
static uint32_t clock_base_ms = 0;
static int      clock_fmt = 24;   // 12 or 24, set from the daemon payload
static int      clock_last_min = -1;   // last rendered minute; avoids redrawing the clock every tick
static lv_obj_t* usage_group;   // the usage module and the dense panels — shown when connected
static lv_obj_t* pair_group;    // pairing hint — shown when disconnected
// Dense layout (C6: Claude carries the model-scoped limit and the board has
// no canvas for the Fable grid): three stacked panels, session / weekly /
// scoped weekly. Restyled with the design tokens, otherwise as before H14.
static lv_obj_t* bar_session;
static lv_obj_t* lbl_session_pct;
static lv_obj_t* lbl_session_label;
static lv_obj_t* lbl_session_reset;
static lv_obj_t* bar_weekly;
static lv_obj_t* lbl_weekly_pct;
static lv_obj_t* lbl_weekly_label;
static lv_obj_t* lbl_weekly_reset;
static lv_obj_t* bar_third;
static lv_obj_t* lbl_third_pct;
static lv_obj_t* lbl_third_label;
static lv_obj_t* lbl_third_reset;
static lv_obj_t* panel_session = nullptr;
static lv_obj_t* panel_weekly = nullptr;
static lv_obj_t* panel_third = nullptr;
// Usage layouts. MODULE is the H14 page (DESIGN.md §4): one header, the
// WEEKLY USAGE figure over a 416×12 track, the reset line and one lower
// module (credit panel, remaining line, the 5h block or the Fable grid).
// DENSE stacks the three bar panels on boards without the canvas when Claude
// carries the scoped limit. See apply_usage_layout().
enum usage_layout_t { LAYOUT_MODULE, LAYOUT_DENSE };
static usage_layout_t layout_mode = LAYOUT_MODULE;
// Fable grid: 10×10 Clawd glyphs drawn into one canvas whose pixel buffer
// lives in PSRAM. The C6 boards have none to spare, so there the scoped
// limit is the third bar of the dense layout.
#ifdef BOARD_HAS_PSRAM
static const bool GRID_AVAILABLE = true;
#else
static const bool GRID_AVAILABLE = false;
#endif
#define GRID_COUNT 100
#define GRID_COLS  10
// ---- Usage module objects (built once by build_module(); shown and hidden
// per view by render_module()). Geometry in design pixels, see MOD_* below.
static lv_obj_t* module_group = nullptr;
static lv_obj_t* lbl_mod_label;        // "WEEKLY USAGE" / "MONTHLY SPENDING"
static lv_obj_t* lbl_mod_value;        // the big number, digits only
static lv_obj_t* lbl_mod_sign;         // "%" after the measured numeric run
static lv_obj_t* lbl_mod_used;         // "used", right-aligned
static lv_obj_t* bar_mod;              // the usage track
static lv_obj_t* lbl_mod_reset;        // "Resets in 5d 23h" / "Reset unavailable"
// Lower module A: credit panel (Codex with reset credits)
#define CREDIT_SEGMENTS_MAX 6
static lv_obj_t* credit_panel;
static lv_obj_t* lbl_credit_title;     // "RESET CREDITS"
static lv_obj_t* lbl_credit_count;     // "2 available", accent, right-aligned
static lv_obj_t* credit_segments[CREDIT_SEGMENTS_MAX];   // solid = held, outlined = used
static lv_obj_t* lbl_credit_more;      // "+N" after the last visible segment
static lv_obj_t* lbl_credit_meta;      // "1 used · Next expires in 13d"
// Lower module B: remaining line (single-window providers without credits)
static lv_obj_t* lbl_mod_remaining;    // "63%" in the accent
static lv_obj_t* lbl_mod_remaining_word;   // "remaining"
static lv_obj_t* module_divider;       // design y 404
// Lower module C: the 5-hour window block (Claude, Kimi; enterprise: billing period)
static lv_obj_t* lbl_win_label;        // "CURRENT · 5H"
static lv_obj_t* lbl_win_pct;          // "17%" right-aligned, accent
static lv_obj_t* bar_win;              // second 416×12 track
static lv_obj_t* lbl_win_reset;        // "Resets in 1h 50m" / pace line
// Lower module D: the Fable grid (Claude's scoped limit as Clawds)
static lv_obj_t* grid_canvas = nullptr;
static uint16_t* grid_buf = nullptr;   // RGB565 pixels, canvas-sized
static int       grid_w = 0, grid_h = 0;
static int       grid_filled = -1;     // glyphs currently drawn in the accent
// Footer: status dot + verb
static lv_obj_t* footer_dot;
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
    return GRID_AVAILABLE && grid_canvas && slots[PROVIDER_CLAUDE].data.has_third;
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

// Animation state: the footer verb rotates every ANIM_MSG_MS.
static uint8_t anim_msg_idx = 0;
static uint32_t anim_msg_start = 0;
#define ANIM_MSG_MS     4000

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

// "Resets in …" for the usage pages; an unknown window reads "Reset
// unavailable" (DESIGN.md §7: never substitute "0h").
static void format_reset_time(int mins, char* buf, size_t len) {
    if (mins < 0) {
        snprintf(buf, len, "Reset unavailable");
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
static void style_pill_geometry(lv_obj_t* pill, const lv_font_t* font, int16_t px, int16_t py);

// ---- Design-pixel helpers (H14). The usage page, the app center and the
// footer are laid out in the 480×480 design's coordinates (DESIGN.md §4);
// MX / MY scale them to the panel. Text y values are baselines.
static inline int MX(int v) { return (int)((float)v * L.sx + 0.5f); }
static inline int MY(int v) { return (int)((float)v * L.sy + 0.5f); }
static inline int text_top(const lv_font_t* f, int baseline_design) {
    return MY(baseline_design) - (lv_font_get_line_height(f) - f->base_line);
}
// Next code point of a UTF-8 string (the UI only carries ASCII plus "·",
// "…" and "—"); advances *p.
static uint32_t utf8_next(const char** p) {
    const unsigned char* c = (const unsigned char*)*p;
    uint32_t cp; int n;
    if (c[0] < 0x80)        { cp = c[0];        n = 1; }
    else if (c[0] < 0xE0)   { cp = c[0] & 0x1F; n = 2; }
    else if (c[0] < 0xF0)   { cp = c[0] & 0x0F; n = 3; }
    else                    { cp = c[0] & 0x07; n = 4; }
    for (int i = 1; i < n; i++) {
        if ((c[i] & 0xC0) != 0x80) { n = i; break; }
        cp = (cp << 6) | (c[i] & 0x3F);
    }
    *p += n;
    return cp;
}
// Rendered width of a string in a font, kerning included (same glyph
// advances the label draws with).
static int text_w(const lv_font_t* f, const char* t) {
    int w = 0;
    uint32_t cur = utf8_next(&t);
    while (cur) {
        const uint32_t nxt = utf8_next(&t);
        w += lv_font_get_glyph_width(f, cur, nxt);
        cur = nxt;
    }
    return w;
}
static int label_w(lv_obj_t* lbl) {
    return text_w(lv_obj_get_style_text_font(lbl, LV_PART_MAIN), lv_label_get_text(lbl));
}
// Place a label with its left edge at design x and its baseline at design y.
static void place_text(lv_obj_t* lbl, int x_design, int baseline_design) {
    lv_obj_set_pos(lbl, MX(x_design), text_top(lv_obj_get_style_text_font(lbl, LV_PART_MAIN), baseline_design));
}
// Same, right-aligned: the right edge lands at design x.
static void place_text_right(lv_obj_t* lbl, int right_design, int baseline_design) {
    lv_obj_set_pos(lbl, MX(right_design) - label_w(lbl),
                   text_top(lv_obj_get_style_text_font(lbl, LV_PART_MAIN), baseline_design));
}
static inline void set_shown(lv_obj_t* o, bool shown) {
    if (!o) return;
    if (shown) lv_obj_clear_flag(o, LV_OBJ_FLAG_HIDDEN);
    else       lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
}

static lv_obj_t* make_label(lv_obj_t* parent, const lv_font_t* font, lv_color_t color, const char* text) {
    lv_obj_t* lbl = lv_label_create(parent);
    lv_label_set_text(lbl, text);
    lv_obj_set_style_text_font(lbl, font, 0);
    lv_obj_set_style_text_color(lbl, color, 0);
    return lbl;
}

// A plain filled box (dividers, status dots, credit segments): no border,
// no padding, no scrolling, taps fall through to the page.
static lv_obj_t* make_box(lv_obj_t* parent, int x, int y, int w, int h, lv_color_t color, int radius) {
    lv_obj_t* o = lv_obj_create(parent);
    lv_obj_set_pos(o, x, y);
    lv_obj_set_size(o, w, h);
    lv_obj_set_style_bg_color(o, color, 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(o, radius, 0);
    lv_obj_set_style_border_width(o, 0, 0);
    lv_obj_set_style_shadow_width(o, 0, 0);
    lv_obj_set_style_pad_all(o, 0, 0);
    lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_clear_flag(o, LV_OBJ_FLAG_CLICKABLE);
    return o;
}

// 1 px divider from design x1 to x2 at design y.
static lv_obj_t* make_rule(lv_obj_t* parent, int x1_design, int x2_design, int y_design) {
    return make_box(parent, MX(x1_design), MY(y_design), MX(x2_design) - MX(x1_design), 1, COL_DIVIDER, 0);
}

// Surface card (credit panel, app tiles, dense panels): radius 12.
static lv_obj_t* make_panel(lv_obj_t* parent, int x, int y, int w, int h) {
    lv_obj_t* panel = lv_obj_create(parent);
    lv_obj_set_pos(panel, x, y);
    lv_obj_set_size(panel, w, h);
    lv_obj_set_style_bg_color(panel, COL_SURFACE, 0);
    lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(panel, MX(12), 0);
    lv_obj_set_style_border_width(panel, 0, 0);
    lv_obj_set_style_shadow_width(panel, 0, 0);
    lv_obj_set_style_pad_left(panel, L.panel_pad_x, 0);
    lv_obj_set_style_pad_right(panel, L.panel_pad_x, 0);
    lv_obj_set_style_pad_top(panel, L.panel_pad_y, 0);
    lv_obj_set_style_pad_bottom(panel, L.panel_pad_y, 0);
    lv_obj_clear_flag(panel, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(panel, LV_OBJ_FLAG_EVENT_BUBBLE);
    return panel;
}

// Usage track: UI_TRACK, radius 6, the filled part in the view's accent (set
// per render). The indicator is exactly w × pct / 100 wide: no minimum, so
// 0 % draws nothing and 100 % fills the track.
static lv_obj_t* make_bar(lv_obj_t* parent, int x, int y, int w, int h) {
    lv_obj_t* bar = lv_bar_create(parent);
    lv_obj_set_pos(bar, x, y);
    lv_obj_set_size(bar, w, h);
    lv_bar_set_range(bar, 0, 100);
    lv_bar_set_value(bar, 0, LV_ANIM_OFF);
    lv_obj_set_style_bg_color(bar, COL_BAR_BG, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_radius(bar, h / 2, LV_PART_MAIN);
    lv_obj_set_style_bg_color(bar, COL_ACCENT, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_radius(bar, h / 2, LV_PART_INDICATOR);
    lv_obj_clear_flag(bar, LV_OBJ_FLAG_CLICKABLE);
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

// Dense-layout pill ("Current" / "Weekly" / "Fable"): track-coloured capsule.
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

// Dense-layout panel (C6 three-bar fallback): percentage left, pill right,
// bar and reset line under them.
static lv_obj_t* make_usage_panel(lv_obj_t* parent, int y, const char* pill_text,
                                  lv_obj_t** out_pct, lv_obj_t** out_pill,
                                  lv_obj_t** out_bar, lv_obj_t** out_reset) {
    lv_obj_t* panel = make_panel(parent, L.margin, y, L.content_w, L.usage_panel_h);

    *out_pct = make_label(panel, L.pct_font, COL_TEXT, "---%");
    lv_obj_set_pos(*out_pct, 0, 0);

    *out_pill = make_pill(panel, pill_text);
    lv_obj_align(*out_pill, LV_ALIGN_TOP_RIGHT, 0, 1);

    *out_bar = make_bar(panel, 0, L.usage_bar_y,
                        L.content_w - 2 * L.panel_pad_x, L.bar_h);

    *out_reset = make_label(panel, L.reset_font, COL_DIM, "---");
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

    lv_obj_t* l1 = make_label(pair_group, L.bt_status_font, COL_TEXT, "To pair");
    lv_obj_align(l1, LV_ALIGN_TOP_MID, 0, L.pair_y1);
    lv_obj_t* l2 = make_label(pair_group, L.bt_device_font, COL_DIM, "hold the power button");
    lv_obj_align(l2, LV_ALIGN_TOP_MID, 0, L.pair_y2);
    lv_obj_t* l3 = make_label(pair_group, L.bt_device_font, COL_DIM, "for 3 seconds, then release");
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
    // sits between the header and the status line; the animated "Listening"
    // status line carries the words, so no extra text is needed here.
    lv_obj_t* creature = splash_mini_create(idle_group, "cloud", L.idle_px);
    if (creature) lv_obj_align(creature, LV_ALIGN_CENTER, 0, -20);

    lv_obj_add_flag(idle_group, LV_OBJ_FLAG_HIDDEN);  // update_view_state decides
}

// ---- Usage module (H14, DESIGN.md §4) ----
// Design geometry, in 480×480 pixels. Text values are baselines.
#define MOD_LABEL_BASE     123   // WEEKLY USAGE
#define MOD_VALUE_X        28    // big figure (its glyph box; the ink lands near x 32)
#define MOD_VALUE_BASE     210
#define MOD_SIGN_GAP       10    // between the measured numeric run and "%"
#define MOD_SIGN_BASE      208
#define MOD_USED_BASE      202   // "used", right-aligned at the inset
#define MOD_TRACK_Y        229   // design 234 with a 12 px track; 22 px keeps the same centre
#define MOD_TRACK_H        22    // design 12; thicker per user feedback on the panel
#define MOD_RESET_BASE     279
#define MOD_PANEL_Y        308   // credit panel
#define MOD_PANEL_H        108
#define MOD_PANEL_PAD      16    // panel inner inset (x 48 / 432)
#define MOD_CREDIT_BASE    337   // RESET CREDITS / N available
#define MOD_SEG_Y          349   // design 351 (12 px) → 16 px, same centre
#define MOD_SEG_W          56
#define MOD_SEG_H          16    // design 12; thicker with the bars
#define MOD_SEG_PITCH      64    // 56 + 8
#define MOD_META_BASE      396
#define MOD_REMAIN_BASE    351   // "63%"; "remaining" one px higher
#define MOD_REMAIN_GAP     24
#define MOD_LOWER_RULE_Y   404
#define MOD_WIN_LABEL_BASE 337   // CURRENT · 5H
#define MOD_WIN_PCT_BASE   340
#define MOD_WIN_TRACK_Y    347   // design 352 (12 px) → 22 px, same centre
#define MOD_WIN_RESET_BASE 392
#define MOD_GRID_Y         226   // Fable: the Clawd grid stands in for the track and reset line
#define MOD_GRID_H         200
#define MOD_FOOT_DOT_X     36    // status dot centre
#define MOD_FOOT_DOT_Y     444
#define MOD_FOOT_DOT_D     8     // design 6; scaled with the 22 px footer text
#define MOD_FOOT_TEXT_X    48
#define MOD_FOOT_TEXT_BASE 449
#define HDR_TITLE_BASE     60
#define HDR_LABEL_RIGHT    390
#define HDR_LABEL_BASE     55
#define HDR_CLOCK_GAP      12
#define HDR_RULE_Y         87
#define HDR_MASCOT_GAP     16
#define HDR_MASCOT_FEET    77

// Build the module once. Every piece is hidden or shown per view by
// render_module(); the positions that depend on text (the "%" sign, the
// "remaining" word, "+N") are set there too.
static void build_module(lv_obj_t* parent) {
    module_group = lv_obj_create(parent);
    lv_obj_set_size(module_group, L.scr_w, L.scr_h);
    lv_obj_set_pos(module_group, 0, 0);
    lv_obj_set_style_bg_opa(module_group, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(module_group, 0, 0);
    lv_obj_set_style_pad_all(module_group, 0, 0);
    lv_obj_clear_flag(module_group, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(module_group, LV_OBJ_FLAG_EVENT_BUBBLE);

    const int inset = L.inset;
    const int width = MX(448) - inset;

    lbl_mod_label = make_label(module_group, L.mod_label_font, COL_DIM, "WEEKLY USAGE");
    place_text(lbl_mod_label, 32, MOD_LABEL_BASE);
    lbl_mod_value = make_label(module_group, L.mod_value_font, COL_TEXT, "\xE2\x80\x94");
    place_text(lbl_mod_value, MOD_VALUE_X, MOD_VALUE_BASE);
    lbl_mod_sign = make_label(module_group, L.mod_sign_font, COL_TEXT, "%");
    lbl_mod_used = make_label(module_group, L.mod_reset_font, COL_DIM, "used");
    place_text_right(lbl_mod_used, 448, MOD_USED_BASE);
    bar_mod = make_bar(module_group, inset, MY(MOD_TRACK_Y), width, MY(MOD_TRACK_H));
    lbl_mod_reset = make_label(module_group, L.mod_reset_font, COL_DIM, "Reset unavailable");
    place_text(lbl_mod_reset, 32, MOD_RESET_BASE);

    // A: credit panel
    credit_panel = make_panel(module_group, inset, MY(MOD_PANEL_Y), width, MY(MOD_PANEL_H));
    lv_obj_set_style_pad_all(credit_panel, 0, 0);   // children are placed in page coordinates
    lbl_credit_title = make_label(credit_panel, L.mod_label_font, COL_DIM, "RESET CREDITS");
    lv_obj_set_pos(lbl_credit_title, MX(MOD_PANEL_PAD), text_top(L.mod_label_font, MOD_CREDIT_BASE) - MY(MOD_PANEL_Y));
    lbl_credit_count = make_label(credit_panel, L.mod_reset_font, COL_TEXT, "0 available");
    for (int i = 0; i < CREDIT_SEGMENTS_MAX; i++) {
        credit_segments[i] = make_box(credit_panel, MX(MOD_PANEL_PAD + i * MOD_SEG_PITCH), MY(MOD_SEG_Y) - MY(MOD_PANEL_Y),
                                      MX(MOD_SEG_W), MY(MOD_SEG_H), COL_TEXT, MY(MOD_SEG_H) / 2);
        lv_obj_add_flag(credit_segments[i], LV_OBJ_FLAG_HIDDEN);
    }
    lbl_credit_more = make_label(credit_panel, L.mod_label_font, COL_DIM, "");
    lbl_credit_meta = make_label(credit_panel, L.mod_small_font, COL_DIM, "");
    lv_obj_set_pos(lbl_credit_meta, MX(MOD_PANEL_PAD), text_top(L.mod_small_font, MOD_META_BASE) - MY(MOD_PANEL_Y));
    lv_obj_add_flag(credit_panel, LV_OBJ_FLAG_HIDDEN);

    // B: remaining line + divider
    lbl_mod_remaining = make_label(module_group, L.mod_sign_font, COL_TEXT, "0%");
    place_text(lbl_mod_remaining, 32, MOD_REMAIN_BASE);
    lbl_mod_remaining_word = make_label(module_group, L.mod_reset_font, COL_DIM, "remaining");
    module_divider = make_rule(module_group, 32, 448, MOD_LOWER_RULE_Y);

    // C: 5-hour window block
    lbl_win_label = make_label(module_group, L.mod_label_font, COL_DIM, "CURRENT \xC2\xB7 5H");
    place_text(lbl_win_label, 32, MOD_WIN_LABEL_BASE);
    lbl_win_pct = make_label(module_group, L.mod_sign_font, COL_TEXT, "0%");
    bar_win = make_bar(module_group, inset, MY(MOD_WIN_TRACK_Y), width, MY(MOD_TRACK_H));
    lbl_win_reset = make_label(module_group, L.mod_small_font, COL_DIM, "");
    place_text(lbl_win_reset, 32, MOD_WIN_RESET_BASE);

    // D: the Fable grid canvas (PSRAM boards)
    if (GRID_AVAILABLE) {
        grid_w = width;
        grid_h = MY(MOD_GRID_H);
        grid_buf = (uint16_t*)heap_caps_malloc((size_t)grid_w * grid_h * 2, MALLOC_CAP_SPIRAM);
        if (grid_buf) {
            grid_canvas = lv_canvas_create(module_group);
            lv_canvas_set_buffer(grid_canvas, grid_buf, grid_w, grid_h, LV_COLOR_FORMAT_RGB565);
            lv_obj_set_pos(grid_canvas, inset, MY(MOD_GRID_Y));
            lv_obj_clear_flag(grid_canvas, LV_OBJ_FLAG_CLICKABLE);   // taps go to the carousel
            lv_obj_add_flag(grid_canvas, LV_OBJ_FLAG_HIDDEN);
        }
    }
}

// Fable view: 10×10 grid of small Clawds, `filled` in Claude's accent and the
// rest in the track colour. The pixels go straight into the canvas buffer (a
// few thousand rects would flood the LVGL draw pool). Glyphs are 12×8 cells
// scaled by an integer so ten rows fit the canvas height; columns spread
// evenly across the working width.
#define CLAWD_GLYPH_W 12
#define CLAWD_GLYPH_H 8
static const char* const CLAWD_GLYPH[CLAWD_GLYPH_H] = {
    "..XXXXXXXX..",
    "..X.XXXX.X..",   // eyes are holes, so they read as ink on the background
    "..X.XXXX.X..",
    "XXXXXXXXXXXX",   // arms
    "XXXXXXXXXXXX",
    "..XXXXXXXX..",
    "..X.X..X.X..",   // four legs
    "..X.X..X.X..",
};

static void draw_clawds(int filled, const ProviderTheme& th) {
    if (!grid_canvas) return;
    lv_canvas_fill_bg(grid_canvas, COL_BG, LV_OPA_COVER);
    lv_draw_buf_t* db = lv_canvas_get_draw_buf(grid_canvas);
    const int pitch_y = grid_h / GRID_COLS;
    int s = pitch_y / CLAWD_GLYPH_H;
    if (s < 1) s = 1;
    const int gw = CLAWD_GLYPH_W * s, gh = CLAWD_GLYPH_H * s;
    const uint16_t on  = lv_color_to_u16(th.accent);
    const uint16_t off = lv_color_to_u16(th.dot_empty);
    for (int i = 0; i < GRID_COUNT; i++) {
        const uint16_t px = (i < filled) ? on : off;
        const int col = i % GRID_COLS, row = i / GRID_COLS;
        const int x0 = (grid_w - gw) * col / (GRID_COLS - 1);
        const int y0 = row * pitch_y + (pitch_y - gh) / 2;
        for (int gy = 0; gy < gh; gy++) {
            const int y = y0 + gy;
            if (y < 0 || y >= grid_h) continue;
            uint16_t* line = (uint16_t*)(db->data + (size_t)y * db->header.stride);
            const char* g = CLAWD_GLYPH[gy / s];
            for (int gx = 0; gx < gw; gx++) {
                const int x = x0 + gx;
                if (x >= 0 && x < grid_w && g[gx / s] == 'X') line[x] = px;
            }
        }
    }
    lv_obj_invalidate(grid_canvas);
    grid_filled = filled;
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

    // Header: title (accent), provider label and clock (muted small caps),
    // divider. The corner mascot and the battery live on the screen object
    // (ui_init) so they also serve the other screens.
    lbl_title = make_label(usage_container, L.mod_title_font, COL_TEXT, "Usage");
    place_text(lbl_title, 32, HDR_TITLE_BASE);
    lbl_provider = make_label(usage_container, L.mod_label_font, COL_DIM, "");
    place_text_right(lbl_provider, HDR_LABEL_RIGHT, HDR_LABEL_BASE);
    lv_obj_add_flag(lbl_provider, LV_OBJ_FLAG_HIDDEN);
    lbl_clock = make_label(usage_container, L.mod_label_font, COL_DIM, "");
    lv_obj_add_flag(lbl_clock, LV_OBJ_FLAG_HIDDEN);
    header_divider = make_rule(usage_container, 32, 448, HDR_RULE_Y);

    // Usage views (shown when connected) live in a transparent full-size group
    // so they can be toggled against the pairing hint as one unit.
    usage_group = lv_obj_create(usage_container);
    lv_obj_set_size(usage_group, L.scr_w, L.scr_h);
    lv_obj_set_pos(usage_group, 0, 0);
    lv_obj_set_style_bg_opa(usage_group, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(usage_group, 0, 0);
    lv_obj_set_style_pad_all(usage_group, 0, 0);
    lv_obj_clear_flag(usage_group, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(usage_group, LV_OBJ_FLAG_EVENT_BUBBLE);

    build_module(usage_group);

    // Dense panels (C6 fallback), positioned by apply_usage_layout(); hidden
    // while the module is up.
    panel_session = make_usage_panel(usage_group, L.content_y, "Current",
                     &lbl_session_pct, &lbl_session_label,
                     &bar_session, &lbl_session_reset);
    panel_weekly = make_usage_panel(usage_group,
                     L.content_y + L.usage_panel_h + L.usage_panel_gap, "Weekly",
                     &lbl_weekly_pct, &lbl_weekly_label,
                     &bar_weekly, &lbl_weekly_reset);
    panel_third = make_usage_panel(usage_group,
                     L.content_y + 2 * (L.usage_panel_h + L.usage_panel_gap), "Fable",
                     &lbl_third_pct, &lbl_third_label,
                     &bar_third, &lbl_third_reset);

    build_pair_group(usage_container);
    build_idle_group(usage_container);

    // Status footer — always visible on the usage view: the dot in the
    // provider accent, the verb driven by ui_tick_anim().
    const int d = MX(MOD_FOOT_DOT_D) < 4 ? 4 : MX(MOD_FOOT_DOT_D);
    footer_dot = make_box(usage_container, MX(MOD_FOOT_DOT_X) - d / 2, MY(MOD_FOOT_DOT_Y) - d / 2, d, d,
                          COL_ACCENT, LV_RADIUS_CIRCLE);
    lbl_anim = make_label(usage_container, L.footer_font, COL_DIM, "");
    place_text(lbl_anim, MOD_FOOT_TEXT_X, MOD_FOOT_TEXT_BASE);
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
}

// ======== App center and Focus (H12) ========
// Two more screens beside the splash and the meter. The app center is a row
// of tiles, one per enabled app (apps.cpp); Focus is a block timer whose
// state machine lives in focus_logic.cpp and only gets millis()-backed
// lv_tick deltas, touch/PWR events and the daemon clock's day from here.

static lv_obj_t* apps_container = nullptr;
static lv_obj_t* app_tiles[APP_COUNT] = {};
static lv_image_dsc_t tile_clawd_dsc;           // the still Clawd on the Meter tile

// Focus layout (H14, DESIGN.md §6): the header and footer of the usage pages,
// a ring of radius 120 centred at (240, 233) with the state label, the
// countdown and a supporting line stacked on its centre, "-5" / "+5" surface
// cards beside it while setting up, and one amber action button under it.
// Design pixels scale by MX / MY; the ring takes the smaller of the two
// factors so it stays round on non-square panels.
#define FX_RING_CX       240
#define FX_RING_CY       233
#define FX_RING_D        248   // outer diameter: radius 120 on the stroke's centre line + 8 px stroke
#define FX_RING_STROKE   8
#define FX_LABEL_BASE    187   // SET DURATION / IN PROGRESS / PAUSED / COMPLETE
#define FX_TIME_BASE     252   // countdown
#define FX_SUPPORT_BASE  285   // minutes / remaining / N min completed
#define FX_CARD_Y        207   // "-5" at x 32, "+5" at x 392, 56 × 52
#define FX_CARD_W        56
#define FX_CARD_H        52
#define FX_CARD_MINUS_X  32
#define FX_CARD_PLUS_X   392
#define FX_BTN_X         96    // the action button, 288 × 48, text baseline 407
#define FX_BTN_Y         376
#define FX_BTN_W         288
#define FX_BTN_H         48
#define FX_BTN_BASE      407
#define FX_HOLD_RIGHT    448   // "Hold timer to cancel", right-aligned in the footer

static lv_obj_t* focus_container = nullptr;
static lv_obj_t* focus_arc;                     // full in setup, the remaining share while counting, track only when done
static lv_obj_t* lbl_focus_label;               // SET DURATION / IN PROGRESS / PAUSED / COMPLETE
static lv_obj_t* lbl_focus_time;                // MM:SS (MM:00 in setup)
static lv_obj_t* lbl_focus_support;             // "minutes" / "remaining" / "N min completed"
static lv_obj_t* focus_card_minus;              // setup only
static lv_obj_t* focus_card_plus;
static lv_obj_t* lbl_focus_minus;
static lv_obj_t* lbl_focus_plus;
static lv_obj_t* btn_focus;                     // Start focus / Pause / Resume / Start next
static lv_obj_t* lbl_focus_btn;
static lv_obj_t* lbl_focus_blocks;              // footer: "N blocks today" / "Block N today"
static lv_obj_t* lbl_focus_hold;                // footer, right: "Hold timer to cancel" while counting
static FocusState focus;
static int        focus_shown_sec = -1;         // last rendered remaining second
static screen_t   last_app_screen = SCREEN_USAGE;   // what the side button returns to

// Bell: the reset clip (bell_pcm.h, 2.4 s at 44.1 kHz stereo) three times
// with 400 ms gaps. chime_play() ignores calls while a clip plays, so the
// repeats are spaced by an lv_timer instead of being queued.
#define FOCUS_BELL_CLIP_MS 2400
#define FOCUS_BELL_GAP_MS  400
#define FOCUS_BELL_TIMES   3
static lv_timer_t* focus_bell_timer = nullptr;
static int         focus_bells_left = 0;

// Alert text for the app center and Focus screens: the usage status line is
// hidden there, so the message rides on this screen-level label instead.
static lv_obj_t* lbl_overlay_alert = nullptr;

// YYYYMMDD from the daemon clock, advanced locally like the title clock; 0
// until a payload with `t` has landed.
static uint32_t clock_day_now(void) {
    if (clock_base_epoch <= 0) return 0;
    time_t cur = (time_t)(clock_base_epoch + (lv_tick_get() - clock_base_ms) / 1000);
    struct tm tmv;
    gmtime_r(&cur, &tmv);
    return (uint32_t)(tmv.tm_year + 1900) * 10000u + (uint32_t)(tmv.tm_mon + 1) * 100u + (uint32_t)tmv.tm_mday;
}

static void focus_bell_cb(lv_timer_t* t) {
    (void)t;
    sound_hal_play_reset();
    if (--focus_bells_left <= 0) lv_timer_pause(focus_bell_timer);
}

static void focus_bell_start(void) {
    sound_hal_play_reset();
    focus_bells_left = FOCUS_BELL_TIMES - 1;
    lv_timer_reset(focus_bell_timer);
    lv_timer_resume(focus_bell_timer);
}

static void render_focus(void) {
    if (!focus_container) return;
    const uint32_t total_ms = (uint32_t)focus.length_min * 60000u;
    const bool counting = focus.phase == FOCUS_RUNNING || focus.phase == FOCUS_PAUSED;
    uint32_t shown_ms = (focus.phase == FOCUS_SETUP) ? total_ms : focus_remaining_ms(&focus);
    // Ceil to the second while counting so 24:59.4 reads 25:00 → 24:59 → …
    uint32_t sec = counting ? (shown_ms + 999) / 1000 : shown_ms / 1000;
    char buf[48];
    snprintf(buf, sizeof(buf), "%02u:%02u", (unsigned)(sec / 60), (unsigned)(sec % 60));
    lv_label_set_text(lbl_focus_time, buf);
    focus_shown_sec = (int)sec;

    // Ring: a full amber preview in setup, remaining / selected length while
    // counting (frozen and muted when paused), the bare track when done.
    int32_t v = (focus.phase == FOCUS_SETUP) ? 1000
              : (focus.phase == FOCUS_DONE) ? 0
              : (int32_t)((uint64_t)shown_ms * 1000u / total_ms);
    lv_arc_set_value(focus_arc, v);
    lv_obj_set_style_arc_color(focus_arc, focus.phase == FOCUS_PAUSED ? COL_DIM : THEME_FOCUS, LV_PART_INDICATOR);

    const char* label;
    const char* action;
    switch (focus.phase) {
    case FOCUS_RUNNING: label = "IN PROGRESS";  action = "Pause";       break;
    case FOCUS_PAUSED:  label = "PAUSED";       action = "Resume";      break;
    case FOCUS_DONE:    label = "COMPLETE";     action = "Start next";  break;
    default:            label = "SET DURATION"; action = "Start focus"; break;
    }
    lv_label_set_text(lbl_focus_label, label);
    // The paused label is muted like its arc (render 07-focus-paused).
    lv_obj_set_style_text_color(lbl_focus_label, focus.phase == FOCUS_PAUSED ? COL_DIM : THEME_FOCUS, 0);
    lv_label_set_text(lbl_focus_btn, action);

    if (focus.phase == FOCUS_DONE) {
        snprintf(buf, sizeof(buf), "%u min completed", (unsigned)focus.length_min);
        lv_label_set_text(lbl_focus_support, buf);
    } else {
        lv_label_set_text(lbl_focus_support, counting ? "remaining" : "minutes");
    }

    // Footer: the block being counted while running / paused, the finished
    // count otherwise; the cancel hint only while a block can be cancelled.
    const uint8_t today = focus_blocks_today(&focus, clock_day_now());
    if (counting) snprintf(buf, sizeof(buf), "Block %u today", today + 1);
    else          snprintf(buf, sizeof(buf), "%u block%s today", today, today == 1 ? "" : "s");
    lv_label_set_text(lbl_focus_blocks, buf);
    set_shown(lbl_focus_hold, counting);

    // "-5" / "+5" cards: setup only, muted at the 5 / 120 minute bounds.
    set_shown(focus_card_minus, focus.phase == FOCUS_SETUP);
    set_shown(focus_card_plus, focus.phase == FOCUS_SETUP);
    lv_obj_set_style_text_color(lbl_focus_minus, focus.length_min > FOCUS_MIN_MINUTES ? COL_TEXT : COL_DIM, 0);
    lv_obj_set_style_text_color(lbl_focus_plus, focus.length_min < FOCUS_MAX_MINUTES ? COL_TEXT : COL_DIM, 0);
}

// Start the block with the selected length. Shared by the action button,
// PWR and serial `focus start`.
static bool focus_do_start(void) {
    if (!focus_start(&focus, lv_tick_get())) return false;
    Serial.printf("focus: block started (%u min)\n", focus.length_min);
    render_focus();
    return true;
}

// "Start next" (DESIGN.md §6): back to setup with the previous length; the
// next block only starts on another "Start focus". The counter and its day
// are kept; the state machine's own DONE → RUNNING edge stays reachable
// through serial `focus start`.
static void focus_next_setup(void) {
    const uint16_t length = focus.length_min;
    focus_init(&focus, focus.blocks, focus.blocks_day);
    focus.length_min = length;
    Serial.println("focus: ready for the next block");
    render_focus();
}

// The primary action for the current state — Start focus / Pause / Resume /
// Start next — shared by the button, PWR and serial `focus next`.
static bool focus_action(void) {
    switch (focus.phase) {
    case FOCUS_SETUP:
        return focus_do_start();
    case FOCUS_RUNNING:
    case FOCUS_PAUSED:
        if (!focus_toggle_pause(&focus, lv_tick_get())) return false;
        render_focus();
        return true;
    case FOCUS_DONE:
        focus_next_setup();
        return true;
    }
    return false;
}

static void focus_finished(void) {
    apps_focus_counter_store(focus.blocks, focus.blocks_day);
    Serial.printf("focus: block done — %u today (day %lu)\n", focus.blocks, (unsigned long)focus.blocks_day);
    focus_bell_start();
    render_focus();
}

// Called every loop from ui_tick_anim(), whatever screen is up: a block keeps
// counting in the background and rings when it ends.
static void focus_tick_ui(void) {
    if (focus.phase != FOCUS_RUNNING) return;
    if (focus_tick(&focus, lv_tick_get(), clock_day_now())) {
        focus_finished();
        return;
    }
    if (current_screen != SCREEN_FOCUS) return;
    int sec = (int)((focus_remaining_ms(&focus) + 999) / 1000);
    if (sec != focus_shown_sec) render_focus();
}

static void focus_btn_cb(lv_event_t* e) {
    (void)e;
    if (gesture_seen || alert_active) return;
    focus_action();
}

// "-5" / "+5" cards (user data: the step sign). They do not bubble, so a tap
// on a card never doubles with the half-screen tap below.
static void focus_card_cb(lv_event_t* e) {
    if (gesture_seen || alert_active) return;
    if (focus_adjust(&focus, (int)(intptr_t)lv_event_get_user_data(e))) render_focus();
}

// Tap elsewhere on the Focus screen: setup → ±5 by half (right +, left −);
// running or paused → pause / resume. Done is handled by the button only.
static void focus_tap_cb(lv_event_t* e) {
    (void)e;
    if (gesture_seen || alert_active) return;
    if (focus.phase == FOCUS_SETUP) {
        lv_point_t p = { L.scr_w / 2, 0 };
        lv_indev_t* indev = lv_indev_active();
        if (indev) lv_indev_get_point(indev, &p);
        if (focus_adjust(&focus, p.x >= L.scr_w / 2 ? +1 : -1)) render_focus();
        return;
    }
    if (focus_toggle_pause(&focus, lv_tick_get())) render_focus();
}

// Long press while running or paused: cancel back to setup without counting.
// (DESIGN.md §6 asks for a 1.2 s hold with feedback and a confirmation
// dialog; this is LVGL's plain long press, as in H12.)
static void focus_long_press_cb(lv_event_t* e) {
    (void)e;
    if (gesture_seen || alert_active) return;
    if (focus_cancel(&focus)) {
        Serial.println("focus: block cancelled");
        render_focus();
    }
}

// A "-5" / "+5" surface card (radius 10) with its own tap handler.
static lv_obj_t* make_focus_card(lv_obj_t* parent, int x_design, const char* text, int step, lv_obj_t** lbl_out) {
    lv_obj_t* card = make_box(parent, MX(x_design), MY(FX_CARD_Y), MX(FX_CARD_W), MY(FX_CARD_H), COL_SURFACE, MX(10));
    lv_obj_add_flag(card, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(card, focus_card_cb, LV_EVENT_SHORT_CLICKED, (void*)(intptr_t)step);
    *lbl_out = make_label(card, L.focus_ctrl_font, COL_TEXT, text);
    lv_obj_center(*lbl_out);
    return card;
}

static void init_focus_screen(lv_obj_t* scr) {
    focus_container = lv_obj_create(scr);
    lv_obj_set_size(focus_container, L.scr_w, L.scr_h);
    lv_obj_set_pos(focus_container, 0, 0);
    lv_obj_set_style_bg_opa(focus_container, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(focus_container, 0, 0);
    lv_obj_set_style_pad_all(focus_container, 0, 0);
    lv_obj_clear_flag(focus_container, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(focus_container, focus_tap_cb, LV_EVENT_SHORT_CLICKED, NULL);
    lv_obj_add_event_cb(focus_container, focus_long_press_cb, LV_EVENT_LONG_PRESSED, NULL);
    lv_obj_add_flag(focus_container, LV_OBJ_FLAG_HIDDEN);

    // Header as on the usage pages: the title in the app's amber, TIMER in
    // the provider-label slot, the rule. The battery lives on the screen
    // object; the corner mascot stays hidden here (ui_show_screen).
    lv_obj_t* title = make_label(focus_container, L.mod_title_font, THEME_FOCUS, "Focus");
    place_text(title, 32, HDR_TITLE_BASE);
    lv_obj_t* kind = make_label(focus_container, L.mod_label_font, COL_DIM, "TIMER");
    place_text_right(kind, HDR_LABEL_RIGHT, HDR_LABEL_BASE);
    make_rule(focus_container, 32, 448, HDR_RULE_Y);

    // Ring: 248 px outer, the 8 px stroke drawn inward, from 12 o'clock
    // clockwise.
    const float s = L.sx < L.sy ? L.sx : L.sy;
    const int ring = (int)(FX_RING_D * s + 0.5f);
    int stroke = (int)(FX_RING_STROKE * s + 0.5f);
    if (stroke < 4) stroke = 4;
    focus_arc = lv_arc_create(focus_container);
    lv_obj_set_size(focus_arc, ring, ring);
    lv_obj_set_pos(focus_arc, MX(FX_RING_CX) - ring / 2, MY(FX_RING_CY) - ring / 2);
    lv_arc_set_rotation(focus_arc, 270);
    lv_arc_set_bg_angles(focus_arc, 0, 360);
    lv_arc_set_range(focus_arc, 0, 1000);
    lv_arc_set_value(focus_arc, 1000);
    lv_arc_set_mode(focus_arc, LV_ARC_MODE_NORMAL);
    lv_obj_remove_style(focus_arc, NULL, LV_PART_KNOB);
    lv_obj_clear_flag(focus_arc, LV_OBJ_FLAG_CLICKABLE);   // taps fall through to the container
    lv_obj_set_style_pad_all(focus_arc, 0, 0);
    lv_obj_set_style_border_width(focus_arc, 0, 0);
    lv_obj_set_style_shadow_width(focus_arc, 0, 0);
    lv_obj_set_style_arc_width(focus_arc, stroke, LV_PART_MAIN);
    lv_obj_set_style_arc_width(focus_arc, stroke, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(focus_arc, COL_BAR_BG, LV_PART_MAIN);
    lv_obj_set_style_arc_color(focus_arc, THEME_FOCUS, LV_PART_INDICATOR);
    lv_obj_set_style_arc_rounded(focus_arc, false, LV_PART_MAIN);
    lv_obj_set_style_arc_rounded(focus_arc, false, LV_PART_INDICATOR);

    // Three centred lines on the ring's centre, each on its design baseline.
    // lv_obj_align() is persistent, so they stay centred as their text changes.
    lbl_focus_label = make_label(focus_container, L.focus_label_font, THEME_FOCUS, "");
    lv_obj_align(lbl_focus_label, LV_ALIGN_TOP_MID, 0, text_top(L.focus_label_font, FX_LABEL_BASE));
    lbl_focus_time = make_label(focus_container, L.focus_time_font, COL_TEXT, "");
    lv_obj_align(lbl_focus_time, LV_ALIGN_TOP_MID, 0, text_top(L.focus_time_font, FX_TIME_BASE));
    lbl_focus_support = make_label(focus_container, L.focus_support_font, COL_DIM, "");
    lv_obj_align(lbl_focus_support, LV_ALIGN_TOP_MID, 0, text_top(L.focus_support_font, FX_SUPPORT_BASE));

    focus_card_minus = make_focus_card(focus_container, FX_CARD_MINUS_X, "-5", -1, &lbl_focus_minus);
    focus_card_plus  = make_focus_card(focus_container, FX_CARD_PLUS_X,  "+5", +1, &lbl_focus_plus);

    // Action button: amber, radius 10, dark ink.
    btn_focus = lv_button_create(focus_container);
    lv_obj_set_size(btn_focus, MX(FX_BTN_W), MY(FX_BTN_H));
    lv_obj_set_pos(btn_focus, MX(FX_BTN_X), MY(FX_BTN_Y));
    lv_obj_set_style_bg_color(btn_focus, THEME_FOCUS, 0);
    lv_obj_set_style_bg_opa(btn_focus, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(btn_focus, MX(10), 0);
    lv_obj_set_style_shadow_width(btn_focus, 0, 0);
    lv_obj_set_style_pad_all(btn_focus, 0, 0);
    lv_obj_add_event_cb(btn_focus, focus_btn_cb, LV_EVENT_SHORT_CLICKED, NULL);
    lbl_focus_btn = make_label(btn_focus, L.focus_ctrl_font, COL_BG, "");
    lv_obj_align(lbl_focus_btn, LV_ALIGN_TOP_MID, 0, text_top(L.focus_ctrl_font, FX_BTN_BASE) - MY(FX_BTN_Y));

    // Footer like the usage status line: amber dot, the blocks line, and the
    // cancel hint right-aligned while a block is counting.
    const int d = MX(MOD_FOOT_DOT_D) < 4 ? 4 : MX(MOD_FOOT_DOT_D);
    make_box(focus_container, MX(MOD_FOOT_DOT_X) - d / 2, MY(MOD_FOOT_DOT_Y) - d / 2, d, d, THEME_FOCUS, LV_RADIUS_CIRCLE);
    lbl_focus_blocks = make_label(focus_container, L.footer_font, COL_DIM, "");
    place_text(lbl_focus_blocks, MOD_FOOT_TEXT_X, MOD_FOOT_TEXT_BASE);
    lbl_focus_hold = make_label(focus_container, L.mod_label_font, COL_DIM, "Hold timer to cancel");
    place_text_right(lbl_focus_hold, FX_HOLD_RIGHT, MOD_FOOT_TEXT_BASE);

    focus_bell_timer = lv_timer_create(focus_bell_cb, FOCUS_BELL_CLIP_MS + FOCUS_BELL_GAP_MS, NULL);
    lv_timer_pause(focus_bell_timer);

    uint8_t blocks; uint32_t day;
    apps_focus_counter_load(&blocks, &day);
    focus_init(&focus, blocks, day);
    render_focus();
}

// ---- App center ----

static lv_obj_t* lbl_apps_footer = nullptr;

static void app_tile_cb(lv_event_t* e) {
    if (gesture_seen || alert_active) return;
    int app = (int)(intptr_t)lv_event_get_user_data(e);
    ui_show_screen(app == APP_FOCUS ? SCREEN_FOCUS : SCREEN_USAGE);
}

// Tile geometry: square surface cards side by side on the working width,
// centred as a group between the header divider and the footer; hidden
// tiles (disabled apps) leave the row and the rest re-center.
#define APPS_TOP_Y     104   // design px, under the header rule
#define APPS_BOTTOM_Y  420   // above the footer
#define APPS_GAP       16
static void layout_apps(void) {
    if (!apps_container) return;
    const int width = MX(448) - L.inset;
    const int gap = MX(APPS_GAP);
    int tile = (width - gap) / 2;
    const int avail_h = MY(APPS_BOTTOM_Y) - MY(APPS_TOP_Y);
    if (tile > avail_h) tile = avail_h;
    const int n = apps_enabled_count();
    const int row_w = n * tile + (n - 1) * gap;
    int x = L.inset + (width - row_w) / 2;
    const int y = MY(APPS_TOP_Y) + (avail_h - tile) / 2;
    for (int i = 0; i < APP_COUNT; i++) {
        if (!app_tiles[i]) continue;
        if (!apps_enabled((app_id_t)i)) { lv_obj_add_flag(app_tiles[i], LV_OBJ_FLAG_HIDDEN); continue; }
        lv_obj_clear_flag(app_tiles[i], LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_pos(app_tiles[i], x, y);
        lv_obj_set_size(app_tiles[i], tile, tile);
        x += tile + gap;
    }
}

// The Focus glyph: an amber ring with two hands, drawn with LVGL primitives
// (no bitmap). `px` is the glyph box.
static void make_timer_glyph(lv_obj_t* parent, int px) {
    lv_obj_t* ring = lv_arc_create(parent);
    lv_obj_set_size(ring, px, px);
    lv_obj_align(ring, LV_ALIGN_TOP_MID, 0, 0);
    lv_arc_set_rotation(ring, 270);
    lv_arc_set_bg_angles(ring, 0, 360);
    lv_arc_set_range(ring, 0, 360);
    lv_arc_set_value(ring, 300);                    // a few minutes gone
    lv_obj_remove_style(ring, NULL, LV_PART_KNOB);
    lv_obj_clear_flag(ring, LV_OBJ_FLAG_CLICKABLE);
    const int w = px >= 60 ? 6 : 4;
    lv_obj_set_style_arc_width(ring, w, LV_PART_MAIN);
    lv_obj_set_style_arc_width(ring, w, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(ring, COL_BAR_BG, LV_PART_MAIN);
    lv_obj_set_style_arc_color(ring, THEME_FOCUS, LV_PART_INDICATOR);

    static lv_point_precise_t hands[APP_COUNT][3];   // one hand set per tile that asks
    static int used = 0;
    lv_point_precise_t* h = hands[used < APP_COUNT ? used++ : 0];
    const lv_value_precise_t c = px / 2;
    h[0] = { c + (lv_value_precise_t)(px * 0.22f), c - (lv_value_precise_t)(px * 0.12f) };  // minute hand (~2 o'clock)
    h[1] = { c, c };
    h[2] = { c, c - (lv_value_precise_t)(px * 0.32f) };                                       // hour hand (12 o'clock)
    lv_obj_t* line = lv_line_create(parent);
    lv_obj_set_size(line, px, px);
    lv_obj_align(line, LV_ALIGN_TOP_MID, 0, 0);
    lv_line_set_points(line, h, 3);
    lv_obj_set_style_line_width(line, w, 0);
    lv_obj_set_style_line_color(line, COL_TEXT, 0);
    lv_obj_set_style_line_rounded(line, true, 0);
    lv_obj_clear_flag(line, LV_OBJ_FLAG_CLICKABLE);
}

static void init_apps_screen(lv_obj_t* scr) {
    apps_container = lv_obj_create(scr);
    lv_obj_set_size(apps_container, L.scr_w, L.scr_h);
    lv_obj_set_pos(apps_container, 0, 0);
    lv_obj_set_style_bg_opa(apps_container, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(apps_container, 0, 0);
    lv_obj_set_style_pad_all(apps_container, 0, 0);
    lv_obj_clear_flag(apps_container, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(apps_container, LV_OBJ_FLAG_HIDDEN);

    // Header like the usage pages: title, divider (the battery is shared).
    lv_obj_t* title = make_label(apps_container, L.mod_title_font, COL_TEXT, "Apps");
    place_text(title, 32, HDR_TITLE_BASE);
    make_rule(apps_container, 32, 448, HDR_RULE_Y);

    if (L.small_icons) init_icon_dsc_rgb565a8(&tile_clawd_dsc, CLAWD_STILL_SMALL_W, CLAWD_STILL_SMALL_H, clawd_still_small_data);
    else               init_icon_dsc_rgb565a8(&tile_clawd_dsc, CLAWD_STILL_W, CLAWD_STILL_H, clawd_still_data);
    const int glyph = L.small_icons ? CLAWD_STILL_SMALL_H + 8 : CLAWD_STILL_H + 24;

    for (int i = 0; i < APP_COUNT; i++) {
        lv_obj_t* tile = make_panel(apps_container, 0, 0, 10, 10);
        lv_obj_set_style_pad_all(tile, MX(MOD_PANEL_PAD), 0);
        lv_obj_clear_flag(tile, LV_OBJ_FLAG_EVENT_BUBBLE);
        lv_obj_add_flag(tile, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(tile, app_tile_cb, LV_EVENT_SHORT_CLICKED, (void*)(intptr_t)i);
        // Icon box: fixed height so the label lands at the same y on both tiles.
        lv_obj_t* box = lv_obj_create(tile);
        lv_obj_set_size(box, glyph, glyph);
        lv_obj_align(box, LV_ALIGN_TOP_MID, 0, MY(12));
        lv_obj_set_style_bg_opa(box, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_width(box, 0, 0);
        lv_obj_set_style_pad_all(box, 0, 0);
        lv_obj_clear_flag(box, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_clear_flag(box, LV_OBJ_FLAG_CLICKABLE);
        if (i == APP_METER) {
            lv_obj_t* img = lv_image_create(box);
            lv_image_set_src(img, &tile_clawd_dsc);
            lv_obj_center(img);
            lv_obj_clear_flag(img, LV_OBJ_FLAG_CLICKABLE);
        } else {
            make_timer_glyph(box, glyph);
        }
        // Meter in primary text, Focus in its amber: the app's own accent.
        lv_obj_t* name = make_label(tile, L.mod_reset_font, i == APP_FOCUS ? THEME_FOCUS : COL_TEXT, apps_name((app_id_t)i));
        lv_obj_align(name, LV_ALIGN_BOTTOM_MID, 0, 0);
        app_tiles[i] = tile;
    }

    // Footer: dot + hint, like the usage status line.
    const int d = MX(MOD_FOOT_DOT_D) < 4 ? 4 : MX(MOD_FOOT_DOT_D);
    make_box(apps_container, MX(MOD_FOOT_DOT_X) - d / 2, MY(MOD_FOOT_DOT_Y) - d / 2, d, d, COL_DIM, LV_RADIUS_CIRCLE);
    lbl_apps_footer = make_label(apps_container, L.footer_font, COL_DIM, "Pick an app");
    place_text(lbl_apps_footer, MOD_FOOT_TEXT_X, MOD_FOOT_TEXT_BASE);
    layout_apps();
}

// Alert text on the app center / Focus screens (the usage status line is
// hidden there). Shown only while an alert is active on one of them.
static void apply_alert_overlay(void) {
    if (!lbl_overlay_alert) return;
    const bool show = alert_active && (current_screen == SCREEN_APPS || current_screen == SCREEN_FOCUS);
    if (show) lv_obj_clear_flag(lbl_overlay_alert, LV_OBJ_FLAG_HIDDEN);
    else      lv_obj_add_flag(lbl_overlay_alert, LV_OBJ_FLAG_HIDDEN);
}

static void init_alert_overlay(lv_obj_t* scr) {
    lbl_overlay_alert = make_label(scr, L.mod_reset_font, COL_ACCENT, "");
    lv_obj_set_style_bg_color(lbl_overlay_alert, COL_BG, 0);
    lv_obj_set_style_bg_opa(lbl_overlay_alert, LV_OPA_COVER, 0);
    lv_obj_set_style_text_align(lbl_overlay_alert, LV_TEXT_ALIGN_LEFT, 0);
    lv_label_set_long_mode(lbl_overlay_alert, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_width(lbl_overlay_alert, MX(448) - MX(MOD_FOOT_TEXT_X));
    place_text(lbl_overlay_alert, MOD_FOOT_TEXT_X, MOD_FOOT_TEXT_BASE);
    lv_obj_add_flag(lbl_overlay_alert, LV_OBJ_FLAG_HIDDEN);
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
    apps_init();
    init_apps_screen(scr);
    init_focus_screen(scr);
    splash_init(scr);

    if (splash_get_root()) {
        lv_obj_add_event_cb(splash_get_root(), global_click_cb, LV_EVENT_CLICKED, NULL);
    }
    // Gestures bubble (LV_OBJ_FLAG_GESTURE_BUBBLE, default on) from the splash
    // root and the usage container up to the screen, so one handler there
    // covers both views; it dispatches on current_screen.
    lv_obj_add_event_cb(scr, gesture_cb, LV_EVENT_GESTURE, NULL);

    // Corner mascot in the header, right after the title (H14): the slot
    // starts past the widest title so it never moves between views, and the
    // art's feet sit at design y 77 so the character is centred on the title.
    {
        int title_w = 0;
        const char* titles[] = { provider_name(PROVIDER_CLAUDE), provider_name(PROVIDER_CODEX),
                                 provider_name(PROVIDER_KIMI), provider_name(PROVIDER_GROK), "Fable" };
        for (const char* t : titles) {
            const int w = text_w(L.mod_title_font, t);
            if (w > title_w) title_w = w;
        }
        const int slot_x = L.inset + title_w + MX(HDR_MASCOT_GAP);
        const int feet_y = MY(HDR_MASCOT_FEET);
#ifdef BOARD_HAS_PSRAM
        // Animated: idles, does acts, and takes walk-off/lurk trips.
        splash_mascot_create(scr, slot_x, feet_y, L.small_icons ? 2 : 3);
#else
        const int art_h = L.small_icons ? CLAWD_STILL_SMALL_H : CLAWD_STILL_H;
        logo_img = lv_image_create(scr);
        lv_image_set_src(logo_img, &logo_dsc);
        lv_obj_set_pos(logo_img, slot_x, feet_y - art_h);
#endif
    }

    battery_img = lv_image_create(scr);
    lv_image_set_src(battery_img, &battery_dscs[0]);
    lv_obj_set_pos(battery_img, MX(448) - L.batt_w, L.batt_y);
    // Boards without battery telemetry never show the indicator (per the HAL
    // contract; previously every board drew the empty-battery glyph).
    if (!board_caps().has_battery) {
        lv_obj_del(battery_img);
        battery_img = nullptr;
    }

    init_alert();
    init_alert_overlay(scr);
    apply_usage_layout(LAYOUT_MODULE);
    picked_view = load_picked_view();
    visible_view = picked_view;
}

// ---- Title area: title, clock, provider label ----
// The title is the provider name (or the Fable label) in the provider accent,
// "Usage" in primary text until the first payload. The provider label sits in
// muted small caps right-aligned at design x 390; the clock, once the daemon
// sends `t`, rides to its left and ticks forward locally.
static void layout_title(void) {
    place_text(lbl_title, 32, HDR_TITLE_BASE);
    place_text_right(lbl_provider, HDR_LABEL_RIGHT, HDR_LABEL_BASE);
    const bool clock = (clock_base_epoch > 0) && data_received;
    set_shown(lbl_provider, data_received);
    set_shown(lbl_clock, clock);
    if (!clock) return;
    const int right = MX(HDR_LABEL_RIGHT) - label_w(lbl_provider) - MX(HDR_CLOCK_GAP);
    lv_obj_set_pos(lbl_clock, right - label_w(lbl_clock), text_top(L.mod_label_font, HDR_LABEL_BASE));
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
    if (data_received) {
        lv_label_set_text(lbl_title, view_title(visible_view));
        lv_obj_set_style_text_color(lbl_title, provider_color(prov), 0);
        char up[16];
        const char* name = provider_name(prov);
        size_t i = 0;
        for (; name[i] && i < sizeof(up) - 1; i++) up[i] = (char)toupper((unsigned char)name[i]);
        up[i] = '\0';
        lv_label_set_text(lbl_provider, up);
    } else {
        lv_label_set_text(lbl_title, "Usage");
        lv_obj_set_style_text_color(lbl_title, COL_TEXT, 0);
    }
    layout_title();
}

// ---- Layouts: the module vs the dense three-panel fallback ----
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
    set_shown(module_group, !dense);
    lv_obj_t* panels[3] = { panel_session, panel_weekly, panel_third };
    lv_obj_t* pcts[3]   = { lbl_session_pct, lbl_weekly_pct, lbl_third_pct };
    lv_obj_t* pills[3]  = { lbl_session_label, lbl_weekly_label, lbl_third_label };
    lv_obj_t* bars[3]   = { bar_session, bar_weekly, bar_third };
    lv_obj_t* resets[3] = { lbl_session_reset, lbl_weekly_reset, lbl_third_reset };
    for (int i = 0; i < 3; i++) {
        set_shown(panels[i], dense);
        if (!dense) continue;
        lv_obj_set_pos(panels[i], L.margin, L.content_y + i * (L.dense_panel_h + L.dense_panel_gap));
        lv_obj_set_height(panels[i], L.dense_panel_h);
        lv_obj_set_style_pad_top(panels[i], L.dense_pad_y, 0);
        lv_obj_set_style_pad_bottom(panels[i], L.dense_pad_y, 0);
        lv_obj_set_style_text_font(pcts[i], L.dense_pct_font, 0);
        style_pill_geometry(pills[i], L.dense_pill_font, L.dense_pill_pad_x, L.dense_pill_pad_y);
        lv_obj_align(pills[i], LV_ALIGN_TOP_RIGHT, 0, 1);
        lv_obj_set_y(bars[i], L.dense_bar_y);
        lv_obj_set_height(bars[i], L.dense_bar_h);
        lv_obj_set_style_text_font(resets[i], L.dense_reset_font, 0);
        lv_obj_set_y(resets[i], L.dense_reset_y);
    }
}

// Which layout a view wants: the module everywhere, except Claude carrying
// the scoped limit on a board without the Fable grid, which stacks the
// three panels instead.
static usage_layout_t layout_for(int idx, const UsageData* data) {
    if (idx == PROVIDER_CLAUDE && data->has_third && !grid_canvas) return LAYOUT_DENSE;
    return LAYOUT_MODULE;
}

static int pct_round(float v) {
    int p = (int)(v + 0.5f);
    if (p < 0) p = 0;
    if (p > 100) p = 100;
    return p;
}

// Expiry of the soonest held credit, in whole days from 48 h up and in
// hours (rounded up, so a held credit never reads "0h") below.
static void format_credit_expiry(int mins, char* buf, size_t len) {
    if (mins < 0)            snprintf(buf, len, "Available");
    else if (mins >= 48 * 60) snprintf(buf, len, "Next expires in %dd", mins / 1440);
    else                     snprintf(buf, len, "Next expires in %dh", (mins + 59) / 60);
}

// Credit panel: "N available" in the accent, one segment per credit (solid =
// held, outlined = used; up to six, then five plus "+N"), and the metadata
// line "1 used · Next expires in 13d". An account with nothing held keeps the
// panel with "0 available" and only its used segments (DESIGN.md §4).
static void render_credits(const UsageData* data, const ProviderTheme& th) {
    const int held = data->reset_credits < 0 ? 0 : data->reset_credits;
    const int used = data->reset_credits_used < 0 ? 0 : data->reset_credits_used;
    const int total = held + used;
    lv_label_set_text_fmt(lbl_credit_count, "%d available", held);
    lv_obj_set_style_text_color(lbl_credit_count, th.accent, 0);
    lv_obj_set_pos(lbl_credit_count, MX(448 - MOD_PANEL_PAD) - MX(32) - label_w(lbl_credit_count),
                   text_top(L.mod_reset_font, MOD_CREDIT_BASE) - MY(MOD_PANEL_Y));

    const int shown = total <= CREDIT_SEGMENTS_MAX ? total : CREDIT_SEGMENTS_MAX - 1;
    for (int i = 0; i < CREDIT_SEGMENTS_MAX; i++) {
        lv_obj_t* c = credit_segments[i];
        set_shown(c, i < shown);
        const bool lit = (i < held);
        lv_obj_set_style_bg_color(c, th.accent, 0);
        lv_obj_set_style_bg_opa(c, lit ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_color(c, th.accent, 0);
        lv_obj_set_style_border_opa(c, LV_OPA_70, 0);
        lv_obj_set_style_border_width(c, lit ? 0 : 1, 0);
    }
    if (total > CREDIT_SEGMENTS_MAX) {
        lv_label_set_text_fmt(lbl_credit_more, "+%d", total - shown);
        lv_obj_set_pos(lbl_credit_more, MX(MOD_PANEL_PAD + shown * MOD_SEG_PITCH),
                       text_top(L.mod_label_font, MOD_SEG_Y + MOD_SEG_H / 2 + 5) - MY(MOD_PANEL_Y));
        set_shown(lbl_credit_more, true);
    } else {
        set_shown(lbl_credit_more, false);
    }

    char meta[48], exp[32];
    if (held > 0) {
        format_credit_expiry(data->reset_credits_exp_mins, exp, sizeof(exp));
        if (used > 0) snprintf(meta, sizeof(meta), "%d used \xC2\xB7 %s", used, exp);
        else          snprintf(meta, sizeof(meta), "%s", exp);
    } else if (used > 0) {
        snprintf(meta, sizeof(meta), "%d used", used);
    } else {
        snprintf(meta, sizeof(meta), "None available");
    }
    lv_label_set_text(lbl_credit_meta, meta);
}

// Render the visible view into the module. The main figure is the weekly
// window (the scoped limit on the Fable view, the spending on enterprise
// accounts); the lower module is the credit panel, the 5-hour block, the
// Fable grid, or the remaining line.
static void render_module(int idx, const UsageData* data, const ProviderTheme& th) {
    const bool fable = (idx == UI_VIEW_FABLE);
    const bool ent   = data->enterprise && !fable;
    const char* label = "WEEKLY USAGE";
    const char* used_word = "used";
    bool  known = true;
    float main_pct = 0;
    int   reset_mins = -1;
    if (fable)                 { main_pct = data->third_pct;   reset_mins = data->third_reset_mins; }
    else if (ent)              { main_pct = data->session_pct; label = "MONTHLY SPENDING"; used_word = "of budget"; }
    else if (data->has_weekly) { main_pct = data->weekly_pct;  reset_mins = data->weekly_reset_mins; }
    else if (data->has_session){ main_pct = data->session_pct; reset_mins = data->session_reset_mins; label = "CURRENT \xC2\xB7 5H"; }
    else                       { known = false; }

    lv_label_set_text(lbl_mod_label, label);
    lv_label_set_text(lbl_mod_used, used_word);
    place_text_right(lbl_mod_used, 448, MOD_USED_BASE);
    const int main_i = pct_round(main_pct);
    if (known) lv_label_set_text_fmt(lbl_mod_value, "%d", main_i);
    else       lv_label_set_text(lbl_mod_value, "\xE2\x80\x94");
    set_shown(lbl_mod_sign, known);
    lv_obj_set_pos(lbl_mod_sign, MX(MOD_VALUE_X) + label_w(lbl_mod_value) + MX(MOD_SIGN_GAP),
                   text_top(L.mod_sign_font, MOD_SIGN_BASE));
    lv_bar_set_value(bar_mod, known ? main_i : 0, LV_ANIM_ON);
    lv_obj_set_style_bg_color(bar_mod, th.accent, LV_PART_INDICATOR);

    char buf[48];
    if (ent && data->reset_date[0]) snprintf(buf, sizeof(buf), "Resets %s", data->reset_date);
    else if (known)                 format_reset_time(reset_mins, buf, sizeof(buf));
    else                            snprintf(buf, sizeof(buf), "Loading usage");
    lv_label_set_text(lbl_mod_reset, buf);   // placed below, once the lower module is known

    // Lower module
    enum { LOW_CREDITS, LOW_WINDOW, LOW_GRID, LOW_REMAINING } low;
    if (fable)                                             low = LOW_GRID;
    else if (ent)                                          low = LOW_WINDOW;
    else if (data->has_credits)                            low = LOW_CREDITS;
    else if (data->has_session && data->has_weekly)        low = LOW_WINDOW;
    else                                                   low = LOW_REMAINING;

    set_shown(credit_panel, low == LOW_CREDITS);
    set_shown(lbl_mod_remaining, low == LOW_REMAINING);
    set_shown(lbl_mod_remaining_word, low == LOW_REMAINING);
    set_shown(module_divider, low == LOW_REMAINING || low == LOW_WINDOW);
    set_shown(lbl_win_label, low == LOW_WINDOW);
    set_shown(lbl_win_pct, low == LOW_WINDOW);
    set_shown(bar_win, low == LOW_WINDOW);
    set_shown(lbl_win_reset, low == LOW_WINDOW);
    set_shown(grid_canvas, low == LOW_GRID);
    // The Fable grid stands in for the track, so the reset line takes the
    // "used" slot right of the figure (same face, right-aligned).
    set_shown(bar_mod, low != LOW_GRID);
    set_shown(lbl_mod_used, low != LOW_GRID);
    if (low == LOW_GRID) place_text_right(lbl_mod_reset, 448, MOD_USED_BASE);
    else                 place_text(lbl_mod_reset, 32, MOD_RESET_BASE);

    switch (low) {
    case LOW_CREDITS:
        render_credits(data, th);
        break;
    case LOW_WINDOW: {
        const float pct = ent ? (float)data->time_pct : data->session_pct;
        const int pct_i = pct_round(pct);
        lv_label_set_text(lbl_win_label, ent ? "BILLING PERIOD" : "CURRENT \xC2\xB7 5H");
        lv_label_set_text_fmt(lbl_win_pct, "%d%%", pct_i);
        lv_obj_set_style_text_color(lbl_win_pct, th.accent, 0);
        place_text_right(lbl_win_pct, 448, MOD_WIN_PCT_BASE);
        lv_bar_set_value(bar_win, pct_i, LV_ANIM_ON);
        lv_obj_set_style_bg_color(bar_win, th.accent, LV_PART_INDICATOR);
        if (ent) {
            // Pace: spending against the elapsed share of the billing period.
            const char* pace = "Under pace";
            lv_color_t  color = th.bar_ok;
            if (data->session_pct > (float)data->time_pct + 15.0f)      { pace = "Over pace"; color = th.bar_danger; }
            else if (data->session_pct > (float)data->time_pct - 15.0f) { pace = "On pace";   color = th.bar_warn; }
            lv_label_set_text(lbl_win_reset, pace);
            lv_obj_set_style_text_color(lbl_win_reset, color, 0);
        } else {
            format_reset_time(data->session_reset_mins, buf, sizeof(buf));
            lv_label_set_text(lbl_win_reset, buf);
            lv_obj_set_style_text_color(lbl_win_reset, COL_DIM, 0);
        }
        break;
    }
    case LOW_GRID:
        if (main_i != grid_filled) draw_clawds(main_i, th);
        break;
    case LOW_REMAINING:
        lv_label_set_text_fmt(lbl_mod_remaining, "%d%%", known ? 100 - main_i : 0);
        lv_obj_set_style_text_color(lbl_mod_remaining, th.accent, 0);
        lv_obj_set_pos(lbl_mod_remaining_word, MX(32) + label_w(lbl_mod_remaining) + MX(MOD_REMAIN_GAP),
                       text_top(L.mod_reset_font, MOD_REMAIN_BASE - 1));
        break;
    }
    // The mascot's full-size lurk peeks in over the lower area: only the
    // remaining line leaves it room.
    splash_mascot_set_trips(low == LOW_REMAINING);
}

// Dense fallback (C6): the three bars, every fill in the accent.
static void render_dense(const UsageData* data, const ProviderTheme& th) {
    char buf[48];
    const int s_pct = pct_round(data->session_pct);
    lv_label_set_text(lbl_session_label, "Current");
    lv_label_set_text_fmt(lbl_session_pct, "%d%%", s_pct);
    format_reset_time(data->session_reset_mins, buf, sizeof(buf));
    lv_label_set_text(lbl_session_reset, buf);
    lv_bar_set_value(bar_session, s_pct, LV_ANIM_ON);
    lv_obj_set_style_bg_color(bar_session, th.accent, LV_PART_INDICATOR);

    const int w_pct = pct_round(data->weekly_pct);
    lv_label_set_text(lbl_weekly_label, "Weekly");
    lv_label_set_text_fmt(lbl_weekly_pct, "%d%%", w_pct);
    lv_bar_set_value(bar_weekly, w_pct, LV_ANIM_ON);
    lv_obj_set_style_bg_color(bar_weekly, th.accent, LV_PART_INDICATOR);
    format_reset_time(data->weekly_reset_mins, buf, sizeof(buf));
    lv_label_set_text(lbl_weekly_reset, buf);

    const int t_pct = pct_round(data->third_pct);
    lv_label_set_text(lbl_third_label, data->third_label[0] ? data->third_label : "Fable");
    lv_obj_align(lbl_third_label, LV_ALIGN_TOP_RIGHT, 0, 1);
    lv_label_set_text_fmt(lbl_third_pct, "%d%%", t_pct);
    lv_bar_set_value(bar_third, t_pct, LV_ANIM_ON);
    lv_obj_set_style_bg_color(bar_third, th.accent, LV_PART_INDICATOR);
    format_reset_time(data->third_reset_mins, buf, sizeof(buf));
    lv_label_set_text(lbl_third_reset, buf);
    splash_mascot_set_trips(false);
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

// Render one view's data and make it the visible view.
static void show_view(int idx) {
    if (idx == UI_VIEW_FABLE && !fable_available()) idx = PROVIDER_CLAUDE;   // the limit went away
    // Logged only on a change; tools/test/shell/test_sim_sticky_view.sh reads it.
    if (idx != visible_view) Serial.printf("UI: showing view %d\n", idx);
    visible_view = idx;
    const int prov = view_provider(idx);
    const UsageData* data = &slots[prov].data;
    refresh_title();
    splash_mascot_set_provider(prov);   // corner mascot follows the visible provider

    // Everything accented on this screen follows the provider's palette.
    const ProviderTheme th = provider_theme(prov);
    lv_obj_set_style_bg_color(footer_dot, th.accent, 0);
    if (!alert_active) lv_obj_set_style_text_color(lbl_anim, th.status_text, 0);

    const usage_layout_t mode = layout_for(idx, data);
    if (layout_mode != mode) apply_usage_layout(mode);
    if (mode == LAYOUT_DENSE) render_dense(data, th);
    else                      render_module(idx, data, th);
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
    focus_tick_ui();   // a running block counts down on every screen
    if (current_screen != SCREEN_USAGE) return;
    update_view_state();
    if (view_state == 1) splash_mini_tick();   // animate the sleeping creature on the idle screen

    uint32_t now = lv_tick_get();

    // Header clock: once the daemon has sent wall-clock time, the clock rides
    // left of the provider label, advanced locally so it ticks every minute
    // between payloads.
    if (clock_base_epoch > 0) {
        time_t cur = (time_t)(clock_base_epoch + (now - clock_base_ms) / 1000);
        struct tm tmv;
        gmtime_r(&cur, &tmv);   // epoch is already local wall-clock → gmtime keeps it as-is
        if (tmv.tm_min != clock_last_min) {   // only rewrite the clock when the minute changes
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
            lv_label_set_text(lbl_clock, tbuf);
            layout_title();   // the clock width changed → re-align it against the provider label
        }
    }

    if (alert_active) return;          // the status line holds the alert message

    if (now - anim_msg_start >= ANIM_MSG_MS) {
        anim_msg_idx = (anim_msg_idx + 1) % ANIM_MSG_COUNT;
        anim_msg_start = now;
    }

    // Status verb by priority. Whimsical verbs only when connected & settled.
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
    if (strcmp(lv_label_get_text(lbl_anim), text) != 0) lv_label_set_text(lbl_anim, text);
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
        // Single-button boards have no side button: a swipe down that starts
        // in the header opens the app center instead of the splash.
        if (dir == LV_DIR_BOTTOM && board_caps().button_count < 2 && apps_enabled_count() > 1) {
            lv_indev_t* indev = lv_indev_active();
            lv_point_t p = { 0, L.scr_h };
            if (indev) lv_indev_get_point(indev, &p);
            if (p.y < L.content_y) { ui_show_screen(SCREEN_APPS); return true; }
        }
        if (vertical)                 { ui_show_screen(SCREEN_SPLASH); return true; }
        if (dir == LV_DIR_LEFT)       return ui_carousel_next();
        if (dir == LV_DIR_RIGHT)      return ui_carousel_prev();
        return false;
    case SCREEN_FOCUS:
        // Setup: swipe up +5 / down −5. Running, paused and done ignore swipes.
        if (dir == LV_DIR_TOP)        { if (focus_adjust(&focus, +1)) { render_focus(); return true; } return false; }
        if (dir == LV_DIR_BOTTOM)     { if (focus_adjust(&focus, -1)) { render_focus(); return true; } return false; }
        return false;
    default:
        return false;
    }
}

void ui_show_screen(screen_t screen) {
    lv_obj_add_flag(usage_container, LV_OBJ_FLAG_HIDDEN);
    if (apps_container)  lv_obj_add_flag(apps_container, LV_OBJ_FLAG_HIDDEN);
    if (focus_container) lv_obj_add_flag(focus_container, LV_OBJ_FLAG_HIDDEN);
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
    case SCREEN_APPS:    layout_apps(); lv_obj_clear_flag(apps_container, LV_OBJ_FLAG_HIDDEN); break;
    case SCREEN_FOCUS:   render_focus(); lv_obj_clear_flag(focus_container, LV_OBJ_FLAG_HIDDEN); break;
    default: break;
    }

    // The corner mascot / still logo belong to the meter only.
    splash_mascot_set_visible(screen == SCREEN_USAGE);
    if (logo_img) {
        if (screen == SCREEN_USAGE) lv_obj_clear_flag(logo_img, LV_OBJ_FLAG_HIDDEN);
        else                        lv_obj_add_flag(logo_img, LV_OBJ_FLAG_HIDDEN);
    }

    if (screen != SCREEN_SPLASH) prev_non_splash_screen = screen;
    if (screen == SCREEN_USAGE || screen == SCREEN_FOCUS) last_app_screen = screen;
    current_screen = screen;
    apply_battery_visibility();
    apply_alert_overlay();
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
    lv_obj_set_width(lbl_anim, MX(448) - MX(MOD_FOOT_TEXT_X));
    lv_obj_set_style_text_color(lbl_anim, provider_color(view_provider(visible_view)), 0);
    lv_label_set_text(lbl_anim, message);
    if (lbl_overlay_alert) lv_label_set_text(lbl_overlay_alert, message);
    apply_alert_overlay();
    lv_timer_reset(alert_timer);
    lv_timer_resume(alert_timer);
}

void ui_hide_alert(void) {
    if (!alert_active) return;
    alert_active = false;
    splash_mascot_attention(false);
    lv_label_set_long_mode(lbl_anim, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(lbl_anim, LV_SIZE_CONTENT);
    lv_obj_set_style_text_color(lbl_anim, provider_theme(view_provider(visible_view)).status_text, 0);
    lv_timer_pause(alert_timer);
    apply_alert_overlay();
}

// ---- App center and Focus public API (H12) ----

bool ui_apps_toggle(void) {
    if (current_screen == SCREEN_APPS) {
        ui_show_screen(apps_enabled(APP_FOCUS) || last_app_screen == SCREEN_USAGE ? last_app_screen : SCREEN_USAGE);
        return true;
    }
    if (apps_enabled_count() < 2) return false;   // only Meter: nothing to pick from
    ui_show_screen(SCREEN_APPS);
    return true;
}

void ui_apps_refresh(void) {
    layout_apps();
    // Focus got disabled while it was up: back to the meter.
    if (!apps_enabled(APP_FOCUS)) {
        // A block that was still counting would otherwise ring the bell from
        // an app the host just switched off.
        if (focus_cancel(&focus)) Serial.println("focus: block cancelled (app disabled)");
        if (current_screen == SCREEN_FOCUS || last_app_screen == SCREEN_FOCUS) {
            last_app_screen = SCREEN_USAGE;
            if (current_screen == SCREEN_FOCUS) ui_show_screen(SCREEN_USAGE);
        }
    }
}

bool ui_focus_running(void) {
    return focus.phase == FOCUS_RUNNING;
}

bool ui_focus_pwr_press(void) {
    if (current_screen != SCREEN_FOCUS) return false;
    return focus_action();
}

bool ui_focus_command(const char* action) {
    if (!action) return false;
    bool ok = false;
    if (strcmp(action, "start") == 0)       ok = focus_do_start();
    else if (strcmp(action, "next") == 0)   { if (focus.phase != FOCUS_DONE) return false; focus_next_setup(); return true; }
    else if (strcmp(action, "pause") == 0)  ok = focus_toggle_pause(&focus, lv_tick_get());
    else if (strcmp(action, "cancel") == 0) ok = focus_cancel(&focus);
    else if (strcmp(action, "plus") == 0)   ok = focus_adjust(&focus, +1);
    else if (strcmp(action, "minus") == 0)  ok = focus_adjust(&focus, -1);
    else if (strcmp(action, "finish") == 0) {
        ok = focus_finish_now(&focus, clock_day_now());
        if (ok) { focus_finished(); return true; }
    }
    else return false;
    if (ok) render_focus();
    return ok;
}
