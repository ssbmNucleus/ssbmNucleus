'use strict';

// "Report this chat" on the phone: the payload built from one Randall thread,
// secret scrubbing, the size cap, the zip the worker receives, and the
// two-stage send that retries into the same remote report.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const load = (name) => import(`data:text/javascript;base64,${Buffer.from(
  fs.readFileSync(path.join(__dirname, '..', '..', '..', 'services', 'mobile', 'src', name), 'utf8')).toString('base64')}`);

// jszip ships with the desktop frontend; used here only to READ the archive back.
let JSZip = null;
try { JSZip = require(path.join(__dirname, '..', '..', '..', 'app', 'frontend', 'node_modules', 'jszip')); } catch { /* optional */ }

const OPENROUTER_KEY = `sk-or-v1-${'0123456789abcdef'.repeat(4)}`;
const DEVICE_TOKEN = 'dvc_7f3a9c1e5b2d4f6a8c0e';

let report;
test.before(async () => { report = await load('chat-report.js'); });

function thread() {
  return {
    id: 'tabc123', title: "Who's my worst matchup?", updated: 1_700_000_100_000,
    api: [
      { role: 'user', content: "Who's my worst matchup?" },
      { role: 'assistant', content: '', tool_calls: [{ id: 'c1', type: 'function',
        function: { name: 'get_overview', arguments: '{"my_char":"Falco"}' } }] },
      { role: 'tool', tool_call_id: 'c1', name: 'get_overview', content: JSON.stringify({ record: { games: 40 } }) },
      { role: 'assistant', content: 'Marth: 3-9.' },
    ],
    display: [
      { role: 'user', content: "Who's my worst matchup?", at: 1_700_000_000_000 },
      { role: 'randall', content: 'Marth: 3-9.', at: 1_700_000_020_000, chips: [{ hash: 'h' }],
        meta: { model: 'minimax', rounds: 2, tools: ['get_overview'], served: ['minimax/minimax-m3'],
                usage: { prompt_tokens: 900, completion_tokens: 80, cost: 0.004 } } },
    ],
  };
}

const INFO = { appVersion: '0.9.1', model: 'minimax', usage: { weekly_allowance: 5, remaining: 3 }, userAgent: 'test' };

test('the report carries the transcript, tool calls, per-turn route and budget', () => {
  const built = report.buildMobileReport({ thread: thread(), note: 'Wrong matchup', info: INFO, now: 0 });
  assert.deepEqual(built.files.map((f) => f.name), ['report.json', 'conversation.json', 'transcript.md']);
  const conv = JSON.parse(built.conversationText);
  assert.equal(conv.surface, 'mobile');
  assert.equal(conv.display[0].at, new Date(1_700_000_000_000).toISOString());
  assert.equal(conv.display[1].turn.rounds, 2);
  assert.deepEqual(conv.display[1].turn.served, ['minimax/minimax-m3']);
  assert.equal(conv.api[1].tool_calls[0].name, 'get_overview');
  assert.equal(conv.api[1].tool_calls[0].arguments, '{"my_char":"Falco"}');
  assert.match(conv.api[2].result, /"games":40/);
  assert.deepEqual(conv.budget, { source: 'nucleus_ai_tier', weekly_allowance: 5, remaining: 3 });
  assert.deepEqual(conv.counts, { messages: 2, user: 1, assistant: 1, tool_calls: 1 });
  assert.deepEqual(built.meta, {
    kind: 'chat', app_version: '0.9.1', platform: 'mobile', description: 'Wrong matchup', contact: '',
    truncated: false,
    chat: { surface: 'mobile', message_count: 2, tool_calls: 1, errors: 0, conversation_id: 'tabc123', model: 'minimax' },
  });
  assert.match(built.transcript, /## What went wrong\n\nWrong matchup/);
  assert.doesNotMatch(built.conversationText, /Wrong matchup/);   // the note lives in report.json only
});

test('an empty note still files with a description', () => {
  const built = report.buildMobileReport({ thread: thread(), info: INFO });
  assert.equal(built.meta.description, 'Randall chat report (no note)');
});

test('an OpenRouter key and the device token never reach the bundle or the meta', () => {
  const t = thread();
  t.api[0].content += ` key ${OPENROUTER_KEY}`;
  t.api[1].tool_calls[0].function.arguments = JSON.stringify({ api_key: OPENROUTER_KEY, token: DEVICE_TOKEN });
  t.api[2].content = JSON.stringify({ error: `401 Bearer ${OPENROUTER_KEY}`, echo: DEVICE_TOKEN });
  t.display[0].content = `my token is ${DEVICE_TOKEN}`;
  const built = report.buildMobileReport({ thread: t, note: `here ${OPENROUTER_KEY}`, contact: DEVICE_TOKEN,
    info: INFO, secrets: [DEVICE_TOKEN] });
  const everything = built.files.map((f) => f.text).join('') + JSON.stringify(built.meta);
  assert.ok(!everything.includes(OPENROUTER_KEY));
  assert.ok(!everything.includes(OPENROUTER_KEY.slice(9, 40)));
  assert.ok(!everything.includes(DEVICE_TOKEN));
  assert.ok(everything.includes('sk-or-v1-***'));
});

test('credential keys inside JSON tool text are masked above and below the cap', () => {
  for (const padding of ['short', 'row: '.repeat(20_000)]) {
    const t = thread();
    t.api[1].tool_calls[0].function.arguments = JSON.stringify({ password: 'example-password', padding });
    t.api[2].content = JSON.stringify({ password: 'example-password', padding });
    const built = report.buildMobileReport({ thread: t, info: INFO });
    assert.ok(!built.files.map((f) => f.text).join('').includes('example-password'), padding.length);
    assert.match(JSON.parse(built.conversationText).api[2].result, /^\{"password":"\*\*\*"/);
  }
});

test('a huge tool result is cut with a visible marker', () => {
  const t = thread();
  t.api[2].content = JSON.stringify({ rows: 'x'.repeat(50_000) });
  const built = report.buildMobileReport({ thread: t, info: INFO });
  assert.equal(built.truncated, true);
  assert.equal(built.meta.truncated, true);
  const conv = JSON.parse(built.conversationText);
  assert.ok(conv.api[2].result.length < report.RESULT_MAX + 40);
  assert.match(conv.api[2].result, /…\[truncated \d+ chars\]$/);
});

test('the stored zip is a valid archive with the exact file contents', async (t) => {
  const built = report.buildMobileReport({ thread: thread(), info: INFO, now: 0 });
  const zip = report.zipStore(built.files);
  assert.equal(zip[0], 0x50); assert.equal(zip[1], 0x4b);        // "PK", all the worker checks
  assert.deepEqual(report.zipStore(built.files), zip);           // same inputs, same bytes
  if (!JSZip) { t.skip('jszip not installed (frontend/node_modules)'); return; }
  const archive = await JSZip.loadAsync(zip, { checkCRC32: true });
  for (const f of built.files) assert.equal(await archive.file(f.name).async('string'), f.text);
});

function fakeWorker(script = {}) {
  const calls = [];
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) };
  let created = 0;
  const fetchImpl = async (url, init) => {
    calls.push({ url, method: init.method, body: init.body });
    if (init.method === 'POST') {
      created += 1;
      return new Response(JSON.stringify({ id: `${created}`.padStart(32, '0') }), { status: 200 });
    }
    const next = (script.put || []).shift();
    if (next instanceof Error) throw next;
    if (next) return new Response(JSON.stringify(next.body || {}), { status: next.status });
    return new Response(JSON.stringify({ ok: true, notified: true }), { status: 200 });
  };
  return { calls, storage, fetchImpl };
}

test('send is two-stage: create with kind chat, then PUT the exact zip', async () => {
  const built = report.buildMobileReport({ thread: thread(), info: INFO, now: 0 });
  const zip = report.zipStore(built.files);
  const w = fakeWorker();
  const out = await report.sendMobileReport({ zip, meta: built.meta, fetchImpl: w.fetchImpl, url: 'https://example.invalid/bugreport', storage: w.storage });
  assert.equal(out.state, 'sent');
  assert.equal(w.calls[0].url, 'https://example.invalid/bugreport');
  const meta = JSON.parse(w.calls[0].body);
  assert.equal(meta.kind, 'chat'); assert.equal(meta.platform, 'mobile'); assert.equal(meta.zip_size, zip.length);
  assert.equal(w.calls[1].url, `https://example.invalid/bugreport/${out.id}/zip`);
  assert.equal(w.calls[1].body, zip);
});

test('a failed upload retries into the same remote report', async () => {
  const built = report.buildMobileReport({ thread: thread(), info: INFO, now: 0 });
  const zip = report.zipStore(built.files);
  const w = fakeWorker({ put: [new TypeError('network down')] });
  const args = { zip, meta: built.meta, fetchImpl: w.fetchImpl, url: 'https://example.invalid/bugreport', storage: w.storage };
  await assert.rejects(report.sendMobileReport(args), (err) => {
    assert.match(report.errorText(err), /No connection/);
    return true;
  });
  const out = await report.sendMobileReport(args);
  assert.equal(out.state, 'sent');
  assert.equal(w.calls.filter((c) => c.method === 'POST').length, 1);
  const puts = w.calls.filter((c) => c.method === 'PUT');
  assert.equal(puts[0].url, puts[1].url);
});

test('a lost acknowledgment is not filed twice', async () => {
  const built = report.buildMobileReport({ thread: thread(), info: INFO, now: 0 });
  const zip = report.zipStore(built.files);
  // The worker stored it; the retry into the same id answers from its receipt.
  const w = fakeWorker({ put: [new TypeError('reply lost'),
    { status: 200, body: { ok: true, notified: true, already_stored: true } }] });
  const args = { zip, meta: built.meta, fetchImpl: w.fetchImpl, url: 'https://example.invalid/bugreport', storage: w.storage };
  await assert.rejects(report.sendMobileReport(args));
  const out = await report.sendMobileReport(args);
  assert.deepEqual([out.state, out.confirmed], ['sent', true]);
  assert.equal(w.calls.filter((c) => c.method === 'POST').length, 1);
});

test('a 404 after an earlier attempt is not delivery: the next try files anew', async () => {
  const built = report.buildMobileReport({ thread: thread(), info: INFO, now: 0 });
  const zip = report.zipStore(built.files);
  // Upload fails; the slot expires and its 410 is lost; the next retry sees 404.
  const w = fakeWorker({ put: [new TypeError('network down'), new TypeError('410 reply lost'),
    { status: 404, body: { error: 'unknown report' } }] });
  const args = { zip, meta: built.meta, fetchImpl: w.fetchImpl, url: 'https://example.invalid/bugreport', storage: w.storage };
  await assert.rejects(report.sendMobileReport(args));
  await assert.rejects(report.sendMobileReport(args));
  await assert.rejects(report.sendMobileReport(args), (err) => err.status === 404);
  const out = await report.sendMobileReport(args);
  assert.deepEqual([out.state, out.confirmed], ['sent', true]);
  const posts = w.calls.filter((c) => c.method === 'POST');
  assert.equal(posts.length, 2);
  assert.notEqual(w.calls.at(-1).url, w.calls[1].url);           // uploaded into the NEW report
});

test('rate limits read as a plain message', async () => {
  assert.match(report.errorText({ status: 429, data: {} }), /Too many reports/);
});
