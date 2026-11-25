import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule, hookHarness, deferred, flush } from '../../../../../tests/frontend/hookHarness.mjs'
import * as outcome from '../../shared/jobs/jobOutcome.js'
import * as shelfAdd from '../../shared/jobs/shelfAdd.js'

function fixture(module, exportName, options = {}) {
  const h = hookHarness(), posts = [], gets = [], records = new Map(), finished = new Map()
  const timers = new Map(), alerts = [], downloads = []; let timerId = 0, refreshed = 0
  const paths = { vanilla_iso_path: 'vanilla.iso', slippi_dolphin_path: 'Slippi', ...options.paths }
  const api = {
    post: (path, body) => { const reply = deferred(); posts.push({ path, body, ...reply }); return reply.promise },
    get: async path => { gets.push(path); return { patches: [{ id: 'patch' }] } },
  }
  const loaded = loadModule(new URL(module, import.meta.url), {
    react: h.react, '../../shared/transport/api': { api }, '../../shared/jobs/jobOutcome': outcome,
    '../../shared/jobs/useJobs': { useJob: id => records.get(id) || null, useFinishedJobs: kind => finished.get(kind) || '' },
    '../../shared/ui/appDialogs': { appConfirm: options.confirm || (async () => true) },
    '../../shared/jobs/shelfAdd': shelfAdd,
    '../../shared/config/config.js': { API_URL: 'http://test/api/mex', backendMediaUrl: value => value },
    '../patches/patchDownload': { downloadPatchFile: async () => {} },
  }, {
    localStorage: { getItem: key => paths[key] || null }, alert: message => alerts.push(message),
    setTimeout: (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId }, clearTimeout: id => timers.delete(id),
    document: { createElement: () => { const link = { click: () => downloads.push({ href: link.href, name: link.download }) }; return link },
      body: { appendChild() {}, removeChild() {} } },
  })
  const render = () => h.render(() => loaded[exportName]({ onBundleImportSuccess: () => refreshed++ }))
  return { render, posts, gets, records, finished, timers, alerts, downloads, paths, h, refreshed: () => refreshed }
}

test('patch build follows its job even when completion beats the HTTP reply, and downloads by job id', async () => {
  const f = fixture('./useXdeltaPatches.js', 'useXdeltaPatches')
  assert.equal(f.render().xdeltaBuildState, 'idle')
  const start = f.render().handleBuildXdeltaIso({ id: 'patch' })
  assert.equal(f.render().xdeltaBuildState, 'building'); assert.equal(f.render().showXdeltaBuildModal, true)
  assert.equal(f.posts[0].path, '/xdelta/build/patch'); assert.deepEqual(f.posts[0].body, { vanillaIsoPath: 'vanilla.iso' })
  f.records.set('job/a', { id: 'job/a', status: 'done', result: { filename: 'chosen.iso' }, progress: 1 })
  f.posts[0].resolve({ job_id: 'job/a' }); await start
  const view = f.render()
  assert.equal(view.xdeltaBuildState, 'complete'); assert.equal(view.xdeltaBuildFilename, 'chosen.iso')
  assert.equal(view.xdeltaBuildProgress, 100)
  view.handleDownloadXdeltaIso()
  assert.deepEqual(f.downloads, [{ href: 'http://test/api/mex/xdelta/download/job%2Fa', name: 'chosen.iso' }])
  view.closeXdeltaBuildModal(); assert.equal(f.render().showXdeltaBuildModal, false)
  f.h.unmount()
})

test('a late build answer cannot replace another attempt, including another build of the same patch', async () => {
  const f = fixture('./useXdeltaPatches.js', 'useXdeltaPatches')
  const old = f.render().handleBuildXdeltaIso({ id: 'same' })
  const fresh = f.render().handleBuildXdeltaIso({ id: 'same' })
  f.posts[1].resolve({ job_id: 'new' }); await fresh
  f.records.set('new', { status: 'running', progress: .25, detail: 'New build' })
  f.posts[0].reject(new Error('old failed')); await old
  assert.equal(f.render().xdeltaBuildState, 'building'); assert.equal(f.render().xdeltaBuildError, null)
  assert.equal(f.render().xdeltaBuildMessage, 'New build')
  f.render().closeXdeltaBuildModal()
  const closing = f.render().handleBuildXdeltaIso({ id: 'same' })
  f.render().closeXdeltaBuildModal(); f.posts[2].resolve({ job_id: 'late' }); await closing
  assert.equal(f.render().xdeltaBuildState, 'idle'); f.h.unmount()
})

test('build, create and install failures release progress and retain their own error', async () => {
  const f = fixture('./useXdeltaPatches.js', 'useXdeltaPatches')
  const start = f.render().handleBuildXdeltaIso({ id: 'p' })
  f.posts[0].resolve({ job_id: 'build' }); await start
  for (const status of ['failed', 'cancelled', 'interrupted']) {
    f.records.set('build', { status, error: 'disk full' })
    assert.equal(f.render().xdeltaBuildState, 'error')
    assert.equal(f.render().xdeltaBuildError, status === 'cancelled' ? 'Cancelled.' : 'disk full')
  }
  f.render().setXdeltaCreateData({ name: 'Patch', moddedIsoPath: 'modded.iso', description: 'desc' })
  const create = f.render().handleStartCreateXdelta()
  assert.equal(f.render().xdeltaCreateState, 'creating')
  assert.deepEqual(f.posts[1].body, { vanillaIsoPath: 'vanilla.iso', name: 'Patch', moddedIsoPath: 'modded.iso', description: 'desc' })
  f.posts[1].resolve({ job_id: 'create' }); await create
  f.records.set('create', { status: 'done', result: { patch_id: 'created' } })
  assert.equal(f.render().xdeltaCreateResult.patch_id, 'created')
  f.finished.set('xdelta_create', 'create'); f.render(); f.render(); await flush()
  assert.deepEqual(f.gets, ['/xdelta/list'])
  const install = f.render().installBundle('bundle', { slippiPath: 'Dolphin' })
  assert.equal(f.render().bundleImporting, true)
  f.posts[2].resolve({ job_id: 'install' }); await install
  f.records.set('install', { status: 'interrupted', error: 'Backend stopped' })
  assert.equal(f.render().bundleImporting, false); assert.equal(f.render().bundleError, 'Backend stopped')
  f.h.unmount()
})

test('bundle install success refreshes once, keeps warnings, and reset ignores an in-flight old answer', async () => {
  const f = fixture('./useXdeltaPatches.js', 'useXdeltaPatches')
  const start = f.render().installBundle('b', { vanillaIsoPath: 'v' })
  f.posts[0].resolve({ job_id: 'install' }); await start
  f.records.set('install', { status: 'running', progress: .42, detail: 'Textures' })
  assert.equal(f.render().bundleProgress, 42); assert.equal(f.render().bundleMessage, 'Textures')
  const result = { installed: true, warnings: ['HD textures unavailable'] }
  f.records.set('install', { status: 'done', result })
  assert.equal(f.render().bundleComplete, true); assert.equal(f.render().bundleResult, result)
  f.render(); assert.equal(f.refreshed(), 1)
  const late = f.render().installBundle('b', {})
  f.render().handleBundleReset(); f.posts[1].reject(new Error('old')); await late
  assert.equal(f.render().bundleError, null); assert.equal(f.render().bundleImporting, false)
  assert.equal(f.render().bundleComplete, false); f.h.unmount()
})

test('request errors end attempts with the appropriate backend or transport wording', async () => {
  const f = fixture('./useXdeltaPatches.js', 'useXdeltaPatches')
  const start = f.render().installBundle('b', {})
  f.posts[0].reject(new Error('offline')); await start
  assert.equal(f.render().bundleError, 'Install error: offline')
  const next = f.render().installBundle('b', {})
  f.posts[1].reject(Object.assign(new Error('refused'), { data: {} })); await next
  assert.equal(f.render().bundleError, 'refused'); assert.equal(f.render().bundleImporting, false)
  f.h.unmount()
})

test('Play follows the returned job, ignores older attempts, and stale dismissal timers cannot hide a new play', async () => {
  const f = fixture('./useVaultPlay.js', 'useVaultPlay')
  const old = f.render().handlePlayBundle({ id: 'b' })
  const fresh = f.render().handlePlayPatch({ id: 'p' })
  f.posts[1].resolve({ job_id: 'new' }); await fresh
  f.posts[0].resolve({ job_id: 'old' }); await old
  assert.deepEqual(f.posts.map(p => p.path), ['/bundle/play/b', '/xdelta/play/p'])
  f.records.set('old', { status: 'failed', error: 'old failure' })
  f.records.set('new', { status: 'running', progress: .6, detail: 'Building' })
  assert.equal(f.render().playingId, 'p'); assert.equal(f.render().playPercent, 60)
  assert.equal(f.render().playError, null)
  f.records.set('new', { status: 'done' }); assert.equal(f.render().playLaunched, true)
  const timer = [...f.timers.values()][0]; assert.equal(timer.delay, 2500)
  const next = f.render().handlePlayPatch({ id: 'p' })
  timer.fn(); assert.equal(f.render().playingId, 'p')
  f.posts[2].reject(new Error('offline')); await next
  assert.equal(f.render().playError, 'Play error: offline')
  f.render().dismissPlay(); assert.equal(f.render().playingId, null); f.h.unmount()
})

test('dismissing Play while start is pending prevents resurrection and no Slippi path sends no request', async () => {
  const f = fixture('./useVaultPlay.js', 'useVaultPlay')
  const start = f.render().handlePlayBundle({ id: 'b' })
  f.render().dismissPlay(); f.posts[0].resolve({ job_id: 'late' }); await start
  assert.equal(f.render().playingId, null)
  f.paths.slippi_dolphin_path = ''
  await f.render().handlePlayBundle({ id: 'b' })
  assert.equal(f.posts.length, 1); assert.match(f.alerts[0], /Slippi Dolphin path/); f.h.unmount()
})

test('bundle actions validate both paths, open progress first, and delegate to the job-backed installer', async () => {
  const h = hookHarness(), order = [], wait = deferred(), paths = {}
  const { useVaultBundles } = loadModule(new URL('./useVaultBundles.js', import.meta.url), {
    react: h.react, '../../shared/config/config.js': {}, '../../shared/transport/api': { api: {} },
  }, { localStorage: { getItem: key => paths[key] }, alert: text => order.push(text) })
  const render = () => h.render(() => useVaultBundles({ openImportModal: () => order.push('open'),
    installBundle: (id, body) => { order.push({ id, body }); return wait.promise } }))
  await render().handleInstallBundle({ id: 'b' }); assert.match(order.pop(), /Slippi Dolphin path/)
  paths.slippi_dolphin_path = 'Dolphin'
  await render().handleInstallBundle({ id: 'b' }); assert.match(order.pop(), /Vanilla ISO path/)
  paths.vanilla_iso_path = 'vanilla'
  const installing = render().handleInstallBundle({ id: 'b' })
  assert.deepEqual(order, ['open', { id: 'b', body: { slippiPath: 'Dolphin', vanillaIsoPath: 'vanilla' } }])
  wait.resolve(); await installing; h.unmount()
})

test('bundle export completion refreshes the vault and bundle install receives the Xdelta job action', () => {
  const h = hookHarness(); let finished = '', refreshed = 0, passed
  const installBundle = () => {}, modal = []
  const { useVaultPatches } = loadModule(new URL('./useVaultPatches.js', import.meta.url), {
    react: h.react, '../../shared/jobs/useJobs': { useFinishedJobs: kind => { assert.equal(kind, 'bundle_export'); return finished } },
    './useXdeltaPatches': { useXdeltaPatches: () => ({ installBundle, setShowXdeltaImportModal: value => modal.push(value) }) },
    './useVaultBundles': { useVaultBundles: options => { passed = options; return {} } },
  })
  const render = () => h.render(() => useVaultPatches({ fetchBundles: () => refreshed++ }))
  render(); assert.equal(refreshed, 0); assert.equal(passed.installBundle, installBundle)
  passed.openImportModal(); assert.deepEqual(modal, [true])
  finished = 'one'; render(); render(); assert.equal(refreshed, 1)
  finished = 'two,one'; render(); assert.equal(refreshed, 2); h.unmount()
})

test('Add to Unlocked names the Vault item by id only, follows its shelf_add job, and ignores an older answer', async () => {
  const f = fixture('./useVaultShelfAdd.js', 'useVaultShelfAdd')
  const old = f.render().handleAddBundleToPlay({ id: 'b', name: 'Bundle' })
  const fresh = f.render().handleAddPatchToPlay({ id: 'p', name: 'Patch', path: 'C:\never\sent' })
  f.posts[1].resolve({ job_id: 'new' }); await fresh
  f.posts[0].resolve({ job_id: 'old' }); await old
  assert.deepEqual(f.posts.map(p => [p.path, p.body]),
    [['/api/play/shelf/add', { bundleId: 'b' }], ['/api/play/shelf/add', { patchId: 'p' }]])
  f.records.set('old', { status: 'failed', error: 'old failure' })
  f.records.set('new', { status: 'running', progress: 0.4, detail: 'Building ISO... 35%' })
  let view = f.render()
  assert.equal(view.addingId, 'p'); assert.equal(view.addPercent, 40); assert.equal(view.addMessage, 'Building ISO... 35%')
  assert.equal(view.addError, null); assert.equal(view.addDone, false)
  f.records.set('new', { status: 'done', result: { entryId: 'e', name: 'Patch' } })
  view = f.render()
  assert.equal(view.addDone, true); assert.equal(view.addDoneText, 'Patch is on your Unlocked shelf.')
  const failing = f.render().handleAddPatchToPlay({ id: 'p', name: 'Patch' })
  const refusal = Object.assign(new Error('Nucleus needs your Melee ISO to build this.'), { data: {} })
  f.posts[2].reject(refusal); await failing
  assert.equal(f.render().addError, 'Nucleus needs your Melee ISO to build this.')
  f.render().dismissAdd(); assert.equal(f.render().addingId, null); f.h.unmount()
})

test('Add to Unlocked offers to replace a game of the same name, and keeping it ends quietly', async () => {
  const asked = []
  let answer = true
  const f = fixture('./useVaultShelfAdd.js', 'useVaultShelfAdd',
    { confirm: async (message, options) => { asked.push([message, options.confirmText]); return answer } })
  const same = () => Object.assign(new Error('"Patch" is already on your Unlocked shelf.'),
    { status: 409, data: { success: false, code: 'already_on_shelf', existing: { id: 'e', name: 'Patch' } } })
  const replacing = f.render().handleAddPatchToPlay({ id: 'p', name: 'Patch' })
  f.posts[0].reject(same()); await flush()
  assert.deepEqual(f.posts.map(p => p.body), [{ patchId: 'p' }, { patchId: 'p', replace: 'e' }])
  assert.equal(asked[0][1], 'Replace'); assert.match(asked[0][0], /^"Patch" is already on your Unlocked shelf/)
  f.posts[1].resolve({ job_id: 'r' }); await replacing
  f.records.set('r', { status: 'done', result: { entryId: 'e', name: 'Patch', replaced: true } })
  assert.equal(f.render().addDoneText, 'Patch was replaced on your Unlocked shelf.')
  answer = false
  const keeping = f.render().handleAddPatchToPlay({ id: 'p', name: 'Patch' })
  f.posts[2].reject(same()); await keeping
  assert.equal(f.posts.length, 3); assert.equal(asked.length, 2)
  assert.equal(f.render().addingId, null); assert.equal(f.render().addError, null); f.h.unmount()
})
