#!/bin/bash
# Download the ChatGPT pet sprite sheets that Petmeter archives under
# research/codex-pets/ (eight 1536x1872 WebP sheets plus pets-metadata.json)
# into a local, git-ignored directory for tools/convert_pet_spritesheet.py.
# The artwork is OpenAI's and is not redistributed with ToknMon (see
# NOTICE.md); fetch it on demand only. Idempotent: a file that already
# exists and carries the right magic bytes is kept, a stale or truncated
# one is replaced.
#
# Usage: tools/fetch_codex_pets.sh [DEST_DIR]   (default research/codex-pets)
set -u
BASE="https://raw.githubusercontent.com/nathanjohnpayne/Petmeter/main/research/codex-pets"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$REPO_ROOT/research/codex-pets}"
mkdir -p "$DEST"
cd "$DEST" || exit 2
echo "== destination: $DEST"

PETS="bsod codex dewey fireball null-signal rocky seedy stacky"

# RIFF....WEBP: bytes 0-3 "RIFF", 8-11 "WEBP" (4-7 are the little-endian size).
is_webp() {
    [ -s "$1" ] && [ "$(head -c 4 "$1" 2>/dev/null)" = "RIFF" ] \
        && [ "$(dd if="$1" bs=1 skip=8 count=4 2>/dev/null)" = "WEBP" ]
}
# The metadata is a JSON object; a GitHub 404 is plain text.
is_json() {
    [ -s "$1" ] && [ "$(head -c 1 "$1" 2>/dev/null)" = "{" ]
}

# fetch <file> <check-fn>: keep a valid local copy, otherwise download and
# validate; prints one status line and returns non-zero on a miss.
fetch() {
    local f="$1" check="$2" tmp
    if "$check" "$f"; then
        echo "kept $f"
        return 0
    fi
    tmp="$(mktemp "$DEST/.$f.XXXXXX")"
    if curl -sfL -o "$tmp" "$BASE/$f" && "$check" "$tmp"; then
        mv -f "$tmp" "$f"
        echo "ok   $f ($(wc -c < "$f" | tr -d ' ') bytes)"
        return 0
    fi
    rm -f "$tmp"
    echo "MISS $f"
    return 1
}

ok=0; miss=0
fetch pets-metadata.json is_json && ok=$((ok + 1)) || miss=$((miss + 1))
for p in $PETS; do
    fetch "$p-spritesheet.webp" is_webp && ok=$((ok + 1)) || miss=$((miss + 1))
done

echo "== $ok file(s) ready, $miss missing"
[ "$miss" -eq 0 ]
