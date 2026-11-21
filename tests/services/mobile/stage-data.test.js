'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { gzipSync } = require('node:zlib');
const root = path.resolve(__dirname, '../../..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const url = name => pathToFileURL(path.join(root, name)).href;
const dataUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const replays = 'app/frontend/src/tracker/replays/';
let serial = 0;

async function setup(t, fetcher) {
  const values = new Map([['nucleus.vault.token', 'test-token']]);
  for (const [key, value] of Object.entries({ window: { __VAULT: { supabaseUrl: 'local:test', anonKey: 'test' } },
    localStorage: { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v), removeItem: k => values.delete(k) },
    fetch: fetcher })) {
    const before = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    t.after(() => before ? Object.defineProperty(globalThis, key, before) : delete globalThis[key]);
  }
  const cacheUrl = dataUrl(read(replays + 'stageData.js')
    .replace("'./data/stageCollision.json'", JSON.stringify(url(replays + 'data/stageCollision.json'))) + `\n// ${serial++}`);
  const account = dataUrl(read('services/mobile/src/account-generation.js') + `\n// ${serial}`);
  const worker = dataUrl(read('services/mobile/src/derive-worker.js')
    .replace('../../../app/frontend/src/tracker/replays/liteDeriver/index.js', url(replays + 'liteDeriver/index.js')));
  const apiUrl = dataUrl(read('services/mobile/src/api.js')
    .replace("'./account-generation'", JSON.stringify(account))
    .replace("'./derive-worker'", JSON.stringify(worker))
    .replace("'../../../app/frontend/src/tracker/replays/stageData.js'", JSON.stringify(cacheUrl)));
  return { api: await import(apiUrl), cache: await import(cacheUrl) };
}

test('phone clips wait for their stage, share concurrent loads, and never fetch small stages', async t => {
  let start, finish, calls = 0, settled = false;
  const started = new Promise(resolve => { start = resolve; });
  const { api, cache } = await setup(t, async (address, options) => {
    if (options) {
      const { content_hashes: [id] } = JSON.parse(options.body);
      return Response.json({ urls: { [id]: 'local:frames' } });
    }
    if (address === 'local:frames') return new Response(gzipSync(JSON.stringify({ meta: { stage: 10, n: 2 } })));
    assert.equal(address, 'stages/10.json');
    calls++;
    start();
    return new Promise(resolve => { finish = resolve; });
  });
  for (const id of [12, 8, 14, 30, 31, 32]) assert.equal(await api.ensureClipStageData(id), true);
  assert.equal(calls, 0);
  const clip = api.fetchClip('a').then(value => { settled = true; return value; });
  await started;
  const other = api.ensureClipStageData(10);
  assert.equal(settled, false);
  assert.equal(cache.stageDataFor(10), null);
  finish(Response.json(JSON.parse(read(replays + 'data/stages/10.json'))));
  assert.equal((await clip).bundle.meta.stage, 10);
  assert.equal(await other, true);
  assert.ok(cache.stageDataFor(10).sim);
  await api.fetchClip('b');
  assert.equal(calls, 1);
});

test('stage HTTP/JSON failures keep phone clips playable and permit retry', async t => {
  let attempts = 0;
  const { api, cache } = await setup(t, async (address, options) => {
    if (options) {
      const { content_hashes: [id] } = JSON.parse(options.body);
      return Response.json({ urls: { [id]: 'local:frames' } });
    }
    if (address === 'local:frames') return new Response(gzipSync(JSON.stringify({ meta: { stage: 23, n: 2 } })));
    assert.equal(address, 'stages/23.json');
    attempts++;
    if (attempts === 1) return new Response('', { status: 503 });
    if (attempts === 2) return new Response('invalid JSON');
    return Response.json(JSON.parse(read(replays + 'data/stages/23.json')));
  });
  for (const id of ['a', 'b']) {
    assert.equal((await api.fetchClip(id)).bundle.meta.stage, 23);
    assert.equal(cache.stageDataFor(23), null);
  }
  assert.equal((await api.fetchClip('c')).bundle.meta.stage, 23);
  assert.ok(cache.stageDataFor(23).movers);
  assert.equal(attempts, 3);
});
