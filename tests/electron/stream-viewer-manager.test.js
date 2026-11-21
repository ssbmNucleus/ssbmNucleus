'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const StreamViewerManager = require('../../app/electron/viewers/stream-viewer-manager');

function fakeChild() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.killed = false;
  child.killCalls = [];
  child.kill = (signal) => {
    child.killed = true;
    child.killCalls.push(signal);
  };
  return child;
}

test('startup readiness failure stops the exact spawned child', async () => {
  const child = fakeChild();
  const manager = new StreamViewerManager({ spawn: () => child });
  manager.getViewerPath = () => __filename;
  manager._getFreePort = async () => 4567;
  manager._waitHttpReady = async () => { throw new Error('forced timeout'); };

  await assert.rejects(manager.start({ datFile: 'fake.dat' }), /forced timeout/);
  assert.equal(child.killCalls.length, 1);
  assert.equal(manager.process, null);
});

test('HTTP timeout plus resulting error schedules only one retry', async () => {
  const request = new EventEmitter();
  request.destroy = () => request.emit('error', new Error('destroyed'));
  const scheduled = [];
  const manager = new StreamViewerManager({
    http: { get: (_options, _callback) => request },
    setTimeout: (callback, delay) => { scheduled.push({ callback, delay }); return scheduled.length; },
    clearTimeout: () => {},
  });
  manager.port = 4567;
  const waiting = manager._waitHttpReady();
  request.emit('timeout');
  const poll = StreamViewerManager.HEALTH_POLL_MS;
  assert.equal(scheduled.filter((item) => item.delay === poll).length, 1);
  manager._processExited = true;
  scheduled.find((item) => item.delay === poll).callback();
  await assert.rejects(waiting, /exited during startup/);
});

test('the health poll retries quickly: a viewer start is not rounded up to a slow poll', () => {
  // Every workbench reload waits on this poll; 400 ms added up to 0.4 s to each one.
  assert.ok(StreamViewerManager.HEALTH_POLL_MS <= 100);
  assert.ok(StreamViewerManager.HEALTH_POLL_MS > 0);
});

test('stop during HTTP startup cancels the wait and kills only its child', async () => {
  const child = fakeChild();
  const request = new EventEmitter();
  request.destroy = () => {};
  const manager = new StreamViewerManager({
    http: { get: () => request },
  });
  manager.process = child;
  manager.port = 4567;
  const waiting = manager._waitHttpReady();
  await manager.stop();
  await assert.rejects(waiting, /cancelled/);
  assert.equal(child.killCalls.length, 1);
});

test('startup failures preserve legacy stdout diagnostics and native stderr', async () => {
  const child = fakeChild();
  const manager = new StreamViewerManager({ spawn: () => child });
  manager.getViewerPath = () => __filename;
  manager._getFreePort = async () => 4567;
  const waitHttpReady = manager._waitHttpReady.bind(manager);
  manager._waitHttpReady = () => {
    for (let i = 0; i < 25; i++) child.stdout.emit('data', Buffer.from(`progress ${i}`));
    child.stdout.emit('data', Buffer.from('Streaming server error: editor construction failed'));
    child.stderr.emit('data', Buffer.from('Inner exception: missing dependency'));
    child.exitCode = 1;
    child.emit('close', 1);
    return waitHttpReady();
  };
  await assert.rejects(manager.start({ datFile: 'fixture.dat' }), error => {
    assert.match(error.message, /editor construction failed/);
    assert.match(error.message, /Inner exception: missing dependency/);
    assert.doesNotMatch(error.message, /progress 0\n/);
    return true;
  });
  assert.equal(manager._stdoutTail.length, 20);
  assert.equal(child.killCalls.length, 0);
});

test('WebSocket rejection during start also cleans up child', async () => {
  const child = fakeChild();
  const manager = new StreamViewerManager({ spawn: () => child });
  manager.getViewerPath = () => __filename;
  manager._getFreePort = async () => 4567;
  manager._waitHttpReady = async () => {};
  manager._connectWebSocket = async () => { throw new Error('upgrade rejected'); };

  await assert.rejects(manager.start({ datFile: 'fake.dat' }), /upgrade rejected/);
  assert.equal(child.killCalls.length, 1);
  assert.equal(manager.process, null);
});

test('stream launch hides the Windows helper and shares a fresh token only with its local transport', async () => {
  const child = fakeChild();
  let spawnOptions, requestOptions, socketOptions;
  class Socket extends EventEmitter {
    constructor(_url, options) { super(); socketOptions = options; queueMicrotask(() => this.emit('open')); }
    send() {}
    close() { this.emit('close'); }
  }
  const manager = new StreamViewerManager({
    spawn: (_executable, _args, options) => { spawnOptions = options; return child; },
    http: { get: (options, callback) => {
      requestOptions = options;
      const request = new EventEmitter();
      queueMicrotask(() => callback({ statusCode: 200, resume() {} }));
      return request;
    } }, WebSocket: Socket,
  });
  manager.getViewerPath = () => __filename;
  manager._getFreePort = async () => 4567;
  await manager.start({ datFile: 'fixture.dat', viewerSessionId: 'test' });
  const token = spawnOptions.env.NUCLEUS_VIEWER_SESSION_TOKEN;
  assert.match(token, /^[0-9a-f]{64}$/);
  assert.equal(spawnOptions.windowsHide, true);
  assert.equal(requestOptions.headers['X-Nucleus-Viewer-Token'], token);
  assert.equal(socketOptions.headers['X-Nucleus-Viewer-Token'], token);
  assert.equal(socketOptions.handshakeTimeout, 10000);
  await manager.stop();
});

test('hidden streams pause, render dimensions are bounded and actual server ticks replace estimates', () => {
  const manager = new StreamViewerManager();
  const sent = [], events = [];
  manager.isConnected = true;
  manager.ws = { send: text => sent.push(JSON.parse(text)) };
  manager.onMessage('all', event => events.push(event));
  manager.hide(); manager.show();
  assert.deepEqual(sent.slice(0, 2).map(message => message.type), ['hide', 'show']);
  assert.equal(manager.resize(0, 0, Infinity, 100), false);
  manager.resize(10, 20, 5000, 1000);
  assert.deepEqual(sent.at(-1), { type: 'resize', width: 2048, height: 410 });
  manager.handleMessage({ type: 'capabilities', animationTicks: true });
  manager.handleMessage({ type: 'animLoaded', frameCount: 60 });
  assert.equal(manager._animTimer, null);
  manager.handleMessage({ type: 'animFrame', frame: 17, frameCount: 100, playing: false, speed: 0.5 });
  assert.equal(manager._anim.frame, 17);
  assert.equal(events.at(-1).frame, 17);
  manager.handleMessage({ type: 'animLoaded', success: false, error: 'Invalid animation' });
  assert.deepEqual(manager._anim, { frame: 17, frameCount: 100, playing: false, speed: 0.5 });
  manager.cleanup();
});

test('a socket that dies stops the synthetic animation ticker', () => {
  const manager = new StreamViewerManager();
  manager.isConnected = true;
  manager.ws = { send: () => {} };
  manager.handleMessage({ type: 'animLoaded', frameCount: 60 });
  assert.notEqual(manager._animTimer, null);
  manager.isConnected = false;
  manager._syncAnimTicker();
  assert.equal(manager._animTimer, null);
  manager.cleanup();
});


for (const event of ['close', 'error']) {
  test(`actual WebSocket ${event} stops the animation ticker and reports disconnection once`, async t => {
    let socket;
    class Socket extends EventEmitter {
      constructor() { super(); socket = this; }
      send() {}
      close() { this.emit('close'); }
    }
    const manager = new StreamViewerManager({ WebSocket: Socket });
    t.after(() => manager.cleanup());
    const disconnected = [];
    manager.onMessage('disconnected', value => disconnected.push(value));
    const connected = manager._connectWebSocket(); socket.emit('open'); await connected;
    manager.handleMessage({ type: 'animLoaded', frameCount: 60 });
    assert.notEqual(manager._animTimer, null);
    socket.emit(event, ...(event === 'error' ? [new Error('lost socket')] : []));
    assert.equal(manager.isConnected, false);
    assert.equal(manager._animTimer, null);
    socket.emit('close');
    assert.equal(disconnected.length, 1);
    manager.handleMessage({ type: 'animLoaded', frameCount: 90 });
    assert.equal(manager._animTimer, null);
  });
}
