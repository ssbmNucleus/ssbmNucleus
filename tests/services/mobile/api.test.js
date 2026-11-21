'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');
const { gzipSync } = require('node:zlib');
const { replayBytes } = require('./raw-slp-fixture.cjs');

const root = path.resolve(__dirname, '../../..');
const src = path.join(root, 'services/mobile/src');
const dataUrl = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const accountUrl = dataUrl(fs.readFileSync(path.join(src, 'account-generation.js'), 'utf8'));
const deriverUrl = pathToFileURL(path.join(root, 'app/frontend/src/tracker/replays/liteDeriver/index.js')).href;
const workerSource = fs.readFileSync(path.join(src, 'derive-worker.js'), 'utf8')
  .replace('../../../app/frontend/src/tracker/replays/liteDeriver/index.js', deriverUrl);
const workerUrl = dataUrl(workerSource);
const apiSource = fs.readFileSync(path.join(src, 'api.js'), 'utf8')
  .replace("'./account-generation'", JSON.stringify(accountUrl))
  .replace("'./derive-worker'", JSON.stringify(workerUrl));
let nextModule = 0;
let deriveClip;

const json = (value) => Response.json(value);
const gz = (value) => new Response(gzipSync(typeof value === 'string' || value instanceof Uint8Array
  ? value : JSON.stringify(value)));
const frames = () => ({ meta: { v: 4, start_frame: -123, n: 4 }, frames: {}, conversions: {} });

test.before(async () => { ({ deriveClip } = await import(workerUrl)); });

async function freshApi(t, fetcher, Worker) {
  const values = new Map([['nucleus.vault.token', 'local-test-token'], ['nucleus.vault.generation', 'local']]);
  const overrides = {
    window: { __VAULT: { supabaseUrl: 'http://127.0.0.1:1', anonKey: 'local' } },
    localStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
    // Never let a missing stub fall through to the real network.
    fetch: fetcher || (() => { throw new Error('unexpected network request'); }),
    Worker,
  };
  for (const [key, value] of Object.entries(overrides)) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    t.after(() => descriptor
      ? Object.defineProperty(globalThis, key, descriptor) : delete globalThis[key]);
  }
  return import(dataUrl(`${apiSource}\n// fresh module ${nextModule++}`));
}

function clipFetch(entry, requests, raw = replayBytes(), legacy = frames()) {
  return async (url, options) => {
    requests.push({ url, payload: options && JSON.parse(options.body) });
    if (options) {
      const body = JSON.parse(options.body);
      assert.equal(body.action, 'urls');
      assert.equal(body.v, 2);
      assert.equal(body.token, 'local-test-token');
      return json({ urls: { [body.content_hashes[0]]: entry } });
    }
    if (url === 'local:slp') return gz(raw);
    if (url === 'local:frames') return gz(legacy);
    throw new Error(`unexpected URL ${url}`);
  };
}

test('list v2 keeps raw-only rows across keyset pages and direct vaultRead', async (t) => {
  const requests = [];
  const rawOnly = { id: 2, content_hash: 'raw', object_key: null, slp_key: 'raw.slp.gz' };
  const old = { id: 1, content_hash: 'frames', object_key: 'frames.json.gz' };
  const api = await freshApi(t, async (url, options) => {
    const p = JSON.parse(options.body);
    requests.push(p);
    assert.equal(p.v, 2);
    return json(p.before ? { games: [old] } : { games: [rawOnly], next_before: 2 });
  });
  const pages = [];
  const lib = await api.fetchLibrary((n) => pages.push(n));
  assert.deepEqual(lib.games, [rawOnly, old]);
  assert.deepEqual(pages, [1, 2]);
  assert.deepEqual(requests.map((p) => p.before), [null, 2]);
  assert.ok(requests.every((p) => p.token === 'local-test-token'));
  await api.vaultRead({ action: 'list' });
  assert.equal(requests.length, 3);
});

for (const [label, entry, wrapped] of [
  ['v2', { frames: 'local:frames' }, false],
  ['old flat', 'local:frames', false],
  ['wrapped old bundle', 'local:frames', true],
]) test(`urls ${label} uses the unchanged gzip frames path`, async (t) => {
  const requests = [], b = frames();
  const api = await freshApi(t, clipFetch(entry, requests, undefined, wrapped ? { bundle: b } : b));
  assert.deepEqual(await api.fetchClip('hash'), { bundle: b, source: 'frames' });
  assert.equal(requests.length, 2);
});

test('raw is preferred, inflated before Worker, and rows survive structured clone', async (t) => {
  const requests = [], workers = [];
  class Worker {
    constructor(url) { this.url = url; workers.push(this); }
    postMessage(bytes, transfer) {
      assert.deepEqual(bytes, replayBytes());
      assert.deepEqual(transfer, [bytes.buffer]);
      const copy = structuredClone(bytes, { transfer });
      queueMicrotask(() => this.onmessage({ data: structuredClone(deriveClip(copy)) }));
    }
    terminate() { this.terminated = true; }
  }
  const api = await freshApi(t, clipFetch({ slp: 'local:slp', frames: 'local:frames' }, requests), Worker);
  const clip = await api.fetchClip('hash');
  assert.equal(clip.source, 'slp');
  assert.equal(clip.bundle.meta.finalized, true);
  assert.equal(clip.bundle.meta.n, 4);
  assert.equal(clip.firstFrame, -123);
  assert.deepEqual([...clip.rowFids], [-123, -122, -121, -122, -121, -120]);
  assert.equal(clip.bundle.conversions, null);
  assert.deepEqual(requests.map((r) => r.url).slice(1), ['local:slp']);
  assert.equal(workers[0].terminated, true);
});

for (const mode of ['absent', 'constructor', 'post', 'error', 'messageerror', 'reported', 'invalid', 'timeout']) {
  test(`Worker ${mode} failure derives on the main thread with intact bytes`, async (t) => {
    const requests = [], workers = [];
    class Worker {
      constructor() {
        if (mode === 'constructor') throw new Error('blocked');
        workers.push(this);
      }
      postMessage(bytes, transfer) {
        structuredClone(bytes, { transfer }); // detach, as an actual browser does
        if (mode === 'post') throw new Error('clone failed');
        queueMicrotask(() => {
          if (mode === 'error') this.onerror({ message: 'worker failed', preventDefault() {} });
          if (mode === 'messageerror') this.onmessageerror();
          if (mode === 'reported') this.onmessage({ data: { error: 'derive failed' } });
          if (mode === 'invalid') this.onmessage({ data: {} });
        });
      }
      terminate() { this.terminated = true; }
    }
    if (mode === 'timeout') {
      const timer = globalThis.setTimeout;
      t.mock.method(globalThis, 'setTimeout', (fn, ms) => timer(fn, ms === 30000 ? 1 : ms));
    }
    const api = await freshApi(t, clipFetch({ slp: 'local:slp' }, requests), mode === 'absent' ? undefined : Worker);
    const clip = await api.fetchClip('hash');
    assert.equal(clip.source, 'slp');
    assert.equal(clip.bundle.meta.n, 4);
    assert.deepEqual([...clip.rowFids], [-123, -122, -121, -122, -121, -120]);
    assert.ok(workers.every((worker) => worker.terminated));
  });
}

for (const mode of ['http', 'gzip', 'parse', 'empty']) {
  test(`raw ${mode} failure falls back to available frames`, async (t) => {
    const requests = [];
    const fetcher = clipFetch({ slp: 'local:slp', frames: 'local:frames' }, requests,
      mode === 'empty' ? replayBytes([]) : new Uint8Array([1, 2, 3]));
    const api = await freshApi(t, (url, opts) => {
      if (url === 'local:slp' && mode === 'http') return new Response('', { status: 404 });
      if (url === 'local:slp' && mode === 'gzip') return new Response('not gzip');
      return fetcher(url, opts);
    });
    assert.deepEqual(await api.fetchClip('hash'), { bundle: frames(), source: 'frames' });
  });
}

test('missing urls and corrupt raw-only clips reject and failed requests can retry', async (t) => {
  let count = 0;
  const api = await freshApi(t, async (url, options) => {
    if (options) {
      count++;
      return json({ urls: { hash: count === 1 ? {} : { slp: 'local:slp' } } });
    }
    return gz(new Uint8Array([1, 2, 3]));
  });
  await assert.rejects(api.fetchClip('hash'), /clip not in vault/);
  await assert.rejects(api.fetchClip('hash'));
  await assert.rejects(api.fetchClip('hash'));
  assert.equal(count, 3);
});

test('one helper translates both combo endpoints through rollback rows and clamps table ends', async (t) => {
  const api = await freshApi(t);
  const raw = { ...deriveClip(replayBytes()), source: 'slp' };
  assert.equal(api.comboFrame(raw, -120), -122);
  assert.equal(api.comboFrame(raw, -118), -120);
  assert.equal(api.comboFrame(raw, -999), -123);
  assert.equal(api.comboFrame(raw, 999), -120);
  // Explicit firstFrame must win if the bundle is subsequently windowed.
  raw.bundle.meta.start_frame = -121;
  assert.equal(api.comboFrame(raw, -120), -122);
  const combo = { start_frame: -120, end_frame: -118 };
  assert.deepEqual([api.comboFrame(raw, combo.start_frame), api.comboFrame(raw, combo.end_frame)], [-122, -120]);
  assert.deepEqual(combo, { start_frame: -120, end_frame: -118 });
  assert.equal(api.comboFrame({ ...raw, source: 'frames' }, 999), 999);
  raw.bundle.meta.finalized = false;
  assert.equal(api.comboFrame(raw, -120), -120);
});

test('LRU deduplicates pending requests, promotes hits, and retains at most four games', async (t) => {
  const reads = [];
  const api = await freshApi(t, async (url, options) => {
    if (options) {
      const hash = JSON.parse(options.body).content_hashes[0];
      reads.push(hash);
      return json({ urls: { [hash]: 'local:frames' } });
    }
    return gz(frames());
  });
  const first = api.fetchClip('a');
  assert.equal(api.fetchClip('a'), first);
  await first;
  for (const hash of ['b', 'c', 'd', 'a', 'e', 'a', 'c', 'd', 'e']) await api.fetchClip(hash);
  assert.deepEqual(reads, ['a', 'b', 'c', 'd', 'e']);
  await api.fetchClip('b'); // least-recently-used b was evicted by e
  assert.deepEqual(reads, ['a', 'b', 'c', 'd', 'e', 'b']);
  await api.fetchClip('a'); // b evicted a, the oldest of the four survivors
  assert.equal(reads.at(-1), 'a');
  assert.equal(reads.length, 7);
});

test('a late failure of an evicted request cannot evict its replacement', async (t) => {
  let rejectOld, aReads = 0;
  const api = await freshApi(t, async (url, options) => {
    if (options) {
      const hash = JSON.parse(options.body).content_hashes[0];
      if (hash === 'a' && ++aReads === 1) return new Promise((resolve, reject) => { rejectOld = reject; });
      return json({ urls: { [hash]: 'local:frames' } });
    }
    return gz(frames());
  });
  const old = api.fetchClip('a');
  const rejection = assert.rejects(old, /old request failed/);
  for (const hash of ['b', 'c', 'd', 'e']) await api.fetchClip(hash);
  const newer = api.fetchClip('a');
  await newer;
  rejectOld(new Error('old request failed'));
  await rejection;
  assert.equal(api.fetchClip('a'), newer);
  assert.equal(aReads, 2);
});

test('empty raw conversions engage the existing percent-delta overlay without changing its code', async (t) => {
  const api = await freshApi(t, clipFetch({ slp: 'local:slp' }, []));
  const { bundle } = await api.fetchClip('hash');
  const overlaySource = fs.readFileSync(path.join(src, 'overlays.js'), 'utf8')
    .replace(/import \{ pcolor \} from '[^']+'/, "const pcolor = () => '#fff'")
    .replace(/import \{ stateLabel, moveName \} from '[^']+'/, 'const stateLabel = String, moveName = String')
    .replace(/import \{ sheet, sheetRow \} from '[^']+'/, 'const sheet = () => {}, sheetRow = () => {}');
  const { paintOverlays } = await import(dataUrl(overlaySource));
  const texts = [];
  const ctx = new Proxy({
    measureText: (text) => ({ width: text.length * 5 }),
    fillText: (text) => texts.push(text),
  }, { get: (obj, key) => obj[key] || (() => {}) });
  paintOverlays(ctx, bundle, 2, 500, 400);
  assert.ok(texts.some((s) => s.includes('2 hits')), JSON.stringify(texts));
});
