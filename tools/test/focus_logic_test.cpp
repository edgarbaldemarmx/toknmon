// Native tests for the Focus block timer state machine (firmware/src/focus_logic.cpp).
// Build and run through tools/test/shell/test_focus_logic.sh. Plain asserts,
// one PASS/FAIL line per case, non-zero exit on any failure.
#include "focus_logic.h"
#include <cstdio>
#include <cstdint>

static int fails = 0;

#define CHECK(label, cond)                                   \
    do {                                                     \
        if (cond) printf("PASS: %s\n", label);               \
        else { printf("FAIL: %s\n", label); fails++; }        \
    } while (0)

static const uint32_t MIN_MS = 60000u;

static void test_adjust_clamps(void) {
    FocusState st;
    focus_init(&st, 0, 0);
    CHECK("default length is 25 min", st.length_min == 25 && st.phase == FOCUS_SETUP);
    focus_adjust(&st, +1);
    CHECK("+5 -> 30", st.length_min == 30);
    focus_adjust(&st, -1);
    focus_adjust(&st, -1);
    CHECK("-5 twice -> 20", st.length_min == 20);
    for (int i = 0; i < 10; i++) focus_adjust(&st, -1);
    CHECK("-5 clamps at 5", st.length_min == 5);
    bool changed = focus_adjust(&st, -1);
    CHECK("-5 at the floor reports no change", !changed && st.length_min == 5);
    for (int i = 0; i < 40; i++) focus_adjust(&st, +1);
    CHECK("+5 clamps at 120", st.length_min == 120);
    changed = focus_adjust(&st, +1);
    CHECK("+5 at the ceiling reports no change", !changed && st.length_min == 120);
    focus_start(&st, 1000);
    changed = focus_adjust(&st, -1);
    CHECK("adjust ignored while running", !changed && st.length_min == 120);
}

static void test_transitions(void) {
    FocusState st;
    focus_init(&st, 0, 0);
    CHECK("pause in setup is ignored", !focus_toggle_pause(&st, 10) && st.phase == FOCUS_SETUP);
    CHECK("cancel in setup is ignored", !focus_cancel(&st));
    CHECK("start from setup", focus_start(&st, 1000) && st.phase == FOCUS_RUNNING);
    CHECK("remaining equals the block length at start", focus_remaining_ms(&st) == 25 * MIN_MS);
    CHECK("start while running is ignored", !focus_start(&st, 2000));
    focus_tick(&st, 1000 + 10 * MIN_MS, 0);
    CHECK("ten minutes in, 15 remain", focus_remaining_ms(&st) == 15 * MIN_MS);
    CHECK("tap pauses", focus_toggle_pause(&st, 1000 + 10 * MIN_MS) && st.phase == FOCUS_PAUSED);
    focus_tick(&st, 1000 + 20 * MIN_MS, 0);
    CHECK("paused time does not count", focus_remaining_ms(&st) == 15 * MIN_MS);
    CHECK("tap resumes", focus_toggle_pause(&st, 1000 + 20 * MIN_MS) && st.phase == FOCUS_RUNNING);
    focus_tick(&st, 1000 + 25 * MIN_MS, 0);
    CHECK("resumed countdown continues from where it paused", focus_remaining_ms(&st) == 10 * MIN_MS);
    CHECK("long press cancels back to setup", focus_cancel(&st) && st.phase == FOCUS_SETUP);
    CHECK("cancel does not count a block", st.blocks == 0);
    CHECK("cancel keeps the length", st.length_min == 25);
}

static void test_countdown_exact(void) {
    FocusState st;
    focus_init(&st, 0, 0);
    focus_adjust(&st, -4);           // 5 min
    focus_start(&st, 500);
    bool fin = focus_tick(&st, 500 + 5 * MIN_MS - 1, 0);
    CHECK("one ms before the end: still running", !fin && st.phase == FOCUS_RUNNING && focus_remaining_ms(&st) == 1);
    fin = focus_tick(&st, 500 + 5 * MIN_MS, 0);
    CHECK("done exactly at the block length", fin && st.phase == FOCUS_DONE && focus_remaining_ms(&st) == 0);
    fin = focus_tick(&st, 500 + 6 * MIN_MS, 0);
    CHECK("done reported once", !fin && st.phase == FOCUS_DONE);
    CHECK("finished block counted", st.blocks == 1);
    // Overshoot: a late tick lands on done, never wraps.
    FocusState st2;
    focus_init(&st2, 0, 0);
    focus_adjust(&st2, -4);
    focus_start(&st2, 0);
    fin = focus_tick(&st2, 9 * MIN_MS, 0);
    CHECK("late tick past the end finishes with 0 remaining", fin && focus_remaining_ms(&st2) == 0);
}

static void test_next_block_keeps_length(void) {
    FocusState st;
    focus_init(&st, 0, 0);
    focus_adjust(&st, +3);           // 40 min
    focus_start(&st, 0);
    focus_tick(&st, 40 * MIN_MS, 0);
    CHECK("first block done", st.phase == FOCUS_DONE);
    CHECK("start next from done", focus_start(&st, 41 * MIN_MS) && st.phase == FOCUS_RUNNING);
    CHECK("next block has the same length", st.length_min == 40 && focus_remaining_ms(&st) == 40 * MIN_MS);
    focus_tick(&st, 81 * MIN_MS, 0);
    CHECK("second block counted", st.phase == FOCUS_DONE && st.blocks == 2);
}

static void finish_block(FocusState* st, uint32_t* t, uint32_t day) {
    focus_start(st, *t);
    *t += (uint32_t)st->length_min * MIN_MS;
    focus_tick(st, *t, day);
    *t += 1000;
}

static void test_day_counter(void) {
    uint32_t t = 0;
    FocusState st;
    focus_init(&st, 3, 20261021);
    CHECK("counter restored from storage", focus_blocks_today(&st, 20261021) == 3);
    finish_block(&st, &t, 20261021);
    CHECK("same day increments", st.blocks == 4 && st.blocks_day == 20261021);
    CHECK("display matches on the same day", focus_blocks_today(&st, 20261021) == 4);
    CHECK("a new known day shows 0 before any block", focus_blocks_today(&st, 20261022) == 0);
    finish_block(&st, &t, 20261022);
    CHECK("day change resets to 1 and stores the day", st.blocks == 1 && st.blocks_day == 20261022);

    FocusState nc;
    focus_init(&nc, 0, 0);
    t = 0;
    finish_block(&nc, &t, 0);
    finish_block(&nc, &t, 0);
    CHECK("unknown day keeps counting", nc.blocks == 2 && nc.blocks_day == 0);
    CHECK("unknown day displays the running count", focus_blocks_today(&nc, 0) == 2);
    finish_block(&nc, &t, 20261022);
    CHECK("first known day adopts the day without reset", nc.blocks == 3 && nc.blocks_day == 20261022);
    CHECK("stored day with unknown clock keeps displaying", focus_blocks_today(&nc, 0) == 3);
    finish_block(&nc, &t, 0);
    CHECK("clock lost again: still counting on the stored day", nc.blocks == 4 && nc.blocks_day == 20261022);
    finish_block(&nc, &t, 20261023);
    CHECK("clock back on a later day resets to 1", nc.blocks == 1 && nc.blocks_day == 20261023);

    FocusState sat;
    focus_init(&sat, 255, 0);
    t = 0;
    finish_block(&sat, &t, 0);
    CHECK("uint8 counter saturates at 255", sat.blocks == 255);
}

static void test_finish_now(void) {
    FocusState st;
    focus_init(&st, 0, 0);
    CHECK("finish-now in setup is ignored", !focus_finish_now(&st, 0) && st.phase == FOCUS_SETUP);
    focus_start(&st, 0);
    CHECK("finish-now ends a running block", focus_finish_now(&st, 20261022) && st.phase == FOCUS_DONE && st.blocks == 1);
}

int main(void) {
    test_adjust_clamps();
    test_transitions();
    test_countdown_exact();
    test_next_block_keeps_length();
    test_day_counter();
    test_finish_now();
    if (fails == 0) { printf("All focus_logic tests passed.\n"); return 0; }
    printf("%d check(s) failed.\n", fails);
    return 1;
}
