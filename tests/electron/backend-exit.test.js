'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBackendRuntime } = require('../../app/electron/runtime/backend');

// backendLaunch checks that the dev entry point and interpreter exist.
const appRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-backend-exit-'));
const python = process.platform === 'win32' ? ['venv', 'Scripts', 'python.exe'] : ['venv', 'bin', 'python'];
for (const parts of [['backend', 'app.py'], python]) {
  fs.mkdirSync(path.join(appRoot, ...parts.slice(0, -1)), { recursive: true });
  fs.writeFileSync(path.join(appRoot, ...parts), '');
}
test.after(() => fs.rmSync(appRoot, { recursive: true, force: true }));

function fakeChild() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.pid = 4242;
  child.killed = false;
  return child;
}

function runtime(ctx, exits) {
  let child;
  const backend = createBackendRuntime({
    app: {}, dialog: {}, clipboard: {}, ctx, isDev: true, appRoot, resourcesPath: appRoot,
    environment: () => ({}), secrets: [],
    onExit: (exit) => exits.push(exit),
    spawnProcess: () => { child = fakeChild(); return child; },
  });
  return { backend, child: () => child };
}

test('a backend that dies after startup is reported once, with its code', async () => {
  const ctx = { isQuitting: false };
  const exits = [];
  const { backend, child } = runtime(ctx, exits);
  const started = backend.start();
  child().stdout.emit('data', Buffer.from('BACKEND_PORT:51234\n'));
  assert.equal(await started, 51234);

  child().emit('close', 3, null);
  assert.deepEqual(exits, [{ code: 3, signal: null }]);
  assert.deepEqual(backend.diagnostics().exit, { code: 3, signal: null });
  assert.equal(backend.diagnostics().alive, false);
});

test('a backend stopped by a quit is not reported', async () => {
  const ctx = { isQuitting: false };
  const exits = [];
  const { backend, child } = runtime(ctx, exits);
  const started = backend.start();
  child().stdout.emit('data', Buffer.from('BACKEND_PORT:51235\n'));
  await started;

  ctx.isQuitting = true;
  child().emit('close', 0, null);
  assert.deepEqual(exits, []);
  assert.equal(backend.diagnostics().exit, null);
});

test('a backend that dies before reporting its port is a startup failure, not an exit', async () => {
  const exits = [];
  const { backend, child } = runtime({ isQuitting: false }, exits);
  const started = backend.start();
  child().emit('close', 1, null);
  await assert.rejects(started, /before reporting port/);
  assert.deepEqual(exits, []);
});


test('signal exits remain in diagnostics for a renderer that reloads after the event', async () => {
  const exits = [];
  const { backend, child } = runtime({ isQuitting: false }, exits);
  const started = backend.start();
  child().stdout.emit('data', Buffer.from('BACKEND_PORT:51236\n'));
  await started;
  child().emit('close', null, 'SIGTERM');
  assert.deepEqual(exits, [{ code: null, signal: 'SIGTERM' }]);
  const lateWindow = backend.diagnostics();
  assert.deepEqual(lateWindow.exit, { code: null, signal: 'SIGTERM' });
  assert.equal(lateWindow.pid, null);
  assert.equal(lateWindow.alive, false);
  assert.equal(lateWindow.port, 51236);
  assert.match(lateWindow.output.join('\n'), /Backend stopped.*SIGTERM/);
  assert.deepEqual(backend.diagnostics().exit, lateWindow.exit);
});
