const test = require('node:test');
const assert = require('node:assert/strict');

const { parseNucleusUrl, ProtocolHandoffQueue } = require('../../app/electron/protocol/protocol-handoff');

test('cold links wait for renderer readiness and advance only after ack', () => {
  const sent = [];
  const queue = new ProtocolHandoffQueue((channel, envelope) => sent.push({ channel, envelope }));
  const first = parseNucleusUrl(
    'nucleus://import?url=https%3A%2F%2Fmods.example%2Fa.zip&name=A');
  const second = parseNucleusUrl('nucleus://patreon-link?token=secret&active=1');
  queue.enqueue(first);
  queue.enqueue(second);
  assert.deepEqual(sent, []);

  queue.rendererReady();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].channel, 'nucleus-import');
  assert.equal(queue.acknowledge(sent[0].envelope.id), true);
  assert.equal(sent.length, 2);
  assert.equal(sent[1].channel, 'nucleus-patreon');
});

test('an unacknowledged handoff survives renderer reload', () => {
  const sent = [];
  const queue = new ProtocolHandoffQueue((_channel, envelope) => sent.push(envelope));
  queue.enqueue(parseNucleusUrl('nucleus://patreon-link?token=secret&active=1'));
  queue.rendererReady();
  const id = sent[0].id;
  queue.rendererGone();
  queue.rendererReady();
  assert.deepEqual(sent.map((row) => row.id), [id, id]);
});

test('duplicate OS delivery is suppressed briefly but later deliberate use works', () => {
  let now = 1000;
  const sent = [];
  const queue = new ProtocolHandoffQueue((_channel, envelope) => sent.push(envelope), {
    now: () => now, dedupeMs: 1500,
  });
  const item = parseNucleusUrl('nucleus://import?url=https%3A%2F%2Fmods.example%2Fb.zip');
  assert.equal(queue.enqueue(item), true);
  assert.equal(queue.enqueue(item), false);
  now += 1500;
  assert.equal(queue.enqueue(item), true);
});

test('malformed or unsafe protocol routes are rejected before queueing', () => {
  assert.equal(parseNucleusUrl('https://example.com/'), null);
  assert.equal(parseNucleusUrl('nucleus://import?url=file%3A%2F%2F%2Fsecret'), null);
  assert.equal(parseNucleusUrl('nucleus://import?url=http%3A%2F%2Fevil.example%2Fx'), null);
  // nucleus://play?build= links went with Friends build sharing (0.8.16).
  assert.equal(parseNucleusUrl(`nucleus://play?build=${'a'.repeat(32)}`), null);
  assert.equal(parseNucleusUrl('nucleus://patreon-link'), null);
});

test('a patreon-link carries its OAuth state through to the window', () => {
  const link = parseNucleusUrl('nucleus://patreon-link?token=t&active=1&name=A&state=nonce-1');
  assert.equal(link.channel, 'nucleus-patreon');
  assert.equal(link.payload.state, 'nonce-1');
  assert.equal(parseNucleusUrl('nucleus://patreon-link?token=t').payload.state, null);
});
