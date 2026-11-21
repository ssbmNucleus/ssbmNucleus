'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { parseArgs, childEnv, preflight, launch } = require('../../tools/dev/launch.cjs');
const { runVite } = require('../../tools/dev/launcher-vite.cjs');

const root = path.resolve('mock space & bang! checkout/app');
const portFile = path.join(root, 'frontend/.vite-port');
const config = { electron: path.join(root, 'node_modules/electron/dist/electron.exe'), env: { SAFE: 'yes' } };
function memoryFs(initial = {}) {
  const files = new Map(Object.entries(initial));
  return { files, existsSync: file => files.has(file),
    readFileSync: file => { if (!files.has(file)) throw new Error(`ENOENT: ${file}`); return files.get(file); },
    writeFileSync: (file, data) => files.set(file, data), unlinkSync: file => files.delete(file),
    copyFileSync: (src, dest) => files.set(dest, files.get(src)) };
}
function fakeChild(pid) {
  const child = new EventEmitter();
  Object.assign(child, { pid, connected: true, stdout: new PassThrough(), stderr: new PassThrough(), messages: [],
    send(message, callback) { this.messages.push(message); callback?.(); if (message.type === 'stop') queueMicrotask(() => this.emit('exit', 0, null)); },
    disconnect() { this.connected = false; this.emit('disconnect'); }, unref() {},
    kill() { assert.fail('Process termination is forbidden'); } });
  return child;
}
function harness(options = {}) {
  const io = memoryFs(options.initial);
  const calls = [];
  const checks = [];
  const logs = [];
  const vite = fakeChild(90001);
  const electron = fakeChild(90002);
  const deps = { fs: io, timeoutMs: options.timeoutMs || 1000,
    portInUse: async () => !!options.occupied,
    probe: async (port, route) => { checks.push([port, route]); return options.ready !== false; },
    spawn(command, args, spawnOptions) {
      calls.push({ command, args, options: spawnOptions });
      if (calls.length === 1) {
        queueMicrotask(() => {
          if (options.viteError) vite.emit('error', new Error('Vite spawn failed'));
          else if (options.viteExit) vite.emit('exit', 7, null);
          else {
            if (options.concurrentDuringStartup) io.files.set(portFile, '3017');
            vite.emit('message', { type: 'listening', port: 3017 });
          }
        });
        return vite;
      }
      assert.equal(io.files.get(portFile), '3017', 'handoff must precede Electron');
      assert.deepEqual(checks.slice(-2), [[3017, '/@vite/client'], [3017, '/']]);
      queueMicrotask(() => {
        if (options.concurrentPort) io.files.set(portFile, '4555');
        if (options.electronError) electron.emit('error', new Error('Electron spawn failed'));
        else electron.emit('exit', options.electronExit || 0, null);
      });
      return electron;
    } };
  return { io, calls, logs, vite, electron, run: () => launch(root, config, line => logs.push(line), deps) };
}

test('arguments reject unknown flags; check/dry-run override rebuild execution', () => {
  assert.throws(() => parseArgs(['--rebiuld']), /Unknown option/);
  assert.deepEqual(parseArgs(['--check', '--rebuild', '--record']), { check: true, rebuild: true, record: true });
  assert.equal(parseArgs(['--dry-run']).check, true);
});

test('record environment and case-insensitive Electron Node mode removal do not mutate parent', () => {
  const env = { ELECTRON_RUN_AS_NODE: '1', Electron_Run_As_Node: '1', OTHER: 'keep' };
  assert.deepEqual(childEnv(env, root, true), { OTHER: 'keep', VITE_RECORD_MODE: '1', NUCLEUS_STORAGE_DIR: path.join(root, 'storage-sample') });
  assert.equal(env.ELECTRON_RUN_AS_NODE, '1');
});

test('local executables, shell-free arguments, cwd with spaces, actual Vite port and private IPC shutdown', async () => {
  const h = harness();
  await h.run();
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].command, process.execPath);
  assert.equal(h.calls[0].options.cwd, path.join(root, 'frontend'));
  assert.equal(h.calls[1].command, config.electron);
  assert.deepEqual(h.calls[1].args, ['.']);
  assert.equal(h.calls[1].options.cwd, root);
  for (const call of h.calls) assert.equal(call.options.shell, false);
  assert.equal(h.calls[0].options.windowsHide, true, 'Vite is a background helper');
  assert.equal(h.calls[1].options.windowsHide, false, 'Electron must show its app window');
  assert.deepEqual(h.vite.messages, [{ type: 'stop' }]);
  assert.deepEqual(h.electron.messages, []);
  assert.equal(h.io.existsSync(portFile), false);
});

test('live recorded Vite is neither reused nor overwritten; no subprocess starts', async () => {
  const h = harness({ initial: { [portFile]: '3012' }, occupied: true });
  await assert.rejects(h.run(), /recorded Vite port 3012/);
  assert.equal(h.calls.length, 0);
  assert.equal(h.io.files.get(portFile), '3012');
});

test('stale handoff restored after owned session; concurrent replacement preserved', async () => {
  const stale = harness({ initial: { [portFile]: '3009' } });
  await stale.run();
  assert.equal(stale.io.files.get(portFile), '3009');
  const concurrent = harness({ concurrentPort: true });
  await concurrent.run();
  assert.equal(concurrent.io.files.get(portFile), '4555');
});

test('concurrent handoff during readiness is preserved even if its value matches our port', async () => {
  const h = harness({ concurrentDuringStartup: true });
  await assert.rejects(h.run(), /changed concurrently/);
  assert.equal(h.calls.length, 1);
  assert.equal(h.io.files.get(portFile), '3017');
});

for (const failure of ['viteError', 'viteExit']) test(`${failure} prevents Electron startup`, async () => {
  const h = harness({ [failure]: true });
  await assert.rejects(h.run(), /Vite exited before readiness/);
  assert.equal(h.calls.length, 1);
  assert.equal(h.io.existsSync(portFile), false);
});

test('HTTP readiness timeout prevents Electron even after a listening message', async () => {
  const h = harness({ ready: false, timeoutMs: 150 });
  await assert.rejects(h.run(), /readiness timed out/);
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.vite.messages, [{ type: 'stop' }]);
});

for (const failure of ['electronError', 'electronExit']) test(`${failure} surfaces failure and closes only owned Vite`, async () => {
  const h = harness({ [failure]: failure === 'electronExit' ? 9 : true });
  await assert.rejects(h.run(), /Electron failed/);
  assert.deepEqual(h.vite.messages, [{ type: 'stop' }]);
  assert.equal(h.io.existsSync(portFile), false);
});

function preflightFixture(options = {}) {
  const io = memoryFs();
  for (const relative of ['venv/Scripts/python.exe', 'frontend/node_modules/vite/dist/node/index.js', 'node_modules/electron/dist/electron.exe']) io.files.set(path.join(root, relative), 'mock');
  io.files.set(path.join(root, 'node_modules/electron/path.txt'), 'electron.exe\n');
  const calls = [];
  // fetch_native.py --check exits 0 when the pinned unpack is current, 1 when it is missing or stale.
  const state = { current: options.current !== false };
  const deps = { fs: io, resolve: () => 'mock', run: (command, args, options) => {
    calls.push({ command, args, options });
    const fetching = args.some(a => String(a).endsWith('fetch_native.py'));
    if (fetching && args.includes('--check')) return { status: state.current ? 0 : 1, stdout: '', stderr: '' };
    if (fetching) state.current = true;
    return { status: 0, stdout: '', stderr: '' };
  } };
  return { io, calls, deps, state };
}
const nativeCalls = f => f.calls.filter(c => c.args.some(a => String(a).endsWith('fetch_native.py')));
const fetcherPath = path.resolve(__dirname, '..', '..', 'tools', 'build', 'fetch_native.py');

test('current native tools are only checked; nothing is fetched', () => {
  const f = preflightFixture();
  preflight(root, parseArgs([]), () => {}, f.deps);
  assert.equal(f.calls.length, 2);
  assert.equal(f.calls[0].command, path.join(root, 'venv/Scripts/python.exe'));
  assert.deepEqual(f.calls[0].args.slice(0, 2), ['-I', '-B']);
  assert.deepEqual(f.calls[1].args, [fetcherPath, 'all', '--platform', 'host', '--check']);
  assert.equal(f.calls[1].options.shell, false);
});

test('missing or stale native tools are fetched, not built (no dotnet anywhere)', () => {
  const f = preflightFixture({ current: false });
  preflight(root, parseArgs([]), () => {}, f.deps);
  assert.deepEqual(nativeCalls(f).map(c => c.args), [
    [fetcherPath, 'all', '--platform', 'host', '--check'],
    [fetcherPath, 'all', '--platform', 'host'],
  ]);
  for (const call of f.calls) {
    assert.equal(call.options.shell, false);
    assert.doesNotMatch(String(call.command), /dotnet/i);
  }
});

test('--check never fetches, installs or writes files, even when the tools are stale', () => {
  const f = preflightFixture({ current: false });
  const before = Array.from(f.io.files);
  const logs = [];
  preflight(root, parseArgs(['--check', '--rebuild']), s => logs.push(s), f.deps);
  assert.deepEqual(Array.from(f.io.files), before);
  assert.equal(f.calls.length, 2);
  assert.ok(f.calls[1].args.includes('--check'));
  assert.ok(logs.some(s => s.includes('Would fetch')));
});

test('--rebuild forces a re-fetch of the pinned tools and propagates failures', () => {
  const f = preflightFixture();
  preflight(root, parseArgs(['--rebuild']), () => {}, f.deps);
  assert.deepEqual(nativeCalls(f).map(c => c.args).pop(), [fetcherPath, 'all', '--platform', 'host', '--force']);
  const failed = preflightFixture();
  failed.deps.run = () => ({ status: 4, stderr: 'missing Flask-SocketIO' });
  const logs = [];
  assert.throws(() => preflight(root, parseArgs(['--check']), s => logs.push(s), failed.deps), /exit 4/);
  assert.ok(logs.some(s => s.includes('missing Flask-SocketIO')));
});

test('a failed fetch blocks launch', () => {
  const f = preflightFixture({ current: false });
  const run = f.deps.run;
  f.deps.run = (command, args, options) => args.some(a => String(a).endsWith('fetch_native.py')) && !args.includes('--check')
    ? { status: 1, stderr: 'REFUSED: sha256 mismatch' } : run(command, args, options);
  const logs = [];
  assert.throws(() => preflight(root, parseArgs([]), s => logs.push(s), f.deps), /exit 1/);
  assert.ok(logs.some(s => s.includes('sha256 mismatch')));
});

test('Vite worker overrides strict3000, reports actual bound port and closes through IPC', async () => {
  const channel = fakeChild(90003);
  let options;
  let closes = 0;
  const vite = {
    loadConfigFromFile: async () => ({ config: { plugins: [{ name: 'react' }, { name: 'vite-port-handoff' }], server: { port: 3000, strictPort: true } } }),
    createServer: async opts => { options = opts; return { listen: async () => {}, httpServer: { address: () => ({ port: 3017 }) }, close: async () => { closes++; } }; },
  };
  await runVite(vite, path.join(root, 'frontend'), channel);
  assert.equal(options.root, path.join(root, 'frontend'));
  assert.equal(options.configFile, false);
  assert.equal(options.server.strictPort, false);
  assert.equal(options.server.host, 'localhost');
  assert.deepEqual(options.plugins.map(p => p.name), ['react']);
  assert.deepEqual(channel.messages, [{ type: 'listening', port: 3017 }]);
  channel.emit('message', { type: 'stop' });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(closes, 1);
  assert.equal(channel.connected, false);
});

test('orphaned worker never starts Vite after its parent disconnects during module load', async () => {
  const channel = fakeChild(90004);
  channel.connected = false;
  await runVite({ loadConfigFromFile: () => assert.fail('orphan cannot load config') }, root, channel);
  assert.deepEqual(channel.messages, []);
});

test('parent disconnect while config loads closes the eventual Vite server without listening', async () => {
  const channel = fakeChild(90005);
  let closes = 0;
  await runVite({
    loadConfigFromFile: async () => { channel.disconnect(); return { config: {} }; },
    createServer: async () => ({ listen: () => assert.fail('orphan cannot listen'), close: async () => { closes++; } }),
  }, root, channel);
  assert.equal(closes, 1);
  assert.deepEqual(channel.messages, []);
});

test('launcher sources contain no process sweep or termination APIs', () => {
  for (const file of ['launch.cjs', 'launcher-vite.cjs', 'run.bat']) {
    const source = fs.readFileSync(path.join(__dirname, '..', '..', 'tools', 'dev', file), 'utf8');
    assert.doesNotMatch(source, /taskkill|Stop-Process|Get-CimInstance|WINDOWTITLE|\.kill\s*\(|timeout\s+\/t/i);
  }
});
