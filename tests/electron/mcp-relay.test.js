'use strict';

// The `--mcp` stdio relay (app/electron/mcp/relay.js) and its discovery file (mcp/discovery.js).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { PassThrough } = require('stream');
const { createRelay, NOT_RUNNING } = require('../../app/electron/mcp/relay');
const discovery = require('../../app/electron/mcp/discovery');

function tempFile(t) {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-mcp-'));
  t.after(() => fs.rmSync(folder, { recursive: true, force: true }));
  return path.join(folder, 'mcp-endpoint.json');
}

// A relay over in-memory streams; `lines()` is everything it wrote to stdout, parsed.
function harness(options) {
  const input = new PassThrough();
  const output = new PassThrough();
  let text = '';
  output.on('data', chunk => { text += chunk; });
  const relay = createRelay({ input, output, launchApp: () => {}, sleep: async () => {}, ...options });
  const send = (...messages) => messages.forEach(message =>
    input.write(`${typeof message === 'string' ? message : JSON.stringify(message)}\n`));
  const finish = async () => { input.end(); await relay.done; return text.split('\n').filter(Boolean).map(line => JSON.parse(line)); };
  return { send, finish, raw: () => text };
}

async function waitFor(check) {
  for (let round = 0; round < 1000 && !check(); round += 1) await new Promise(resolve => setImmediate(resolve));
  assert.ok(check(), 'timed out waiting');
}

function fakeApp(t, { token = 'tok-1', answer } = {}) {
  const seen = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      seen.push({ token: req.headers['x-nucleus-token'], body: JSON.parse(body) });
      if (req.headers['x-nucleus-token'] !== token) { res.writeHead(401).end('{"error":"Unauthorized"}'); return; }
      const message = JSON.parse(body);
      if (!('id' in message)) { res.writeHead(202).end(); return; }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(answer ? answer(message) : { jsonrpc: '2.0', id: message.id, result: { echo: message.method } }));
    });
  });
  return new Promise(resolve => server.listen(0, '127.0.0.1', () => {
    t.after(() => server.close());
    resolve({ port: server.address().port, seen });
  }));
}

test('forwards each request over HTTP with the token and prints one JSON line per answer', async t => {
  const file = tempFile(t);
  const app = await fakeApp(t);
  discovery.writeDiscovery(file, { port: app.port, token: 'tok-1', pid: process.pid });
  const relay = harness({ discoveryFile: file });
  relay.send(
    { jsonrpc: '2.0', id: 1, method: 'initialize', params: {} },
    { jsonrpc: '2.0', method: 'notifications/initialized' },
    { jsonrpc: '2.0', id: 'b', method: 'tools/list' },
  );
  const lines = await relay.finish();
  assert.deepEqual(lines.map(line => line.id).sort(), [1, 'b'].sort());
  assert.deepEqual(lines.find(line => line.id === 1).result, { echo: 'initialize' });
  assert.equal(app.seen.length, 3, 'the notification reaches the app too');
  assert.ok(app.seen.every(entry => entry.token === 'tok-1'));
  assert.ok(relay.raw().endsWith('\n') && relay.raw().split('\n').filter(Boolean).length === 2);
});

test('a line that is not JSON gets a parse error with a null id', async t => {
  const relay = harness({ discoveryFile: tempFile(t) });
  relay.send('{not json');
  const lines = await relay.finish();
  assert.equal(lines.length, 1);
  assert.equal(lines[0].id, null);
  assert.equal(lines[0].error.code, -32700);
});

test('with no app running it starts one once and waits for its discovery file', async t => {
  let launches = 0;
  let reads = 0;
  const endpoint = { url: 'http://127.0.0.1:1/api/mcp', token: 't', pid: 1 };
  const relay = harness({
    discoveryFile: 'unused',
    launchApp: () => { launches += 1; },
    readEndpoint: () => (++reads > 3 ? endpoint : null),
    request: async (target, body) => ({ status: 200, text: JSON.stringify({ jsonrpc: '2.0', id: JSON.parse(body).id, result: {} }) }),
  });
  relay.send({ jsonrpc: '2.0', id: 1, method: 'ping' }, { jsonrpc: '2.0', id: 2, method: 'ping' });
  const lines = await relay.finish();
  assert.equal(launches, 1);
  assert.deepEqual(lines.map(line => line.id).sort(), [1, 2]);
  assert.ok(lines.every(line => line.result));
});

test('when the app never comes, each request is told to open SSBM Nucleus, without a second wait', async t => {
  let launches = 0;
  let sleeps = 0;
  let clock = 0;
  const realNow = Date.now;
  Date.now = () => clock;
  t.after(() => { Date.now = realNow; });
  const relay = harness({
    discoveryFile: 'unused', waitMs: 1000, pollMs: 100,
    launchApp: () => { launches += 1; },
    readEndpoint: () => null,
    sleep: async ms => { sleeps += 1; clock += ms; },
    request: async () => { throw new Error('must not be called'); },
  });
  relay.send({ jsonrpc: '2.0', id: 1, method: 'initialize' });
  await waitFor(() => relay.raw().includes('"id":1'));
  relay.send({ jsonrpc: '2.0', id: 2, method: 'tools/list' }, { jsonrpc: '2.0', method: 'notifications/initialized' });
  const lines = await relay.finish();
  assert.equal(launches, 1);
  assert.equal(sleeps, 10, 'one 1 s wait in 100 ms polls, then no more');
  assert.deepEqual(lines.map(line => line.id).sort(), [1, 2]);
  for (const line of lines) {
    assert.equal(line.error.code, NOT_RUNNING);
    assert.match(line.error.message, /Open SSBM Nucleus/);
  }
});

test('a 401 (the app restarted with a new token) rereads the discovery file and retries once', async t => {
  const file = tempFile(t);
  const app = await fakeApp(t, { token: 'new' });
  discovery.writeDiscovery(file, { port: app.port, token: 'old', pid: process.pid });
  const relay = harness({
    discoveryFile: file,
    request: async (target, body) => {
      if (target.token === 'old') discovery.writeDiscovery(file, { port: app.port, token: 'new', pid: process.pid });
      return require('../../app/electron/mcp/relay').post(target, body);
    },
  });
  relay.send({ jsonrpc: '2.0', id: 7, method: 'tools/list' });
  const lines = await relay.finish();
  assert.deepEqual(lines, [{ jsonrpc: '2.0', id: 7, result: { echo: 'tools/list' } }]);
  assert.deepEqual(app.seen.map(entry => entry.token), ['old', 'new']);
});

test('a refused connection (the app quit) looks for the app again', async t => {
  let launches = 0;
  let generation = 0;
  const endpoints = [
    { url: 'http://127.0.0.1:1/api/mcp', token: 'gone', pid: 1 },
    { url: 'http://127.0.0.1:2/api/mcp', token: 'fresh', pid: 2 },
  ];
  const relay = harness({
    discoveryFile: 'unused',
    launchApp: () => { launches += 1; generation = 1; },
    readEndpoint: () => endpoints[generation],
    request: async (target, body) => {
      if (target.token === 'gone') throw Object.assign(new Error('connect ECONNREFUSED'), { code: 'ECONNREFUSED' });
      return { status: 200, text: JSON.stringify({ jsonrpc: '2.0', id: JSON.parse(body).id, result: { at: target.token } }) };
    },
  });
  relay.send({ jsonrpc: '2.0', id: 3, method: 'ping' });
  const lines = await relay.finish();
  assert.equal(launches, 1);
  assert.deepEqual(lines, [{ jsonrpc: '2.0', id: 3, result: { at: 'fresh' } }]);
});

test('an app without the endpoint (404) or a non-JSON answer becomes a JSON-RPC error', async t => {
  let status = 404;
  const relay = harness({
    discoveryFile: 'unused',
    readEndpoint: () => ({ url: 'http://127.0.0.1:1/api/mcp', token: 't', pid: 1 }),
    request: async () => ({ status, text: status === 404 ? 'Not Found' : '<html>' }),
  });
  relay.send({ jsonrpc: '2.0', id: 1, method: 'ping' });
  await waitFor(() => relay.raw().includes('"id":1'));
  status = 500;
  relay.send({ jsonrpc: '2.0', id: 2, method: 'ping' });
  const lines = (await relay.finish()).sort((a, b) => a.id - b.id);
  assert.match(lines[0].error.message, /no MCP server/);
  assert.match(lines[1].error.message, /HTTP 500 without a JSON-RPC reply/);
});

test('discovery: written for a live loopback app, ignored when its process is gone, removed only by its writer', t => {
  const file = tempFile(t);
  discovery.writeDiscovery(file, { port: 5123, token: 'abc', pid: process.pid });
  assert.deepEqual(JSON.parse(fs.readFileSync(file, 'utf8')),
    { url: 'http://127.0.0.1:5123/api/mcp', token: 'abc', pid: process.pid });
  assert.deepEqual(discovery.readDiscovery(file), { url: 'http://127.0.0.1:5123/api/mcp', token: 'abc', pid: process.pid });
  assert.equal(discovery.readDiscovery(file, () => false), null, 'a dead pid means no app');
  fs.writeFileSync(file, JSON.stringify({ url: 'http://example.com/api/mcp', token: 'abc', pid: process.pid }));
  assert.equal(discovery.readDiscovery(file), null, 'only loopback endpoints');
  discovery.writeDiscovery(file, { port: 5123, token: 'abc', pid: process.pid });
  assert.equal(discovery.removeDiscovery(file, process.pid + 1), false);
  assert.ok(fs.existsSync(file));
  assert.equal(discovery.removeDiscovery(file, process.pid), true);
  assert.equal(fs.existsSync(file), false);
  assert.equal(discovery.readDiscovery(file), null);
  assert.equal(discovery.discoveryPath('C:/userdata', { NUCLEUS_MCP_DISCOVERY: 'X:/elsewhere.json' }), 'X:/elsewhere.json');
  assert.equal(discovery.discoveryPath('C:/userdata', {}), path.join('C:/userdata', 'mcp-endpoint.json'));
});

test('the --mcp Electron process starts no GPU and keeps no cache in the running app\'s folder', t => {
  // 0.9.0 smoke test: its Chromium printed "Unable to move the cache: Access is denied" and "Gpu Cache Creation
  // failed" to the AI client's stderr, opening the caches the running app holds.
  const { EventEmitter } = require('events');
  const { CACHE_DIR, runElectronRelay } = require('../../app/electron/mcp/relay');
  const saved = { ...console };
  t.after(() => Object.assign(console, saved));    // runElectronRelay sends console output to stderr
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-mcp-cache-'));
  t.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
  const ended = path.join(tmp, CACHE_DIR, '999999999');     // a relay that has ended left its folder
  fs.mkdirSync(path.join(ended, 'GPUCache'), { recursive: true });
  const calls = [];
  const app = {
    disableHardwareAcceleration: () => calls.push(['disableHardwareAcceleration']),
    commandLine: { appendSwitch: name => calls.push(['switch', name]) },
    setPath: (name, value) => calls.push(['setPath', name, value]),
    getPath: name => { assert.equal(name, 'userData'); return path.join(tmp, 'userData'); },
    exit: code => calls.push(['exit', code]),
  };
  const child = new EventEmitter();
  let spawned;
  runElectronRelay({ app, tmp, env: {}, spawn: (...args) => { spawned = args; return child; } });
  const own = path.join(tmp, CACHE_DIR, String(process.pid));
  assert.deepEqual(calls, [
    ['disableHardwareAcceleration'], ['switch', 'disable-gpu'], ['switch', 'disable-gpu-compositing'],
    ['switch', 'disable-gpu-shader-disk-cache'], ['switch', 'disable-http-cache'], ['setPath', 'sessionData', own],
  ], 'all before the relay starts, and userData (the discovery file) stays the app\'s');
  assert.equal(fs.existsSync(ended), false, 'an ended relay\'s folder is swept');
  assert.equal(fs.existsSync(own), true);
  assert.equal(spawned[2].env.NUCLEUS_MCP_RELAY_FILE, path.join(tmp, 'userData', 'mcp-endpoint.json'),
    'the relay still finds the app through userData');
  child.emit('exit', 0);
  assert.deepEqual(calls.at(-1), ['exit', 0]);
  assert.equal(fs.existsSync(own), false, 'its own folder goes when it ends');
});
