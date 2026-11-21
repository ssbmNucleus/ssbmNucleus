import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

const realRequire = createRequire(import.meta.url)
const load = (file, resolve = () => null) => {
  const built = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', built)(name => resolve(name) || realRequire(name), mod, mod.exports)
  return mod.exports
}

// The 3D view and the game are Electron's; the panel is drawn around stand-ins that say what they were given.
const workbench = await import('./workbench.js')
const { default: WorkbenchPanel } = load('./WorkbenchPanel.jsx', name => ({
  '../../shared/config/config': { backendMediaUrl: value => `http://backend${value}` },
  './GameTestCard': { __esModule: true, default: ({ tool }) => React.createElement('div', { className: 'stub-game' }, tool.id) },
  './WorkbenchViewer': { __esModule: true,
    default: ({ model }) => React.createElement('div', { className: 'stub-viewer' }, `${model.fileId} on ${model.character}`) },
  './workbench': workbench,
  './WorkbenchPanel.css': {},
})[name] || null)

const png = (id, name = `${id}.png`) => ({ file_id: id, name, extension: '.png' })
const dat = (id, name = `${id}.dat`) => ({ file_id: id, name, extension: '.dat' })
const turn = (...tools) => ({ role: 'assistant', tools })
let n = 0
const tool = (name, result, extra = {}) => ({ id: `p${++n}`, name, status: 'done', result, ...extra })
const render = (messages, { game = null, open = true } = {}) => {
  const state = workbench.workbenchState(messages, game?.id || null)
  return renderToStaticMarkup(React.createElement(WorkbenchPanel, { state, visible: true, open, onOpenChange: () => {},
    gameTool: game, chatId: 'c1', onAttach: () => {} }))
}
const tabs = html => [...html.matchAll(/role="tab"[^>]*>([^<]+)/g)].map(match => match[1])

const tag = { studio_import: { tool: 'import_model', id: 'clank-58524d' }, project: 'clank-58524d', fighter: 'Pichu' }
const imported = tool('import_model', { ...tag, status: 'done', saved: { name: 'Clank' },
  files: [png('csp', 'finish_csp.png'), dat('pichu', 'Pichu.dat')] })

test('during an import the panel is not there: the chat card carries the steps', () => {
  const running = tool('import_model', { ...tag, status: 'running', step: 'loading the model' }, { status: 'running' })
  assert.equal(render([turn(running)]), '')
  assert.equal(render([turn(running)], { open: false }), '', 'not even the slim Workbench tab')
})

test('a finished import opens on its costume in 3D, titled with the costume and its fighter, no Pictures', () => {
  const html = render([turn(imported)])
  assert.match(html, /<strong>Clank on Pichu<\/strong>/)
  assert.deepEqual(tabs(html), ['3D'])
  assert.match(html, /stub-viewer">pichu on Pichu/)
  assert.doesNotMatch(html, /workbench-step/, 'no step under the title')
  assert.doesNotMatch(html, /Pictures|workbench-picture|until this import writes/)
  assert.doesNotMatch(html, /No file yet/)
})

test('a tested import adds In game', () => {
  const game = tool('test_in_game', { game_test: { session_id: 'x', label: 'Pichu — Clank' } })
  const html = render([turn(imported, game)], { game })
  assert.deepEqual(tabs(html), ['3D', 'In game'])
  assert.match(html, /aria-selected="true"[^>]*>In game/)
  assert.match(html, /stub-game">p\d+/)
  assert.match(html, /<strong>Clank on Pichu<\/strong>/)
})

test('a Skin Lab costume has 3D and Pictures, and its step under the title', () => {
  const target = { character: 'Fox' }
  const opened = tool('skin_lab_open', { session_id: 's1', source_file_id: 'src', skin_target: target })
  const edit = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp1'), skin_target: target,
    files: [png('recolor-1', 'Recolor before and after.png'), png('recolor-2')] })
  const html = render([turn(opened, edit)])
  assert.match(html, /<strong>Fox costume<\/strong>/)
  assert.deepEqual(tabs(html), ['3D', 'Pictures'])
  assert.match(html, /workbench-count">2</)
  assert.match(html, /class="workbench-step">[^<]*</)
  // The 3D view is the costume's newest checkpoint.
  assert.match(html, /stub-viewer">cp1 on Fox/)
})

test('a lab with nothing made yet says so plainly', () => {
  const opened = tool('skin_lab_open', { session_id: 's2' }, { arguments: {} })
  const running = tool('skin_lab', {}, { status: 'running', arguments: { session_id: 's2' } })
  const html = render([turn(opened, running)])
  assert.match(html, /Nothing to show in 3D yet\./)
  assert.doesNotMatch(html, /Randall's pictures are in Pictures/)
})

test('hidden: the slim tab, its pulse only while a lab step runs', () => {
  assert.match(render([turn(imported)], { open: false }), /class="workbench-reopen"/)
  assert.doesNotMatch(render([turn(imported)], { open: false }), /assistant-work-pulse/)
  const opened = tool('stage_lab_open', { session_id: 'g1', checkpoint_file: dat('base'),
    stage_target: { stage_code: 'GrNBa', name: 'Battlefield' } })
  const running = tool('stage_lab', {}, { status: 'running', arguments: { session_id: 'g1' } })
  assert.match(render([turn(opened, running)], { open: false }), /assistant-work-pulse/)
})
