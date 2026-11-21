// nucleus-bugreport: report kinds, the chat ping, mobile chat reports and CORS.
// Runs on plain Node (>= 20): an in-memory R2 stand-in and a fetch stub for
// the release manifest and the Discord webhook. Nothing leaves the process.
import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { buildEmbed, cleanMeta, compareVersions } from '../../../services/cloudflare/bugreport-worker/src/index.js';

const WEBHOOK = 'https://discord.example/api/webhooks/1/test';
const ORIGIN = 'https://ssbmnucleus.net';

class MemoryR2 {
  constructor() { this.objects = new Map(); }
  async put(key, value, options = {}) {
    let bytes;
    if (typeof value === 'string') bytes = new TextEncoder().encode(value);
    else if (value instanceof Uint8Array) bytes = value;
    else bytes = new Uint8Array(await new Response(value).arrayBuffer());
    this.objects.set(key, { bytes, options });
  }
  async get(key, opts = {}) {
    const hit = this.objects.get(key);
    if (!hit) return null;
    const bytes = opts.range ? hit.bytes.slice(opts.range.offset, opts.range.offset + opts.range.length) : hit.bytes;
    return {
      customMetadata: hit.options.customMetadata || {},
      httpEtag: '"etag"',
      body: new Blob([bytes]).stream(),
      async json() { return JSON.parse(new TextDecoder().decode(bytes)); },
      async arrayBuffer() { return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength); },
      async blob() { return new Blob([bytes]); },
      writeHttpMetadata(headers) { if (hit.options.httpMetadata?.contentType) headers.set('content-type', hit.options.httpMetadata.contentType); },
    };
  }
  async delete(key) { this.objects.delete(key); }
  async list({ prefix = '', include } = {}) {
    const objects = [...this.objects.entries()].filter(([k]) => k.startsWith(prefix)).map(([key, v]) => ({
      key, size: v.bytes.length, uploaded: new Date('2026-09-25T00:00:00Z'), customMetadata: v.options.customMetadata || {} }));
    return { objects, truncated: false };
  }
}

function env(extra = {}) {
  return { REPORTS: new MemoryR2(), RELEASES_BASE: 'https://releases.example', DISCORD_WEBHOOK_URL: WEBHOOK,
    LINK_SIGNING_SECRET: 'x'.repeat(32), SUPABASE_URL: 'https://supabase.example', SUPABASE_ANON_KEY: 'anon', ...extra };
}

// A fetch stub: the latest.json manifest per channel, a capture of Discord
// posts, and the Supabase identity RPC (answered with `identity`).
function stubFetch({ latest = { windows: '0.9.1' }, identity = null } = {}) {
  const calls = { manifest: [], discord: [], rpc: [] };
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    const u = String(url);
    if (u.startsWith('https://supabase.example/rest/v1/rpc/')) {
      calls.rpc.push({ name: u.split('/').pop(), auth: init.headers?.authorization });
      return identity ? Response.json(identity) : new Response('{}', { status: 401 });
    }
    if (u.startsWith('https://releases.example/')) {
      const channel = u.split('/')[3];
      calls.manifest.push(channel);
      if (!latest[channel]) return new Response('nope', { status: 404 });
      return Response.json({ version: latest[channel], platforms: { x: { url: `https://dl.example/${channel}.exe` } } });
    }
    if (u.startsWith(WEBHOOK)) {
      let payload;
      if (init.body instanceof FormData) {
        payload = JSON.parse(init.body.get('payload_json'));
        payload.file = init.body.get('files[0]')?.name;
      } else payload = JSON.parse(init.body);
      calls.discord.push(payload);
      return new Response('{}', { status: 200 });
    }
    throw new Error(`unexpected fetch ${u}`);
  };
  return { calls, restore: () => { globalThis.fetch = original; } };
}

// A minimal valid zip body ("PK" magic is all the worker checks).
const ZIP = new Uint8Array([0x50, 0x4b, 0x05, 0x06, ...new Array(18).fill(0)]);

async function file(e, meta, headers = {}) {
  const created = await worker.fetch(new Request(`${ORIGIN}/bugreport`, {
    method: 'POST', headers: { 'content-type': 'application/json', 'cf-connecting-ip': '203.0.113.9', ...headers },
    body: JSON.stringify({ zip_size: ZIP.length, ...meta }),
  }), e);
  const body = await created.json();
  if (created.status !== 200) return { status: created.status, body };
  const put = await worker.fetch(new Request(`${ORIGIN}/bugreport/${body.id}/zip`, {
    method: 'PUT', headers: { 'content-type': 'application/zip', 'content-length': String(ZIP.length) }, body: ZIP,
  }), e);
  return { status: put.status, body: await put.json(), id: body.id };
}

const chatMeta = {
  kind: 'chat', platform: 'windows', app_version: '0.9.1', description: 'It forgot my Falco',
  chat: { surface: 'tracker', message_count: 12, tool_calls: 4, errors: 1, conversation_id: '42', model: 'minimax' },
};

test('absent kind is a bug report, exactly as before', () => {
  const { meta } = cleanMeta({ platform: 'windows', app_version: '0.9.1', description: 'x', zip_size: 10 }, {});
  assert.equal(meta.kind, 'bug');
  assert.equal(meta.chat, undefined);
  const embed = buildEmbed({ ...meta, id: 'a'.repeat(32), size: 10, gate: 'ok', stored: 0, renderer_errors: [] });
  assert.equal(embed.title, 'v0.9.1 · windows');
  assert.ok(embed.fields.some((f) => f.name === 'Renderer errors'));
});

test('unknown kinds are filed as bugs, not refused', () => {
  const { meta, error } = cleanMeta({ kind: 'mystery', platform: 'mac', app_version: '1.0.0', description: 'x', zip_size: 1 }, {});
  assert.equal(error, undefined);
  assert.equal(meta.kind, 'bug');
});

test('a chat report posts a chat-labelled ping with the note and message count', async () => {
  const f = stubFetch();
  try {
    const e = env();
    const res = await file(e, chatMeta);
    assert.equal(res.status, 200);
    assert.equal(res.body.notified, true);
    const [ping] = f.calls.discord;
    assert.equal(ping.username, 'Nucleus chat reports');
    const [embed] = ping.embeds;
    assert.match(embed.title, /^💬 Randall chat report · v0\.9\.1 · windows$/);
    assert.equal(embed.description, 'It forgot my Falco');
    const field = (name) => embed.fields.find((x) => x.name === name)?.value;
    assert.equal(field('Messages'), '12');
    assert.equal(field('Surface'), 'tracker');
    assert.equal(field('Tool calls'), '4');
    assert.equal(field('Model'), 'minimax');
    assert.equal(ping.file, `chatreport-${res.id.slice(0, 8)}.zip`);
    // The stored meta and the zip's R2 metadata both remember the kind.
    const stored = [...e.REPORTS.objects.entries()];
    const metaJson = JSON.parse(new TextDecoder().decode(stored.find(([k]) => k.endsWith('meta.json'))[1].bytes));
    assert.equal(metaJson.kind, 'chat');
    assert.equal(metaJson.chat.message_count, 12);
    assert.equal(stored.find(([k]) => k.endsWith('report.zip'))[1].options.customMetadata.kind, 'chat');
  } finally { f.restore(); }
});

test('a chat report with no note still files', async () => {
  const f = stubFetch();
  try {
    const res = await file(env(), { ...chatMeta, description: '' });
    assert.equal(res.status, 200);
    assert.equal(f.calls.discord[0].embeds[0].description, '(no note)');
  } finally { f.restore(); }
});

test('a signed-in report carries the Discord names from bugreport_identity', async () => {
  const uid = '0f0e0d0c-0b0a-4908-8706-050403020100';
  const f = stubFetch({ identity: { user_id: uid.toUpperCase(),
    profile: { discord_username: 'falcoplayer', display_name: 'Falco Player' } } });
  try {
    const e = env();
    const token = 't'.repeat(40);
    const res = await file(e, chatMeta, { authorization: `Bearer ${token}` });
    assert.equal(res.status, 200);
    assert.deepEqual(f.calls.rpc, [{ name: 'bugreport_identity', auth: `Bearer ${token}` }]);
    const stored = [...e.REPORTS.objects.entries()];
    const metaJson = JSON.parse(new TextDecoder().decode(stored.find(([k]) => k.endsWith('meta.json'))[1].bytes));
    assert.deepEqual(metaJson.reporter, { uid, discord_username: 'falcoplayer', display_name: 'Falco Player' });
  } finally { f.restore(); }
});

test('a rejected or banned identity files the report anonymously', async () => {
  for (const identity of [null, { user_id: null, banned: true }]) {
    const f = stubFetch({ identity });
    try {
      const e = env();
      const res = await file(e, chatMeta, { authorization: `Bearer ${'t'.repeat(40)}` });
      assert.equal(res.status, 200);
      const stored = [...e.REPORTS.objects.entries()];
      const metaJson = JSON.parse(new TextDecoder().decode(stored.find(([k]) => k.endsWith('meta.json'))[1].bytes));
      assert.equal(metaJson.reporter, null);
    } finally { f.restore(); }
  }
});

test('a bug report still requires a description', () => {
  const { error } = cleanMeta({ platform: 'windows', app_version: '0.9.1', description: '', zip_size: 1 }, {});
  assert.equal(error, 'bad description');
});

test('the version gate refuses an outdated chat report with 426', async () => {
  // A channel no earlier test touched: the worker caches manifests per isolate.
  const f = stubFetch({ latest: { linux: '0.9.4' } });
  try {
    const res = await file(env(), { ...chatMeta, platform: 'linux' });
    assert.equal(res.status, 426);
    assert.equal(res.body.latest, '0.9.4');
    assert.equal(res.body.url, 'https://dl.example/linux.exe');
    assert.equal(f.calls.discord.length, 0);
  } finally { f.restore(); }
});

test('mobile is accepted for chat reports only, and skips the gate', async () => {
  const f = stubFetch();
  try {
    const mobile = { ...chatMeta, platform: 'mobile', chat: { ...chatMeta.chat, surface: 'mobile' } };
    const res = await file(env(), mobile);
    assert.equal(res.status, 200);
    assert.deepEqual(f.calls.manifest, []);
    const embed = f.calls.discord[0].embeds[0];
    assert.equal(embed.fields.find((x) => x.name === 'Version gate').value, 'n/a (mobile)');
    assert.equal(embed.fields.find((x) => x.name === 'Surface').value, 'mobile');
    const bug = await file(env(), { platform: 'mobile', app_version: '0.9.1', description: 'x' });
    assert.equal(bug.status, 400);
    assert.equal(bug.body.error, 'bad platform');
  } finally { f.restore(); }
});

test('chat fields are bounded and typed', () => {
  const { meta } = cleanMeta({ ...chatMeta, zip_size: 5, chat: {
    surface: '<script>', message_count: '12', tool_calls: -1, conversation_id: 'x'.repeat(500), model: 'm'.repeat(500) } }, {});
  assert.equal(meta.chat.surface, 'unknown');
  assert.equal(meta.chat.message_count, null);
  assert.equal(meta.chat.tool_calls, null);
  assert.equal(meta.chat.conversation_id.length, 64);
  assert.equal(meta.chat.model.length, 80);
});

test('CORS preflight is answered for the create and upload routes', async () => {
  for (const path of ['/bugreport', `/bugreport/${'a'.repeat(32)}/zip`]) {
    const res = await worker.fetch(new Request(`${ORIGIN}${path}`, {
      method: 'OPTIONS', headers: { origin: 'https://nucleus-vault-3ds.pages.dev', 'access-control-request-method': 'PUT' },
    }), env());
    assert.equal(res.status, 204);
    assert.equal(res.headers.get('access-control-allow-origin'), '*');
    assert.match(res.headers.get('access-control-allow-methods'), /PUT/);
    assert.match(res.headers.get('access-control-allow-headers'), /content-type/);
  }
});

test('the feature-request kind wishes already send gets its own label', () => {
  const { meta } = cleanMeta({ kind: 'capability_gap', platform: 'windows', app_version: '0.9.1', description: 'x', zip_size: 1 }, {});
  const embed = buildEmbed({ ...meta, id: 'a'.repeat(32), size: 1, gate: 'ok', stored: 0 });
  assert.match(embed.title, /feature request/);
});

const put = (e, id) => worker.fetch(new Request(`${ORIGIN}/bugreport/${id}/zip`, {
  method: 'PUT', headers: { 'content-type': 'application/zip', 'content-length': String(ZIP.length) }, body: ZIP,
}), e);

test('re-uploading a stored report answers from its receipt, not 404', async () => {
  const f = stubFetch();
  try {
    const e = env();
    const res = await file(e, chatMeta);
    assert.equal(res.status, 200);
    assert.ok(!e.REPORTS.objects.has(`s/${res.id}`));
    // The first reply was lost; the client retries into the same id.
    const again = await put(e, res.id);
    assert.equal(again.status, 200);
    assert.deepEqual(await again.json(), { ok: true, id: res.id, notified: true, already_stored: true });
    assert.equal(f.calls.discord.length, 1);                       // no second ping
    assert.equal([...e.REPORTS.objects.keys()].filter((k) => k.endsWith('report.zip')).length, 1);
  } finally { f.restore(); }
});

test('an expired slot is 410 once, then 404, and never a receipt', async () => {
  const f = stubFetch();
  try {
    const e = env();
    const created = await worker.fetch(new Request(`${ORIGIN}/bugreport`, {
      method: 'POST', headers: { 'content-type': 'application/json', 'cf-connecting-ip': '203.0.113.9' },
      body: JSON.stringify({ zip_size: ZIP.length, ...chatMeta }),
    }), e);
    const { id } = await created.json();
    const slot = JSON.parse(new TextDecoder().decode(e.REPORTS.objects.get(`s/${id}`).bytes));
    await e.REPORTS.put(`s/${id}`, JSON.stringify({ ...slot, created: slot.created - 2 * 60 * 60 * 1000 }));
    assert.equal((await put(e, id)).status, 410);
    // That 410 can be lost too: the next retry must NOT look delivered.
    assert.equal((await put(e, id)).status, 404);
    assert.ok(!e.REPORTS.objects.has(`d/${id}`));
    assert.equal(f.calls.discord.length, 0);
  } finally { f.restore(); }
});

test('a preview build version is accepted', () => {
  const { meta, error } = cleanMeta({ kind: 'chat', platform: 'windows', app_version: '0.9.0-preview.7', description: 'x', zip_size: 1 }, {});
  assert.equal(error, undefined);
  assert.equal(meta.app_version, '0.9.0-preview.7');
  assert.equal(cleanMeta({ platform: 'windows', app_version: '0.9.0-', description: 'x', zip_size: 1 }, {}).error, 'bad version');
  assert.equal(cleanMeta({ platform: 'windows', app_version: '0.9.0-pre view', description: 'x', zip_size: 1 }, {}).error, 'bad version');
});

test('a prerelease is older than its release and newer than the one before', () => {
  assert.equal(compareVersions('0.9.0-preview.7', '0.8.9'), 1);
  assert.equal(compareVersions('0.9.0-preview.7', '0.9.0'), -1);
  assert.equal(compareVersions('0.9.0', '0.9.0-preview.7'), 1);
  assert.equal(compareVersions('0.9.0-preview.7', '0.9.0-preview.3'), 0);
  assert.equal(compareVersions('0.9.1', '0.9.0'), 1);
});


const ADMIN = 'a'.repeat(40);
function adminReq(path, token = ADMIN) {
  return new Request(`${ORIGIN}${path}`, { headers: token ? { authorization: `Bearer ${token}` } : {} });
}

test('admin routes do not exist without ADMIN_TOKEN, and refuse a wrong token', async () => {
  const e = env();
  assert.equal((await worker.fetch(adminReq('/bugreport/admin/list'), e)).status, 404);
  const e2 = env({ ADMIN_TOKEN: ADMIN });
  assert.equal((await worker.fetch(adminReq('/bugreport/admin/list', 'b'.repeat(40)), e2)).status, 401);
  assert.equal((await worker.fetch(adminReq('/bugreport/admin/list', null), e2)).status, 401);
});

test('admin lists recent reports by kind and fetches meta and zip', async () => {
  const e = env({ ADMIN_TOKEN: ADMIN });
  const d = new Date();
  const day = `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, '0')}${String(d.getUTCDate()).padStart(2, '0')}`;
  const id = 'c'.repeat(32), id2 = 'd'.repeat(32);
  await e.REPORTS.put(`r/${day}/${id}/meta.json`, JSON.stringify({ kind: 'chat' }), { customMetadata: { kind: 'chat', platform: 'windows', app_version: '0.9.0-preview.7' } });
  await e.REPORTS.put(`r/${day}/${id}/report.zip`, new Uint8Array([80, 75, 3, 4]), { customMetadata: { kind: 'chat' } });
  await e.REPORTS.put(`r/${day}/${id2}/meta.json`, JSON.stringify({ kind: 'bug' }), { customMetadata: { kind: 'bug', platform: 'windows', app_version: '0.8.9' } });
  const all = await (await worker.fetch(adminReq('/bugreport/admin/list?days=2'), e)).json();
  assert.equal(all.reports.length, 2);
  const chats = await (await worker.fetch(adminReq('/bugreport/admin/list?days=2&kind=chat'), e)).json();
  assert.deepEqual(chats.reports.map((r) => [r.id, r.kind, r.app_version]), [[id, 'chat', '0.9.0-preview.7']]);
  const meta = await worker.fetch(adminReq(`/bugreport/admin/${day}/${id}/meta`), e);
  assert.equal((await meta.json()).kind, 'chat');
  const zip = await worker.fetch(adminReq(`/bugreport/admin/${day}/${id}/zip`), e);
  assert.equal(new Uint8Array(await zip.arrayBuffer())[0], 80);
  assert.equal((await worker.fetch(adminReq(`/bugreport/admin/${day}/../zip`), e)).status, 404);
});
