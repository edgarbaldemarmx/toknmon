#!/bin/bash
# Download the official Clawd assets from claude.ai (static assets are not
# Cloudflare-gated; only HTML routes are) into a local, git-ignored directory
# for tools/convert_official_clawd.js. Also probes for not-yet-referenced
# names — the server answers a real GIF for valid names and an HTML catch-all
# otherwise, so magic bytes distinguish hits. See CLAUDE.md, "Splash
# animations", for the methodology. These assets are Anthropic's and are not
# redistributed with ToknMon; fetch them on demand only.
#
# Usage: tools/fetch_official_clawd.sh [DEST_DIR]   (default research/clawd-official)
set -u
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$REPO_ROOT/research/clawd-official}"
mkdir -p "$DEST"
cd "$DEST"
echo "== destination: $DEST"

KNOWN="
clawd/core/Clawd-CrabWalking.gif
clawd/core/Clawd-Waving.gif
clawd/core/Clawd-Walking.gif
clawd/core/Clawd-Jumping.gif
clawd/core/Clawd-JumpingHappy.gif
clawd/core/Clawd-Pointing.gif
clawd/core/Clawd-Still.png
clawd/core/Clawd-Lurking.gif
clawd/persona/Clawd-Cloud-once.gif
clawd/persona/Clawd-Cloud-still.png
clawd/persona/Clawd-Magnifier.gif
clawd/persona/Clawd-RacingCar.gif
clawd/persona/Clawd-Soccer.gif
clawd/persona/Clawd-Basketball.gif
clawd/persona/Clawd-Skateboard.gif
clawd/persona/Clawd-Trumpet.gif
clawd/persona/7bbe5052.gif
clawd/persona/ac0fa108.gif
spotlights/claude-code-celebration/Clawd-Dancing.gif
clawd-guest-pass.svg
"

echo "== fetching known assets"
for p in $KNOWN; do
  f=$(basename "$p")
  curl -sf -A "$UA" -o "$f" "https://claude.ai/images/$p" && echo "ok  $f" || echo "MISS $p"
done

# Probe list: extend when hunting for new seasonal drops.
PROBE="Halloween Christmas Snowman Birthday Party Trophy Baseball Tennis Golf
Guitar Piano Drums Reading Coffee Sleeping Astronaut Surfing Fishing"

echo "== probing for unreferenced names"
for n in $PROBE; do
  for d in persona core; do
    tmp=$(mktemp)
    curl -s -A "$UA" -o "$tmp" "https://claude.ai/images/clawd/$d/Clawd-$n.gif"
    if head -c 6 "$tmp" | grep -qE 'GIF8|PNG'; then
      mv "$tmp" "Clawd-$n.gif"
      echo "NEW HIT: $d/Clawd-$n.gif  <-- add to KNOWN and to the ANIMS catalog in tools/convert_official_clawd.js"
    else
      rm -f "$tmp"
    fi
  done
done
echo "done"
