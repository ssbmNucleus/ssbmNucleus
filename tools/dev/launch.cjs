'use strict';

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const { createRequire } = require('node:module');

function parseArgs(args) {
  const allowed = new Set(['--check', '--dry-run', '--rebuild', '--record']);
  for (const arg of args) if (!allowed.has(arg)) throw new Error(`Unknown option: ${arg}`);
  return { check: args.includes('--check') || args.includes('--dry-run'),
    rebuild: args.includes('--rebuild'), record: args.includes('--record') };
}

function childEnv(env, root, record) {
  const result = { ...env };
  for (const key of Object.keys(result)) {
    if (key.toUpperCase() === 'ELECTRON_RUN_AS_NODE') delete result[key];
  }
  if (record) {
    result.VITE_RECORD_MODE = '1';
    result.NUCLEUS_STORAGE_DIR = path.join(root, 'storage-sample');
  }
  return result;
}

function runCommand(command, args, options, log, run = spawnSync) {
  log(`[RUN] ${JSON.stringify([command, ...args])}`);
  const result = run(command, args, { ...options, shell: false, windowsHide: true, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
  if (result.stdout) log(result.stdout.trimEnd());
  if (result.stderr) log(result.stderr.trimEnd());
  if (result.error || result.status !== 0) throw new Error(`${path.basename(command)} failed: ${result.error?.message || `exit ${result.status}, signal ${result.signal || 'none'}`}`);
}

// MexCLI and HSDRawViewer are prebuilt, pinned releases of the fork repos (see
// app/utility/mex.manifest.json and hsdlib.manifest.json), fetched by
// tools/build/fetch_native.py. No .NET SDK is involved. `--check` is read-only: it
// only reports whether the fetch would run.
function ensureNative(root, python, env, flags, log, run = spawnSync) {
  const fetcher = path.join(__dirname, '..', 'build', 'fetch_native.py');
  const base = [fetcher, 'all', '--platform', 'host'];
  const options = { cwd: root, env, shell: false, windowsHide: true, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 };
  log(`[RUN] ${JSON.stringify([python, ...base, '--check'])}`);
  const current = run(python, [...base, '--check'], options);
  if (!current.error && current.status === 0 && !flags.rebuild) {
    log('[NATIVE] pinned MexCLI and HSDRawViewer are current');
    return;
  }
  if (flags.check) {
    log('[CHECK] Would fetch the pinned MexCLI and HSDRawViewer (python tools/build/fetch_native.py all --platform host)');
    return;
  }
  runCommand(python, [...base, ...(flags.rebuild ? ['--force'] : [])], { cwd: root, env }, log, run);
}

function preflight(root, flags, log, deps = {}) {
  const io = deps.fs || fs;
  const run = deps.run || spawnSync;
  const resolve = deps.resolve || ((name, dir) => createRequire(path.join(dir, 'package.json')).resolve(name));
  // Match the installed Vite 7 engine requirement; Node 18 passes the old batch
  // check but cannot run this frontend.
  const [major, minor] = process.versions.node.split('.').map(Number);
  if (!(major === 20 && minor >= 19 || major === 22 && minor >= 12 || major > 22)) {
    throw new Error('Vite requires Node.js 20.19+ (20.x) or 22.12+');
  }
  const python = path.join(root, 'venv', 'Scripts', 'python.exe');
  const vite = path.join(root, 'frontend/node_modules/vite/dist/node/index.js');
  const electronDir = path.join(root, 'node_modules/electron');
  for (const file of [python, vite, path.join(electronDir, 'path.txt')]) {
    if (!io.existsSync(file)) throw new Error(`Missing prerequisite: ${file}. Install dependencies separately; this launcher never installs them.`);
  }
  const electron = path.resolve(electronDir, 'dist', io.readFileSync(path.join(electronDir, 'path.txt'), 'utf8').trim());
  if (!io.existsSync(electron)) throw new Error(`Missing Electron executable: ${electron}`);
  resolve('ws', root);
  for (const name of ['vite', '@vitejs/plugin-react', 'react', 'react-dom']) resolve(name, path.join(root, 'frontend'));
  const env = childEnv(process.env, root, flags.record);
  runCommand(python, ['-I', '-B', path.join(__dirname, 'launcher-preflight.py')], { cwd: root, env }, log, run);
  ensureNative(root, python, env, flags, log, run);
  return { electron, env };
}

function probe(port, route) {
  return new Promise(resolve => {
    const req = http.get({ hostname: 'localhost', port, path: route, timeout: 1000 }, res => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('timeout', () => req.destroy());
    req.on('error', () => resolve(false));
  });
}

async function portInUse(port) {
  const results = await Promise.all(['127.0.0.1', '::1'].map(host => new Promise(resolve => {
    const socket = net.connect({ host, port });
    const finish = value => { socket.destroy(); resolve(value); };
    socket.setTimeout(1000, () => finish(false));
    socket.on('connect', () => finish(true));
    socket.on('error', () => finish(false));
  })));
  return results.some(Boolean);
}

function observe(child, label, log) {
  const state = { child, ended: false, result: null };
  for (const stream of [child.stdout, child.stderr]) stream?.on('data', data => log(`[${label}] ${data.toString().trimEnd()}`));
  state.done = new Promise(resolve => {
    const finish = result => {
      if (state.ended) return;
      state.ended = true;
      state.result = result;
      resolve(result);
    };
    child.on('error', error => finish({ error, code: 1 }));
    child.on('exit', (code, signal) => finish({ code, signal }));
  });
  return state;
}

async function waitForVite(state, check = probe, timeoutMs = 60000) {
  let port;
  const onMessage = message => {
    if (message?.type === 'listening' && Number.isInteger(message.port) && message.port > 0 && message.port <= 65535) port = message.port;
  };
  state.child.on('message', onMessage);
  const deadline = Date.now() + timeoutMs;
  try {
    while (Date.now() < deadline) {
      if (state.ended) throw new Error(`Vite exited before readiness: ${state.result.error?.message || state.result.code}`);
      if (port && await check(port, '/@vite/client') && await check(port, '/') && !state.ended) return port;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error('Vite readiness timed out; Electron was not launched');
  } finally {
    state.child.removeListener('message', onMessage);
  }
}

async function stopVite(state, log) {
  if (state.ended) return;
  if (state.child.connected) state.child.send({ type: 'stop' }, error => {
    if (error) log(`[ERROR] Vite shutdown request: ${error.message}`);
  });
  let timer;
  try {
    await Promise.race([state.done, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Owned Vite did not close after IPC shutdown; no process was killed. Inspect its logged PID manually.')), 5000);
    })]);
  } finally {
    clearTimeout(timer);
    if (!state.ended) {
      if (state.child.connected) state.child.disconnect();
      state.child.stdout?.destroy();
      state.child.stderr?.destroy();
      state.child.unref();
    }
  }
}

async function launch(root, config, log, deps = {}) {
  const start = deps.spawn || spawn;
  const io = deps.fs || fs;
  const check = deps.probe || probe;
  const occupied = deps.portInUse || portInUse;
  const portFile = path.join(root, 'frontend/.vite-port');
  const previous = io.existsSync(portFile) ? io.readFileSync(portFile, 'utf8') : null;
  const oldPort = Number(previous?.trim());
  // A live shared handoff might belong to another user session. Never adopt it,
  // overwrite it, or terminate it based only on its port or HTTP response.
  if (Number.isInteger(oldPort) && oldPort > 0 && oldPort <= 65535 && await occupied(oldPort)) {
    throw new Error(`A server occupies recorded Vite port ${oldPort}. Preserve that session; close it yourself before launching another from this checkout.`);
  }
  let port;
  let wroteHandoff = false;
  const vite = observe(start(process.execPath, [path.join(__dirname, 'launcher-vite.cjs')], {
    cwd: path.join(root, 'frontend'), env: config.env, shell: false, windowsHide: true,
    detached: true, stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
  }), 'Vite', log);
  log(`[START] Owned Vite child PID ${vite.child.pid || 'pending'}`);
  try {
    port = await waitForVite(vite, check, deps.timeoutMs);
    const current = io.existsSync(portFile) ? io.readFileSync(portFile, 'utf8') : null;
    if (current !== previous) throw new Error('Vite handoff changed concurrently; retry after closing the other dev session');
    io.writeFileSync(portFile, String(port));
    wroteHandoff = true;
    log(`[READY] Vite http://localhost:${port}`);
    const electron = observe(start(config.electron, ['.'], { cwd: root, env: config.env,
      // Electron is the requested interactive app, not a background helper.
      // SW_HIDE in its startup info can hide its first native window on Windows.
      shell: false, windowsHide: false, detached: true, stdio: ['ignore', 'pipe', 'pipe'] }), 'Electron', log);
    log(`[START] Electron child PID ${electron.child.pid || 'pending'}; backend readiness is reported by Electron, not this launcher. Close the app window to finish.`);
    const first = await Promise.race([electron.done.then(result => ({ result })), vite.done.then(result => ({ vite: true, result }))]);
    if (first.vite) {
      log('[ERROR] Vite exited while Electron was running. Electron is preserved; close its window to finish.');
      await electron.done;
      throw new Error(`Vite exited unexpectedly: ${first.result.error?.message || first.result.code}`);
    }
    if (first.result.error || first.result.code !== 0) throw new Error(`Electron failed: ${first.result.error?.message || `exit ${first.result.code}, signal ${first.result.signal || 'none'}`}`);
    log('[EXIT] Electron exited with code 0 (an existing instance may have handled the request).');
  } finally {
    await stopVite(vite, log);
    // Restore only our own handoff; a concurrent writer's value is preserved.
    if (wroteHandoff && io.existsSync(portFile) && io.readFileSync(portFile, 'utf8') === String(port)) {
      if (previous === null) io.unlinkSync(portFile);
      else io.writeFileSync(portFile, previous);
    }
  }
}

async function main(args = process.argv.slice(2)) {
  let log = message => console.log(message);
  let lockFd;
  const root = path.resolve(__dirname, '..', '..', 'app');  // the app/ folder
  const lock = path.join(root, 'logs/dev-launcher.lock');
  const onInterrupt = () => log('[INFO] No processes were terminated. Close the Electron window to finish this session.');
  try {
    const flags = parseArgs(args);
    if (!flags.check) {
      fs.mkdirSync(path.dirname(lock), { recursive: true });
      // A crashed launch requires human inspection: never reclaim via PID guesses.
      try { lockFd = fs.openSync(lock, 'wx'); }
      catch (error) { throw new Error(`Cannot acquire ${lock}: ${error.message}. Another launch or a stale lock needs manual inspection.`); }
      fs.writeFileSync(lockFd, JSON.stringify({ pid: process.pid, started: new Date().toISOString() }));
      const logfile = path.join(root, 'logs', `dev-launch-${Date.now()}-${process.pid}.log`);
      const logFd = fs.openSync(logfile, 'wx');
      log = message => { console.log(message); fs.writeSync(logFd, `${message}\n`); };
      log(`[LOG] ${logfile}`);
      // Keep fd until process exit so final child stdout/stderr is captured too.
    }
    const config = preflight(root, flags, log);
    if (flags.check) { log('[CHECK] Preflight passed. No install, build, app launch, or Nucleus data access was performed.'); return 0; }
    process.on('SIGINT', onInterrupt);
    process.on('SIGTERM', onInterrupt);
    await launch(root, config, log);
    return 0;
  } catch (error) {
    log(`[ERROR] ${error.stack || error}`);
    return 1;
  } finally {
    process.removeListener('SIGINT', onInterrupt);
    process.removeListener('SIGTERM', onInterrupt);
    if (lockFd !== undefined) { fs.closeSync(lockFd); fs.unlinkSync(lock); }
  }
}

module.exports = { parseArgs, childEnv, ensureNative, runCommand, preflight, observe, waitForVite, stopVite, launch, main };
if (require.main === module) main().then(code => { process.exitCode = code; });
