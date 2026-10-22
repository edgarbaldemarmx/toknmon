#include "focus_logic.h"

static const uint32_t MS_PER_MIN = 60000u;

void focus_init(FocusState* st, uint8_t blocks, uint32_t blocks_day) {
    st->phase = FOCUS_SETUP;
    st->length_min = FOCUS_DEFAULT_MINUTES;
    st->remaining_ms = 0;
    st->last_tick_ms = 0;
    st->blocks = blocks;
    st->blocks_day = blocks_day;
}

bool focus_adjust(FocusState* st, int steps) {
    if (st->phase != FOCUS_SETUP) return false;
    int len = (int)st->length_min + steps * FOCUS_STEP_MINUTES;
    if (len < FOCUS_MIN_MINUTES) len = FOCUS_MIN_MINUTES;
    if (len > FOCUS_MAX_MINUTES) len = FOCUS_MAX_MINUTES;
    if (len == (int)st->length_min) return false;
    st->length_min = (uint16_t)len;
    return true;
}

bool focus_start(FocusState* st, uint32_t now_ms) {
    if (st->phase != FOCUS_SETUP && st->phase != FOCUS_DONE) return false;
    st->remaining_ms = (uint32_t)st->length_min * MS_PER_MIN;
    st->last_tick_ms = now_ms;
    st->phase = FOCUS_RUNNING;
    return true;
}

bool focus_toggle_pause(FocusState* st, uint32_t now_ms) {
    if (st->phase == FOCUS_RUNNING) {
        focus_tick(st, now_ms, 0);          // bank the time up to the pause
        if (st->phase == FOCUS_RUNNING) st->phase = FOCUS_PAUSED;
        return true;
    }
    if (st->phase == FOCUS_PAUSED) {
        st->last_tick_ms = now_ms;
        st->phase = FOCUS_RUNNING;
        return true;
    }
    return false;
}

bool focus_cancel(FocusState* st) {
    if (st->phase != FOCUS_RUNNING && st->phase != FOCUS_PAUSED) return false;
    st->phase = FOCUS_SETUP;
    st->remaining_ms = 0;
    return true;
}

// S1.3: a finished block on a known day that differs from the stored known
// day starts a new count; otherwise the count grows. A stored day of 0 adopts
// the first known day without resetting, so blocks finished before the clock
// arrived still count for the day it reports.
static void count_block(FocusState* st, uint32_t clock_day) {
    if (clock_day != 0 && st->blocks_day != 0 && clock_day != st->blocks_day) {
        st->blocks = 1;
        st->blocks_day = clock_day;
        return;
    }
    if (st->blocks < 255) st->blocks++;
    if (clock_day != 0 && st->blocks_day == 0) st->blocks_day = clock_day;
}

bool focus_tick(FocusState* st, uint32_t now_ms, uint32_t clock_day) {
    if (st->phase != FOCUS_RUNNING) return false;
    uint32_t delta = now_ms - st->last_tick_ms;   // unsigned wrap-safe
    st->last_tick_ms = now_ms;
    if (delta < st->remaining_ms) {
        st->remaining_ms -= delta;
        return false;
    }
    st->remaining_ms = 0;
    st->phase = FOCUS_DONE;
    count_block(st, clock_day);
    return true;
}

bool focus_finish_now(FocusState* st, uint32_t clock_day) {
    if (st->phase != FOCUS_RUNNING && st->phase != FOCUS_PAUSED) return false;
    st->remaining_ms = 0;
    st->phase = FOCUS_DONE;
    count_block(st, clock_day);
    return true;
}

uint32_t focus_remaining_ms(const FocusState* st) {
    return st->remaining_ms;
}

uint8_t focus_blocks_today(const FocusState* st, uint32_t clock_day) {
    if (clock_day != 0 && st->blocks_day != 0 && clock_day != st->blocks_day) return 0;
    return st->blocks;
}
