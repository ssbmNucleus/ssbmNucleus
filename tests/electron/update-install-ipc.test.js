'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { registerUpdateIpc } = require('../../app/electron/ipc/updates');

function setup() {
  const handlers = {};
  const sent = [];
  let finish, installs = 0;
  const updater = {
    install: (onProgress) => new Promise((resolve, reject) => {
      installs++;
      onProgress(5, 10);
      finish = (error) => (error ? reject(error) : resolve());
    }),
  };
  const ctx = {
    mainWindow: { isDestroyed: () => false, webContents: { send: (channel, data) => sent.push([channel, data]) } },
  };
  registerUpdateIpc({
    handleTrustedIpc: (channel, fn) => { handlers[channel] = fn; },
    app: { getVersion: () => '1.0.0' },
    ctx,
    updater,
    updateMonitor: { getStatus: () => ({}), check: () => null },
  });
  return { handlers, sent, ctx, installs: () => installs, finish: (error) => finish(error) };
}

test('a card that mounts mid-download reads the download main is running', async () => {
  const { handlers, sent, finish } = setup();
  const first = handlers['update:install']();
  assert.deepEqual(await handlers['update:install-status'](),
    { installing: true, received: 5, total: 10, error: null });

  // A second card's click does not start or clobber anything.
  assert.deepEqual(await handlers['update:install'](), { success: false, error: 'Update already in progress' });
  assert.equal((await handlers['update:install-status']()).installing, true);

  finish(new Error('checksum'));
  assert.deepEqual(await first, { success: false, error: 'checksum' });
  assert.deepEqual(await handlers['update:install-status'](),
    { installing: false, received: 0, total: 0, error: 'checksum' });
  assert.deepEqual(sent.at(-1), ['update:install-done', { success: false, error: 'checksum' }]);
});


test('install status is an isolated snapshot, success is broadcast, and a second click does not launch twice', async () => {
  const f = setup();
  assert.deepEqual(f.handlers['update:install-status'](), { installing: false, received: 0, total: 0, error: null });
  const installing = f.handlers['update:install']();
  const snapshot = f.handlers['update:install-status']();
  snapshot.installing = false; snapshot.received = 999;
  assert.deepEqual(f.handlers['update:install-status'](), { installing: true, received: 5, total: 10, error: null });
  await f.handlers['update:install']();
  assert.equal(f.installs(), 1);
  f.finish();
  assert.deepEqual(await installing, { success: true });
  assert.deepEqual(f.sent, [['update:progress', { received: 5, total: 10 }], ['update:install-done', { success: true }]]);
  assert.equal(f.handlers['update:install-status']().installing, false);
});

test('no window or a destroyed window cannot lose install state; a replacement receives completion', async () => {
  for (const unavailable of [null, { isDestroyed: () => true }]) {
    const f = setup(); f.ctx.mainWindow = unavailable;
    const installing = f.handlers['update:install']();
    assert.equal(f.handlers['update:install-status']().received, 5);
    assert.deepEqual(f.sent, []);
    f.ctx.mainWindow = { isDestroyed: () => false, webContents: { send: (...args) => f.sent.push(args) } };
    f.finish(new Error('download failed')); await installing;
    assert.deepEqual(f.sent, [['update:install-done', { success: false, error: 'download failed' }]]);
    const retry = f.handlers['update:install']();
    assert.equal(f.handlers['update:install-status']().error, null);
    assert.equal(f.installs(), 2); f.finish(); await retry;
  }
});
