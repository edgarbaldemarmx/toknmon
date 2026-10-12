#!/bin/bash
# Tests for the shared `valid_device_name` validator that flash-mac.sh and
# install-mac.sh both carry verbatim. Plain bash, no framework:
#   bash tools/test/shell/test_device_name_validator.sh
# Prints one PASS/FAIL line per case and exits non-zero on any failure.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

extract_validator() {
    sed -n '/^valid_device_name()/,/^}/p' "$REPO_ROOT/$1" > "$TMP_DIR/$1.fn"
    [ -s "$TMP_DIR/$1.fn" ] || { echo "FAIL: no valid_device_name() in $1"; exit 1; }
}
extract_validator flash-mac.sh
extract_validator install-mac.sh

fails=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; fails=$((fails + 1)); }

# Both copies must stay byte-identical.
if diff -q "$TMP_DIR/flash-mac.sh.fn" "$TMP_DIR/install-mac.sh.fn" >/dev/null; then
    pass "validator copies in flash-mac.sh and install-mac.sh are byte-identical"
else
    fail "validator copies differ:"
    diff "$TMP_DIR/flash-mac.sh.fn" "$TMP_DIR/install-mac.sh.fn"
fi

# shellcheck disable=SC1090
source "$TMP_DIR/flash-mac.sh.fn"

# expect_valid <label> <input> <expected echoed value>
expect_valid() {
    local label="$1" input="$2" want="$3" got
    if got=$(valid_device_name "$input") && [ "$got" = "$want" ]; then
        pass "$label -> '$got'"
    else
        fail "$label (got rc=$? value='${got:-}', want '$want')"
    fi
}

# expect_invalid <label> <input>
expect_invalid() {
    local label="$1" input="$2" got
    if got=$(valid_device_name "$input"); then
        fail "$label was accepted as '$got'"
    elif [ -n "$got" ]; then
        fail "$label rejected but echoed '$got'"
    else
        pass "$label rejected"
    fi
}

expect_valid   "1 char"                       "A"                   "A"
expect_valid   "18 chars"                     "ABCDEFGHIJKLMNOPQR"  "ABCDEFGHIJKLMNOPQR"
expect_valid   "spaces inside are kept"       "ToknMon Desk One"   "ToknMon Desk One"
expect_valid   "surrounding whitespace trimmed" " Desk 2 "          "Desk 2"
expect_valid   "tab/newline around trimmed"   $'\tDesk 2\n'         "Desk 2"
expect_invalid "19 chars"                     "ABCDEFGHIJKLMNOPQRS"
expect_invalid "hash (config comment marker)" "Desk #2"
expect_invalid "embedded newline"             $'a\nb'
expect_invalid "embedded carriage return"     $'a\rb'
expect_invalid "embedded tab"                 $'a\tb'
expect_invalid "non-ASCII (Tokén)"            "Tokén"
expect_invalid "empty"                        ""
expect_invalid "whitespace only"              "   "

if [ "$fails" -eq 0 ]; then
    echo "All device-name validator tests passed."
    exit 0
fi
echo "$fails test(s) failed."
exit 1
