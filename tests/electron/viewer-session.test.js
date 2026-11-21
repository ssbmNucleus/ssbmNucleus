const test = require('node:test');
const assert = require('node:assert/strict');
const { ViewerFrameRelay, ViewerSession, viewerTransport } = require('../../app/electron/viewers/viewer-session');

test('slow renderer keeps only the newest pending frame and requires the exact acknowledgement', () => {
  const delivered = [];
  const relay = new ViewerFrameRelay((buffer, metadata) => delivered.push({ buffer, metadata }));
  relay.reset('first');
  for (let frame = 0; frame < 10000; frame++) relay.push(frame + 1);
  assert.deepEqual(delivered.map(item => item.buffer), [1]);
  assert.equal(relay.pending, 10000);
  assert.equal(relay.consumed({ ...delivered[0].metadata, frameId: 9 }), false);
  assert.equal(relay.consumed({ ...delivered[0].metadata, viewerSessionId: 'old' }), false);
  assert.equal(relay.consumed(delivered[0].metadata), true);
  assert.deepEqual(delivered.map(item => item.buffer), [1, 10000]);
  assert.equal(relay.consumed(delivered[0].metadata), false);
  relay.reset('replacement');
  relay.push(10001);
  assert.equal(relay.consumed(delivered[1].metadata), false);
  assert.equal(delivered[2].metadata.viewerSessionId, 'replacement');
});

test('a missing renderer does not leave the next session stalled', () => {
  let visible = false;
  const relay = new ViewerFrameRelay(() => visible);
  relay.reset('one');
  relay.push(Buffer.from('first'));
  assert.equal(relay.inFlight, null);
  visible = true;
  relay.push(Buffer.from('second'));
  assert.ok(relay.inFlight);
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function fakeManager(startResult = Promise.resolve({ streaming: true })) {
  return {
    stops: 0,
    onMessage(_type, callback) { this.emit = callback; },
    async start(options) { this.viewerSessionId = options.viewerSessionId; return startResult; },
    async stop() { this.stops++; },
  };
}

test('overlapping starts fence old messages, frames and late completion from the new viewer', async () => {
  const firstStart = deferred();
  const first = fakeManager(firstStart.promise), second = fakeManager();
  const managers = [first, second], messages = [], frames = [];
  const host = new ViewerSession({ createManager: () => managers.shift(),
    onMessage: message => messages.push(message), onFrame: frame => frames.push(frame) });
  const old = host.start({ viewerSessionId: 'old' });
  const oldFailure = assert.rejects(old, /superseded/);
  await host.start({ viewerSessionId: 'new' });
  first.emit({ type: 'ready' }); first.onFrame('obsolete');
  second.emit({ type: 'ready' }); second.onFrame('current');
  firstStart.resolve({ streaming: true });
  await oldFailure;
  assert.equal(host.manager, second);
  assert.deepEqual(frames, ['current']);
  assert.equal(messages.length, 1);
  assert.equal(second.stops, 0);
  assert.equal(await host.stop('old'), false);
  assert.equal(host.manager, second);
  await host.stop('new');
  assert.equal(second.stops, 1);
});

test('close during startup prevents a late ready or frame from reviving the viewer', async () => {
  const start = deferred(), manager = fakeManager(start.promise), events = [];
  const host = new ViewerSession({ createManager: () => manager,
    onMessage: event => events.push(event), onFrame: event => events.push(event) });
  const opening = host.start({ viewerSessionId: 'closed' });
  const failure = assert.rejects(opening, /superseded/);
  await host.stop('closed');
  manager.emit({ type: 'ready' }); manager.onFrame('late');
  start.resolve({ streaming: true });
  await failure;
  assert.equal(host.manager, null);
  assert.deepEqual(events, []);
});

test('a kept view learns whether it is still the running viewer after another view replaced it', async () => {
  const first = fakeManager(), second = fakeManager(), managers = [first, second];
  const host = new ViewerSession({ createManager: () => managers.shift(), onMessage() {}, onFrame() {} });
  await host.start({ viewerSessionId: 'workbench' });
  assert.equal(host.running('workbench'), false, 'not connected yet');
  first.isConnected = true;
  assert.equal(host.running('workbench'), true);
  assert.equal(host.running('other'), false);
  assert.equal(host.running(undefined), false, 'no id never matches');
  first.isConnected = false;
  assert.equal(host.running('workbench'), false, 'its renderer went away');
  first.isConnected = true;
  await host.start({ viewerSessionId: 'vault' });
  second.isConnected = true;
  assert.equal(host.running('workbench'), false, 'replaced by another view');
  assert.equal(host.running('vault'), true);
  await host.stop('vault');
  assert.equal(host.running('vault'), false, 'stopped');
});

test('canvas is the default on every platform; only an explicit Windows override enables the overlay', () => {
  for (const platform of ['win32', 'linux', 'darwin']) assert.equal(viewerTransport(platform, ''), 'stream');
  assert.equal(viewerTransport('win32', 'embedded'), 'embedded');
  assert.throws(() => viewerTransport('linux', 'embedded'), /only available/);
  assert.throws(() => viewerTransport('win32', 'typo'), /Unknown/);
});
