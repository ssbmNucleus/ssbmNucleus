'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadPreload(argv = [], getPathForFile = () => '', secrets = null) {
  const listeners = new Map();
  const calls = [];
  const errors = [];
  const logs = [];
  let bridge;
  const electron = {
    contextBridge: {
      exposeInMainWorld(name, api) {
        assert.equal(name, 'electron');
        bridge = api;
      },
    },
    ipcRenderer: {
      on: (channel, callback) => listeners.set(channel, callback),
      removeListener: (channel, callback) => {
        if (listeners.get(channel) === callback) listeners.delete(channel);
      },
      invoke: async (...args) => { calls.push(args); },
      sendSync: (channel) => {
        assert.equal(channel, 'renderer:secrets');
        return secrets;
      },
    },
    webFrame: {},
    webUtils: { getPathForFile },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'electron', 'preload.js'), 'utf8'), {
    require(name) {
      if (name === 'electron') return electron;
      throw new Error(`Sandbox preload cannot require ${name}`);
    },
    process: { argv },
    console: { log: (...args) => logs.push(args), error: (...args) => errors.push(args) },
  }, { filename: 'preload.js' });
  return { bridge, listeners, calls, errors, logs };
}

test('viewer messages reach the renderer without a console line each', () => {
  // 0.9.0 smoke test: one console line per viewer message, 1,405 in one session
  const { bridge, listeners, logs } = loadPreload();
  logs.length = 0;      // the one line the bridge logs when it loads
  const seen = [];
  const stop = bridge.onViewerMessage((data) => seen.push(data.type));
  for (const type of ['state', 'frame', 'state']) listeners.get('viewer:message')({}, { type });
  stop();
  assert.deepEqual(seen, ['state', 'frame', 'state']);
  assert.equal(listeners.has('viewer:message'), false);
  assert.deepEqual(logs, []);
});

test('complete sandbox preload exposes backend credentials and native APIs', async () => {
  const { bridge, calls } = loadPreload([
    'electron', '--backend-port=51234', '--backend-token=from-the-command-line',
  ], () => '', { backendToken: 'synthetic-session-token', uiApprovalKey: 'synthetic-ui-key' });
  assert.equal(bridge.backendPort, 51234);
  // the secrets come over IPC; a command-line value is never read (security review 11-19, L1)
  assert.equal(bridge.backendToken, 'synthetic-session-token');
  assert.equal(bridge.uiApprovalKey, 'synthetic-ui-key');
  assert.equal(bridge.isElectron, true);
  await bridge.selectDirectory();
  await bridge.viewerStop('viewer-session');
  await bridge.viewerRunning('viewer-session');
  assert.deepEqual(calls, [
    ['select-directory-dialog'], ['viewer:stop', 'viewer-session'], ['viewer:running', 'viewer-session'],
  ]);
});

test('selected and dropped Files resolve through webUtils without IPC or File.path', () => {
  const file = { name: 'Melee.iso' };
  const { bridge, calls } = loadPreload([], input => {
    assert.equal(input, file);
    return 'C:\\ISOs\\Melee.iso';
  });
  assert.equal(bridge.getPathForFile(file), 'C:\\ISOs\\Melee.iso');
  assert.deepEqual(calls, []);
});

for (const [subscribe, channel] of [
  ['onNucleusImport', 'nucleus-import'],
  ['onNucleusPatreon', 'nucleus-patreon'],
]) {
  test(`${channel} acknowledges only after delivery and removes its listener`, async () => {
    const { bridge, listeners, calls } = loadPreload();
    let finish;
    const pending = new Promise(resolve => { finish = resolve; });
    const cleanup = bridge[subscribe](async data => {
      assert.equal(data.value, 'ok');
      await pending;
    });
    const delivery = listeners.get(channel)({}, { id: 'handoff-1', data: { value: 'ok' } });
    await Promise.resolve();
    assert.deepEqual(calls, []);
    finish();
    await delivery;
    assert.deepEqual(calls, [['protocol:ack', 'handoff-1']]);
    cleanup();
    assert.equal(listeners.has(channel), false);
  });

  test(`${channel} preserves rejected handoffs for retry`, async () => {
    const { bridge, listeners, calls, errors } = loadPreload();
    bridge[subscribe](async () => { throw new Error('renderer rejected handoff'); });
    await assert.doesNotReject(listeners.get(channel)({}, { id: 'handoff-2', data: {} }));
    assert.deepEqual(calls, []);
    assert.equal(errors.length, 1);
    assert.match(String(errors[0][1]), /renderer rejected handoff/);
  });
}


for (const [method, channel] of [
  ['onBackendExited', 'backend:exited'], ['onUpdateInstallDone', 'update:install-done'],
]) {
  test(`${method} forwards only the payload and removes its IPC listener`, () => {
    const { bridge, listeners } = loadPreload();
    const received = [];
    const off = bridge[method]((...args) => received.push(args));
    const payload = { code: 3, success: false, error: 'failed' };
    listeners.get(channel)({ sender: 'private Electron event' }, payload);
    assert.deepEqual(received, [[payload]]);
    off();
    assert.equal(listeners.has(channel), false);
  });
}

test('reloaded renderers can request backend diagnostics and main-owned install status, or relaunch', async () => {
  const { bridge, calls } = loadPreload();
  await bridge.getBackendDiagnostics();
  await bridge.getUpdateInstallStatus();
  await bridge.relaunchApp();
  assert.deepEqual(calls, [['backend-diagnostics'], ['update:install-status'], ['app:relaunch']]);
});

test('a page the main process refuses gets no secrets, and a failing IPC does not break the bridge', () => {
  assert.equal(loadPreload(['electron'], () => '', null).bridge.backendToken, '');
  assert.equal(loadPreload(['electron'], () => '', { backendToken: 7 }).bridge.uiApprovalKey, '');
});

test('Export Vault asks main for its save dialog and passes nothing, no URL or token', async () => {
  const { bridge, calls } = loadPreload([], () => '', { backendToken: 'synthetic-session-token' });
  await bridge.saveVaultBackupDialog('ignored');
  assert.deepEqual(calls, [['save-vault-backup-dialog']]);
});
