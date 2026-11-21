const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createDolphinCaptureHost, installCapturePermissions, windowHandle } = require('../../app/electron/viewers/dolphin-capture');
function fixture(overrides = {}) {
  const frame = { url: 'file:///nucleus/index.html' };
  const sender = { mainFrame: frame };
  const event = { sender, senderFrame: frame };
  let target = { found: true, pid: 321, hwnd: '987654321', sessionId: 'one' };
  let time = 100;
  const calls = [];
  const host = createDolphinCaptureHost({ platform: 'win32', now: () => time,
    isTrusted: e => e.sender === sender && e.senderFrame === sender.mainFrame,
    desktopCapturer: { getSources: async options => {
      assert.deepEqual(options.types, ['window']);
      return [{ id: 'screen:0:0' }, { id: 'window:987654321:0' }, { id: 'window:123:0' }];
    } }, readTarget: async () => target,
    presentTarget: async (t, mode) => { calls.push([t, mode]); return { found: true }; }, ...overrides });
  return { host, event, sender, calls, setTarget: value => { target = value; }, advance: () => { time += 16000; } };
}
test('only exact owned window source is returned; preparation never moves a window', async () => {
  const f = fixture(); const result = await f.host.prepare(f.event);
  assert.equal(result.sourceId, 'window:987654321:0'); assert.equal(f.calls.length, 0);
  assert.equal(result.sessionId, 'one');
  assert.equal((await f.host.check(f.event, result.leaseId, { present: true })).active, true);
  assert.equal(f.calls[0][1], 'behind');
  assert.equal(windowHandle('screen:987654321:0'), null);
});

test('an old chat card cannot take another session or revoke its capture lease', async () => {
  const f = fixture(); const current = await f.host.prepare(f.event, 'one');
  assert.equal((await f.host.prepare(f.event, 'old')).found, false);
  assert.equal((await f.host.check(f.event, current.leaseId)).active, true);
  assert.equal(f.calls.length, 0);
});
test('iframe and unrelated webcontents cannot prepare or manipulate capture', async () => {
  const f = fixture();
  await assert.rejects(f.host.prepare({ ...f.event, senderFrame: { url: f.event.senderFrame.url } }), /Untrusted/);
  const lease = await f.host.prepare(f.event);
  assert.equal((await f.host.check(f.event, 'wrong')).active, false);
  assert.equal(f.host.allowsMedia({}, { isMainFrame: true }), false);
  assert.equal(f.host.allowsMedia(f.sender, { isMainFrame: false }), false);
  assert.equal(f.host.allowsMedia(f.sender, { isMainFrame: true, requestingUrl: 'https://website/' }), false);
  assert.equal(f.host.allowsMedia(f.sender, { isMainFrame: true, mediaTypes: ['video', 'audio'] }), false);
  assert.equal(f.host.allowsMedia(f.sender, { isMainFrame: true, mediaTypes: ['video'] }), true);
  f.advance(); assert.equal(f.host.allowsMedia(f.sender, { isMainFrame: true }), false);
  f.host.release(f.event, lease.leaseId);
});
test('target replacement during enumeration never grants a lease', async () => {
  let reads = 0;
  const f = fixture({ readTarget: async () => ({ found: true, pid: 321, hwnd: '987654321', sessionId: String(++reads) }) });
  assert.equal((await f.host.prepare(f.event)).found, false);
});
test('missing exact source never falls back to screen or another window', async () => {
  const f = fixture({ desktopCapturer: { getSources: async () => [{ id: 'screen:987654321:0' }, { id: 'window:123:0' }] } });
  assert.equal((await f.host.prepare(f.event)).found, false);
});
test('old lease cannot pop out a replacement session', async () => {
  const f = fixture(), lease = await f.host.prepare(f.event);
  f.setTarget({ found: true, pid: 321, hwnd: '987654321', sessionId: 'new' });
  assert.equal((await f.host.separate(f.event, lease.leaseId)).active, false);
  assert.equal(f.calls.length, 0);
  assert.equal((await f.host.check(f.event, lease.leaseId)).active, false);
});
test('pending preparation cancelled by revoke cannot install permissions', async () => {
  let resolve;
  const f = fixture({ readTarget: () => new Promise(r => { resolve = r; }) });
  const pending = f.host.prepare(f.event); f.host.revoke();
  resolve({ found: true, pid: 321, hwnd: '987654321', sessionId: 'one' });
  assert.equal((await pending).found, false);
});
test('permissions use the same production installer as the Electron smoke', async () => {
  const f = fixture(); let check, request;
  installCapturePermissions({ setPermissionCheckHandler: cb => { check = cb; }, setPermissionRequestHandler: cb => { request = cb; } }, f.host);
  assert.equal(check(f.sender, 'media', '', { isMainFrame: true }), false);
  await f.host.prepare(f.event);
  assert.equal(check(f.sender, 'media', '', { isMainFrame: true, mediaType: 'video' }), true);
  request(f.sender, 'media', result => assert.equal(result, false), { isMainFrame: false });
  assert.equal(check(f.sender, 'notifications', '', {}), true);
  f.host.revoke(); assert.equal(check(f.sender, 'media', '', { isMainFrame: true }), false);
});
test('backend failure immediately expires permission, retaining only cleanup identity', async () => {
  let fail = false;
  const f = fixture({ readTarget: async () => { if (fail) throw Error('offline'); return { found: true, pid: 321, hwnd: '987654321', sessionId: 'one' }; } });
  const lease = await f.host.prepare(f.event); fail = true;
  await assert.rejects(f.host.check(f.event, lease.leaseId), /offline/);
  assert.equal(f.host.allowsMedia(f.sender, { isMainFrame: true }), false);
});
test('navigation during pending first presentation restores only that session after it finishes', async () => {
  let finish; const modes = [];
  const f = fixture({ presentTarget: async (_target, mode) => {
    modes.push(mode); if (mode === 'behind') await new Promise(r => { finish = r; });
    return { found: true };
  } });
  const lease = await f.host.prepare(f.event);
  const pending = f.host.check(f.event, lease.leaseId, { present: true });
  await new Promise(r => setImmediate(r));
  f.host.revoke(); finish(); await pending; await new Promise(r => setImmediate(r));
  assert.deepEqual(modes, ['behind', 'separate']);
  assert.equal(f.host.allowsMedia(f.sender, { isMainFrame: true }), false);
});
test('presentation and explicit popout are serialized in arrival order', async () => {
  let finish; const modes = [];
  const f = fixture({ presentTarget: async (_target, mode) => {
    modes.push(mode); if (mode === 'behind') await new Promise(r => { finish = r; });
    return { found: true };
  } });
  const lease = await f.host.prepare(f.event);
  const pending = f.host.check(f.event, lease.leaseId, { present: true });
  await new Promise(r => setImmediate(r));
  const separate = f.host.separate(f.event, lease.leaseId);
  await new Promise(r => setImmediate(r)); assert.deepEqual(modes, ['behind']);
  finish(); await pending; await separate; assert.deepEqual(modes, ['behind', 'separate']);
});

test('the client area inside the captured frame travels with the lease, malformed values never do', async () => {
  const { clientGeometry } = require('../../app/electron/viewers/dolphin-capture');
  const client = { x: 1, y: 31, width: 640, height: 480, frameWidth: 642, frameHeight: 512 };
  const f = fixture(); f.setTarget({ found: true, pid: 321, hwnd: '987654321', sessionId: 'one', client });
  const lease = await f.host.prepare(f.event);
  assert.deepEqual(lease.client, client);
  f.setTarget({ found: true, pid: 321, hwnd: '987654321', sessionId: 'one', client: { ...client, y: 40, height: 472 } });
  assert.equal((await f.host.check(f.event, lease.leaseId)).client.y, 40);
  assert.equal(clientGeometry(null), null);
  assert.equal(clientGeometry({ ...client, height: 500 }), null);
  assert.equal(clientGeometry({ ...client, x: -1 }), null);
  assert.equal(clientGeometry({ ...client, width: 0 }), null);
  assert.equal(clientGeometry({ ...client, y: '31' }), null);
  assert.equal(clientGeometry({ ...client, extra: 'ignored' }).extra, undefined);
});
