#!/bin/bash
# Tests for install-mac.sh's `configure_apps` (the `--apps meter|suite` option
# and the `apps` config key). Plain bash, no framework:
#   bash tools/test/shell/test_install_apps.sh
# The functions are extracted from the installer and run against a scratch
# config file, so nothing under ~/.config is touched.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

extract() {
    sed -n "/^$1()/,/^}/p" "$REPO_ROOT/install-mac.sh" > "$TMP_DIR/$1.fn"
    [ -s "$TMP_DIR/$1.fn" ] || { echo "FAIL: no $1() in install-mac.sh"; exit 1; }
}
extract current_config_value
extract upsert_config_key
extract configure_apps

fails=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; fails=$((fails + 1)); }

# run <opt_apps> <interactive 0|1> <stdin> [existing apps value]
# Prints the installer output, then "---", then the resulting config file.
run() {
    local opt="$1" inter="$2" input="$3" existing="${4:-}"
    local cfg="$TMP_DIR/config"
    rm -f "$cfg"
    if [ -n "$existing" ]; then printf 'device_name = Desk\napps = %s\n' "$existing" > "$cfg"; fi
    printf '%s' "$input" | bash -c "
        set -u
        CONFIG_FILE='$cfg'
        OPT_APPS='$opt'
        interactive() { [ '$inter' = 1 ]; }
        $(cat "$TMP_DIR/current_config_value.fn" "$TMP_DIR/upsert_config_key.fn" "$TMP_DIR/configure_apps.fn")
        configure_apps
        echo '---'
        [ -f \"\$CONFIG_FILE\" ] && cat \"\$CONFIG_FILE\"
    " 2>&1
}

out=$(run "" 0 "")
if echo "$out" | grep -q "default" && ! echo "$out" | grep -q "^apps ="; then
    pass "--yes without a saved value keeps the daemon default (suite) and writes nothing"
else
    fail "--yes default case: $out"
fi

out=$(run "meter" 0 "")
if echo "$out" | grep -q "^apps = meter$"; then
    pass "--apps meter writes apps = meter"
else
    fail "--apps meter: $out"
fi

out=$(run "suite" 0 "" "meter")
if echo "$out" | grep -q "^apps = meter,focus$"; then
    pass "--apps suite writes apps = meter,focus over an existing meter-only value"
else
    fail "--apps suite: $out"
fi

out=$(run "" 0 "" "meter")
if echo "$out" | grep -q "unchanged" && echo "$out" | grep -q "^apps = meter$"; then
    pass "--yes keeps an existing explicit value"
else
    fail "--yes keep existing: $out"
fi

out=$(run "focus" 0 "")
if echo "$out" | grep -qi "error" && ! echo "$out" | grep -q "^apps ="; then
    pass "--apps with an unknown value is an error and writes nothing"
else
    fail "--apps unknown value: $out"
fi

out=$(run "" 1 $'meter\n')
if echo "$out" | grep -q "^apps = meter$"; then
    pass "interactive answer 'meter' writes apps = meter"
else
    fail "interactive meter: $out"
fi

out=$(run "" 1 $'\n' "meter")
if echo "$out" | grep -q "^apps = meter$"; then
    pass "interactive empty answer keeps the saved value"
else
    fail "interactive keep: $out"
fi

out=$(run "" 1 $'suite\n')
if echo "$out" | grep -q "^apps = meter,focus$"; then
    pass "interactive answer 'suite' writes apps = meter,focus"
else
    fail "interactive suite: $out"
fi

if [ "$fails" -eq 0 ]; then
    echo "All install --apps tests passed."
    exit 0
fi
echo "$fails test(s) failed."
exit 1
