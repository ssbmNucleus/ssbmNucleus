'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');
const { gzipSync, gunzipSync } = require('node:zlib');
const { replayBytes } = require('./raw-slp-fixture.cjs');

const root = path.resolve(__dirname, '../../..');
const src = path.join(root, 'services/mobile/src');
const read = (name) => fs.readFileSync(path.join(src, name), 'utf8');
const dataUrl = (s) => `data:text/javascript;base64,${Buffer.from(s).toString('base64')}`;
const workerUrl = dataUrl(read('derive-worker.js').replace(
  '../../../app/frontend/src/tracker/replays/liteDeriver/index.js',
  pathToFileURL(path.join(root, 'app/frontend/src/tracker/replays/liteDeriver/index.js')).href));
const gz = (value) => new Response(gzipSync(value instanceof Uint8Array ? value : JSON.stringify(value)));
let serial = 0;

async function setup(t, fetcher) {
  const values = new Map([['nucleus.vault.token', 'token'], ['nucleus.vault.generation', 'generation']]);
  const globals = {
    window: { __VAULT: { supabaseUrl: 'https://local.invalid', anonKey: 'local' } },
    localStorage: { getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) },
    Worker: undefined,
    fetch: fetcher || (() => { throw new Error('unexpected network'); }),
  };
  for (const [key, value] of Object.entries(globals)) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    t.after(() => original ? Object.defineProperty(globalThis, key, original) : delete globalThis[key]);
  }
  const id = serial++;
  const account = dataUrl(read('account-generation.js') + `\n// ${id}`);
  const apiUrl = dataUrl(read('api.js').replace("'./account-generation'", JSON.stringify(account))
    .replace("'./derive-worker'", JSON.stringify(workerUrl)) + `\n// ${id}`);
  const api = await import(apiUrl);
  const share = await import(dataUrl(read('share.js')
    .replace("'./api'", JSON.stringify(apiUrl))
    .replace("'../../../app/frontend/src/tracker/replays/litePaint'", JSON.stringify(dataUrl('export const P=[]')))
    .replace("'../../../app/frontend/src/tracker/replays/koFlight'", JSON.stringify(dataUrl('export const flightPoseState=()=>null')))
    .replace("'./ui'", JSON.stringify(dataUrl('export function toast(){}'))) + `\n// ${id}`));
  const viewer = await import(dataUrl(read('share-viewer.js')
    .replace(/import \{[\s\S]*?\} from [^\n]+/g, '') + `\n// ${id}`));
  return { api, share, viewer };
}

function reads(entry, sidecar, seen = []) {
  return async (url, options) => {
    seen.push(url);
    if (options) {
      const p = JSON.parse(options.body);
      assert.equal(p.action, 'urls');
      assert.equal(p.v, 2);
      return Response.json({ urls: { [p.content_hashes[0]]: entry } });
    }
    if (url === 'local:slp') return gz(replayBytes());
    if (url === 'local:conv') return typeof sidecar === 'function' ? sidecar() : gz(sidecar);
    if (url === 'local:frames') return gz({ meta: { n: 2, start_frame: -123 }, frames: {}, conversions: { legacy: true } });
    throw new Error(`unexpected network ${url}`);
  };
}

test('raw conversions fetched in parallel and merged without row translation', async (t) => {
  const conv = { 0: [{ start_frame: -122, end_frame: -120, hits: 4 }], 1: [] };
  const seen = [];
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const fallback = reads({ slp: 'local:slp', conv: 'local:conv' }, conv, seen);
  const { api } = await setup(t, async (url, opts) => {
    if (url === 'local:slp') { seen.push(url); return pending; }
    return fallback(url, opts);
  });
  const loading = api.fetchClip('hash');
  await new Promise((r) => setImmediate(r));
  assert.ok(seen.includes('local:conv') && seen.includes('local:slp'));
  release(gz(replayBytes()));
  const clip = await loading;
  assert.deepEqual(clip.bundle.conversions, conv);
  assert.equal(api.comboFrame(clip, -120), -122); // rollbacks affect combos only
  assert.equal(clip.bundle.conversions[0][0].start_frame, -122);
});

for (const [name, sidecar] of [
  ['absent', undefined], ['404', () => new Response('', { status: 404 })],
  ['corrupt gzip', () => new Response('bad gzip')], ['bad JSON', () => new Response(gzipSync('{'))],
  ['wrong shape', { 0: [] }], ['network failure', () => { throw new Error('offline'); }],
]) test(`sidecar ${name} preserves raw playback and percent fallback`, async (t) => {
  const { api } = await setup(t, reads({ slp: 'local:slp', ...(name === 'absent' ? {} : { conv: 'local:conv' }) }, sidecar));
  const clip = await api.fetchClip('hash');
  assert.equal(clip.source, 'slp');
  assert.equal(clip.bundle.conversions, null);
});

test('successful zero-conversion sidecar disables heuristic', async (t) => {
  const conv = { 0: [], 1: [] };
  const { api } = await setup(t, reads({ slp: 'local:slp', conv: 'local:conv' }, conv));
  assert.deepEqual((await api.fetchClip('hash')).bundle.conversions, conv);
});

test('frames path does not fetch or merge true-frame sidecars', async (t) => {
  const seen = [];
  const { api } = await setup(t, reads({ frames: 'local:frames', conv: 'local:conv' }, {}, seen));
  const clip = await api.fetchClip('hash');
  assert.equal(clip.source, 'frames');
  assert.deepEqual(clip.bundle.conversions, { legacy: true });
  assert.ok(!seen.includes('local:conv'));
});

test('a share is mint-only: no replay fetched, nothing uploaded', async (t) => {
  const seen = [];
  const { share } = await setup(t, async (url, opts) => {
    seen.push(url);
    assert.ok(url.endsWith('/vault-public'), `unexpected network ${url}`);
    assert.equal(JSON.parse(opts.body).action, 'mint');
    return Response.json({ id: '0123456789ab', created: true });
  });
  assert.equal(await share.shareUrl('hash', 2), 'https://ssbmnucleus.net/replay/0123456789ab/combo/2');
  assert.equal(seen.length, 1);
  assert.equal(share.putShareSnapshot, undefined);
});

test('a raw share page plays the .slp through the vault deriver, combos on its row map', async (t) => {
  const { api, viewer } = await setup(t);
  const { deriveClip } = await import(workerUrl);
  const clip = { ...deriveClip(replayBytes()), source: 'slp' };
  const conv = { 0: [{ start_frame: -122, end_frame: -120, hits: 4 }], 1: [] };
  const bytes = new Uint8Array(replayBytes());
  assert.equal(api.isSlp(bytes), true);
  const bundle = await api.shareBundle(bytes, conv);
  assert.equal(bundle.meta.finalized, true);
  assert.deepEqual(Array.from(bundle.meta.row_fids), Array.from(clip.rowFids));
  assert.equal(bundle.meta.row_first, clip.firstFrame);
  assert.deepEqual(bundle.conversions, conv);    // TRUE frames, merged as-is
  for (const f of [-999, -123, -120, -119, 9000]) {
    assert.equal(viewer.snapshotComboFrame(bundle, f), api.comboFrame(clip, f));
  }
});

test('a share of a game uploaded before raw replays still plays its frames file', async (t) => {
  const { api, viewer } = await setup(t);
  const frames = { meta: { n: 2, start_frame: -123 }, frames: {}, conversions: { legacy: true } };
  for (const body of [frames, { bundle: frames }]) {
    const bytes = new Uint8Array(Buffer.from(JSON.stringify(body)));
    assert.equal(api.isSlp(bytes), false);
    const bundle = await api.shareBundle(bytes, { 0: [], 1: [] });
    assert.deepEqual(bundle, frames);              // its own conversions, untouched
    assert.equal(viewer.snapshotComboFrame(bundle, -100), -100);
  }
});
test('frames shares keep mint-only path; concurrent different hashes stay separate', async (t) => {
  const calls = [];
  const { share } = await setup(t, async (url, opts) => {
    const p = JSON.parse(opts.body);
    assert.equal(p.action, 'mint');
    calls.push(p.content_hash);
    return Response.json({ id: p.content_hash, created: false });
  });
  const urls = await Promise.all([share.shareUrl('one'), share.shareUrl('two'), share.shareUrl('one', 1)]);
  assert.deepEqual(calls, ['one', 'two']);
  assert.deepEqual(urls, ['https://ssbmnucleus.net/replay/one', 'https://ssbmnucleus.net/replay/two', 'https://ssbmnucleus.net/replay/one/combo/1']);
});

test('account change during mint refuses the link', async (t) => {
  let api;
  const modules = await setup(t, async () => {
    api.setToken('different');
    return Response.json({ id: '0123456789ab' });
  });
  api = modules.api;
  await assert.rejects(modules.share.shareUrl('hash'), /account changed/);
});

test('public snapshot combo mapping matches api including clamps and keeps legacy frames', async (t) => {
  const { api, viewer } = await setup(t);
  const { deriveClip } = await import(workerUrl);
  const clip = { ...deriveClip(replayBytes()), source: 'slp' };
  const bundle = { ...clip.bundle, meta: { ...clip.bundle.meta,
    row_fids: Array.from(clip.rowFids), row_first: clip.firstFrame } };
  for (const f of [-999, -123, -120, -119, 9000]) {
    assert.equal(viewer.snapshotComboFrame(bundle, f), api.comboFrame(clip, f));
    assert.equal(viewer.snapshotComboFrame({ meta: { start_frame: -123 } }, f), f);
  }
  assert.throws(() => viewer.snapshotComboFrame({ meta: { finalized: true } }, 0), /missing row frame map/);
  // Both the selected clip and combo list timestamps use the same mapping.
  const publicSource = read('public-viewer.js');
  assert.match(publicSource, /snapshotComboFrame\(bundle, combo.start_frame/);
  assert.match(publicSource, /snapshotComboFrame\(bundle, combo.end_frame/);
  assert.match(publicSource, /start_frame: snapshotComboFrame\(bundle, c.start_frame\)/);
});
