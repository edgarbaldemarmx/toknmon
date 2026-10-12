// Tests for tools/convert_grid_animations.js — run with `node --test tools/test/`.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const conv = require(path.join(__dirname, '..', 'convert_grid_animations.js'));

// A 4x3 grid at origin (20, 34): the bottom row is stage row 36, so the
// crop satisfies the feet rule. Column 0 and row 0 are empty in every frame
// and must be cropped away.
const FIXTURE = `
# fixture: two frames, one color + ink
name: test.blob
origin: 20 34
palette:
  . = transparent
  g = #10A37F
  k = #141413
hold: 90
loop: 0-1
....
.gg.
.gkg
--- hold=300
....
.gg.
.ggg
`;

test('parses header, crops to the union bounding box and keeps stage offsets', () => {
  const anim = conv.buildAnimation(conv.parseGrid(FIXTURE, 'fixture.txt'));
  assert.equal(anim.name, 'test.blob');
  assert.equal(anim.ident, 'test_blob');
  assert.equal(anim.w, 3);
  assert.equal(anim.h, 2);
  assert.equal(anim.ox, 21);               // origin x + first used column
  assert.equal(anim.oy, 35);               // origin y + first used row
  assert.equal(anim.oy + anim.h, 37);      // feet on stage row 36
  assert.deepEqual(anim.loop, [0, 1]);
  assert.deepEqual(anim.holds, [90, 300]);
  assert.equal(anim.palette.length, 3);
  assert.deepEqual(anim.palette[0], [0, 0, 0]);
  assert.deepEqual(anim.palette[1], [0x10, 0xa3, 0x7f]);
  assert.deepEqual(anim.palette565.slice(0, 3), [0x0000, 0x150f, 0x10A2]);
  assert.equal(anim.frames.length, 2);
  assert.deepEqual(Array.from(anim.frames[0]), [1, 1, 0, 1, 2, 1]);
  assert.deepEqual(Array.from(anim.frames[1]), [1, 1, 0, 1, 1, 1]);
});

test('emits a header the firmware can compile against', () => {
  const anim = conv.buildAnimation(conv.parseGrid(FIXTURE, 'fixture.txt'));
  const out = conv.emitHeader([anim]);
  assert.match(out, /#include "splash_animations.h"/);
  assert.match(out, /static const uint16_t custom_test_blob_palette\[16\] = \{0x0000,0x150F,0x10A2,0x0000/);
  assert.match(out, /static const uint8_t custom_test_blob_frames\[12\] = \{/);
  assert.match(out, /static const uint16_t custom_test_blob_holds\[2\] = \{90,300\};/);
  assert.match(out, /#define CUSTOM_ANIM_COUNT 1/);
  assert.match(out, /\{"test\.blob", "custom", 3, 2, 21, 35, 2, 0, 1, 3, custom_test_blob_palette, custom_test_blob_frames, custom_test_blob_holds\}/);
});

test('an empty input set still emits a compilable header', () => {
  const out = conv.emitHeader([]);
  assert.match(out, /#define CUSTOM_ANIM_COUNT 0/);
  assert.match(out, /custom_anims = nullptr;/);
});

test('rejects more than 15 colors plus transparent', () => {
  const legend = ['  . = transparent'];
  const chars = 'abcdefghijklmnop';               // 16 colors
  for (let i = 0; i < chars.length; i++) legend.push(`  ${chars[i]} = #${(0x0f0f0f * (i + 1)).toString(16).padStart(6, '0')}`);
  const text = `name: t\norigin: 20 36\npalette:\n${legend.join('\n')}\n${chars}\n`;
  assert.throws(() => conv.buildAnimation(conv.parseGrid(text, 't.txt')), /too many colors/);
});

test('rejects uneven frames', () => {
  const text = `name: t\norigin: 20 35\npalette:\n  . = transparent\n  g = #ffffff\ngg\ngg\n---\nggg\nggg\n`;
  assert.throws(() => conv.buildAnimation(conv.parseGrid(text, 't.txt')), /uneven frames/);
});

test('rejects art whose feet are not on stage row 36', () => {
  const text = `name: t\norigin: 20 30\npalette:\n  . = transparent\n  g = #ffffff\ngg\ngg\n`;
  assert.throws(() => conv.buildAnimation(conv.parseGrid(text, 't.txt')), /feet/);
});

test('rejects unknown palette characters and bad loop ranges', () => {
  const unknown = `name: t\norigin: 20 35\npalette:\n  . = transparent\n  g = #ffffff\ngx\ngg\n`;
  assert.throws(() => conv.buildAnimation(conv.parseGrid(unknown, 't.txt')), /unknown palette character/);
  const loop = `name: t\norigin: 20 35\npalette:\n  . = transparent\n  g = #ffffff\nloop: 0-3\ngg\ngg\n`;
  assert.throws(() => conv.buildAnimation(conv.parseGrid(loop, 't.txt')), /loop/);
});

test('warns on edge snap and on mascot-oversized art', () => {
  const rows = Array(22).fill('g'.repeat(29)).join('\n');
  const text = `name: t\norigin: 0 15\npalette:\n  . = transparent\n  g = #ffffff\n${rows}\n`;
  const anim = conv.buildAnimation(conv.parseGrid(text, 't.txt'));
  assert.ok(anim.warnings.some(w => /edge snap/.test(w)));
  assert.ok(anim.warnings.some(w => /mascot/.test(w)));
});
