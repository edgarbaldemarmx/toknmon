// Tests for the `--gif DIR` export of tools/convert_grid_animations.js.
// Run with `node --test tools/test/`. The GIF assembly needs ImageMagick; the
// test skips (with a message) when neither `magick` nor `convert` is installed.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const conv = require(path.join(__dirname, '..', 'convert_grid_animations.js'));

// Same shape as the converter fixture: a 3x2 crop with two frames and holds 90/300.
const FIXTURE = `
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

function fixtureAnim() {
  return conv.buildAnimation(conv.parseGrid(FIXTURE, 'fixture.txt'));
}

test('renders a frame as a binary PPM at the requested scale on black', () => {
  const anim = fixtureAnim();
  const ppm = conv.renderFramePpm(anim, 0, 6);
  const header = Buffer.from('P6\n18 12\n255\n');
  assert.deepEqual(ppm.subarray(0, header.length), header);
  assert.equal(ppm.length, header.length + 18 * 12 * 3);
  const px = (x, y) => Array.from(ppm.subarray(header.length + (y * 18 + x) * 3, header.length + (y * 18 + x) * 3 + 3));
  assert.deepEqual(px(0, 0), [0x10, 0xa3, 0x7f]);   // cell (0,0) is 'g'
  assert.deepEqual(px(17, 0), [0, 0, 0]);           // cell (2,0) is transparent -> black
  assert.deepEqual(px(8, 11), [0x14, 0x14, 0x13]);  // cell (1,1) is 'k' (dark ink, not index 0)
});

test('--gif export writes a non-empty, deterministic animated GIF', (t) => {
  if (!conv.findImageMagick()) {
    t.skip('ImageMagick (magick/convert) not installed; GIF export not exercised');
    return;
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'grid-gif-'));
  try {
    const anim = fixtureAnim();
    const gif = conv.writeGif(anim, dir);
    assert.equal(gif, path.join(dir, 'test.blob.gif'));
    assert.ok(fs.existsSync(gif), 'GIF file exists');
    const bytes = fs.readFileSync(gif);
    assert.ok(bytes.length > 0, 'GIF is non-empty');
    assert.equal(bytes.subarray(0, 6).toString('latin1'), 'GIF89a');

    // Second run must be byte-identical (no timestamps, fixed frame order).
    const again = fs.readFileSync(conv.writeGif(anim, dir));
    assert.ok(bytes.equals(again), 'repeated export is byte-identical');

    // Scratch frame directories are cleaned up; only the GIF remains.
    assert.deepEqual(fs.readdirSync(dir), ['test.blob.gif']);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
