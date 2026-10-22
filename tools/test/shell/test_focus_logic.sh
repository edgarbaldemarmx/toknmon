#!/bin/bash
# Native build-and-run of the Focus timer state machine tests
# (tools/test/focus_logic_test.cpp against firmware/src/focus_logic.cpp).
# The module has no LVGL/Arduino includes, so any C++17 compiler works:
#   bash tools/test/shell/test_focus_logic.sh
# Prints one PASS/FAIL line per check and exits non-zero on any failure.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

CXX="${CXX:-c++}"
if ! "$CXX" -std=c++17 -Wall -Wextra -I "$REPO_ROOT/firmware/src" \
        "$REPO_ROOT/firmware/src/focus_logic.cpp" \
        "$REPO_ROOT/tools/test/focus_logic_test.cpp" -o "$TMP_DIR/t"; then
    echo "FAIL: focus_logic test build failed"
    exit 1
fi
"$TMP_DIR/t"
