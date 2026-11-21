import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as helpers from './modelImportTools.js'

const realRequire = createRequire(import.meta.url)
const loadModule = (file, resolve) => {
  const built = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', built)(name => resolve(name) || realRequire(name), mod, mod.exports)
  return mod.exports
}
// The connected part (the hook: the api and the job store) is not drawn here; the view is.
let hookState = null
const section = loadModule('./ModelImportToolsSection.jsx', name => {
  if (name === './modelImportTools') return helpers
  if (name === './useModelImportTools') return { useModelImportTools: () => hookState }
  if (name === '../shared/audio/sounds') return { playHoverSound: () => {}, playSound: () => {} }
  return null
})
const { ModelImportToolsView } = section
const Section = section.default

const PIECES = [
  { name: 'blender', label: 'Blender 4.3.2', source: 'download.blender.org', size: 400e6, installed: false },
  { name: 'python', label: 'Python 3.13.17', source: 'python.org', size: 11e6, installed: false },
  { name: 'wheels', label: 'bpy 5.2.2, numpy 2.5.3 and 11 more', source: 'PyPI (files.pythonhosted.org)', size: 380e6, installed: false },
]
const status = (fields = {}) => ({ platform: 'win-x64', supported: true, state: 'not_installed', download_bytes: 791e6,
  needed_bytes: 791e6, disk_bytes: 1.62e9, disk_estimated: true, pieces: PIECES, path: 'C:\\Data\\tools\\model-import',
  job: null, error: null, ...fields })
const draw = (tools, job = null, extra = {}) =>
  renderToStaticMarkup(React.createElement(ModelImportToolsView, { view: helpers.toolsView(tools, job), ...extra }))

test('not installed: what the tools are for, the sizes, the sources and Download', () => {
  const html = draw(status())
  assert.match(html, /<h3>Model import tools<\/h3>/)
  assert.match(html, /import_model from your own AI/)
  assert.match(html, /class="ai-chip">791 MB download<\/span><span class="ai-chip">1\.6 GB on disk</)
  // 0.9.0 build 3 smoke: it read "… and 11 more (PyPI (files.pythonhosted.org))".
  assert.match(html, />Blender 4\.3\.2 from download\.blender\.org; Python 3\.13\.17 from python\.org; bpy 5\.2\.2, numpy 2\.5\.3 and 11 more from PyPI \(files\.pythonhosted\.org\)\. Each file is checked/)
  assert.doesNotMatch(html, /\(PyPI \(/)
  assert.match(html, /role="status">Not installed</)
  assert.match(html, />Download \(791 MB\)<\/button>/)
  assert.doesNotMatch(html, />Remove<|>Cancel<|update-progress-track/)
})

test('downloading: a progress bar, its line and Cancel', () => {
  const html = draw(status(), { id: 'j', status: 'running', progress: 0.42, detail: 'Downloading bpy 5.2.2 (120 of 338 MB)' })
  assert.match(html, /role="status">Downloading · 42%</)
  assert.match(html, /class="update-progress-fill" style="width:42%"/)
  assert.match(html, /Downloading bpy 5\.2\.2 \(120 of 338 MB\)/)
  assert.match(html, />Cancel<\/button>/)
  assert.doesNotMatch(html, />Download \(|>Remove</)
})

test('paused: what is in, what is left, and Resume, all in the same sizes', () => {
  // 0.9.0 build 3 smoke: after Cancel at 168 MB the card said "Not installed" and "Download (609 MB)" under "about 779 MB".
  const html = draw(status({ state: 'paused', download_bytes: 779e6, needed_bytes: 611e6, downloaded_bytes: 168e6 }))
  assert.match(html, /role="status">Paused · 168 of 779 MB</)
  assert.match(html, /class="ai-chip">611 MB left of 779 MB<\/span><span class="ai-chip">1\.6 GB on disk</)
  assert.match(html, />Resume \(611 MB\)<\/button>/)
  assert.match(html, /What came down is kept, and Resume\s+carries on from there\./)
  assert.doesNotMatch(html, /Not installed|>Download \(|>Remove<|>Cancel<|update-progress-track/)
})

test('installed: ready, where they are, and Remove with a confirm', () => {
  const tools = status({ state: 'installed', needed_bytes: 0, disk_bytes: 1.58e9, disk_estimated: false,
    pieces: PIECES.map(piece => ({ ...piece, installed: true })) })
  const html = draw(tools)
  assert.match(html, /On disk: 1\.6 GB/)
  assert.match(html, /role="status">Installed</)
  assert.doesNotMatch(html, /class="ai-chip"/, 'no download size once installed')
  assert.match(html, /In C:\\Data\\tools\\model-import/)
  assert.match(html, />Remove<\/button>/)
  const confirm = draw(tools, null, { confirming: true })
  assert.match(confirm, /Remove the tools\? You can download them again\./)
  assert.match(confirm, /class="btn-cancel">Keep<\/button>/)
  assert.match(confirm, /class="btn-confirm">Remove<\/button>/)
})

test('update needed, failed and not available say so in words', () => {
  const update = draw(status({ state: 'update_needed', needed_bytes: 380e6, pieces: [{ ...PIECES[0], installed: true }] }))
  assert.match(update, /role="status">Update needed</)
  assert.match(update, />Update \(380 MB\)<\/button>/)
  assert.match(update, />Remove<\/button>/)
  const failed = draw(status({ state: 'failed', error: 'The download of Blender 4.3.2 did not match its pinned checksum.' }))
  assert.match(failed, /class="update-status-error">The download of Blender 4\.3\.2 did not match its pinned checksum\.</)
  assert.match(failed, />Try again<\/button>/)
  const other = draw(status({ supported: false, state: 'unsupported', pieces: [], download_bytes: 0, needed_bytes: 0, disk_bytes: 0 }))
  assert.match(other, /Not available on this computer/)
  assert.doesNotMatch(other, /<button/)
})

test('the card reads the hook: the live job and a refused request', () => {
  hookState = { tools: status(), job: { id: 'j', status: 'queued', progress: null, detail: '' }, busy: false,
    requestError: null, start() {}, cancel() {}, remove() {} }
  assert.match(renderToStaticMarkup(React.createElement(Section)), /role="status">Downloading</)
  hookState = { ...hookState, job: null, requestError: 'Another download is running.' }
  assert.match(renderToStaticMarkup(React.createElement(Section)), /Another download is running\./)
})

test('Settings shows the card in the AI category beside the MCP card, under the same build gate and no other', () => {
  const settings = readFileSync(new URL('./Settings.jsx', import.meta.url), 'utf8')
  assert.match(settings, /const aiTab = ASSISTANT_ENABLED && !RECORD_MODE\r?\n/)
  assert.match(settings, /\.\.\.\(aiTab \? \[\{ id: 'ai', label: 'AI', cards: <>\r?\n\s*<McpSection \/>\r?\n.*\r?\n\s*<ModelImportToolsSection \/>\r?\n\s*<CreationToolkitSection \/>/)
  assert.equal(settings.match(/<ModelImportToolsSection \/>/g).length, 1, 'only in the AI category')
  const source = readFileSync(new URL('./ModelImportToolsSection.jsx', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /patreon|entitle|isPremium/i, 'open to everyone')
})
