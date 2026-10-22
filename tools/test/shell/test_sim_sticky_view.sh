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
KILL_S=60      # a run that has not exited by then is killed and fails
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [ ! -x "$PROGRAM" ]; then
    echo "FAIL: no sim binary at $PROGRAM (run: pio run -d firmware -e sim)"
    exit 1
fi

# run_sim <case> <slot>: the sim exits on its own after RUN_MS (autoshot);
# perl's alarm is the portable watchdog (macOS has no `timeout`).
run_sim() {
    (cd "$REPO_ROOT/firmware" && \
        SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
        SIM_SCENARIO="$SCENARIO" SIM_SLOT="$2" \
        SIM_AUTOSHOT_MS="$RUN_MS" SIM_AUTOSHOT_PATH="$TMP_DIR/$1.bmp" \
        perl -e 'alarm shift; exec @ARGV or die "exec: $!"' "$KILL_S" "$PROGRAM" \
        > "$TMP_DIR/$1.log" 2>&1)
    echo $? > "$TMP_DIR/$1.rc"
}

# A run only counts when the sim exited cleanly, restored the seeded view,
# took every provider's payload and reached its final screenshot; otherwise
# "no view change" would pass on a crash or a run that never got data.
run_ok() {   # <case> <slot>
    local rc; rc="$(cat "$TMP_DIR/$1.rc")"
    if [ "$rc" != 0 ]; then fail "$1: sim exited with $rc"; return 1; fi
    if ! grep -q "UI: restored picked view $2\$" "$TMP_DIR/$1.log"; then
        fail "$1: no 'UI: restored picked view $2' in the boot log"; return 1
    fi
    local p
    for p in claude codex kimi grok; do
        if ! grep -q "BLE: packet p=$p ok=1" "$TMP_DIR/$1.log"; then
            fail "$1: the $p payload never landed"; return 1
        fi
    done
    if [ ! -s "$TMP_DIR/$1.bmp" ]; then fail "$1: no final screenshot"; return 1; fi
    pass "$1: sim ran ${RUN_MS} ms, restored view $2 and took all four payloads"
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

run_ok stay 0 &&
    expect_shown stay "" "Claude picked: the view never moves on its own for 12 s"
run_ok restore 3 &&
    expect_shown restore "0 3" "Grok picked: Claude stands in until Grok's data lands, then Grok stays"
# Fable's data is Claude's payload, the first to land, so the restored view
# shows at once; without the limit show_view() would fall back to Claude (0).
run_ok fable 4 &&
    expect_shown fable "" "Fable picked: the Fable view stays up (no fallback to Claude)"

[ "$fails" -eq 0 ] || { echo "$fails failure(s)"; exit 1; }
