#pragma once
#include <lvgl.h>
#include "data.h"

// Design tokens — single source of truth for UI colors. Anthropic-inspired
// dark palette, AMOLED-friendly (true black bg).
#define THEME_BG       lv_color_hex(0x000000)   // screen background
#define THEME_PANEL    lv_color_hex(0x1f1f1e)   // card/zone fill
#define THEME_TEXT     lv_color_hex(0xfaf9f5)   // primary text
#define THEME_DIM      lv_color_hex(0xb0aea5)   // secondary text
#define THEME_ACCENT   lv_color_hex(0xd97757)   // brand terra-cotta
#define THEME_GREEN    lv_color_hex(0x788c5d)
#define THEME_AMBER    lv_color_hex(0xd97757)
#define THEME_RED      lv_color_hex(0xc0392b)
#define THEME_BAR_BG   lv_color_hex(0x2a2a28)   // unfilled bar track
// Provider accents — title / pill color per carousel slot (see data.h).
#define THEME_CLAUDE   THEME_ACCENT                 // Anthropic terra-cotta
#define THEME_CODEX    lv_color_hex(0x10a37f)   // OpenAI green-teal
#define THEME_KIMI     lv_color_hex(0x3b6cf6)   // Moonshot blue

// Per-provider palette. Every colored element on a provider's usage screen
// (title / pill, bar fills, dot grid, status spinner) draws from its theme,
// so a Codex or Kimi screen never shows the Claude terra-cotta.
struct ProviderTheme {
    lv_color_t accent;       // title text / provider pill / filled dots
    lv_color_t bar_ok;       // bar fill below 50 %
    lv_color_t bar_warn;     // bar fill 50-79 %
    lv_color_t bar_danger;   // bar fill 80 % and above
    lv_color_t status_text;  // animated status line at the bottom
    lv_color_t dot_empty;    // unfilled dot in the Codex dot grid
};

static inline ProviderTheme provider_theme(int provider) {
    ProviderTheme t;
    switch (provider) {
    case PROVIDER_CODEX:
        t.accent      = THEME_CODEX;
        t.bar_ok      = THEME_CODEX;
        t.bar_warn    = lv_color_hex(0xc9d42b);   // yellow-green, deliberately not orange
        t.bar_danger  = lv_color_hex(0xe5484d);
        t.status_text = THEME_CODEX;
        t.dot_empty   = lv_color_hex(0x1f3a33);
        break;
    case PROVIDER_KIMI:
        t.accent      = THEME_KIMI;
        t.bar_ok      = THEME_KIMI;
        t.bar_warn    = lv_color_hex(0x8b5cf6);   // violet
        t.bar_danger  = lv_color_hex(0xe5484d);
        t.status_text = THEME_KIMI;
        t.dot_empty   = lv_color_hex(0x1e2a4a);
        break;
    default:   // Claude keeps the historical palette
        t.accent      = THEME_CLAUDE;
        t.bar_ok      = THEME_GREEN;
        t.bar_warn    = THEME_AMBER;
        t.bar_danger  = THEME_RED;
        t.status_text = THEME_CLAUDE;
        t.dot_empty   = THEME_BAR_BG;
        break;
    }
    return t;
}
