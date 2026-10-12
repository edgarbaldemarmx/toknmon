#pragma once
#include <stdint.h>
#include <lvgl.h>
#include "data.h"

// Initialize splash module. Creates the canvas widget inside `parent` and
// allocates the 480x480 pixel buffer (PSRAM).
void splash_init(lv_obj_t *parent);

// Advance animation frame if hold time elapsed. Call from main loop.
void splash_tick(void);

// Cycle to the next animation in the catalog.
void splash_next(void);

// Show/hide the splash container.
void splash_show(void);
void splash_hide(void);

// Pick the next animation matching the current usage-rate group.
// Called automatically by splash_show(); also exposed so other modules can
// trigger a re-pick when the rate group changes mid-display.
void splash_pick_for_current_rate(void);

// True when splash is currently rendering (used to gate re-picks).
bool splash_is_active(void);

// Mascot mode: pin the splash to one provider's play-list (PROVIDER_* in
// data.h). Codex and Kimi cycle their own sets (idle, acts, bike) with a
// small provider label on top; PWR advances within the set. Claude or -1
// restores the default rate-group splash (the boot path). Takes effect on
// the next splash_show() when the splash is hidden.
void splash_set_provider(int slot);
// Parade: rotate the stage across the fresh provider slots every
// PARADE_PROVIDER_MS, each playing its own set (Claude uses its rate groups).
// Does nothing when no slot is fresh. The UI stops it on any touch.
void splash_parade_start(const bool fresh[PROVIDER_COUNT]);
void splash_parade_stop(void);
bool splash_is_parade(void);

// Root container (so ui.cpp can attach a click event).
lv_obj_t* splash_get_root(void);

// Mini animated creature for embedding elsewhere (e.g. the idle screen).
// Renders the named official animation (e.g. "cloud") at ~px×px
// inside `parent`; returns the canvas object (position it with lv_obj_align) or
// NULL if the animation isn't found / allocation fails. Drive it with
// splash_mini_tick(). One mini creature at a time.
lv_obj_t* splash_mini_create(lv_obj_t *parent, const char *anim_name, int px);
void splash_mini_tick(void);

// Corner mascot (usage screen, PSRAM boards): the still Clawd idles in the
// logo slot, does occasional acts, and takes walk-off/lurk/walk-back trips.
// feet_y = px of the art's ground line; cell = px per art cell in the corner.
lv_obj_t* splash_mascot_create(lv_obj_t *parent, int slot_x, int feet_y, int cell);
void splash_mascot_tick(void);
void splash_mascot_set_visible(bool v);
// Attention: the corner Clawd walks off, a full-size one walks in and waves
// and points until attention(false), then they swap back. No-op without the
// PSRAM mascot.
void splash_mascot_attention(bool on);
// Swap the corner mascot for the given provider slot (PROVIDER_* in data.h):
// Clawd for Claude, the dots for Codex, the moon for Kimi. Called by the UI
// whenever the carousel changes slot. No-op without the PSRAM mascot.
void splash_mascot_set_provider(int slot);
// Allow or pause the walk-off / lurk / walk-back trips (the full-size lurk
// crosses the panel area). Acts in place keep playing either way.
void splash_mascot_set_trips(bool enabled);
