#!/bin/bash
# Headless checks of the sticky usage view (H10) against the desktop sim.
# Build the sim first (`pio run -d firmware -e sim`), then:
#   bash tools/test/shell/test_sim_sticky_view.sh
# Each case seeds the picked view with SIM_SLOT, plays the gallery scenario
# (every provider lands in the first pass, Claude first) and reads the
# firmware's serial log: "UI: restored picked view N" at boot and
# "UI: showing view N" whenever the view on screen changes. SIM_PROGRAM
# overrides the binary (e.g. a build of an older commit for a RED run).
# Prints one PASS/FAIL line per case and exits non-zero on any failure.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PROGRAM="${SIM_PROGRAM:-$REPO_ROOT/firmware/.pio/build/sim/program}"
SCENARIO="$REPO_ROOT/firmware/sim/gallery.jsonl"
RUN_MS=12000   # past the 8 s the removed carousel took to rotate
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [ ! -x "$PROGRAM" ]; then
    echo "FAIL: no sim binary at $PROGRAM (run: pio run -d firmware -e sim)"
    exit 1
fi

# run_sim <case> <slot>: the sim exits on its own after RUN_MS (autoshot).
run_sim() {
    (cd "$REPO_ROOT/firmware" && \
        SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
        SIM_SCENARIO="$SCENARIO" SIM_SLOT="$2" \
        SIM_AUTOSHOT_MS="$RUN_MS" SIM_AUTOSHOT_PATH="$TMP_DIR/$1.bmp" \
        "$PROGRAM" > "$TMP_DIR/$1.log" 2>&1)
}

# Views shown in order, space separated ("" when the first view never changed).
shown() { grep -o 'UI: showing view [0-9]*' "$TMP_DIR/$1.log" | awk '{print $4}' | xargs; }

fails=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; fails=$((fails + 1)); }
expect_shown() {   # <case> <expected sequence> <description>
    local got; got="$(shown "$1")"
    if [ "$got" = "$2" ]; then pass "$3"
    else fail "$3 (views shown: '${got}', expected '$2')"; tail -n 20 "$TMP_DIR/$1.log"; fi
}

run_sim stay 0 &
run_sim restore 3 &
run_sim fable 4 &
wait

expect_shown stay "" "Claude picked: the view never moves on its own for 12 s"
expect_shown restore "0 3" "Grok picked: Claude stands in until Grok's data lands, then Grok stays"
if grep -q 'UI: restored picked view 3' "$TMP_DIR/restore.log"; then
    pass "the picked view is restored from NVS at boot"
else
    fail "no 'UI: restored picked view 3' in the boot log"
fi
# Fable's data is Claude's payload, the first to land, so the restored view
# shows at once; without the limit show_view() would fall back to Claude (0).
if grep -q 'UI: restored picked view 4' "$TMP_DIR/fable.log"; then
    expect_shown fable "" "Fable picked: the Fable view stays up (no fallback to Claude)"
else
    fail "no 'UI: restored picked view 4' in the boot log"
fi

[ "$fails" -eq 0 ] || { echo "$fails failure(s)"; exit 1; }
