import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule, hookHarness, deferred, flush } from '../../../../../tests/frontend/hookHarness.mjs'
import { ACTIVE, createJobStore } from '../../shared/jobs/jobStore.js'
import * as pass from '../../shared/jobs/passView.js'

const owner = { pid: 1, created: 10 }
const now = () => Date.now() / 1000
const record = (fields = {}) => ({
  id: 'imp', kind: 'mcp_model_import', status: 'running', owner, seq: 1, created_at: now(),
  params: { source: 'C:\\Users\\me\\Downloads\\Neos.glb', fighter: 'Marth' },
  extra: { model: 'Neos', fighter: 'Marth', change: null, step: 'putting it on the fighter', asking: false },
  detail: String.raw`00:03.485 render | Saved: 'E:\Nucleus Data\storage\model_imports\neos-a370ff\rigswap\2-swap\front-1.png'`,
  ...fields,
})

// The window's real job store and useJobs hooks, on the harness's React: records arrive as the `job` event does.
function fixture() {
  const h = hookHarness(), cancels = [], timers = new Map()
  let timerId = 0
  const store = createJobStore({ fetchJobs: async () => ({ jobs: [], owner }), fetchJob: async () => null })
  const jobs = { jobStore: store, startJobStore() {}, markJobSeen: async () => {}, refreshJob: async () => null,
    cancelJob: (id) => { const reply = deferred(); cancels.push({ id, ...reply }); return reply.promise } }
  const useJobs = loadModule(new URL('../../shared/jobs/useJobs.js', import.meta.url),
    { react: h.react, './jobs': jobs, './passView': pass })
  // the shared socket: the events the module listens to, as subscribe() leaves them
  const listeners = new Map()
  const socket = { subscribe(handlers) {
    for (const [event, fn] of Object.entries(handlers)) listeners.set(event, fn)
    return () => { for (const event of Object.keys(handlers)) listeners.delete(event) }
  } }
  const mcp = loadModule(new URL('./mcpImport.js', import.meta.url), {
    react: h.react, '../../shared/jobs/jobStore': { ACTIVE }, '../../shared/jobs/useJobs': useJobs,
    '../../shared/transport/socket': socket,
  }, {
    setTimeout: (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId },
    clearTimeout: (id) => timers.delete(id),
  })
  return { h, store, cancels, timers, mcp, listeners }
}

test('the chip names the model, the fighter and the step in plain words, never rigswap\'s raw line', () => {
  const { mcp } = fixture()
  assert.equal(mcp.chipView(null), null)
  assert.deepEqual(mcp.chipView(record()), {
    id: 'imp', state: 'running', model: 'Neos', fighter: 'Marth', change: false, step: 'putting it on the fighter',
    canCancel: true, error: null, title: 'Your AI is importing Neos as Marth: putting it on the fighter',
  })
  // the raw line (clock, file paths) stays the record's detail, for job_status; no step yet means no step shown
  const early = mcp.chipView(record({ extra: { model: 'Neos', fighter: 'Marth' } }))
  assert.equal(early.step, null); assert.equal(early.title, 'Your AI is importing Neos as Marth')
  for (const view of [mcp.chipView(record()), early]) assert.doesNotMatch(JSON.stringify(view), /render \||Nucleus Data|00:03/)
  // an ask open on the user's AI says so, whatever the step was
  const asking = mcp.chipView(record({ extra: { model: 'Neos', fighter: 'Marth', step: 'loading the model', asking: true } }))
  assert.equal(asking.step, mcp.ASKING); assert.equal(asking.step, 'waiting on your AI’s answer')
  assert.equal(asking.title, 'Your AI is importing Neos as Marth: waiting on your AI’s answer')
  // Before the job's own fields: the file from the call without its extension, no fighter when the importer picks one.
  const bare = mcp.chipView(record({ extra: {}, params: { source: '/home/me/Neos.fbx' }, detail: '' }))
  assert.equal(bare.model, 'Neos'); assert.equal(bare.fighter, null); assert.equal(bare.step, null)
  assert.equal(bare.title, 'Your AI is importing Neos')
  // a record from before the backend sent the costume's name still shows it without the extension
  assert.equal(mcp.chipView(record({ extra: { model: 'Clank.zip', fighter: 'Kirby' } })).model, 'Clank')
  // A fix_import: the import's own name, on its fighter.
  const change = mcp.chipView(record({ extra: { model: 'Neos', fighter: 'Marth', change: 'the legs look wrong',
    step: 'working out the change' } }))
  assert.equal(change.change, true)
  assert.equal(change.title, 'Your AI is changing Neos on Marth: working out the change')
  assert.equal(mcp.chipView(record({ status: 'queued' })).state, 'running')
})

test('a model is named as the import saves it: the file\'s extension goes', () => {
  const { mcp } = fixture()
  for (const [given, shown] of [['Clank.zip', 'Clank'], ['Neos.GLB', 'Neos'], ['a.b.fbx', 'a.b'], ['Clank', 'Clank'],
    ['Mr. Game & Watch', 'Mr. Game & Watch'], ['  Neos.gltf ', 'Neos'], ['.zip', '.zip'], ['notes.txt', 'notes.txt']]) {
    assert.equal(mcp.modelName(given), shown, given)
  }
  for (const nothing of [null, undefined, '', '   ', 3]) assert.equal(mcp.modelName(nothing), null)
})

test('a stop shows as stopping however it was asked for, and then the chip says nothing was saved', () => {
  const { mcp } = fixture()
  for (const job of [record({ detail: 'Stopping…' }), record({ extra: { model: 'Neos', stopping: true, asking: true } })]) {
    const view = mcp.chipView(job)
    assert.equal(view.state, 'stopping'); assert.equal(view.canCancel, false); assert.equal(view.step, mcp.STOPPING)
  }
  assert.equal(mcp.chipView(record(), { asked: true }).state, 'stopping')
  // a failed Cancel says so until the import stops another way; while stopping it is not shown
  assert.equal(mcp.chipView(record(), { error: 'offline' }).error, 'Could not stop it: offline')
  assert.equal(mcp.chipView(record(), { error: 'offline' }).title,
    'Your AI is importing Neos as Marth: putting it on the fighter. Could not stop it: offline')
  assert.equal(mcp.chipView(record({ detail: 'Stopping…' }), { error: 'offline' }).error, null)
  const stopped = record({ status: 'cancelled' })
  assert.deepEqual(mcp.chipView(stopped, { seen: true }), { id: 'imp', state: 'stopped',
    text: 'Import stopped: nothing saved', title: 'Import stopped: nothing saved (Neos)', canCancel: false })
  assert.equal(mcp.chipView(record({ status: 'cancelled', extra: { model: 'Neos', change: 'x' } }), { seen: true }).text,
    'Change stopped: nothing saved')
  assert.equal(mcp.chipView(stopped), null, 'an earlier session\'s stop it never saw running shows nothing')
  assert.equal(mcp.chipView(stopped, { seen: true, gone: true }), null)
  for (const status of ['done', 'failed', 'interrupted']) assert.equal(mcp.chipView(record({ status }), { seen: true }), null)
})

test('Cancel calls the job cancel route; the stopped note goes after a few seconds', async () => {
  const f = fixture()
  const render = () => f.h.render(() => f.mcp.useMcpImportChip())
  assert.equal(render().view, null)
  f.store.receive(record())
  let chip = render()
  assert.equal(chip.view.state, 'running')
  const pressed = chip.cancel()
  assert.equal(render().view.state, 'stopping', 'the press shows at once')
  await flush()
  assert.deepEqual(f.cancels.map(c => c.id), ['imp'])
  f.cancels[0].resolve({ success: true, stopping: true }); await pressed
  f.store.receive(record({ seq: 2, detail: 'Stopping…' }))
  assert.equal(render().view.state, 'stopping')
  f.store.receive(record({ seq: 3, status: 'cancelled', ended_at: now() }))
  chip = render()
  assert.equal(chip.view.state, 'stopped'); assert.equal(chip.view.text, 'Import stopped: nothing saved')
  const [[timer, { fn, delay }]] = [...f.timers]
  assert.equal(delay, f.mcp.LINGER_MS)
  f.timers.delete(timer); fn()
  assert.equal(render().view, null, 'then it goes')
  f.h.unmount()
})

test('a Cancel that fails says so and can be pressed again', async () => {
  const f = fixture()
  const render = () => f.h.render(() => f.mcp.useMcpImportChip())
  f.store.receive(record())
  const pressed = render().cancel()
  await flush()
  f.cancels[0].reject(new Error('the backend is not answering')); await pressed
  const view = render().view
  assert.equal(view.state, 'running'); assert.equal(view.canCancel, true)
  assert.equal(view.error, 'Could not stop it: the backend is not answering')
  f.h.unmount()
})

test('an import that saves a costume makes the window read the vault again, once; a stop or a failure does not', () => {
  const f = fixture()
  const saved = []
  const render = () => f.h.render(() => f.mcp.useMcpImportSaved((job) => saved.push(job.id)))
  render()
  f.store.receive(record())
  render()
  assert.deepEqual(saved, [])
  f.store.receive(record({ seq: 2, status: 'done', ended_at: now() + 1,
    result: { status: 'done', vault_changed: true, saved: { name: 'Neos', character: 'Marth', skin_id: 'neos' } } }))
  render(); render()
  assert.deepEqual(saved, ['imp'])
  for (const [id, status] of [['stop', 'cancelled'], ['fail', 'failed']]) {
    f.store.receive(record({ id, status: 'running', created_at: now() + 2 }))
    render()
    f.store.receive(record({ id, seq: 2, status, ended_at: now() + 3, created_at: now() + 2 }))
    render()
  }
  // done without a save (the save refused): nothing changed in the vault either
  f.store.receive(record({ id: 'nosave', seq: 2, status: 'done', ended_at: now() + 4, created_at: now() + 4,
    result: { status: 'done', saved: null, not_saved: 'no costume file' } }))
  render()
  assert.deepEqual(saved, ['imp'])
  assert.equal(f.mcp.savedToVault({ status: 'done', result: { saved: { name: 'x' } } }), true)
  assert.equal(f.mcp.savedToVault({ status: 'running', result: { vault_changed: true } }), false)
  f.h.unmount()
})

test('another tool the user’s AI ran that saved to the vault (a Stage Lab save) makes the window read it again', () => {
  const f = fixture()
  let reads = 0
  const read = () => { reads += 1 }
  f.h.render(() => f.mcp.useMcpVaultChanged(read))
  assert.equal(f.mcp.VAULT_EVENT, 'mcp_vault_changed')
  f.listeners.get(f.mcp.VAULT_EVENT)({ tool: 'stage_lab' })
  f.listeners.get(f.mcp.VAULT_EVENT)({ tool: 'download_website_mod' })
  assert.equal(reads, 2)
  f.h.unmount()
  assert.equal(f.listeners.has(f.mcp.VAULT_EVENT), false)
})
