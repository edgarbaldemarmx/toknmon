#!/bin/bash
# Scan every tracked file for personal or hardware identifiers that must not
# be published: home directory paths, hostnames, e-mail addresses, Bluetooth
# MAC addresses outside the documentation range, and credential-looking
# strings. Placeholders used by docs and tests are allowed (see ALLOW below).
#
# Usage: tools/check_pii.sh            # exit 0 when clean, 1 with findings
set -u

cd "$(git rev-parse --show-toplevel)" || exit 2

# Patterns that are always fine (documentation ranges, synthetic fixtures).
ALLOW='AA:BB:CC:DD:EE:|aa-bb-cc-dd-ee-|AABBCCDDEE|00:00:00:00:00:00|<author email>|<upstream path>|noreply@|example\.com|sk-ant-test-|sk-ant-ort-test-|sk-ant-oat01-(CLAUDE|DESIGN)|SUPERSECRET|sk-ant-secret-token|sk-ant-\.\.\.|bbbbbbbbbbbb|0000000000(0|1|2|3|4)|4c41555a-|tokencount/Clawdmeter'

status=0
scan() {
    local label="$1" pattern="$2"
    local hits
    hits=$(git grep -nIiE "$pattern" -- . ':!tools/check_pii.sh' | grep -vE "$ALLOW" || true)
    if [ -n "$hits" ]; then
        echo "== $label"
        echo "$hits" | head -20
        status=1
    fi
}

scan "home directory paths"      '(/Users/[A-Za-z0-9_.-]+|/home/[A-Za-z0-9_.-]+|C:\\\\Users\\\\)'
scan "hostnames"                  '[A-Za-z0-9-]+\.local\b'
scan "e-mail addresses"           '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
scan "MAC addresses"              '\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b'
scan "credential-looking strings" '(sk-ant-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{20,}|github_pat_|eyJ[A-Za-z0-9_-]{30,}|xox[bp]-|AIza[0-9A-Za-z_-]{20,})'
scan "temporary scratch paths"    '(/private/tmp/|/tmp/claude-[0-9])'

if [ "$status" -eq 0 ]; then
    echo "check_pii: clean"
fi
exit "$status"
