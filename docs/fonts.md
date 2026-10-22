# Recompiling fonts

The `firmware/src/font_*.c` files are pre-compiled LVGL bitmap fonts.

```bash
npm install -g lv_font_conv
```

Generate each one (one at a time — `lv_font_conv` doesn't like loop-driven
invocations) with `--no-compress` (required for LVGL 9):

```bash
# Tiempos Text (titles, 56px)
lv_font_conv --font assets/TiemposText-400-Regular.otf -r 0x20-0x7E \
  --size 56 --format lvgl --bpp 4 --no-compress \
  -o firmware/src/font_tiempos_56.c --lv-include "lvgl.h"

# Styrene B (large numbers 48, panel labels 28, small text 24, minimal 20)
for size in 48 28 24 20; do
  lv_font_conv --font assets/StyreneB-Regular.otf -r 0x20-0x7E \
    --size $size --format lvgl --bpp 4 --no-compress \
    -o firmware/src/font_styrene_${size}.c --lv-include "lvgl.h"
done

# DejaVu Sans Mono (32px, with spinner Unicode chars)
lv_font_conv --font assets/DejaVuSansMono.ttf \
  -r 0x20-0x7E,0xB7,0x2026,0x2722,0x2733,0x2736,0x273B,0x273D \
  --size 32 --format lvgl --bpp 4 --no-compress \
  -o firmware/src/font_mono_32.c --lv-include "lvgl.h"
```

**Important:** `lv_font_conv` v1.5.3 outputs LVGL 8 format. Each generated
file must be patched for LVGL 9 compatibility:

1. Remove `#if LVGL_VERSION_MAJOR >= 8` guards around `font_dsc` and the font struct
2. Remove the `.cache` field from `font_dsc`
3. Add `.release_glyph = NULL`, `.kerning = 0`, `.static_bitmap = 0` to the font struct
4. Add `.fallback = NULL`, `.user_data = NULL` to the font struct

Without these patches, fonts compile but render as invisible.

## Inter (design system)

The H14 design system (`docs/odd/toknmon-h14-ui-redesign.md`, L9/L10) sets
the usage pages, the app center and the status footer in **Inter** (Rasmus
Andersson, SIL Open Font License 1.1 — see `NOTICE.md`). The TTFs are **not**
committed; download the release zip into a temporary directory and generate
the six faces from `extras/ttf/`:

```bash
D=$(mktemp -d)
curl -sSL -o "$D/inter.zip" https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip
unzip -q "$D/inter.zip" -d "$D/inter"
F="$D/inter/extras/ttf"
O=firmware/src

# 92 px Medium — the main usage figure: digits, "%", "-", "—" (0x2014)
npx --yes lv_font_conv@1.5.3 --font "$F/Inter-Medium.ttf" -r 0x30-0x39,0x25,0x2D,0x2014 \
  --size 92 --format lvgl --bpp 4 --no-compress -o $O/font_inter_92.c --lv-include "lvgl.h"
# 60 px Medium — the Focus countdown: digits, ":", "-"
npx --yes lv_font_conv@1.5.3 --font "$F/Inter-Medium.ttf" -r 0x30-0x39,0x3A,0x2D \
  --size 60 --format lvgl --bpp 4 --no-compress -o $O/font_inter_60.c --lv-include "lvgl.h"
# 29 px SemiBold — screen titles, "%", the remaining / 5h figures
npx --yes lv_font_conv@1.5.3 --font "$F/Inter-SemiBold.ttf" -r 0x20-0x7E \
  --size 29 --format lvgl --bpp 4 --no-compress -o $O/font_inter_29.c --lv-include "lvgl.h"
# 17 px Regular — reset line, "used", "remaining", tile names (+ "·" and "…")
npx --yes lv_font_conv@1.5.3 --font "$F/Inter-Regular.ttf" -r 0x20-0x7E,0xB7,0x2026 \
  --size 17 --format lvgl --bpp 4 --no-compress -o $O/font_inter_17.c --lv-include "lvgl.h"
# 15 px Regular — credit metadata, 5h reset, footer verb (+ "·" and "…")
npx --yes lv_font_conv@1.5.3 --font "$F/Inter-Regular.ttf" -r 0x20-0x7E,0xB7,0x2026 \
  --size 15 --format lvgl --bpp 4 --no-compress -o $O/font_inter_15.c --lv-include "lvgl.h"
# 13 px SemiBold — small-caps labels, provider label, clock (+ "·")
npx --yes lv_font_conv@1.5.3 --font "$F/Inter-SemiBold.ttf" -r 0x20-0x7E,0xB7 \
  --size 13 --format lvgl --bpp 4 --no-compress -o $O/font_inter_13.c --lv-include "lvgl.h"
```

Then apply the LVGL 9 patch above to each file (drop the `LVGL_VERSION_MAJOR`
guards and the `cache` field, add `.release_glyph`, `.kerning`,
`.static_bitmap`, `.fallback`, `.user_data`). Generated sizes (bpp 4): 92 px
≈ 117 KB of source / 13 glyphs, 60 px ≈ 47 KB, 29 px ≈ 98 KB, 17 px ≈ 47 KB,
15 px ≈ 39 KB, 13 px ≈ 35 KB; the six faces cost about 1.7 % of the 2.16's
flash (75.6 % → 77.3 %).

The pages lay text out by **baseline** (`text_top()` in `ui.cpp` turns a
design baseline into the label's top edge with the face's `line_height` and
`base_line`), so a regenerated face with different metrics keeps the design
coordinates.
