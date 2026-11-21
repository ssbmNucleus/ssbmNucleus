import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { transformSync } from 'esbuild'
import { loadModule, deferred, flush, hookHarness } from '../../../../tests/frontend/hookHarness.mjs'
import * as storeModule from '../shared/jobs/jobStore.js'
import * as pass from '../shared/jobs/passView.js'
import * as restoreJob from './restoreJob.js'

// BackupRestore with the real job store and hooks; the backend is a list of GETs and POSTs and one fake XHR per
// upload. `electron` is the app's bridge (window.electron); without one the window is the browser dev flow.
function mount({ electron } = {}) {
  const h = hookHarness(), gets = [], posts = [], xhrs = [], storage = new Map()
  const api = { get(path) { const reply = deferred(); gets.push({ path, ...reply }); return reply.promise } }
  const jobs = loadModule(new URL('../shared/jobs/jobs.js', import.meta.url), {
    '../transport/api': { __esModule: true, default: api }, '../transport/socket': { subscribe() {} },
    './jobStore': storeModule,
  })
  const hooks = loadModule(new URL('../shared/jobs/useJobs.js', import.meta.url),
    { react: h.react, './jobs': jobs, './passView': pass })
  class FakeXhr {
    constructor() { this.upload = {}; xhrs.push(this) }
    open(method, url) { this.url = url }
    setRequestHeader() {}
    send(body) { this.body = body }
  }
  const window = { electron, sessionStorage: {
    getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key),
  } }
  const stubs = {
    react: h.react,
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'Fragment' },
    '../shared/ui/ProgressPanel': () => null,
    '../shared/audio/sounds': { playSound() {}, playHoverSound() {} },
    '../shared/transport/api': { api: {
      url: path => path,
      post(path, body) { const reply = deferred(); posts.push({ path, body, ...reply }); return reply.promise },
    } },
    '../shared/config/config': { BACKEND_TOKEN: '', backendMediaUrl: url => url },
    '../shared/jobs/jobStore': storeModule,
    './restoreJob': restoreJob,
    '../shared/jobs/useJobs': hooks,
  }
  const code = transformSync(readFileSync(new URL('./BackupRestore.jsx', import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const module = { exports: {} }
  new Function('require', 'module', 'exports', 'window', 'XMLHttpRequest', code)(
    name => { if (!(name in stubs)) throw new Error(`Unstubbed dependency: ${name}`); return stubs[name] },
    module, module.exports, window, FakeXhr)
  const BackupRestore = module.exports.default
  return { render: () => h.render(() => BackupRestore({})), gets, posts, xhrs, jobs }
}

const nodes = function* (node) {
  if (Array.isArray(node)) for (const child of node) yield* nodes(child)
  else if (node && typeof node === 'object') { yield node; yield* nodes(node.props?.children) }
}
const text = node => (Array.isArray(node) ? node.map(text).join('')
  : node && typeof node === 'object' ? text(node.props?.children) : node == null || node === false ? '' : String(node))
const find = (tree, match) => [...nodes(tree)].find(match)
const button = (tree, label) => find(tree, node => node.type === 'button' && text(node).includes(label))
const radio = (tree, value) => find(tree, node => node.type === 'input' && node.props.type === 'radio' && node.props.value === value)
const fileInput = tree => find(tree, node => node.type === 'input' && node.props.type === 'file')

test('every open of the restore dialog starts on Replace, after a Merge restore too', async () => {
  const view = mount()
  let tree = view.render()
  button(tree, 'Import Vault').props.onClick(); tree = view.render()
  assert.equal(radio(tree, 'replace').props.checked, true)
  radio(tree, 'merge').props.onChange({ target: { value: 'merge' } }); tree = view.render()
  fileInput(tree).props.onChange({ target: { files: [{ name: 'old.zip' }] } }); tree = view.render()
  button(tree, 'Restore Vault').props.onClick(); tree = view.render()
  assert.equal(view.xhrs[0].body.get('mode'), 'merge')
  assert.equal(radio(tree, 'merge'), undefined)                    // the dialog closed

  const xhr = view.xhrs[0], id = xhr.body.get('restore_id')
  Object.assign(xhr, { status: 200, responseText: JSON.stringify({ success: true, restore_id: id }) })
  xhr.onload(); view.render()
  view.gets.at(-1).resolve({ job: { id, kind: 'vault_restore', status: 'failed', error: 'disk full', seq: 1, created_at: 1 } })
  await flush(); tree = view.render()
  assert.match(text(tree), /Restore failed: disk full/)

  button(tree, 'Import Vault').props.onClick(); tree = view.render()
  assert.equal(radio(tree, 'replace').props.checked, true)
  assert.equal(radio(tree, 'merge').props.checked, false)
  assert.match(text(tree), /Choose backup file/)                   // no file carried over either
  assert.equal(button(tree, 'Restore Vault').props.disabled, true)
})

test('the window asks for its restore job only once the upload is in, so the start has no 404', async () => {
  const view = mount()
  let tree = view.render()
  button(tree, 'Import Vault').props.onClick(); tree = view.render()
  fileInput(tree).props.onChange({ target: { files: [{ name: 'backup.zip' }] } }); tree = view.render()
  button(tree, 'Restore Vault').props.onClick(); view.render()
  await flush(); view.render()
  assert.deepEqual(view.gets.map(get => get.path), [])            // uploading: the backend has no such job yet

  const xhr = view.xhrs[0], id = xhr.body.get('restore_id')
  Object.assign(xhr, { status: 200, responseText: JSON.stringify({ success: true, restore_id: id }) })
  xhr.onload(); view.render()
  assert.deepEqual(view.gets.map(get => get.path), [`/api/jobs/${id}`])
  view.gets[0].resolve({ job: { id, kind: 'vault_restore', status: 'running', seq: 1, created_at: 1, progress: 0.5 } })
  await flush(); view.render(); await flush(); view.render()
  assert.equal(view.gets.length, 1)
  assert.equal(view.jobs.jobStore.get(id).status, 'running')
})

// Tester B8, 0.9.0 build 8: Export Vault was a Chromium download, whose Save As dialog was titled with the backend
// URL and its token, and whose Cancel deleted the backup. The app now asks where first and the backend saves there.
test('Export Vault asks where to save before making a backup; Cancel makes none', async () => {
  const asked = []
  const view = mount({ electron: { saveVaultBackupDialog: async () => { asked.push('dialog'); return null } } })
  let tree = view.render()
  button(tree, 'Export Vault').props.onClick()
  await flush(); tree = view.render()
  assert.deepEqual(asked, ['dialog'])
  assert.deepEqual(view.posts, [])                                 // no backup made, so nothing to clean up
  assert.equal(button(tree, 'Export Vault').props.disabled, false)
  assert.doesNotMatch(text(tree), /Creating backup|failed/)
})

test('Export Vault saves the backup where the dialog chose, with no download', async () => {
  const chosen = 'C:\\Backups\\SSBM-Nucleus-Vault-2026-11-20.zip'
  const view = mount({ electron: { saveVaultBackupDialog: async () => chosen } })
  let tree = view.render()
  button(tree, 'Export Vault').props.onClick()
  await flush(); tree = view.render()
  assert.deepEqual(view.posts.map(({ path, body }) => ({ path, body })),
    [{ path: '/storage/backup', body: { destination: chosen } }])
  assert.match(text(tree), /Creating backup/)
  assert.equal(button(tree, 'Creating Backup...').props.disabled, true)

  // `document` does not exist here: a download link would have failed the export.
  view.posts[0].resolve({ success: true, path: chosen, filename: 'SSBM-Nucleus-Vault-2026-11-20.zip', size: 10 })
  await flush(); tree = view.render()
  assert.match(text(tree), /Vault exported to C:\\Backups\\SSBM-Nucleus-Vault-2026-11-20\.zip/)
  assert.equal(button(tree, 'Export Vault').props.disabled, false)
})

test('a failed export says why', async () => {
  const view = mount({ electron: { saveVaultBackupDialog: async () => 'C:\\Backups\\v.zip' } })
  let tree = view.render()
  button(tree, 'Export Vault').props.onClick()
  await flush(); view.render()
  view.posts[0].reject(new Error('Could not save the backup to C:\\Backups'))
  await flush(); tree = view.render()
  assert.match(text(tree), /Backup failed: Could not save the backup to C:\\Backups/)
  assert.equal(button(tree, 'Export Vault').props.disabled, false)
})
