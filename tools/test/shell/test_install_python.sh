#!/bin/bash
# Tests for install-mac.sh's interpreter choice (`pick_python`) and the
# self-heal check for a venv tied to a Homebrew keg (`venv_pinned_to_keg`).
# Plain bash, no framework:
#   bash tools/test/shell/test_install_python.sh
# The functions are extracted from the installer and run against interpreters
# and venvs built in a scratch directory, so nothing outside it is touched.
# Needs one of python3.13 … python3.10 on PATH (CI's setup-python provides
# 3.12); skips otherwise.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

extract() {
    sed -n "/^$1()/,/^}/p" "$REPO_ROOT/install-mac.sh" > "$TMP_DIR/$1.fn"
    [ -s "$TMP_DIR/$1.fn" ] || { echo "FAIL: no $1() in install-mac.sh"; exit 1; }
}
# py_ge_310 is a one-liner, so the range extraction above does not fit it.
grep '^py_ge_310()' "$REPO_ROOT/install-mac.sh" > "$TMP_DIR/py_ge_310.fn"
[ -s "$TMP_DIR/py_ge_310.fn" ] || { echo "FAIL: no py_ge_310() in install-mac.sh"; exit 1; }
extract py_is_venv
extract pick_python
extract venv_pinned_to_keg

fails=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; fails=$((fails + 1)); }

# A real base interpreter (not a venv) under one of the names pick_python
# searches: the first python3.13 … python3.10 on PATH, resolved to the install
# it is built on (it may itself be a venv). A plain `python3` can be 3.14+,
# which pick_python never looks for by name.
FOUND_PY=""
for name in python3.13 python3.12 python3.11 python3.10; do
    FOUND_PY="$(command -v "$name")" && break
done
if [ -z "$FOUND_PY" ]; then
    echo "SKIP: no python3.13 … python3.10 on PATH, which are the names pick_python searches"
    exit 0
fi
BASE_PY="$("$FOUND_PY" -c 'import sys, os; print(os.path.join(sys.base_prefix, "bin", "python%d.%d" % sys.version_info[:2]))')"
PY_NAME="$(basename "$BASE_PY")"
[ -x "$BASE_PY" ] || { echo "FAIL: no base interpreter at $BASE_PY"; exit 1; }

# Two plain dirs exposing the base interpreter, and a venv built from it (the
# shape of PlatformIO's penv sitting ahead of Homebrew on PATH).
mkdir -p "$TMP_DIR/base-a" "$TMP_DIR/base-b"
ln -s "$BASE_PY" "$TMP_DIR/base-a/$PY_NAME"
ln -s "$BASE_PY" "$TMP_DIR/base-b/$PY_NAME"
"$BASE_PY" -m venv --without-pip "$TMP_DIR/penv" || { echo "FAIL: could not create a venv"; exit 1; }

# pick <PATH> — prints what pick_python chose (or nothing) on that PATH.
pick() {
    PATH="$1" "$BASH" -c "
        $(cat "$TMP_DIR/py_ge_310.fn" "$TMP_DIR/py_is_venv.fn" "$TMP_DIR/pick_python.fn")
        pick_python
    " 2>/dev/null
}

out=$(pick "$TMP_DIR/penv/bin:$TMP_DIR/base-a")
if [ "$out" = "$TMP_DIR/base-a/$PY_NAME" ]; then
    pass "a virtualenv python first on PATH is skipped for the base python behind it"
else
    fail "venv first on PATH: picked '$out', expected $TMP_DIR/base-a/$PY_NAME"
fi

out=$(pick "$TMP_DIR/base-a:$TMP_DIR/base-b")
if [ "$out" = "$TMP_DIR/base-a/$PY_NAME" ]; then
    pass "without a virtualenv on PATH the first matching python is picked, as before"
else
    fail "plain PATH: picked '$out', expected $TMP_DIR/base-a/$PY_NAME"
fi

# pinned <home line> — exit status of venv_pinned_to_keg for a pyvenv.cfg
# holding that line ("" = no pyvenv.cfg at all).
pinned() {
    local venv="$TMP_DIR/cfg-venv"
    rm -rf "$venv"; mkdir -p "$venv"
    [ -n "$1" ] && printf 'home = %s\nversion = 3.13.16\n' "$1" > "$venv/pyvenv.cfg"
    "$BASH" -c "$(cat "$TMP_DIR/venv_pinned_to_keg.fn"); venv_pinned_to_keg '$venv'"
}

if pinned "/opt/homebrew/Cellar/python@3.13/3.13.16/Frameworks/Python.framework/Versions/3.13/bin"; then
    pass "a venv built from a versioned Apple-silicon Homebrew keg is flagged for rebuild"
else
    fail "Cellar keg (Apple silicon) not flagged"
fi

if pinned "/usr/local/Cellar/python@3.12/3.12.7/Frameworks/Python.framework/Versions/3.12/bin"; then
    pass "a venv built from a versioned Intel Homebrew keg is flagged for rebuild"
else
    fail "Cellar keg (Intel) not flagged"
fi

if ! pinned "/opt/homebrew/opt/python@3.13/bin"; then
    pass "a venv on Homebrew's stable opt/ path is kept"
else
    fail "opt/ path venv flagged for rebuild"
fi

if ! pinned ""; then
    pass "a venv without pyvenv.cfg is left to the existing interpreter check"
else
    fail "missing pyvenv.cfg flagged for rebuild"
fi

if [ "$fails" -eq 0 ]; then
    echo "All install python tests passed."
else
    echo "$fails install python test(s) failed."
    exit 1
fi
