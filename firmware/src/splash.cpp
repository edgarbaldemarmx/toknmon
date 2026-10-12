#include "splash.h"
#include "splash_animations.h"
#include "custom_animations.h"
#include "splash_geometry.h"
#include "theme.h"
#include "usage_rate.h"
#include "data.h"
#include "hal/board_caps.h"
#include "hal/display_hal.h"
#include <Arduino.h>
#include <string.h>
#include <esp_heap_caps.h>

// ─── Animation registry ──────────────────────────────────────────────────────
// Two generated tables share one format: the official Clawd set
// (splash_animations.h) followed by the hand-authored grids
// (custom_animations.h, see tools/convert_grid_animations.js). Everything
// below indexes through these two helpers so the catalog is one flat list.
static inline int anim_count(void) {
    return SPLASH_ANIM_COUNT + CUSTOM_ANIM_COUNT;
}
static inline const splash_anim_def_t* anim_at(int i) {
    if (i < 0 || i >= anim_count()) return NULL;
    return (i < SPLASH_ANIM_COUNT) ? &splash_anims[i] : &custom_anims[i - SPLASH_ANIM_COUNT];
}
static int anim_index_by_name(const char *n) {
    if (!n) return -1;
    for (int i = 0; i < anim_count(); i++)
        if (strcmp(anim_at(i)->name, n) == 0) return i;
    return -1;
}
static const splash_anim_def_t* anim_by_name(const char *n) {
    const int i = anim_index_by_name(n);
    return (i < 0) ? NULL : anim_at(i);
}

// 60×60 stage. CELL sized so the canvas fits the smaller display dimension —
// the canvas is square and centered, so on portrait or letterboxed panels
// it leaves vertical margin rather than cropping. On PSRAM-less boards the
// buffer is rendered tiny (cell == 1) and LVGL scales it up to fill the panel;
// the geometry decision lives in splash_compute_geometry() (splash_geometry.h).
//
// Animations are stored as bounding-box crops of the official 55×37 art stage
// (see tools/convert_official_clawd.js); compose_stage() places the current
// frame centered on the 60×60 stage. The oversized stage leaves room to later
// translate animations across the screen (walks, lurking).
#define GRID         SPLASH_GRID
static int  cell      = 8;         // recomputed in splash_init()
static int  canvas_w  = GRID * 8;
static int  canvas_h  = GRID * 8;

// Splash background: true black (matches THEME_BG and palette index 0
// emitted by tools/convert_official_clawd.js). Used for the stage margins
// and as palette fallback.
#define COL_EMPTY    0x0000

LV_FONT_DECLARE(font_styrene_28);
LV_FONT_DECLARE(font_styrene_20);

static lv_obj_t *splash_container = NULL;
static lv_obj_t *canvas = NULL;
static lv_obj_t *label_status = NULL;     // shown only when no animations loaded
static lv_obj_t *label_provider = NULL;   // mascot mode: provider name, top center
static uint16_t *canvas_buf = NULL;        // 480x480 RGB565 (PSRAM)

static uint16_t cur_anim = 0;
static uint16_t cur_frame = 0;
static uint32_t frame_started_ms = 0;
static uint32_t last_pick_ms = 0;
static bool active = false;

// While splash is showing, auto-cycle to the next animation in the current
// rate-driven group every this many ms.
#define SPLASH_ROTATE_INTERVAL_MS 20000

// Usage-rate animation groups: 4 groups × up to 6 animations each.
// Filled at init by matching literal names across both animation tables.
// (jumping is the only unassigned animation — still reachable via splash_next.)
// The custom mountain bikes (H4) ride in the busy groups; unused slots are NULL.
#define GROUP_COUNT 4
#define GROUP_MAX   6
static int8_t  group_lists[GROUP_COUNT][GROUP_MAX];
static uint8_t group_size[GROUP_COUNT] = {0};
static uint8_t group_rotation[GROUP_COUNT] = {0};

static const char* GROUP_NAMES[GROUP_COUNT][GROUP_MAX] = {
    // Group 0 — idle / sleepy (calm, investigative). Magnifier first: it's
    // the boot pick, and lurking-first would boot to a near-empty screen.
    { "magnifier", "walking", "pointing", "lurking", NULL, NULL },
    // Group 1 — normal pace
    { "crab walking", "waving", "trumpet", "basketball", NULL, NULL },
    // Group 2 — active (typing along with you; Clawd takes the bike out)
    { "laptop", "dancing", "skateboard", "soccer", "claude.bike", NULL },
    // Group 3 — heavy burn (high-energy rides + the most exuberant jump,
    // and the other two mascots pedaling along)
    { "racing car", "cloud", "sailing scene", "jumping happy", "codex.bike", "kimi.bike" },
};

// Scratch stage: the current animation frame composed centered onto the full
// 60×60 grid (index 0 = background elsewhere). 3.6 KB of static RAM.
static uint8_t stage_cells[GRID * GRID];

// The official 55×37 art stage sits at a fixed anchor on the 60×60 grid, and
// every animation is placed at its authored stage offset (ox/oy) — never
// centered per-animation. All animations share one idle-Clawd position
// (x 15..38, y 21..36 in stage cells), so transitions between them are
// seamless; centering per-crop would make the still pose jump around.
#define STAGE_ANCHOR_X ((GRID - 55) / 2)
#define STAGE_ANCHOR_Y ((GRID - 37) / 2)

// ─── Playback: intro → loop → outro ─────────────────────────────────────────
// Every animation carries a loop region (converter-detected gait cycles and
// scene middles; whole file when nothing repeats). Playback holds the loop
// until released — walkers release on arrival at their target x, scenes after
// SCENE_LOOP_MS — then the outro (pack-away, gait exit) plays and the
// animation completes on its idle bookend. Rotation never hard-cuts: it
// releases the loop and switches after the outro, so transitions always
// happen from the shared idle pose.
static bool     pb_done = false;        // completed; holding idle frame 0
static bool     in_loop = false;
static bool     loop_release = false;
static uint32_t loop_entered_ms = 0;
static bool     pending_pick = false;   // rotate requested; honor at completion
#define SCENE_LOOP_MS 6000

// ─── Mascot mode (per-provider play-lists) and the parade ───────────────────
// The default splash is Claude's: animations come from the usage-rate groups
// above and the PWR button walks the whole catalog. Mascot mode pins the
// splash to one provider's play-list instead: entries play in order (intro →
// loop for SCENE_LOOP_MS → outro, then the next), PWR advances within the
// list, and the rate-group pick is a no-op. Claude has no list — selecting
// it (or -1) restores the default behavior, so the boot path is untouched.
// The parade cycles providers every PARADE_PROVIDER_MS across the fresh
// slots the UI handed over, each playing its own set. The `*.scene.*`
// entries are the full-screen scenes (H7); a name absent from the catalog is
// skipped (logged once), so the sets play before and after the art lands.
#define SET_MAX 6
static const char* const PROVIDER_SETS[PROVIDER_COUNT][SET_MAX] = {
    { NULL, NULL, NULL, NULL, NULL, NULL },                           // Claude: rate groups
    { "codex.idle", "codex.dots", "codex.think", "codex.bike", "codex.scene.wave",  "codex.scene.rain"  },
    { "kimi.idle",  "kimi.glow",  "kimi.sleep",  "kimi.bike",  "kimi.scene.night",  "kimi.scene.orbit"  },
};
static int      provider_mode = -1;     // -1 = Claude default; else PROVIDER_* with a set
static uint8_t  set_pos = 0;            // index into PROVIDER_SETS[provider_mode]
static bool     set_missing_logged[PROVIDER_COUNT][SET_MAX] = {};
#define PARADE_PROVIDER_MS 20000
static bool     parade_on = false;
static bool     parade_fresh[PROVIDER_COUNT] = { false, false, false };
static int      parade_slot = 0;
static uint32_t parade_started_ms = 0;

// ─── Walk translation ────────────────────────────────────────────────────────
// The walk gaits animate in place; screen travel is ours, locked to the feet:
// per-frame movement equals the measured backward drift of the planted feet,
// so planted feet stay put on screen.
//   crab walking (8-frame scuttle loop [1..8]): surges of 1 cell entering
//     frames 4, 5, 8 and the cycle wrap — 4 cells / 640 ms (6.25 cells/s).
//   walking (5-frame waddle loop [2..6]): 1,1,1,1,2 cells → 6 cells / 450 ms
//     (~13.3 cells/s).
// walk_begin(target) plays intro → gait loop, clamps to land exactly on the
// target, then releases the loop so the gait exits and Clawd stands. When
// walking left the frame is mirrored (eyes lead); facing persists standing.
// DEMO: until the BLE-driven state machine exists, a choreography loops
// stand → right edge → off-screen left → re-enter home.
enum WalkKind { WALK_NONE, WALK_CRAB, WALK_FRONT };
static WalkKind walk_kind = WALK_NONE;
static bool    walk_active = false;
static int     walk_x = 0;         // stage x of the frame origin, may be < 0
static int     walk_dir = 0;       // -1 left, +1 right, 0 standing
static int     walk_target = 0;
static uint8_t walk_phase = 0;
static uint32_t walk_phase_started = 0;
static int     walk_home_x = 0;    // authored position to return to
static int     walk_face = +1;     // facing, kept while standing (-1 = left)

// Cells the body moves when the gait advances INTO `frame` (see banner).
static int walk_gait_cells_k(WalkKind kind, uint16_t frame, bool from_loop) {
    if (kind == WALK_CRAB) {
        if (frame == 1) return from_loop ? 1 : 0;     // cycle wrap, mid-surge
        return (frame == 4 || frame == 5 || frame == 8) ? 1 : 0;
    }
    if (kind == WALK_FRONT) {
        if (frame < 2 || frame > 6) return 0;         // idle / wind-up / outro
        if (frame == 2 && !from_loop) return 0;       // first plant
        return (frame == 6) ? 2 : 1;
    }
    return 0;
}
static int walk_gait_cells(uint16_t frame, bool from_loop) {
    return walk_gait_cells_k(walk_kind, frame, from_loop);
}

static void anim_reset(const splash_anim_def_t *a) {
    pb_done = false;
    in_loop = false;
    loop_release = false;
    pending_pick = false;
    walk_active = false;
    walk_kind = WALK_NONE;
    if (strcmp(a->name, "crab walking") == 0) walk_kind = WALK_CRAB;
    else if (strcmp(a->name, "walking") == 0) walk_kind = WALK_FRONT;
    else return;
    walk_active = true;
    walk_home_x = STAGE_ANCHOR_X + a->ox;
    walk_x = walk_home_x;
    walk_dir = 0;
    walk_face = +1;
    walk_phase = 0;
    walk_phase_started = millis();
    pb_done = true;    // walkers start standing; the choreography sets off
}

static const uint8_t* compose_stage(const splash_anim_def_t *a, uint16_t frame);
static void render_frame(const uint8_t *cells, const uint16_t *palette);

// Start walking toward `target` (stage x of the frame origin).
static void walk_begin(int target) {
    if (target == walk_x) return;          // already there; stay standing
    walk_target = target;
    walk_dir = (target > walk_x) ? +1 : -1;
    walk_face = walk_dir;
    cur_frame = 0;
    frame_started_ms = millis();
    pb_done = false;
    loop_release = false;
    in_loop = false;
}

// Demo choreography: advance phases whenever the current walk has completed.
static void walk_choreo(const splash_anim_def_t *a) {
    if (!pb_done) return;
    const uint32_t now = millis();
    switch (walk_phase) {
        case 0:  // standing at home
            if (now - walk_phase_started > 1200) { walk_phase = 1; walk_begin(GRID - a->w); }
            break;
        case 1:  // arrived at the right edge
            walk_phase = 2; walk_phase_started = now;
            break;
        case 2:  // standing at the edge
            if (now - walk_phase_started > 1200) { walk_phase = 3; walk_begin(-a->w); }
            break;
        case 3:  // fully off-screen left
            walk_phase = 4; walk_phase_started = now;
            break;
        case 4:  // hold off-screen (empty stage)
            if (now - walk_phase_started > 800) { walk_phase = 5; walk_begin(walk_home_x); }
            break;
        case 5:  // back home
            walk_phase = 0; walk_phase_started = now;
            break;
    }
}

static const uint8_t* compose_stage(const splash_anim_def_t *a, uint16_t frame) {
    memset(stage_cells, 0, sizeof(stage_cells));
    // Horizontal edge snap: art touching its canvas's left/right edge was
    // designed to hang off that edge (lurking peeks in from the left), so it
    // goes to the true screen edge instead of the anchored stage edge. Not
    // applied vertically — every animation touches the stage bottom, and
    // vertical placement should stay anchored (rounded panel corners).
    int ax = STAGE_ANCHOR_X + a->ox;
    if (a->ox == 0)           ax = 0;
    if (a->ox + a->w == 55)   ax = GRID - a->w;
    if (walk_active)          ax = walk_x;
    const bool mirror = walk_active && walk_face < 0;
    const int ay = STAGE_ANCHOR_Y + a->oy;
    const uint8_t *src = &a->frames[(size_t)frame * a->w * a->h];
    for (int r = 0; r < a->h; r++) {
        const int dy = ay + r;
        if (dy < 0 || dy >= GRID) continue;
        int c0 = 0, c1 = a->w;                 // clip for partial off-screen x
        if (ax + c0 < 0)     c0 = -ax;
        if (ax + c1 > GRID)  c1 = GRID - ax;
        if (c0 >= c1) continue;
        if (mirror) {
            for (int c = c0; c < c1; c++)
                stage_cells[dy * GRID + ax + c] = src[r * a->w + (a->w - 1 - c)];
        } else {
            memcpy(&stage_cells[dy * GRID + ax + c0], &src[r * a->w + c0], c1 - c0);
        }
    }
    return stage_cells;
}

static void resolve_group_lists(void) {
    for (int g = 0; g < GROUP_COUNT; g++) {
        group_size[g] = 0;
        for (int s = 0; s < GROUP_MAX; s++) {
            group_lists[g][s] = -1;
            const char* want = GROUP_NAMES[g][s];
            if (!want) continue;
            for (int i = 0; i < anim_count(); i++) {
                if (strcmp(anim_at(i)->name, want) == 0) {
                    group_lists[g][group_size[g]++] = (int8_t)i;
                    break;
                }
            }
        }
    }
}

static uint16_t *row_buf = NULL;   // scratch row, sized to canvas_w (PSRAM path)

// ─── Two render paths ────────────────────────────────────────────────────────
// PSRAM boards (S3) draw the pixel art into an LVGL canvas at native size and
// let LVGL flush it — they have the RAM and cores to spare, no transform needed.
//
// PSRAM-less boards (C6) can't hold a 480×480 canvas. The prior approach (tiny
// 20×20 canvas + LVGL image-scale) made LVGL software-transform the whole
// upscaled frame on every redraw — measured ~0.76 µs/output-px, i.e. 100–220 ms
// per frame on the single-core C6, and partial invalidation of a transformed
// image both fails to clip the transform and smears. Instead we upscale the
// stage cells ourselves with trivial nearest-neighbour replication and push only
// the *changed* cells straight to the panel via the display HAL, bypassing LVGL.
// That removes the transform cost (leaving just the QSPI flush) and the
// dirty-rect is exact, so no smearing.
#ifndef BOARD_HAS_PSRAM
#  define SPLASH_DIRECT_DRAW 1
#else
#  define SPLASH_DIRECT_DRAW 0
#endif

#if SPLASH_DIRECT_DRAW
static uint16_t*       strip_buf = NULL;   // one grid-row band: (GRID*scr_cell)×scr_cell
static int             scr_cell  = 24;     // on-screen px per grid cell
static int             scr_offx  = 0;      // centering offsets (square art on panel)
static int             scr_offy  = 0;
static uint8_t         prev_cells[GRID * GRID];
static const uint16_t* prev_palette = NULL;
static bool            prev_valid   = false;
static bool            force_full   = false;  // repaint everything on the next render

// Upscale grid cells [gx0..gx1]×[gy0..gy1] and push them to the panel, one
// grid-row band at a time so the scratch buffer stays (GRID*scr_cell × scr_cell).
static void blit_cells(const uint8_t* cells, const uint16_t* palette,
                       int gx0, int gy0, int gx1, int gy1) {
    if (!strip_buf) return;
    const int spc = scr_cell;
    const int bw  = (gx1 - gx0 + 1) * spc;          // band width, px
    const int px  = scr_offx + gx0 * spc;
    for (int gy = gy0; gy <= gy1; gy++) {
        for (int gx = gx0; gx <= gx1; gx++) {       // expand one source row across
            uint8_t code = cells[gy * GRID + gx];
            uint16_t color = (palette && code < SPLASH_PALETTE_SIZE) ? palette[code] : COL_EMPTY;
            uint16_t* p = &strip_buf[(gx - gx0) * spc];
            for (int i = 0; i < spc; i++) p[i] = color;
        }
        for (int dy = 1; dy < spc; dy++)             // replicate that row down
            memcpy(&strip_buf[dy * bw], strip_buf, bw * 2);
        display_hal_draw_bitmap(px, scr_offy + gy * spc, bw, spc, strip_buf);
    }
}

static void render_frame(const uint8_t *cells, const uint16_t *palette) {
    if (!strip_buf) return;
    if (!active) return;          // never draw to the panel while not shown
    bool full = force_full || !prev_valid || palette != prev_palette;
    force_full = false;

    int gx0 = 0, gy0 = 0, gx1 = GRID - 1, gy1 = GRID - 1;
    if (!full) {                                     // bounding box of changed cells
        gx0 = GRID; gy0 = GRID; gx1 = -1; gy1 = -1;
        for (int gy = 0; gy < GRID; gy++)
            for (int gx = 0; gx < GRID; gx++)
                if (cells[gy * GRID + gx] != prev_cells[gy * GRID + gx]) {
                    if (gx < gx0) gx0 = gx;
                    if (gx > gx1) gx1 = gx;
                    if (gy < gy0) gy0 = gy;
                    if (gy > gy1) gy1 = gy;
                }
        if (gx1 < 0) return;                         // identical frame, nothing to do
    }

    blit_cells(cells, palette, gx0, gy0, gx1, gy1);
    // The full repaint went straight to the panel, under the LVGL label.
    if (full && label_provider) lv_obj_invalidate(label_provider);

    memcpy(prev_cells, cells, GRID * GRID);
    prev_palette = palette;
    prev_valid   = true;
}

#else  // ── PSRAM: LVGL canvas render (unchanged) ──

static void render_frame(const uint8_t *cells, const uint16_t *palette) {
    if (!row_buf || !canvas_buf) return;
    for (int gy = 0; gy < GRID; gy++) {
        for (int gx = 0; gx < GRID; gx++) {
            uint8_t code = cells[gy * GRID + gx];
            uint16_t color = (palette && code < SPLASH_PALETTE_SIZE) ? palette[code] : COL_EMPTY;
            uint16_t *p = &row_buf[gx * cell];
            for (int i = 0; i < cell; i++) p[i] = color;
        }
        for (int dy = 0; dy < cell; dy++) {
            memcpy(&canvas_buf[(gy * cell + dy) * canvas_w], row_buf, canvas_w * 2);
        }
    }
    if (canvas) lv_obj_invalidate(canvas);
}
#endif

// ---- Mini creature: a small animated creature for embedding in other screens
//      (e.g. the idle "sleeping" indicator). Self-contained — its own canvas and
//      buffer, independent of the full-screen splash above. ----
static lv_obj_t  *mini_canvas = NULL;
static uint16_t  *mini_buf = NULL;
static int        mini_cell = 0;
static int        mini_w = 0;      // canvas px, mini_anim->w * mini_cell
static int        mini_h = 0;
static const splash_anim_def_t *mini_anim = NULL;
static uint16_t   mini_frame = 0;
static uint32_t   mini_started = 0;

static void mini_render(void) {
    if (!mini_buf || !mini_anim) return;
    const int aw = mini_anim->w, ah = mini_anim->h;
    const uint8_t *cells = &mini_anim->frames[(size_t)mini_frame * aw * ah];
    const uint16_t *pal = mini_anim->palette;
    for (int gy = 0; gy < ah; gy++) {
        for (int gx = 0; gx < aw; gx++) {
            uint8_t code = cells[gy * aw + gx];
            uint16_t color = (pal && code < SPLASH_PALETTE_SIZE) ? pal[code] : COL_EMPTY;
            for (int dy = 0; dy < mini_cell; dy++) {
                uint16_t *dst = &mini_buf[(gy * mini_cell + dy) * mini_w + gx * mini_cell];
                for (int dx = 0; dx < mini_cell; dx++) dst[dx] = color;
            }
        }
    }
    if (mini_canvas) lv_obj_invalidate(mini_canvas);
}

lv_obj_t* splash_mini_create(lv_obj_t *parent, const char *anim_name, int px) {
    mini_anim = anim_by_name(anim_name);
    if (!mini_anim) return NULL;
    const int amax = (mini_anim->w > mini_anim->h) ? mini_anim->w : mini_anim->h;
    mini_cell = px / amax;
    if (mini_cell < 1) mini_cell = 1;
    mini_w = mini_anim->w * mini_cell;
    mini_h = mini_anim->h * mini_cell;
#ifdef BOARD_HAS_PSRAM
    const uint32_t caps = MALLOC_CAP_SPIRAM;
#else
    const uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
#endif
    mini_buf = (uint16_t*)heap_caps_malloc(mini_w * mini_h * 2, caps);
    if (!mini_buf) return NULL;
    mini_canvas = lv_canvas_create(parent);
    lv_canvas_set_buffer(mini_canvas, mini_buf, mini_w, mini_h, LV_COLOR_FORMAT_RGB565);
    mini_frame = 0;
    mini_started = millis();
    mini_render();
    return mini_canvas;
}

void splash_mini_tick(void) {
    if (!mini_buf || !mini_anim || mini_anim->frame_count == 0) return;
    if (millis() - mini_started < mini_anim->holds[mini_frame]) return;
    mini_started = millis();
    mini_frame = (mini_frame + 1) % mini_anim->frame_count;
    mini_render();
}

// ─── Corner mascot (usage screen) ────────────────────────────────────────────
// The corner logo slot, alive: the still Clawd idles, occasionally does a
// small act (waving, dancing, pointing) in place, and every few acts walks
// off the left edge, does the full-size lurking animation over the screen,
// and walks back into the slot. PSRAM boards only (ui.cpp falls back to the
// static clawd_still.h icon on the C6); driven by splash_mascot_tick() from
// the main loop, independent of the splash screen itself.
static lv_obj_t *mas_img = NULL;
static lv_obj_t *mas_lurk_img = NULL;
static uint8_t  *mas_buf = NULL;       // planar RGB565A8, sized for largest act
static uint8_t  *mas_lurk_buf = NULL;
static size_t    mas_buf_cap = 0;      // bytes; mas_render() refuses anything larger
static size_t    mas_lurk_buf_cap = 0;
static lv_image_dsc_t mas_dsc, mas_lurk_dsc;
static int  mas_cell = 3;
static int  mas_slot_x = 0;            // px of the slot (walk-in target)
static int  mas_feet_y = 0;            // px feet line (all art is bottom-anchored)
static int  mas_lurk_cell = 8;
static int  mas_screen_w = 480;
static bool mas_visible = false;

enum MasMode { MAS_STILL, MAS_ACT, MAS_WALK_OFF, MAS_LURK, MAS_WALK_IN,
               MAS_ATTN_OFF, MAS_ATTN_IN, MAS_ATTN_ACT, MAS_ATTN_OUT };
static MasMode mas_mode = MAS_STILL;
static const splash_anim_def_t *mas_anim = NULL;
static uint16_t mas_frame = 0;
static uint32_t mas_frame_started = 0;
static uint32_t mas_mode_started = 0;
static int  mas_x = 0;                 // widget x, px (may be off-screen)
static int  mas_face = +1;
static uint8_t mas_act_idx = 0;
static bool mas_from_loop = false;
static bool mas_attn = false;          // attention requested (splash_mascot_attention)
static int  big_dx = 0;                // attention Clawd's px offset from his centered spot
static int  big_cell = 12;             // px per art cell for the attention Clawd
static int  big_x0 = 0;                // px of stage x 0, chosen so he is centered
static int  big_feet_y = 420;
static uint8_t big_act = 0;            // 0 waving, 1 pointing

// One mascot per provider slot (data.h). The corner mascot mirrors the
// splash's excitement: per usage-rate group, how long it idles between acts
// and which acts it does. The spec's `lurk` entry names the act that means
// the walk-off / full-size-lurk / walk-back trip; a NULL `walk` disables
// those trips (the mascot only ever acts in place). All names resolve through
// anim_by_name(), so a missing animation degrades to "stays still".
#define MAS_ACT_MAX 5
struct MascotSpec {
    const char *idle;                   // frame 0 is the still pose
    const char *walk;                   // gait for trips; NULL = no trips
    WalkKind    gait;                   // foot-lock schedule for `walk`
    const char *acts[4][MAS_ACT_MAX];   // per usage-rate group, NULL-terminated
    const char *lurk;                   // full-size off-slot act; NULL = none
};
static const MascotSpec MASCOT_SPECS[PROVIDER_COUNT] = {
    // Claude: the official Clawd set plus the custom mountain bike once the
    // pace picks up. Acts must fit the corner buffer (jumps are too tall).
    { "walking", "walking", WALK_FRONT,
      { { "pointing", "lurking", NULL,          NULL,          NULL          },   // idle: sparse, sneaky
        { "waving",   "lurking", "pointing",    "claude.bike", NULL          },   // normal
        { "waving",   "dancing", "claude.bike", "lurking",     NULL          },   // active
        { "dancing",  "waving",  "claude.bike", "dancing",     "lurking"     } }, // heavy: can't sit still
      "lurking" },
    // Codex: the three thinking dots, and the bike at every pace. No walk
    // gait, so no trips.
    { "codex.idle", NULL, WALK_NONE,
      { { "codex.dots", "codex.bike", NULL,         NULL, NULL },
        { "codex.dots", "codex.bike", NULL,         NULL, NULL },
        { "codex.bike", "codex.dots", NULL,         NULL, NULL },
        { "codex.bike", "codex.dots", "codex.bike", NULL, NULL } },
      NULL },
    // Kimi: the crescent moon, and the bike at every pace. No walk gait, so
    // no trips.
    { "kimi.idle", NULL, WALK_NONE,
      { { "kimi.glow", "kimi.bike", NULL,        NULL, NULL },
        { "kimi.glow", "kimi.bike", NULL,        NULL, NULL },
        { "kimi.bike", "kimi.glow", NULL,        NULL, NULL },
        { "kimi.bike", "kimi.glow", "kimi.bike", NULL, NULL } },
      NULL },
};
static const uint16_t MAS_STILL_MS_BY_RATE[4] = { 10000, 7000, 5000, 3500 };

static const MascotSpec *mas_spec = &MASCOT_SPECS[PROVIDER_CLAUDE];
// Trips (walk-off / lurk / walk-back) can be paused by the UI — the full-size
// lurk crosses the panel area, which the dense three-panel layout fills.
static bool mas_trips_enabled = true;

static bool mas_is_lurk_act(const char *act) {
    return mas_spec->lurk && strcmp(act, mas_spec->lurk) == 0;
}
static bool mas_can_trip(void) {
    return mas_spec->walk && mas_trips_enabled && mas_lurk_img && mas_lurk_buf;
}

// Render one frame into a planar RGB565A8 image (alpha 0 outside the art) and
// anchor the widget on the shared feet line. `cap` is the buffer's size in
// bytes: a frame that would not fit is skipped (logged once) rather than
// overrun — the buffers are sized from the spec tables at create time, so
// this only trips if an animation grows past what was budgeted.
static void mas_render(const splash_anim_def_t *a, uint16_t frame, bool mirror,
                       lv_image_dsc_t *dsc, uint8_t *buf, size_t cap, lv_obj_t *img,
                       int cell, int x, int feet_y) {
    const int w = a->w * cell, h = a->h * cell;
    if ((size_t)w * h * 3 > cap) {
        static bool warned = false;
        if (!warned) {
            warned = true;
            Serial.printf("mascot: '%s' (%dx%d cells @%d px) exceeds its %u-byte buffer; skipped\n",
                          a->name, a->w, a->h, cell, (unsigned)cap);
        }
        return;
    }
    uint16_t *color = (uint16_t*)buf;
    uint8_t  *alpha = buf + (size_t)w * h * 2;
    const uint8_t *src = &a->frames[(size_t)frame * a->w * a->h];
    for (int gy = 0; gy < a->h; gy++) {
        for (int gx = 0; gx < a->w; gx++) {
            uint8_t code = src[gy * a->w + (mirror ? a->w - 1 - gx : gx)];
            uint16_t c = (code && code < SPLASH_PALETTE_SIZE) ? a->palette[code] : 0;
            uint8_t  al = code ? 255 : 0;
            for (int dy = 0; dy < cell; dy++) {
                uint16_t *cp = &color[(gy * cell + dy) * w + gx * cell];
                uint8_t  *ap = &alpha[(gy * cell + dy) * w + gx * cell];
                for (int dx = 0; dx < cell; dx++) { cp[dx] = c; ap[dx] = al; }
            }
        }
    }
    dsc->header.w = w;
    dsc->header.h = h;
    dsc->header.cf = LV_COLOR_FORMAT_RGB565A8;
    dsc->header.stride = w * 2;
    dsc->data = buf;
    dsc->data_size = (size_t)w * h * 3;
    lv_image_set_src(img, dsc);
    lv_obj_set_pos(img, x, feet_y - h);
    lv_obj_invalidate(img);
}

// Attention mode draws a big Clawd centered on screen, shifted by big_dx while
// he walks. The core poses share one stage origin, so they line up.
static void big_render(const splash_anim_def_t *a, uint16_t frame, bool mirror) {
    mas_render(a, frame, mirror, &mas_lurk_dsc, mas_lurk_buf, mas_lurk_buf_cap, mas_lurk_img,
               big_cell, big_x0 + a->ox * big_cell + big_dx, big_feet_y);
}

// Corner-sprite render at the slot cell size.
static void corner_render(const splash_anim_def_t *a, uint16_t frame, bool mirror, int x) {
    mas_render(a, frame, mirror, &mas_dsc, mas_buf, mas_buf_cap, mas_img,
               mas_cell, x, mas_feet_y);
}

// Full-size lurk render: the art is authored hanging off the LEFT stage edge
// and is mirrored to peek in from the right, on the splash's stage rows.
static void lurk_render(const splash_anim_def_t *a, uint16_t frame) {
    mas_render(a, frame, true, &mas_lurk_dsc, mas_lurk_buf, mas_lurk_buf_cap, mas_lurk_img,
               mas_lurk_cell, mas_screen_w - a->w * mas_lurk_cell,
               (STAGE_ANCHOR_Y + a->oy + a->h) * mas_lurk_cell);
}

// The corner Clawd is off screen: the big one walks in from the left.
static void big_enter(void) {
    const splash_anim_def_t *w = anim_by_name("walking");
    lv_obj_add_flag(mas_img, LV_OBJ_FLAG_HIDDEN);
    mas_anim = w;
    // Start mid-stride: the frames before it would play off screen.
    mas_frame = w->loop_start;
    mas_from_loop = false;
    mas_frame_started = millis();
    big_dx = -(big_x0 + (w->ox + w->w) * big_cell);
    mas_mode = MAS_ATTN_IN;
    lv_obj_clear_flag(mas_lurk_img, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(mas_lurk_img);
    big_render(w, mas_frame, false);
}

static void mas_show_still(void) {
    mas_anim = anim_by_name(mas_spec->idle);   // frame 0 == the still pose
    mas_frame = 0;
    mas_mode = MAS_STILL;
    mas_mode_started = millis();
    mas_x = mas_slot_x;
    mas_face = +1;
    if (mas_anim) corner_render(mas_anim, 0, false, mas_x);
}

// Start the spec's walk gait in `mode`, or fall back when the spec has none:
// the mascot simply reappears standing in its slot.
static void mas_start_walk(MasMode mode, int face) {
    const splash_anim_def_t *w = anim_by_name(mas_spec->walk);
    if (!w) { mas_show_still(); return; }
    mas_anim = w;
    mas_frame = 0;
    mas_from_loop = false;
    mas_frame_started = millis();
    mas_face = face;
    mas_mode = mode;
}

// Bytes for one planar RGB565A8 frame of `name` at `cell` px per art cell.
static size_t mas_frame_bytes(const char *name, int cell) {
    const splash_anim_def_t *a = anim_by_name(name);
    return a ? (size_t)(a->w * cell) * (a->h * cell) * 3 : 0;
}

lv_obj_t* splash_mascot_create(lv_obj_t *parent, int slot_x, int feet_y, int cell) {
    mas_cell = cell;
    mas_slot_x = slot_x;
    mas_feet_y = feet_y;
    mas_screen_w = board_caps().width;
    // Corner buffer: the largest idle / walk / act frame across every
    // provider spec, so switching providers never needs a reallocation.
    size_t mas_bytes = 0;
    for (const MascotSpec &s : MASCOT_SPECS) {
        const char *names[2] = { s.idle, s.walk };
        for (const char *n : names) {
            const size_t b = mas_frame_bytes(n, cell);
            if (b > mas_bytes) mas_bytes = b;
        }
        for (int g = 0; g < 4; g++)
            for (int k = 0; k < MAS_ACT_MAX && s.acts[g][k]; k++) {
                if (s.lurk && strcmp(s.acts[g][k], s.lurk) == 0) continue;  // full-size, own buffer
                const size_t b = mas_frame_bytes(s.acts[g][k], cell);
                if (b > mas_bytes) mas_bytes = b;
            }
    }
    const splash_anim_def_t *lurk = anim_by_name("lurking");
    const BoardCaps& c = board_caps();
    int mind = (c.width < c.height) ? c.width : c.height;
    mas_lurk_cell = mind / SPLASH_GRID;
    if (mas_lurk_cell < 1) mas_lurk_cell = 1;
    // The attention Clawd is 1.5x the lurk size, centered, with his feet just
    // above the status line.
    big_cell = mas_lurk_cell * 3 / 2;
    if (big_cell < 1) big_cell = 1;
    big_feet_y = c.height * 7 / 8;
    const splash_anim_def_t *walk = anim_by_name("walking");
    if (walk) big_x0 = (c.width - walk->w * big_cell) / 2 - walk->ox * big_cell;
    // The full-size image also carries the attention walk, wave and point.
    size_t lurk_bytes = 0;
    if (lurk) {
        static const char *const BIG[] = { "lurking", "walking", "waving", "pointing" };
        for (const char *n : BIG) {
            const splash_anim_def_t *a = anim_by_name(n);
            const int cl = (a == lurk) ? mas_lurk_cell : big_cell;
            const size_t b = a ? (size_t)(a->w * cl) * (a->h * cl) * 3 : 0;
            if (b > lurk_bytes) lurk_bytes = b;
        }
    }
    if (!mas_bytes) return NULL;                 // no mascot art compiled in
    mas_buf      = (uint8_t*)heap_caps_malloc(mas_bytes,  MALLOC_CAP_SPIRAM);
    mas_lurk_buf = lurk_bytes ? (uint8_t*)heap_caps_malloc(lurk_bytes, MALLOC_CAP_SPIRAM) : NULL;
    if (!mas_buf) return NULL;
    mas_buf_cap      = mas_bytes;
    mas_lurk_buf_cap = mas_lurk_buf ? lurk_bytes : 0;
    mas_img = lv_image_create(parent);
    if (mas_lurk_buf) {
        mas_lurk_img = lv_image_create(parent);
        lv_obj_add_flag(mas_lurk_img, LV_OBJ_FLAG_HIDDEN);
    }
    mas_show_still();
    return mas_img;
}

void splash_mascot_set_visible(bool v) {
    mas_visible = v;
    if (!mas_img) return;
    if (v) {
        lv_obj_clear_flag(mas_img, LV_OBJ_FLAG_HIDDEN);
        // The mascot walks over everything — keep him above later-created
        // siblings (battery icon, labels) whenever he's shown.
        lv_obj_move_foreground(mas_img);
        if (mas_lurk_img) lv_obj_move_foreground(mas_lurk_img);
        if (mas_attn) big_enter();              // an alert came in while hidden
        else          mas_show_still();         // restart clean at the slot
    } else {
        lv_obj_add_flag(mas_img, LV_OBJ_FLAG_HIDDEN);
        if (mas_lurk_img) lv_obj_add_flag(mas_lurk_img, LV_OBJ_FLAG_HIDDEN);
    }
}

void splash_mascot_attention(bool on) {
    if (!mas_img || !mas_lurk_img || !mas_lurk_buf || on == mas_attn) return;
    mas_attn = on;
    if (!mas_visible) return;                   // set_visible picks it up
    if (on) {
        if (mas_mode == MAS_LURK) {             // already off screen
            lv_obj_add_flag(mas_lurk_img, LV_OBJ_FLAG_HIDDEN);
            big_enter();
        } else if (mas_mode == MAS_ATTN_OUT) {
            mas_mode = MAS_ATTN_IN;             // was leaving: turn around
        } else if (!anim_by_name(mas_spec->walk)) {
            big_enter();                        // no gait: just hand over
        } else {                                // in or near the slot: walk off
            mas_start_walk(MAS_ATTN_OFF, -1);
        }
    } else if (mas_mode == MAS_ATTN_OFF) {
        mas_mode = MAS_WALK_IN;                 // hadn't left yet: come back
    } else {
        // The attention Clawd is always the official one; he leaves on his
        // own gait regardless of which provider's mascot holds the corner.
        mas_anim = anim_by_name("walking");
        mas_frame = 0;
        mas_from_loop = false;
        mas_frame_started = millis();
        mas_mode = MAS_ATTN_OUT;
    }
}

void splash_mascot_tick(void) {
    if (!mas_img || !mas_visible || !mas_anim) return;
    const uint32_t now = millis();

    if (mas_mode == MAS_STILL) {
        int g = usage_rate_group();
        if (g < 0 || g > 3) g = 0;
        if (now - mas_mode_started < MAS_STILL_MS_BY_RATE[g]) return;
        // Acts the current spec can perform right now: the lurk trip drops
        // out while trips are disabled, the rest play in place.
        const char *acts[MAS_ACT_MAX];
        uint8_t count = 0;
        for (int k = 0; k < MAS_ACT_MAX && mas_spec->acts[g][k]; k++) {
            const char *act = mas_spec->acts[g][k];
            if (mas_is_lurk_act(act) && !mas_can_trip()) continue;
            acts[count++] = act;
        }
        if (count == 0) { mas_mode_started = now; return; }
        const char *act = acts[mas_act_idx++ % count];
        mas_frame = 0;
        mas_frame_started = now;
        mas_from_loop = false;
        if (mas_is_lurk_act(act)) {                     // the lurk trip
            mas_start_walk(MAS_WALK_OFF, -1);
        } else {
            const splash_anim_def_t *a = anim_by_name(act);
            if (!a) { mas_mode_started = now; return; }
            mas_anim = a;
            mas_face = +1;
            mas_mode = MAS_ACT;
        }
        return;
    }

    const splash_anim_def_t *a = mas_anim;
    uint32_t hold = a->holds[mas_frame];
    // The walk to an alert plays at twice the normal speed.
    if (mas_mode == MAS_ATTN_OFF || mas_mode == MAS_ATTN_IN) hold /= 2;
    if (now - mas_frame_started < hold) return;
    mas_frame_started = now;

    uint16_t next = mas_frame + 1;
    const bool big = (mas_mode == MAS_ATTN_IN || mas_mode == MAS_ATTN_ACT ||
                      mas_mode == MAS_ATTN_OUT);
    const bool walking_mode = (mas_mode == MAS_WALK_OFF || mas_mode == MAS_WALK_IN ||
                               mas_mode == MAS_ATTN_OFF || mas_mode == MAS_ATTN_IN ||
                               mas_mode == MAS_ATTN_OUT);
    if (walking_mode && mas_frame == a->loop_end)
        next = a->loop_start;                       // walk: hold the gait loop

    if (next >= a->frame_count && mas_mode == MAS_ATTN_ACT) {
        big_act ^= 1;                               // wave, point, wave, ...
        mas_anim = anim_by_name(big_act ? "pointing" : "waving");
        mas_frame = 0;
        big_render(mas_anim, 0, false);
        return;
    }
    if (next >= a->frame_count) {                   // act / lurk finished
        if (mas_mode == MAS_LURK) {
            lv_obj_add_flag(mas_lurk_img, LV_OBJ_FLAG_HIDDEN);
            mas_x = mas_screen_w;                   // lurked on the right: re-enter from it
            mas_start_walk(MAS_WALK_IN, -1);
            lv_obj_clear_flag(mas_img, LV_OBJ_FLAG_HIDDEN);
            return;
        }
        mas_show_still();                           // acts end on the idle pose
        return;
    }

    const bool from_loop = mas_from_loop;
    mas_frame = next;
    mas_from_loop = walking_mode &&
        mas_frame >= a->loop_start && mas_frame <= a->loop_end;

    if (big && mas_from_loop) {
        const int step = walk_gait_cells_k(WALK_FRONT, mas_frame, from_loop) * big_cell;
        big_dx += (mas_mode == MAS_ATTN_IN) ? step : -step;
        if (mas_mode == MAS_ATTN_IN && big_dx >= 0) {
            big_dx = 0;                             // on his spot: wave
            big_act = 0;
            mas_anim = anim_by_name("waving");
            mas_frame = 0;
            mas_mode = MAS_ATTN_ACT;
            big_render(mas_anim, 0, false);
            return;
        }
        if (mas_mode == MAS_ATTN_OUT &&
            big_x0 + (a->ox + a->w) * big_cell + big_dx <= 0) {
            lv_obj_add_flag(mas_lurk_img, LV_OBJ_FLAG_HIDDEN);
            // The corner mascot walks back home from the left (or simply
            // reappears in the slot when its spec has no gait).
            const splash_anim_def_t *w = anim_by_name(mas_spec->walk);
            mas_x = w ? -w->w * mas_cell : mas_slot_x;
            mas_start_walk(MAS_WALK_IN, +1);
            lv_obj_clear_flag(mas_img, LV_OBJ_FLAG_HIDDEN);
            return;
        }
    } else if (walking_mode && mas_from_loop) {
        const int step = walk_gait_cells_k(mas_spec->gait, mas_frame, from_loop) * mas_cell;
        // Walk-off always exits left; walk-in heads toward the slot from
        // whichever side he's on (right, after the lurk trip).
        const bool leaving = (mas_mode == MAS_WALK_OFF || mas_mode == MAS_ATTN_OFF);
        const int dir = leaving ? -1 : (mas_x < mas_slot_x ? +1 : -1);
        mas_face = leaving ? -1 : dir;
        mas_x += dir * step;
        if (mas_mode == MAS_ATTN_OFF && mas_x <= -a->w * mas_cell) {
            big_enter();
            return;
        }
        if (mas_mode == MAS_WALK_OFF && mas_x <= -a->w * mas_cell) {
            // Fully off: hide the corner sprite, run the full-size lurk.
            lv_obj_add_flag(mas_img, LV_OBJ_FLAG_HIDDEN);
            const splash_anim_def_t *lurk = anim_by_name(mas_spec->lurk);
            if (lurk && mas_lurk_img && mas_lurk_buf) {
                mas_anim = lurk;
                mas_frame = 0;
                mas_mode = MAS_LURK;
                lv_obj_clear_flag(mas_lurk_img, LV_OBJ_FLAG_HIDDEN);
                lv_obj_move_foreground(mas_lurk_img);
                // He left stage left, so he peeks in from the RIGHT edge —
                // mirrored at render time (the art is authored left-edge).
                lurk_render(lurk, 0);
            } else {
                mas_mode = MAS_WALK_IN;             // no lurk asset: turn back
                mas_face = +1;
            }
            return;
        }
        if (mas_mode == MAS_WALK_IN &&
            ((dir > 0 && mas_x >= mas_slot_x) || (dir < 0 && mas_x <= mas_slot_x))) {
            mas_show_still();                       // arrived: settle in the slot
            return;
        }
    }

    if (big) {
        big_render(a, mas_frame, mas_mode == MAS_ATTN_OUT);
    } else if (mas_mode == MAS_LURK) {
        lurk_render(a, mas_frame);
    } else {
        corner_render(a, mas_frame, mas_face < 0, mas_x);
    }
}

void splash_mascot_set_provider(int slot) {
    if (slot < 0 || slot >= PROVIDER_COUNT) slot = PROVIDER_CLAUDE;
    const MascotSpec *spec = &MASCOT_SPECS[slot];
    if (spec == mas_spec) return;
    mas_spec = spec;
    mas_act_idx = 0;
    if (!mas_img || !mas_visible) return;        // create / set_visible render the idle
    switch (mas_mode) {
        case MAS_STILL: {
            // Swap the art in place and keep the idle timer running, so the
            // carousel's dwell does not keep postponing the next act.
            const uint32_t started = mas_mode_started;
            mas_show_still();
            mas_mode_started = started;
            break;
        }
        case MAS_ATTN_OFF: case MAS_ATTN_IN: case MAS_ATTN_ACT: case MAS_ATTN_OUT:
            break;                               // the attention Clawd finishes; the
                                                 // corner reconciles when he leaves
        default:                                 // mid-act or mid-trip: cut to the new idle
            if (mas_lurk_img) lv_obj_add_flag(mas_lurk_img, LV_OBJ_FLAG_HIDDEN);
            lv_obj_clear_flag(mas_img, LV_OBJ_FLAG_HIDDEN);
            mas_show_still();
            break;
    }
}

void splash_mascot_set_trips(bool enabled) {
    mas_trips_enabled = enabled;
}

// Start entry `pos` of the active provider set on the stage (frame 0 drawn
// now; the direct path defers while hidden). A name missing from the catalog
// is skipped in the direction of travel (`step` = +1 forward, -1 backward)
// so a half-compiled set still plays.
static void set_play(uint8_t pos, int step) {
    if (provider_mode < 0) return;
    for (int tries = 0; tries < SET_MAX; tries++) {
        const uint8_t p = (uint8_t)((pos + SET_MAX + tries * step) % SET_MAX);
        const char *name = PROVIDER_SETS[provider_mode][p];
        if (!name) continue;
        const int idx = anim_index_by_name(name);
        if (idx < 0) {
            if (!set_missing_logged[provider_mode][p]) {
                set_missing_logged[provider_mode][p] = true;
                Serial.printf("splash: set entry '%s' not in catalog; skipped\n", name);
            }
            continue;
        }
        const splash_anim_def_t *a = anim_at(idx);
        set_pos = p;
        cur_anim = (uint16_t)idx;
        cur_frame = 0;
        frame_started_ms = millis();
        last_pick_ms = frame_started_ms;
        anim_reset(a);
        render_frame(compose_stage(a, 0), a->palette);
        Serial.printf("splash: -> %s\n", a->name);
        return;
    }
}

// Move `step` entries (+1 / -1) within the active set, skipping gaps.
static void set_step(int step) {
    set_play((uint8_t)((set_pos + SET_MAX + step) % SET_MAX), step);
}

// Next fresh parade slot after `from` in rotation order (wrapping, so a
// single fresh provider returns itself), or -1 when the mask is empty.
static int parade_next_slot(int from) {
    for (int k = 1; k <= PROVIDER_COUNT; k++) {
        const int i = (from + k) % PROVIDER_COUNT;
        if (parade_fresh[i]) return i;
    }
    return -1;
}

static void show_placeholder() {
    // Solid dark background + centered status label. On the direct-draw path
    // there's no canvas; the black container is the background and the LVGL
    // label shows over it.
#if !SPLASH_DIRECT_DRAW
    if (canvas_buf) {
        for (int i = 0; i < canvas_w * canvas_h; i++) canvas_buf[i] = COL_EMPTY;
    }
    if (canvas) lv_obj_invalidate(canvas);
#endif
    if (label_status) lv_obj_clear_flag(label_status, LV_OBJ_FLAG_HIDDEN);
}

void splash_init(lv_obj_t *parent) {
    const BoardCaps& c = board_caps();

    // Shared full-screen black container — the splash background.
    splash_container = lv_obj_create(parent);
    lv_obj_set_size(splash_container, c.width, c.height);
    lv_obj_set_pos(splash_container, 0, 0);
    lv_obj_set_style_bg_color(splash_container, THEME_BG, 0);
    lv_obj_set_style_bg_opa(splash_container, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(splash_container, 0, 0);
    lv_obj_set_style_pad_all(splash_container, 0, 0);
    lv_obj_clear_flag(splash_container, LV_OBJ_FLAG_SCROLLABLE);

#if SPLASH_DIRECT_DRAW
    // Direct-to-panel path (no PSRAM): no LVGL canvas. Compute on-screen cell
    // size + centering, and a scratch band buffer sized for one grid-row strip
    // across the square art (GRID*scr_cell × scr_cell). On the C6 that's
    // 480×24×2 ≈ 23 KB of internal SRAM.
    int mind = (c.width < c.height) ? c.width : c.height;
    scr_cell = mind / GRID;
    int side = GRID * scr_cell;
    scr_offx = (c.width  - side) / 2;
    scr_offy = (c.height - side) / 2;
    strip_buf = (uint16_t*)heap_caps_malloc((size_t)side * scr_cell * 2,
                                            MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!strip_buf) {
        Serial.println("splash: strip buffer alloc failed");
        return;
    }
#else
    // PSRAM path: render into an LVGL canvas at native size (no transform).
    SplashGeometry geo = splash_compute_geometry(c.width, c.height, true);
    cell                = geo.cell;
    canvas_w            = geo.canvas_dim;
    canvas_h            = geo.canvas_dim;
    const int img_scale = geo.scale;

    canvas_buf = (uint16_t*)heap_caps_malloc(canvas_w * canvas_h * 2, MALLOC_CAP_SPIRAM);
    row_buf    = (uint16_t*)heap_caps_malloc(canvas_w * 2,            MALLOC_CAP_SPIRAM);
    if (!canvas_buf || !row_buf) {
        Serial.println("splash: failed to alloc canvas buffer");
        return;
    }

    canvas = lv_canvas_create(splash_container);
    lv_canvas_set_buffer(canvas, canvas_buf, canvas_w, canvas_h, LV_COLOR_FORMAT_RGB565);
    if (img_scale != SPLASH_SCALE_UNITY) {
        lv_image_set_antialias(canvas, false);
        lv_image_set_pivot(canvas, canvas_w / 2, canvas_h / 2);
        lv_image_set_scale(canvas, img_scale);
    }
    lv_obj_center(canvas);
#endif

    // Placeholder label (visible only when no animations are loaded)
    label_status = lv_label_create(splash_container);
    lv_label_set_text(label_status,
        "no animations loaded\n\n"
        "run tools/convert_official_clawd.js");
    lv_obj_set_style_text_font(label_status, &font_styrene_28, 0);
    lv_obj_set_style_text_color(label_status, lv_color_hex(0xb0aea5), 0);
    lv_obj_set_style_text_align(label_status, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_center(label_status);

    // Mascot-mode provider label: hidden on Claude's default splash.
    label_provider = lv_label_create(splash_container);
    lv_label_set_text(label_provider, "");
    lv_obj_set_style_text_font(label_provider, &font_styrene_20, 0);
    lv_obj_set_style_text_color(label_provider, lv_color_hex(0xb0aea5), 0);
    lv_obj_align(label_provider, LV_ALIGN_TOP_MID, 0, 16);
    lv_obj_add_flag(label_provider, LV_OBJ_FLAG_HIDDEN);

    resolve_group_lists();

    if (anim_count() == 0) {
        show_placeholder();
    } else {
        lv_obj_add_flag(label_status, LV_OBJ_FLAG_HIDDEN);
#if !SPLASH_DIRECT_DRAW
        // PSRAM path pre-renders frame 0 into the canvas buffer. The direct
        // path draws nothing here — render_frame() bails while inactive, so the
        // splash never paints to the panel before it's actually shown.
        const splash_anim_def_t *a = anim_at(0);
        render_frame(compose_stage(a, 0), a->palette);
#endif
        frame_started_ms = millis();
    }

    lv_obj_add_flag(splash_container, LV_OBJ_FLAG_HIDDEN);
}

void splash_tick(void) {
    if (!active || anim_count() == 0) return;
    const uint32_t now = millis();

#if SPLASH_DIRECT_DRAW
    // Deferred full repaint after a (re)show — runs now that LVGL has drawn the
    // black background this loop iteration.
    if (force_full) {
        const splash_anim_def_t *fa = anim_at(cur_anim);
        if (fa->frame_count) render_frame(compose_stage(fa, cur_frame), fa->palette);
    }
#endif

    const splash_anim_def_t *a = anim_at(cur_anim);
    if (a->frame_count == 0) return;

    if (walk_active) walk_choreo(a);

    // Parade: hand the stage to the next fresh provider on its timer.
    if (parade_on && now - parade_started_ms >= PARADE_PROVIDER_MS) {
        parade_started_ms = now;
        const int nxt = parade_next_slot(parade_slot);
        if (nxt >= 0 && nxt != parade_slot) {
            parade_slot = nxt;
            splash_set_provider(nxt);
            return;                    // a fresh frame 0 is on the stage
        }
    }

    // Scenes: hold the loop for SCENE_LOOP_MS, then let the outro play.
    if (!walk_active && in_loop && !loop_release &&
        now - loop_entered_ms >= SCENE_LOOP_MS)
        loop_release = true;

    // Auto-rotate — never a hard cut. Walkers switch only while standing at
    // home; everything else releases its loop and switches after the outro.
    // Mascot mode has no rotation timer: the set advances at completion.
    if (provider_mode < 0 && now - last_pick_ms >= SPLASH_ROTATE_INTERVAL_MS) {
        if (walk_active) {
            if (walk_phase == 0 && pb_done) splash_pick_for_current_rate();
        } else {
            loop_release = true;
            pending_pick = true;
            last_pick_ms = now;    // don't re-fire while the outro plays
        }
    }

    if (pb_done) return;                       // holding the idle frame
    if (now - frame_started_ms < a->holds[cur_frame]) return;

    // Advance one frame through intro → loop → outro.
    const bool from_loop = in_loop;
    uint16_t next = cur_frame + 1;
    if (cur_frame == a->loop_end && !loop_release)
        next = a->loop_start;

    if (next >= a->frame_count) {              // completed the file
        if (provider_mode >= 0) {              // mascot mode: next set entry
            set_step(+1);
            return;
        }
        if (pending_pick) {
            pending_pick = false;
            splash_pick_for_current_rate();
            return;
        }
        if (walk_active) {                     // walk finished: stand
            cur_frame = 0;
            frame_started_ms = now;
            pb_done = true;
            render_frame(compose_stage(a, 0), a->palette);
            return;
        }
        next = 0;                              // replay from the intro
        loop_release = false;
    }

    cur_frame = next;
    frame_started_ms = now;
    const bool now_in = cur_frame >= a->loop_start && cur_frame <= a->loop_end;
    if (now_in && !from_loop) loop_entered_ms = now;
    in_loop = now_in;

    // Walk translation, locked to gait frames; clamp to land exactly on the
    // target, then release the loop so the gait exits.
    if (walk_active && walk_dir != 0 && in_loop) {
        walk_x += walk_dir * walk_gait_cells(cur_frame, from_loop);
        if ((walk_dir > 0 && walk_x >= walk_target) ||
            (walk_dir < 0 && walk_x <= walk_target)) {
            walk_x = walk_target;
            walk_dir = 0;
            loop_release = true;
        }
    }

    render_frame(compose_stage(a, cur_frame), a->palette);
}

// Step the stage by `step` (+1 / -1): within the set in mascot mode, through
// the whole catalog on the Claude default.
static void splash_step(int step) {
    if (anim_count() == 0) return;
    if (provider_mode >= 0) {                  // mascot mode: within the set
        set_step(step);
        return;
    }
    cur_anim = (uint16_t)((cur_anim + anim_count() + step) % anim_count());
    cur_frame = 0;
    frame_started_ms = millis();
    last_pick_ms = frame_started_ms;
    const splash_anim_def_t *a = anim_at(cur_anim);
    anim_reset(a);
    render_frame(compose_stage(a, 0), a->palette);
    Serial.printf("splash: -> %s\n", a->name);
}

void splash_next(void) { splash_step(+1); }
void splash_prev(void) { splash_step(-1); }

void splash_pick_for_current_rate(void) {
    if (anim_count() == 0) return;
    if (provider_mode >= 0) return;            // mascot mode owns the stage
    int g = usage_rate_group();
    if (g < 0 || g >= GROUP_COUNT) g = 0;
    if (group_size[g] == 0) return;

    uint8_t slot = group_rotation[g] % group_size[g];
    group_rotation[g]++;
    int8_t idx = group_lists[g][slot];
    if (idx < 0) return;

    cur_anim = (uint16_t)idx;
    cur_frame = 0;
    frame_started_ms = millis();
    last_pick_ms = frame_started_ms;
    const splash_anim_def_t *a = anim_at(cur_anim);
    anim_reset(a);
    render_frame(compose_stage(a, 0), a->palette);
}

// ─── Mascot mode / parade API ────────────────────────────────────────────────
void splash_set_provider(int slot) {
    const bool has_set = slot > 0 && slot < PROVIDER_COUNT && PROVIDER_SETS[slot][0];
    provider_mode = has_set ? slot : -1;
    set_pos = 0;
    if (label_provider) {
        if (has_set) {
            lv_label_set_text(label_provider, provider_name(slot));
            lv_obj_set_style_text_color(label_provider, provider_theme(slot).accent, 0);
            lv_obj_align(label_provider, LV_ALIGN_TOP_MID, 0, 16);
            lv_obj_clear_flag(label_provider, LV_OBJ_FLAG_HIDDEN);
            lv_obj_move_foreground(label_provider);
        } else {
            lv_obj_add_flag(label_provider, LV_OBJ_FLAG_HIDDEN);
        }
    }
    if (!active) return;                       // splash_show() starts playback
    if (has_set) set_play(0, +1);
    else         splash_pick_for_current_rate();
}

void splash_parade_start(const bool fresh[PROVIDER_COUNT]) {
    int first = -1;
    for (int i = 0; i < PROVIDER_COUNT; i++) {
        parade_fresh[i] = fresh && fresh[i];
        if (first < 0 && parade_fresh[i]) first = i;
    }
    if (first < 0) { parade_on = false; return; }   // nothing fresh: no parade
    parade_on = true;
    parade_slot = first;
    parade_started_ms = millis();
    splash_set_provider(first);
}

void splash_parade_stop(void) {
    parade_on = false;
}

bool splash_is_parade(void) { return parade_on; }

bool splash_is_active(void) { return active; }

void splash_show(void) {
    // Select the animation; the direct path defers the draw. Mascot mode
    // starts its set at the retained position, the default path picks by rate.
    if (provider_mode >= 0) set_play(set_pos, +1);
    else                    splash_pick_for_current_rate();
    if (splash_container) lv_obj_clear_flag(splash_container, LV_OBJ_FLAG_HIDDEN);
    active = true;
#if SPLASH_DIRECT_DRAW
    // LVGL fills the container black once on unhide; that would erase a creature
    // drawn now. Defer the full repaint to the next splash_tick(), which runs
    // after lv_timer_handler() in the main loop.
    force_full = true;
#endif
}

void splash_hide(void) {
    if (splash_container) lv_obj_add_flag(splash_container, LV_OBJ_FLAG_HIDDEN);
    active = false;
}

lv_obj_t* splash_get_root(void) {
    return splash_container;
}
