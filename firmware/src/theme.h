#pragma once
#include <lvgl.h>
#include "data.h"

// Design tokens — single source of truth for UI colors (H14 design system,
// docs/odd/toknmon-h14-ui-redesign.md L9). One dark palette for the usage
// pages, the app center and Focus; each provider only contributes its accent.
#define UI_BG          lv_color_hex(0x0B0F14)   // whole display behind the pages
#define UI_SURFACE     lv_color_hex(0x121A23)   // credit panel, app tiles, secondary controls
#define UI_DIVIDER     lv_color_hex(0x293541)   // 1 px quiet structure
#define UI_TRACK       lv_color_hex(0x33414F)   // unfilled usage / ring track
#define UI_TEXT        lv_color_hex(0xF2F5F7)   // percentage, countdown, key values
#define UI_MUTED       lv_color_hex(0xAAB5C0)   // labels, reset time, metadata

// Legacy names kept for the splash and the parts of the UI that have not
// moved to the token names yet. THEME_BG stays true black: it is the splash
// background and palette index 0 of every animation (splash.cpp).
#define THEME_BG       lv_color_hex(0x000000)
#define THEME_PANEL    UI_SURFACE
#define THEME_TEXT     UI_TEXT
#define THEME_DIM      UI_MUTED
#define THEME_ACCENT   THEME_CLAUDE               // Claude accent; Focus keeps it until its own unit
#define THEME_GREEN    lv_color_hex(0x8FBF9F)   // enterprise pace: under
#define THEME_AMBER    THEME_FOCUS                // enterprise pace: on
#define THEME_RED      lv_color_hex(0xE5484D)   // enterprise pace: over
#define THEME_BAR_BG   UI_TRACK

// Provider accents — title, filled bar, available-credit segments, status
// dot and the remaining / 5-hour figures of each page (see data.h).
#define THEME_CLAUDE   lv_color_hex(0xE3A18B)   // terracotta
// Codex: monochrome, the user's pick (L9). The designer's recommendation was
// ice blue 0xB8DDFF; swap the value to compare.
#define THEME_CODEX    lv_color_hex(0xF2F5F7)
// #define THEME_CODEX lv_color_hex(0xB8DDFF)   // ice blue alternative
#define THEME_KIMI     lv_color_hex(0x9DB7FF)   // pastel of Moonshot's 0x3B6CF6
#define THEME_GROK     lv_color_hex(0xCDD5DF)   // silver
#define THEME_FOCUS    lv_color_hex(0xF2C078)   // amber: the Focus app, not a provider

// Per-provider palette. The usage page tints only the accent slots; the
// bar tiers are kept for the enterprise pace line (Under / On / Over pace),
// which is the one place a usage figure still changes colour.
struct ProviderTheme {
    lv_color_t accent;       // title text / filled track / credit segments / status dot
    lv_color_t bar_ok;       // enterprise pace: under
    lv_color_t bar_warn;     // enterprise pace: on
    lv_color_t bar_danger;   // enterprise pace: over
    lv_color_t status_text;  // footer status verb
    lv_color_t dot_empty;    // the unfilled Clawd glyphs of the Fable grid
    lv_color_t pill_text;    // ink on an accent-filled control (mascot-mode label stays accent on black)
};

static inline ProviderTheme provider_theme(int provider) {
    ProviderTheme t;
    switch (provider) {
    case PROVIDER_CODEX: t.accent = THEME_CODEX; break;
    case PROVIDER_KIMI:  t.accent = THEME_KIMI;  break;
    case PROVIDER_GROK:  t.accent = THEME_GROK;  break;
    default:             t.accent = THEME_CLAUDE; break;
    }
    t.bar_ok      = THEME_GREEN;
    t.bar_warn    = THEME_AMBER;
    t.bar_danger  = THEME_RED;
    t.status_text = UI_MUTED;
    t.dot_empty   = UI_TRACK;
    t.pill_text   = UI_BG;
    return t;
}
