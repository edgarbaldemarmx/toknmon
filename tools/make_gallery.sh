#!/usr/bin/env bash
# Regenerate the docs/media gallery: headless simulator screenshots plus one
# animated GIF per custom animation. Deterministic — synthetic scenario data,
# fixed capture times, no timestamps in the outputs.
#
#   bash tools/make_gallery.sh            # build the sim, capture, export GIFs
#   SKIP_BUILD=1 bash tools/make_gallery.sh
#
# Requires: PlatformIO (pio), SDL2, ImageMagick (magick or convert), Node >= 18.
# Capture times come from the firmware constants (see firmware/sim/gallery.jsonl):
# the usage views pick their slot with SIM_SLOT (the carousel never moves on
# its own) and are captured at 4 s; mascot sets play intro -> 6 s loop ->
# outro per entry, so the full-screen scenes land ~37 s (Codex rain, 6th entry),
# ~31 s (Kimi night, 5th entry) and ~27 s (Grok stars, 4th entry, loop 24.5-30.5 s)
# after the SIM_SPLASH_PROVIDER hook at 1 s.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIO="${PIO:-$HOME/.platformio/penv/bin/pio}"
[ -x "$PIO" ] || PIO=pio
if command -v magick >/dev/null 2>&1; then MAGICK=magick
elif command -v convert >/dev/null 2>&1; then MAGICK=convert
else echo "make_gallery: ImageMagick (magick/convert) not found" >&2; exit 1; fi

PROG="$ROOT/firmware/.pio/build/sim/program"
SCENARIO="$ROOT/firmware/sim/gallery.jsonl"
SCREENS="$ROOT/docs/media/screens"
ANIMS="$ROOT/docs/media/animations"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ -z "${SKIP_BUILD:-}" ]; then
  echo "== building the simulator"
  "$PIO" run -d "$ROOT/firmware" -e sim >"$TMP/build.log" 2>&1 || { tail -20 "$TMP/build.log" >&2; exit 1; }
fi
[ -x "$PROG" ] || { echo "make_gallery: $PROG missing" >&2; exit 1; }
mkdir -p "$SCREENS" "$ANIMS"

# shot <name> <autoshot ms> [ENV=VALUE ...] — one headless sim run per screen.
shot() {
  local name="$1" ms="$2"; shift 2
  ( cd "$ROOT/firmware" && env SDL_VIDEODRIVER=dummy SIM_SCENARIO="$SCENARIO" \
      SIM_AUTOSHOT_MS="$ms" SIM_AUTOSHOT_PATH="$TMP/$name.bmp" "$@" \
      "$PROG" >"$TMP/$name.log" 2>&1 ) || { echo "sim failed for $name:" >&2; tail -20 "$TMP/$name.log" >&2; return 1; }
  # -strip drops the date chunks ImageMagick would otherwise write into the PNG.
  "$MAGICK" "$TMP/$name.bmp" -strip "$SCREENS/$name.png"
  echo "  docs/media/screens/$name.png (t=${ms} ms)"
}

echo "== capturing simulator screens"
# Runs are independent processes; run them concurrently (timing is wall-clock
# per process, so parallelism does not change what lands on screen).
shot claude-usage      4000 SIM_SLOT=0 &
shot codex-dots        4000 SIM_SLOT=1 &
shot kimi-usage        4000 SIM_SLOT=2 &
shot grok-dots         4000 SIM_SLOT=3 &
shot splash-claude     4000 SIM_SPLASH_PROVIDER=claude &
shot mascot-codex      3000 SIM_SPLASH_PROVIDER=codex &
shot mascot-kimi       3000 SIM_SPLASH_PROVIDER=kimi &
shot mascot-grok       3000 SIM_SPLASH_PROVIDER=grok &
shot scene-codex-rain 37500 SIM_SPLASH_PROVIDER=codex &
shot scene-kimi-night 30700 SIM_SPLASH_PROVIDER=kimi &
shot scene-grok-stars 27000 SIM_SPLASH_PROVIDER=grok &
shot parade           31000 SIM_PARADE=1 &   # Claude 1-21 s, then Codex: idle -> dots at ~27 s
fail=0
for job in $(jobs -p); do wait "$job" || fail=1; done
[ "$fail" = 0 ] || { echo "make_gallery: a capture failed" >&2; exit 1; }

echo "== exporting animation GIFs"
( cd "$ROOT" && node tools/convert_grid_animations.js --gif "$ANIMS" )

echo "== done: $(ls "$SCREENS" | wc -l | tr -d ' ') screens, $(ls "$ANIMS" | wc -l | tr -d ' ') GIFs"
