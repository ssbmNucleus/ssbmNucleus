'use strict';

// Tracker #93: 5-second skips and playback speed on the phone's replay player.
// The player is frame-based (a raf loop deriving the frame from wall-clock),
// so speed and skips are pure frame math — tested here without a DOM.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

let pb;
test.before(async () => {
  const source = fs.readFileSync(path.join(__dirname, '..', '..', '..', 'services', 'mobile', 'src', 'playback.js'), 'utf8');
  pb = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
});

test('speed scales how many frames a second of wall-clock covers', () => {
  assert.equal(pb.frameAt(1000, 0, 100, 1), 160);
  assert.equal(pb.frameAt(1000, 0, 100, 0.25), 115);
  assert.equal(pb.frameAt(1000, 0, 100, 0.5), 130);
  assert.equal(pb.frameAt(1000, 0, 100, 2), 220);
});

test('re-anchoring after a rate change resumes on the same frame', () => {
  for (const r of pb.SPEEDS) {
    const t0 = pb.anchorFor(5000, 437, 100, r);
    assert.equal(pb.frameAt(5000, t0, 100, r), 437, `rate ${r}`);
  }
});

test('skips move 5 seconds and stay inside the window', () => {
  assert.equal(pb.skipTarget(1000, -1, 0, 5000), 700);
  assert.equal(pb.skipTarget(1000, 1, 0, 5000), 1300);
  assert.equal(pb.skipTarget(120, -1, 50, 5000), 50);
  assert.equal(pb.skipTarget(4900, 1, 0, 5000), 5000);
});

test('only offered speeds are accepted', () => {
  assert.deepEqual(pb.SPEEDS, [0.25, 0.5, 1, 1.5, 2]);
  assert.equal(pb.setRate(0.5), 0.5);
  assert.equal(pb.getRate(), 0.5);
  assert.equal(pb.setRate(3), 1);
  assert.equal(pb.setRate(Number('nope')), 1);
});
