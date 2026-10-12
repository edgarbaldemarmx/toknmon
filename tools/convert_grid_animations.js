#!/usr/bin/env node
// Compile hand-authored text-grid animations into firmware/src/custom_animations.h.
//
//   node tools/convert_grid_animations.js                 # assets/animations/*.txt -> header
//   node tools/convert_grid_animations.js --verify DIR    # + one PNG strip per animation (ImageMagick)
//   node tools/convert_grid_animations.js --gif DIR       # + one animated GIF per animation (ImageMagick)
//   node tools/convert_grid_animations.js --in DIR --out FILE
//
// Authoring format (one animation per assets/animations/<name>.txt):
//
//   # comments start with '#' at the beginning of a line
//   name: codex.idle              required; looked up by the engine
//   origin: 15 21                 required; stage cell of grid column 0 / row 0
//   palette:                      legend lines follow, one per character
//     . = transparent             exactly one transparent entry; it becomes index 0
//     g = #10A37F                 up to 15 colors (RRGGBB)
//   hold: 120                     default ms per frame (optional, default 120)
//   loop: 1-6                     inclusive loop region (optional, default = all frames)
//   <grid rows>                   frame 0: one character per cell, no spaces
//   ---                           frame separator
//   --- hold=300                  separator with a hold override for the frame that follows
//   --- # frame 2                 separators may carry a trailing comment
//
// The grid is authored on the official 55x37 art stage (feet on stage row 36).
// Frames are cropped to their union bounding box; ox/oy are stage offsets so the
// engine places the art exactly where the official Clawd stands. Index 0 draws
// as opaque black on the full splash but as transparency on the corner mascot,
// so visible black ink must be a real palette color such as #141413.
//
// Pure Node, no dependencies. Exports its stages for tools/test/.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const REPO = path.resolve(__dirname, '..');
const DEFAULT_IN = path.join(REPO, 'assets', 'animations');
const DEFAULT_OUT = path.join(REPO, 'firmware', 'src', 'custom_animations.h');

const PALETTE_SIZE = 16;        // SPLASH_PALETTE_SIZE in splash_animations.h
const STAGE_W = 55;
const STAGE_H = 37;
const MASCOT_MAX_W = 28;        // the largest official corner act (pointing)
const MASCOT_MAX_H = 21;
const DEFAULT_HOLD_MS = 120;

function safeIdent(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

function rgb565(r, g, b) {
  return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
}

// ── Parsing ──────────────────────────────────────────────────────────────────

const HEADER_RE = /^([a-z_]+):\s*(.*)$/;
const LEGEND_RE = /^(\S)\s*=\s*(transparent|#[0-9a-fA-F]{6})$/;
const SEP_RE = /^---(?:\s+hold=(\d+))?(?:\s+#.*)?$/;   // trailing comment allowed here only

// Text -> { name, origin, legend: [{ch, rgb|null}], hold, loop, frames: [{rows, hold}] }.
function parseGrid(text, file = '<text>') {
  const fail = (msg, ln) => { throw new Error(`${file}:${ln}: ${msg}`); };
  const parsed = { name: null, origin: null, legend: [], hold: DEFAULT_HOLD_MS, loop: null, frames: [] };
  let cur = null;                     // frame being collected
  let inFrames = false;
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const ln = i + 1;
    const raw = lines[i];
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;

    const sep = SEP_RE.exec(line);
    if (sep) {
      inFrames = true;
      if (cur && cur.rows.length === 0 && parsed.frames.length === 0) {
        // Opening separator before frame 0: just carries its hold.
      } else if (cur && cur.rows.length === 0) {
        fail('empty frame', ln);
      } else if (cur) {
        parsed.frames.push(cur);
      }
      cur = { rows: [], hold: sep[1] !== undefined ? parseInt(sep[1], 10) : parsed.hold, line: ln };
      continue;
    }

    if (!inFrames) {
      const legend = LEGEND_RE.exec(line);
      if (legend) {
        const ch = legend[1];
        if (/[#=:\s]/.test(ch)) fail(`palette character '${ch}' is reserved`, ln);
        if (parsed.legend.some(e => e.ch === ch)) fail(`duplicate palette character '${ch}'`, ln);
        const v = legend[2];
        parsed.legend.push({ ch, rgb: v === 'transparent' ? null : [1, 3, 5].map(o => parseInt(v.slice(o, o + 2), 16)) });
        continue;
      }
      const hdr = HEADER_RE.exec(line);
      if (hdr) {
        const [, key, value] = hdr;
        switch (key) {
          case 'name':
            if (!value) fail('name is empty', ln);
            parsed.name = value;
            break;
          case 'origin': {
            const m = /^(-?\d+)\s+(-?\d+)$/.exec(value);
            if (!m) fail('origin needs two integers: origin: <x> <y>', ln);
            parsed.origin = [parseInt(m[1], 10), parseInt(m[2], 10)];
            break;
          }
          case 'palette':
            if (value) fail('palette: takes no value; legend lines follow', ln);
            break;
          case 'hold':
            if (!/^\d+$/.test(value)) fail('hold needs a positive integer (ms)', ln);
            parsed.hold = parseInt(value, 10);
            break;
          case 'loop': {
            const m = /^(\d+)\s*-\s*(\d+)$/.exec(value);
            if (!m) fail('loop needs a range: loop: <first>-<last>', ln);
            parsed.loop = [parseInt(m[1], 10), parseInt(m[2], 10)];
            break;
          }
          default:
            fail(`unknown header '${key}'`, ln);
        }
        continue;
      }
      // First non-header, non-legend line: the grid begins.
      inFrames = true;
    }

    if (/\s/.test(line)) fail('grid rows must not contain spaces', ln);
    if (!cur) cur = { rows: [], hold: parsed.hold, line: ln };
    cur.rows.push(line);
  }
  if (cur && cur.rows.length) parsed.frames.push(cur);
  else if (cur && parsed.frames.length) fail('trailing separator with no frame after it', lines.length);

  if (!parsed.name) fail('missing name:', 1);
  if (!parsed.origin) fail('missing origin:', 1);
  if (!parsed.frames.length) fail('no frames', lines.length);
  return parsed;
}

// ── Validation + crop ────────────────────────────────────────────────────────

// parseGrid() output -> { name, ident, w, h, ox, oy, loop, holds, palette,
// palette565, frames: Uint8Array[], warnings }.
function buildAnimation(p, file = p.name) {
  const fail = msg => { throw new Error(`${file}: ${msg}`); };
  const warnings = [];

  const transparent = p.legend.filter(e => e.rgb === null);
  if (transparent.length !== 1) fail('palette needs exactly one transparent entry');
  const colors = p.legend.filter(e => e.rgb !== null);
  if (colors.length > PALETTE_SIZE - 1) fail(`too many colors: ${colors.length} (max ${PALETTE_SIZE - 1} plus transparent)`);
  const index = new Map([[transparent[0].ch, 0]]);
  colors.forEach((e, i) => index.set(e.ch, i + 1));
  const palette = [[0, 0, 0], ...colors.map(e => e.rgb)];

  // Uniform frame size.
  const h0 = p.frames[0].rows.length;
  const w0 = p.frames[0].rows[0].length;
  p.frames.forEach((f, fi) => {
    if (f.rows.length !== h0 || f.rows.some(r => r.length !== w0))
      fail(`uneven frames: frame ${fi} (line ${f.line}) is not ${w0}x${h0}`);
  });

  // Cells as palette indices.
  const cellFrames = p.frames.map(f => {
    const cells = new Uint8Array(w0 * h0);
    f.rows.forEach((row, r) => {
      for (let c = 0; c < w0; c++) {
        const idx = index.get(row[c]);
        if (idx === undefined) fail(`unknown palette character '${row[c]}' at line ${f.line + r}`);
        cells[r * w0 + c] = idx;
      }
    });
    return cells;
  });

  // Union bounding box over all frames, then crop (same rule as the official converter).
  let x0 = w0, y0 = h0, x1 = -1, y1 = -1;
  for (const cells of cellFrames)
    for (let r = 0; r < h0; r++)
      for (let c = 0; c < w0; c++)
        if (cells[r * w0 + c]) {
          if (c < x0) x0 = c; if (c > x1) x1 = c;
          if (r < y0) y0 = r; if (r > y1) y1 = r;
        }
  if (x1 < 0) fail('animation is entirely transparent');
  const w = x1 - x0 + 1, h = y1 - y0 + 1;
  const frames = cellFrames.map(cells => {
    const out = new Uint8Array(w * h);
    for (let r = 0; r < h; r++)
      for (let c = 0; c < w; c++)
        out[r * w + c] = cells[(r + y0) * w0 + (c + x0)];
    return out;
  });

  const ox = p.origin[0] + x0, oy = p.origin[1] + y0;
  if (ox < 0 || oy < 0 || ox + w > STAGE_W || oy + h > STAGE_H)
    fail(`art leaves the ${STAGE_W}x${STAGE_H} stage (crop ${w}x${h} at ${ox},${oy})`);
  if (oy + h !== STAGE_H)
    fail(`feet not on stage row ${STAGE_H - 1}: crop bottom is row ${oy + h - 1} (origin y + grid rows must reach ${STAGE_H})`);
  if (ox === 0 || ox + w === STAGE_W)
    warnings.push(`edge snap: ox=${ox} w=${w} touches the stage edge, the engine will push it to the screen edge`);
  if (w > MASCOT_MAX_W || h > MASCOT_MAX_H)
    warnings.push(`${w}x${h} exceeds the ${MASCOT_MAX_W}x${MASCOT_MAX_H} mascot envelope; usable on the splash only`);

  const holds = p.frames.map(f => f.hold);
  holds.forEach((ms, i) => { if (!(ms > 0 && ms <= 0xffff)) fail(`frame ${i}: hold ${ms} ms out of range`); });

  const loop = p.loop || [0, frames.length - 1];
  if (loop[0] > loop[1] || loop[1] >= frames.length)
    fail(`loop ${loop[0]}-${loop[1]} out of range for ${frames.length} frames`);

  const palette565 = new Array(PALETTE_SIZE).fill(0);
  palette.forEach((c, i) => { palette565[i] = rgb565(c[0], c[1], c[2]); });

  return { name: p.name, ident: safeIdent(p.name), w, h, ox, oy, loop, holds, palette, palette565, frames, warnings };
}

// ── Emit ─────────────────────────────────────────────────────────────────────

function emitHeader(anims) {
  let out = '';
  out += '// ============================================================\n';
  out += '// Custom animations — generated by tools/convert_grid_animations.js\n';
  out += '// from the text grids in assets/animations/. Same layout as the\n';
  out += '// official set (bounding-box crops on the 55x37 stage, ox/oy = crop\n';
  out += '// origin, palette index 0 = background/transparent).\n';
  out += '// Do not edit by hand — re-run the converter to refresh.\n';
  out += '// ============================================================\n';
  out += '#pragma once\n';
  out += '#include "splash_animations.h"\n\n';

  for (const a of anims) {
    const cellBytes = a.frames.length * a.w * a.h;
    out += `static const uint16_t custom_${a.ident}_palette[${PALETTE_SIZE}] = {`;
    out += a.palette565.map(c => `0x${c.toString(16).toUpperCase().padStart(4, '0')}`).join(',');
    out += '};\n';
    out += `static const uint8_t custom_${a.ident}_frames[${cellBytes}] = {\n`;
    for (const f of a.frames) out += '    ' + Array.from(f).join(',') + ',\n';
    out += '};\n';
    out += `static const uint16_t custom_${a.ident}_holds[${a.frames.length}] = {${a.holds.join(',')}};\n\n`;
  }

  out += `#define CUSTOM_ANIM_COUNT ${anims.length}\n`;
  if (anims.length === 0) {
    out += 'static const splash_anim_def_t *const custom_anims = nullptr;\n';
    return out;
  }
  out += 'static const splash_anim_def_t custom_anims[CUSTOM_ANIM_COUNT] = {\n';
  for (const a of anims) {
    out += `    {"${a.name}", "custom", ${a.w}, ${a.h}, ${a.ox}, ${a.oy}, ${a.frames.length}, ` +
      `${a.loop[0]}, ${a.loop[1]}, ${a.palette.length}, ` +
      `custom_${a.ident}_palette, custom_${a.ident}_frames, custom_${a.ident}_holds},\n`;
  }
  out += '};\n';
  return out;
}

// ── Verify PNGs ──────────────────────────────────────────────────────────────

// One PNG per animation: every frame side by side at 8 px per cell on a gray
// backdrop (so both the transparent index and dark ink stay visible).
function writeVerifyPng(anim, dir) {
  const scale = 8, gap = 1;
  const { w, h, frames, palette } = anim;
  const W = frames.length * (w + gap) * scale, H = h * scale;
  const buf = Buffer.alloc(W * H * 3, 0x40);
  frames.forEach((f, fi) => {
    const fx = fi * (w + gap) * scale;
    for (let y = 0; y < h * scale; y++)
      for (let x = 0; x < w * scale; x++) {
        const code = f[Math.floor(y / scale) * w + Math.floor(x / scale)];
        if (!code) continue;
        const c = palette[code];
        const o = (y * W + fx + x) * 3;
        buf[o] = c[0]; buf[o + 1] = c[1]; buf[o + 2] = c[2];
      }
  });
  const ppm = path.join(dir, `${anim.ident}.ppm`);
  fs.writeFileSync(ppm, Buffer.concat([Buffer.from(`P6\n${W} ${H}\n255\n`), buf]));
  const png = path.join(dir, `${anim.ident}.png`);
  for (const tool of ['magick', 'convert']) {
    try {
      execFileSync(tool, [ppm, png], { stdio: 'ignore' });
      fs.rmSync(ppm);
      return png;
    } catch { /* try the next tool */ }
  }
  console.warn(`  ImageMagick not found; left ${ppm}`);
  return ppm;
}

// ── Animated GIFs (gallery) ──────────────────────────────────────────────────

const GIF_SCALE = 6;   // px per cell; the device shows 480/55 ≈ 8.7 px per stage cell

// One frame as a binary PPM at `scale` px per cell. Index 0 is opaque black,
// matching how the full splash renders the art on the device.
function renderFramePpm(anim, frameIndex, scale) {
  const { w, h, frames, palette } = anim;
  const W = w * scale, H = h * scale;
  const buf = Buffer.alloc(W * H * 3, 0x00);
  const f = frames[frameIndex];
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++) {
      const code = f[Math.floor(y / scale) * w + Math.floor(x / scale)];
      if (!code) continue;
      const c = palette[code];
      const o = (y * W + x) * 3;
      buf[o] = c[0]; buf[o + 1] = c[1]; buf[o + 2] = c[2];
    }
  return Buffer.concat([Buffer.from(`P6\n${W} ${H}\n255\n`), buf]);
}

// ImageMagick entry point, or null when neither `magick` nor `convert` runs.
function findImageMagick() {
  for (const tool of ['magick', 'convert']) {
    try {
      execFileSync(tool, ['-version'], { stdio: 'ignore' });
      return tool;
    } catch { /* try the next tool */ }
  }
  return null;
}

// Animated GIF of the whole clip: every frame in file order with its own hold
// as the GIF delay (ImageMagick counts in 1/100 s), looping forever. The
// in-file loop region is not unrolled; the clip itself loops. Frame files go
// to a scratch directory that is removed afterwards, so the output depends
// only on the animation data (no timestamps are written to the GIF).
// Returns the GIF path, or null when ImageMagick is unavailable.
function writeGif(anim, dir, scale = GIF_SCALE) {
  const tool = findImageMagick();
  if (!tool) {
    console.warn(`  ImageMagick not found; skipping ${anim.name}.gif`);
    return null;
  }
  const scratch = fs.mkdtempSync(path.join(dir, `.${anim.ident}-frames-`));
  try {
    const args = ['-loop', '0'];
    anim.frames.forEach((_, i) => {
      const ppm = path.join(scratch, `frame-${String(i).padStart(3, '0')}.ppm`);
      fs.writeFileSync(ppm, renderFramePpm(anim, i, scale));
      args.push('-delay', String(Math.max(1, Math.round(anim.holds[i] / 10))), ppm);
    });
    const gif = path.join(dir, `${anim.name}.gif`);
    args.push(gif);
    execFileSync(tool, args, { stdio: 'ignore' });
    return gif;
  } finally {
    fs.rmSync(scratch, { recursive: true, force: true });
  }
}

// ── Main ─────────────────────────────────────────────────────────────────────

function main(argv) {
  let inDir = DEFAULT_IN, outFile = DEFAULT_OUT, verifyDir = null, gifDir = null;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--in') inDir = path.resolve(argv[++i]);
    else if (argv[i] === '--out') outFile = path.resolve(argv[++i]);
    else if (argv[i] === '--verify') verifyDir = path.resolve(argv[++i]);
    else if (argv[i] === '--gif') gifDir = path.resolve(argv[++i]);
    else { console.error(`unknown argument ${argv[i]}`); process.exit(2); }
  }

  const files = fs.existsSync(inDir)
    ? fs.readdirSync(inDir).filter(f => f.endsWith('.txt')).sort()
    : [];
  const anims = [];
  const names = new Set();
  for (const f of files) {
    const file = path.join(inDir, f);
    const anim = buildAnimation(parseGrid(fs.readFileSync(file, 'utf8'), file), file);
    if (names.has(anim.name)) throw new Error(`${file}: duplicate animation name '${anim.name}'`);
    names.add(anim.name);
    const cellBytes = anim.frames.length * anim.w * anim.h;
    console.log(`${anim.name.padEnd(14)} ${String(anim.w).padStart(2)}x${String(anim.h).padEnd(2)} ` +
      `at ${anim.ox},${anim.oy}  ${String(anim.frames.length).padStart(2)} frames, ` +
      `${anim.palette.length} colors, loop ${anim.loop[0]}-${anim.loop[1]}, ${(cellBytes / 1024).toFixed(1)} KB`);
    for (const w of anim.warnings) console.warn(`  warning: ${w}`);
    anims.push(anim);
  }

  fs.writeFileSync(outFile, emitHeader(anims));
  console.log(`Wrote ${path.relative(process.cwd(), outFile)} (${anims.length} animations)`);

  if (verifyDir) {
    fs.mkdirSync(verifyDir, { recursive: true });
    for (const a of anims) console.log(`  ${path.relative(process.cwd(), writeVerifyPng(a, verifyDir))}`);
  }

  if (gifDir) {
    fs.mkdirSync(gifDir, { recursive: true });
    for (const a of anims) {
      const gif = writeGif(a, gifDir);
      if (gif) console.log(`  ${path.relative(process.cwd(), gif)} (${(fs.statSync(gif).size / 1024).toFixed(1)} KB)`);
    }
  }
}

module.exports = { parseGrid, buildAnimation, emitHeader, writeVerifyPng, writeGif, renderFramePpm, findImageMagick, safeIdent, rgb565 };

if (require.main === module) main(process.argv.slice(2));
