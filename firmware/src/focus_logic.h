#pragma once
#include <stdint.h>

// Focus block timer — pure state machine (no LVGL, no Arduino) so it builds
// natively for tools/test/focus_logic_test.cpp. ui.cpp owns the widgets, the
// bell and NVS; it feeds this module millis() deltas, user events and the
// daemon clock's day (YYYYMMDD, 0 when no clock has arrived).
//
// Phases: SETUP (pick the length) → RUNNING ⇄ PAUSED → DONE → RUNNING (next
// block, same length). Cancel returns RUNNING/PAUSED to SETUP without
// counting. A block counts when its countdown reaches zero.

enum focus_phase_t { FOCUS_SETUP, FOCUS_RUNNING, FOCUS_PAUSED, FOCUS_DONE };

#define FOCUS_MIN_MINUTES     5
#define FOCUS_MAX_MINUTES     120
#define FOCUS_STEP_MINUTES    5
#define FOCUS_DEFAULT_MINUTES 25

struct FocusState {
    focus_phase_t phase;
    uint16_t length_min;    // block length, FOCUS_MIN..FOCUS_MAX in steps of 5
    uint32_t remaining_ms;  // countdown while RUNNING/PAUSED; 0 when DONE
    uint32_t last_tick_ms;  // now_ms of the last RUNNING tick (delta source)
    uint8_t  blocks;        // finished blocks on blocks_day (NVS fx_cnt)
    uint32_t blocks_day;    // YYYYMMDD the counter belongs to, 0 = unknown (NVS fx_day)
};

// Reset to SETUP with the default length and the stored counter.
void focus_init(FocusState* st, uint8_t blocks, uint32_t blocks_day);

// SETUP only: move the length by `steps` × 5 min, clamped to 5..120.
// Returns true when the length changed.
bool focus_adjust(FocusState* st, int steps);

// SETUP or DONE → RUNNING with the current length. False in other phases.
bool focus_start(FocusState* st, uint32_t now_ms);

// RUNNING → PAUSED, PAUSED → RUNNING (the countdown resumes from now_ms).
// False in other phases.
bool focus_toggle_pause(FocusState* st, uint32_t now_ms);

// RUNNING or PAUSED → SETUP without counting the block. False otherwise.
bool focus_cancel(FocusState* st);

// Advance the countdown while RUNNING. Returns true exactly once, on the tick
// that reaches zero: the block is counted against clock_day (see below) and
// the phase becomes DONE.
bool focus_tick(FocusState* st, uint32_t now_ms, uint32_t clock_day);

// QA hook: end a RUNNING/PAUSED block now, counting it. False otherwise.
bool focus_finish_now(FocusState* st, uint32_t clock_day);

uint32_t focus_remaining_ms(const FocusState* st);

// Blocks finished today as the UI shows them: `blocks`, except when both the
// clock day and the stored day are known and differ (a new day with no block
// yet), which reads 0.
uint8_t focus_blocks_today(const FocusState* st, uint32_t clock_day);
