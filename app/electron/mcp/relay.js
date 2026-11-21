'use strict';

// `SSBM Nucleus.exe --mcp`: a stdio MCP server for the user's own AI that relays to the running app.
//
// Newline-delimited JSON-RPC comes in on stdin; each message is POSTed to the app's /api/mcp (with the backend
// token from the discovery file, discovery.js) and the JSON answer goes out as one line on stdout. Notifications get
// nothing back (the app answers 202). When no app is running (no discovery file, or its process is gone) the relay
// starts one (the same executable without --mcp, detached) and waits up to 90 s for its file; if none comes, every
// request is answered with a JSON-RPC error saying to open SSBM Nucleus. When the app restarts (connection refused,
// or 401 for an old token) the relay finds the new endpoint. It exits once stdin closes and every answer is out.
// Only JSON-RPC may ever reach stdout: console output goes to stderr.
//
// Two processes. main.js sees --mcp before anything else and calls runElectronRelay, which only works out the
// discovery file and how to start the app, then runs this file again as a plain Node process
// (ELECTRON_RUN_AS_NODE, stdio inherited) and exits with it: on Windows the Electron browser process cannot read
// stdin (its process.stdin ends at once), and Node mode can. runRelayProcess is that Node process.
// createRelay is the testable core (tests/electron/mcp-relay.test.js); docs/dev/APP_MCP.md is the long form.
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const util = require('util');
const { discoveryPath, readDiscovery, pidAlive } = require('./discovery');
const { stableExecutable } = require('../shell/stable-executable');

const MCP_FLAG = '--mcp';
const NOT_RUNNING = -32002;
const RELAY_ERROR = -32603;
const WAIT_MS = 90000;
const OPEN_NUCLEUS = 'SSBM Nucleus is not running, and it did not start within 90 seconds. Open SSBM Nucleus, '
  + 'then try again.';

function post(endpoint, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(endpoint.url);
    const request = http.request({
      hostname: url.hostname.replace(/^\[|\]$/g, ''), port: url.port, path: url.pathname, method: 'POST',
      headers: {
        'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
        'Content-Length': Buffer.byteLength(body), 'X-Nucleus-Token': endpoint.token,
      },
    }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, text: Buffer.concat(chunks).toString('utf8') }));
      response.on('error', reject);
    });
    request.on('error', reject);
    request.end(body);
  });
}

function createRelay({
  input, output, discoveryFile, launchApp, request = post, readEndpoint = readDiscovery,
  waitMs = WAIT_MS, pollMs = 500, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), log = () => {},
}) {
  let cached = null;      // the endpoint in use
  let finding = null;     // the discovery in progress, shared by every message waiting on it
  let launched = false;   // an app was started and has not shown up yet
  let gaveUp = false;     // the last wait ran out: later messages read the file once instead of waiting again
  const pending = new Set();

  const write = message => output.write(`${JSON.stringify(message)}\n`);
  const failure = (id, code, message) => ({ jsonrpc: '2.0', id: id ?? null, error: { code, message } });

  async function discover(staleToken) {
    const found = readEndpoint(discoveryFile);
    if (found && found.token !== staleToken) return found;
    if (gaveUp) return null;
    if (!launched) {
      launched = true;
      log('SSBM Nucleus is not running: starting it');
      try { launchApp(); } catch (error) { log(`could not start SSBM Nucleus: ${error.message}`); }
    }
    for (const deadline = Date.now() + waitMs; Date.now() < deadline;) {
      await sleep(pollMs);
      const next = readEndpoint(discoveryFile);
      if (next && next.token !== staleToken) return next;
    }
    gaveUp = true;
    return null;
  }

  function endpoint(staleToken) {
    if (cached && cached.token !== staleToken) return Promise.resolve(cached);
    if (!finding) {
      finding = discover(staleToken).then(found => {
        finding = null;
        cached = found;
        if (found) launched = gaveUp = false;
        return found;
      });
    }
    return finding;
  }

  async function send(body, staleToken) {
    const target = await endpoint(staleToken);
    if (!target) return { target: null };
    try {
      return { target, response: await request(target, body) };
    } catch (error) {
      return { target, error };
    }
  }

  async function forward(message, isRequest) {
    const id = isRequest ? message.id : null;
    const body = JSON.stringify(message);
    let { target, response, error } = await send(body);
    if (target && error) {
      // Connection refused or reset: the app quit or restarted. Look again (start it if it is gone).
      log(`no answer at ${target.url} (${error.code || error.message}); looking for SSBM Nucleus again`);
      cached = null;
      ({ target, response, error } = await send(body, target.token));
    }
    if (target && response && response.status === 401) {
      // An old token: the app restarted with a new one. Take the file's current endpoint, once.
      cached = null;
      const fresh = readEndpoint(discoveryFile);
      if (fresh && fresh.token !== target.token) ({ target, response, error } = await send(body, target.token));
    }
    if (!isRequest) return;
    if (!target) return write(failure(id, NOT_RUNNING, OPEN_NUCLEUS));
    if (error) return write(failure(id, NOT_RUNNING, `SSBM Nucleus did not answer (${error.code || error.message}). `
      + 'Open SSBM Nucleus, then try again.'));
    if (response.status === 401) {
      return write(failure(id, RELAY_ERROR, 'SSBM Nucleus refused the connection (its token changed). Restart SSBM '
        + 'Nucleus, then try again.'));
    }
    if (response.status === 404) {
      return write(failure(id, RELAY_ERROR, 'This version of SSBM Nucleus has no MCP server. Update SSBM Nucleus.'));
    }
    let answer = null;
    try { answer = response.text.trim() ? JSON.parse(response.text) : null; } catch { answer = null; }
    if (!answer || typeof answer !== 'object' || answer.jsonrpc !== '2.0') {
      return write(failure(id, RELAY_ERROR, `SSBM Nucleus answered HTTP ${response.status} without a JSON-RPC reply.`));
    }
    return write(answer);
  }

  function handleLine(line) {
    if (!line.trim()) return;
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      write(failure(null, -32700, 'Parse error: each line must be one JSON-RPC message.'));
      return;
    }
    const isRequest = Boolean(message) && typeof message === 'object' && !Array.isArray(message)
      && typeof message.method === 'string' && 'id' in message;
    const job = forward(message, isRequest).catch(error => {
      log(`relay error: ${error.stack || error.message}`);
      if (isRequest) write(failure(message.id, RELAY_ERROR, `Relay error: ${error.message}`));
    });
    pending.add(job);
    job.finally(() => pending.delete(job));
  }

  let buffer = '';
  let ended = false;
  let finish;
  const done = new Promise(resolve => { finish = resolve; });

  async function close() {
    if (ended) return;
    ended = true;
    if (buffer) handleLine(buffer.replace(/\r$/, ''));
    buffer = '';
    while (pending.size) await Promise.allSettled([...pending]);
    finish();
  }

  if (typeof input.setEncoding === 'function') input.setEncoding('utf8');
  input.on('data', chunk => {
    buffer += chunk;
    for (let index = buffer.indexOf('\n'); index >= 0; index = buffer.indexOf('\n')) {
      const line = buffer.slice(0, index).replace(/\r$/, '');
      buffer = buffer.slice(index + 1);
      handleLine(line);
    }
  });
  input.on('end', close);
  input.on('close', close);
  input.on('error', close);
  return { done };
}

// What the Electron process hands the Node-mode relay (environment variables, removed before the app starts).
const RELAY_FILE_ENV = 'NUCLEUS_MCP_RELAY_FILE';
const RELAY_LAUNCH_ENV = 'NUCLEUS_MCP_RELAY_LAUNCH';

function stderrConsole() {
  const toStderr = (...args) => process.stderr.write(`${util.format(...args)}\n`);
  console.log = console.info = console.debug = console.warn = console.error = toStderr;
  return toStderr;
}

// The relay itself: a plain Node process (`ELECTRON_RUN_AS_NODE=1 <exe> relay.js`) started by runElectronRelay.
function runRelayProcess({ env = process.env, spawn = require('child_process').spawn } = {}) {
  const log = stderrConsole();
  let launch = null;
  try { launch = JSON.parse(env[RELAY_LAUNCH_ENV] || 'null'); } catch { launch = null; }
  const relay = createRelay({
    input: process.stdin, output: process.stdout, discoveryFile: env[RELAY_FILE_ENV],
    log: message => log(`[nucleus-mcp] ${message}`),
    launchApp: () => {
      if (!launch || env.NUCLEUS_MCP_NO_LAUNCH === '1') return;
      const appEnv = { ...env };
      for (const name of ['ELECTRON_RUN_AS_NODE', RELAY_FILE_ENV, RELAY_LAUNCH_ENV]) delete appEnv[name];
      spawn(launch.command, launch.args, {
        detached: true, stdio: 'ignore', cwd: launch.cwd, env: appEnv, windowsHide: false,
      }).unref();
    },
  });
  relay.done.then(() => process.exit(0));
  return relay;
}

// `--mcp` in the Electron main process (main.js, before anything else of the app starts): find the discovery
// file, then run the relay as a Node process on this process's stdio and exit with it.
// The relay's Electron process shows nothing, but Chromium still starts a GPU process and opens its disk caches under
// the session folder, which is the running app's own (userData): the 0.9.0 smoke test's relay printed "Unable to move
// the cache: Access is denied" and "Gpu Cache Creation failed" to the AI client's stderr. So, before ready: no GPU,
// no shader or HTTP cache, and a session folder of this process's own under the temp folder (CACHE_DIR/<pid>), with
// the ones of relays that have ended swept away. userData stays the app's: the discovery file lives there.
const CACHE_DIR = 'ssbm-nucleus-mcp';
const QUIET_SWITCHES = ['disable-gpu', 'disable-gpu-compositing', 'disable-gpu-shader-disk-cache', 'disable-http-cache'];

function quietChromium(app, { tmp = os.tmpdir(), pid = process.pid, isAlive = pidAlive } = {}) {
  try { app.disableHardwareAcceleration(); } catch { /* already ready: nothing to save */ }
  for (const name of QUIET_SWITCHES) app.commandLine.appendSwitch(name);
  const root = path.join(tmp, CACHE_DIR);
  let ended = [];
  try {
    ended = fs.readdirSync(root).filter(name => /^\d+$/.test(name) && Number(name) !== pid && !isAlive(Number(name)));
  } catch { /* no folder yet */ }
  for (const name of ended) {
    try { fs.rmSync(path.join(root, name), { recursive: true, force: true }); } catch { /* still held: next time */ }
  }
  const own = path.join(root, String(pid));
  try {
    fs.mkdirSync(own, { recursive: true });
    app.setPath('sessionData', own);
  } catch { /* the caches stay where they were: only noise on stderr */ }
  return own;
}

function runElectronRelay({ app, spawn = require('child_process').spawn, env = process.env, tmp = os.tmpdir() }) {
  const log = stderrConsole();
  const sessionData = quietChromium(app, { tmp });
  if (app.dock && typeof app.dock.hide === 'function') app.dock.hide();
  // The same executable as a normal launch: installed, the exe alone; in a checkout, electron.exe and the app folder.
  // On Linux that is the AppImage file, not this relay's own mount, which goes when the relay ends
  // (shell/stable-executable.js); the relay process below runs from the mount and ends with it.
  const launch = {
    command: stableExecutable({ env }), cwd: process.cwd(),
    args: process.argv.slice(1).filter(arg => arg !== MCP_FLAG),
  };
  const childEnv = {
    ...env, ELECTRON_RUN_AS_NODE: '1',
    [RELAY_FILE_ENV]: discoveryPath(app.getPath('userData'), env), [RELAY_LAUNCH_ENV]: JSON.stringify(launch),
  };
  let child;
  try {
    child = spawn(process.execPath, [__filename], { stdio: 'inherit', env: childEnv, windowsHide: true });
  } catch (error) {
    log(`[nucleus-mcp] could not start the relay: ${error.message}`);
    app.exit(1);
    return null;
  }
  const leave = (code) => {
    try { fs.rmSync(sessionData, { recursive: true, force: true }); } catch { /* still held: the next relay sweeps it */ }
    app.exit(code);
  };
  child.on('error', error => { log(`[nucleus-mcp] relay failed: ${error.message}`); leave(1); });
  child.on('exit', code => leave(code ?? 0));
  return child;
}

if (require.main === module) runRelayProcess();

module.exports = { MCP_FLAG, NOT_RUNNING, CACHE_DIR, createRelay, quietChromium, runElectronRelay, runRelayProcess, post };
