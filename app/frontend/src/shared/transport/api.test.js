import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule, deferred } from '../../../../../tests/frontend/hookHarness.mjs'

function fixture() {
  let generation = null
  const calls = [], replies = []
  const client = loadModule(new URL('./api.js', import.meta.url), {
    '../config/config.js': { BACKEND_URL: 'http://127.0.0.1:5000', API_URL: 'http://127.0.0.1:5000/api/mex',
      BACKEND_TOKEN: 'test-token', UI_APPROVAL_KEY: 'test-ui' },
    './projectGeneration.js': { getProjectGeneration: () => generation },
    '../lib/appControl.js': { explainAppControl: text => text },
  }, { fetch: (url, init) => { calls.push({ url, init }); const reply = deferred(); replies.push(reply); return reply.promise } })
  return { ...client, calls, replies, generation: next => { generation = next } }
}
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } })

test('each request captures its project before a switch, including binary and form requests', async () => {
  const f = fixture()
  f.generation(3)
  const first = f.api.post('/reorder-batch', { moves: [] })
  f.generation(4)
  const second = f.api.post('/bundle/export', new FormData())
  const third = f.api.blob('/export/download/id/file.iso')
  assert.deepEqual(f.calls.map(c => c.init.headers.get('X-Nucleus-Project')), ['3', '4', '4'])
  assert.equal(f.calls[0].init.headers.get('X-Nucleus-Token'), 'test-token')
  assert.equal(f.calls[1].init.headers.has('Content-Type'), false)
  f.replies[0].resolve(json({ code: 'project_changed', error: 'Project changed' }, 409))
  await assert.rejects(first, e => e instanceof f.ApiError && e.status === 409 && e.data.code === 'project_changed')
  f.replies[1].resolve(json({ job_id: 'bundle' })); await second
  f.replies[2].resolve(new Response('iso')); assert.equal(await (await third).text(), 'iso')
})

test('unknown project is omitted and an explicit pinned header is preserved without mutating inputs', async () => {
  const f = fixture()
  const noProject = f.authenticatedFetch('http://127.0.0.1:5000/api/jobs')
  assert.equal(f.calls[0].init.headers.has('X-Nucleus-Project'), false)
  f.generation(9)
  const headers = new Headers({ 'x-nucleus-project': '0', 'X-Other': 'keep' })
  const pinned = f.authenticatedFetch('http://127.0.0.1:5000/api/mex/builds/changes/apply', { headers })
  assert.equal(f.calls[1].init.headers.get('X-Nucleus-Project'), '0')
  assert.equal(f.calls[1].init.headers.get('X-Nucleus-UI-Key'), 'test-ui')
  assert.equal(f.calls[0].init.headers.has('X-Nucleus-UI-Key'), false)     // only where a decision is recorded
  assert.equal(headers.has('X-Nucleus-Token'), false)
  for (const reply of f.replies) reply.resolve(json({}))
  await Promise.all([noProject, pinned])
})

test('project identity and backend credentials never accompany another origin', async () => {
  const f = fixture(); f.generation(0)
  const init = { headers: { 'X-Other': 'keep' } }
  const pending = f.authenticatedFetch('https://example.invalid/api/jobs', init)
  assert.equal(f.calls[0].init, init)
  assert.deepEqual(init.headers, { 'X-Other': 'keep' })
  f.replies[0].resolve(json({})); await pending
})

test("the MCP window questions, the window's MCP settings and its MCP account carry the window-only key", async () => {
  const f = fixture()
  const answered = f.authenticatedFetch('http://127.0.0.1:5000/api/mcp/window/confirmations/abc', { method: 'POST' })
  const listed = f.api.get('/api/mcp/window/confirmations')
  const told = f.api.post('/api/mcp/window', { slippi_dolphin_path: null })
  const account = f.api.post('/api/mcp/account', { token: null })
  const rpc = f.authenticatedFetch('http://127.0.0.1:5000/api/mcp', { method: 'POST' })
  assert.deepEqual(f.calls.map(c => c.init.headers.get('X-Nucleus-UI-Key')),
    ['test-ui', 'test-ui', 'test-ui', 'test-ui', null])     // the MCP endpoint itself is the AI's, not the window's
  for (const reply of f.replies) reply.resolve(json({}))
  await Promise.all([answered, listed, told, account, rpc])
})

test("an answer to the assistant's approval and a chat report's send carry the window-only key", async () => {
  const f = fixture()
  const chat = 'a'.repeat(32), approval = 'b'.repeat(32)
  const decided = f.api.post(`/api/assistant/chats/${chat}/approvals/${approval}`, { decision: 'approve' })
  const files = f.api.get(`/api/assistant/chats/${chat}/approvals/${approval}/files`, { query: { choice: 'all' } })
  const sent = f.api.post('/chat-reports/submit', { submission_id: 's', approval_hash: 'h', consent: true })
  const reviewed = f.api.post('/chat-reports/review', { surface: 'assistant', conversation_id: chat })
  const chatted = f.api.post(`/api/assistant/chats/${chat}/messages`, { text: 'hi' })
  assert.deepEqual(f.calls.map(c => c.init.headers.get('X-Nucleus-UI-Key')),
    ['test-ui', null, 'test-ui', null, null])
  for (const reply of f.replies) reply.resolve(json({}))
  await Promise.all([decided, files, sent, reviewed, chatted])
})

test("Play's writes carry the window-only key, its reads do not", async () => {
  const f = fixture()
  const launch = f.authenticatedFetch('http://127.0.0.1:5000/api/play/launch/retail', { method: 'POST' })
  const remove = f.authenticatedFetch('http://127.0.0.1:5000/api/play/shelf/abc', { method: 'delete' })
  const shelf = f.authenticatedFetch('http://127.0.0.1:5000/api/play/shelf')
  assert.equal(f.calls[0].init.headers.get('X-Nucleus-UI-Key'), 'test-ui')
  assert.equal(f.calls[1].init.headers.get('X-Nucleus-UI-Key'), 'test-ui')
  assert.equal(f.calls[2].init.headers.has('X-Nucleus-UI-Key'), false)
  for (const reply of f.replies) reply.resolve(json({}))
  await Promise.all([launch, remove, shelf])
})

test("the Melee Unlocked export's writes carry the window-only key, its list does not", async () => {
  const f = fixture()
  const exported = f.api.post('/melee-unlocked/export', { destination: 'C:/out', kitPath: 'C:/kit', gccBin: 'C:/gcc/bin' })
  const verified = f.api.post('/melee-unlocked/verify', { kitPath: 'C:/kit', gccBin: '' })
  const listed = f.api.get('/melee-unlocked/fighters')
  assert.equal(f.calls[0].init.headers.get('X-Nucleus-UI-Key'), 'test-ui')
  assert.equal(f.calls[1].init.headers.get('X-Nucleus-UI-Key'), 'test-ui')
  assert.equal(f.calls[2].init.headers.has('X-Nucleus-UI-Key'), false)
  for (const reply of f.replies) reply.resolve(json({ success: true }))
  await Promise.all([exported, verified, listed])
})
