import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'


// The card now renders real results through the shared task cards, so those
// modules are loaded for real instead of stubbed away.
const loadModule = (file, resolve) => {
  const built = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', built)(
    name => resolve(name) || createRequire(import.meta.url)(name), mod, mod.exports)
  return mod.exports
}
const activityModule = loadModule('./activity.js', () => null)
const envelopeModule = loadModule('./taskEnvelope.js', () => null)
const taskCardsModule = loadModule('./TaskCards.jsx', name => name === './activity' ? activityModule
  : name === './taskEnvelope' ? envelopeModule : null)
const sharedModule = name => name === './activity' ? activityModule
  : name === './taskEnvelope' ? envelopeModule
    : name === './TaskCards' ? taskCardsModule : null

const source = readFileSync(new URL('./ModFileCards.jsx', import.meta.url), 'utf8')
const compiled = transformSync(source, { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
const realRequire = createRequire(import.meta.url)
const EditorContext = React.createContext({ editor: { texture: {} } })
// Developer details (the settings switch): off unless a test turns it on.
let devDetails = false
const require = name => {
  if (name === './devDetails') return { useDevDetails: () => devDetails }
  if (name === '../../shared/lib/EditorContext') return { EditorContext }
  if (name === '../../shared/config/config') return { backendMediaUrl: value => value }
  if (name === './DownloadProgress') return { DownloadActivity: ({ label }) => React.createElement('span', null, label) }
  if (sharedModule(name)) return sharedModule(name)
  if (name.startsWith('.')) return { __esModule: true, default: () => null }
  return realRequire(name)
}
new Function('require', 'module', 'exports', compiled)(require, module, module.exports)
const render = tool => renderToStaticMarkup(React.createElement(module.exports.ModToolActivity, { tool }))
const file = { file_id: 'abc', name: 'Material.png', extension: '.png', size: 100 }

test('clone results show the costume sheet, package download and vault destination', () => {
  const html = render({ name: 'create_clone_character', status: 'done', result: {
    vault_changed: true, character: { name: 'Neos', costume_count: 5 }, note: 'Gameplay untested.',
    files: [{ ...file, name: 'Neos costumes.png', preview_only: true },
      { file_id: 'zip', name: 'Neos.zip', extension: '.zip', size: 1000 }],
  } })
  assert.match(html, /Neos is in Custom Characters/)
  assert.match(html, /5 costumes/)
  assert.match(html, /Neos.zip/)
  assert.match(html, /Download file/)
  assert.doesNotMatch(html, /Use on selected texture/)
  assert.match(render({ name: 'create_clone_character', status: 'running', result: { progress_label: 'Rendering blue portrait' } }), /Rendering blue portrait/)
})

test('generated swatches stay inside a closed tool row; only developer details show their cost', () => {
  const tool = { name: 'generate_material', status: 'done', result: { reading: true, files: [file], cost_usd: 0.014 } }
  const html = render(tool)
  assert.match(html, /A new material/)
  assert.doesNotMatch(html, /\$|Image generation/)
  assert.match(html, /<details[^>]*>[\s\S]*<img[\s\S]*<\/details>/)
  assert.doesNotMatch(html, /<details[^>]*\sopen/)
  assert.equal((html.match(/<img/g) || []).length, 1)
  devDetails = true
  try { assert.match(render(tool), /Image generation: \$0\.0140/) } finally { devDetails = false }
})

test('mask sheets cannot be applied as texture replacements; rendered edits remain visible', () => {
  const mask = render({ name: 'skin_material', status: 'done', result: { reading: true, files: [{ ...file, preview_only: true }] } })
  assert.doesNotMatch(mask, /Use on selected texture/)
  const applied = render({ name: 'skin_material', status: 'done', result: { note: 'Applied', files: [{ ...file, preview_only: true }] } })
  assert.match(applied, /<\/details>[\s\S]*<img/)
  assert.doesNotMatch(applied, /Use on selected texture/)
})

test('generation exposes its own working state and provider errors', () => {
  assert.match(render({ name: 'generate_material', status: 'running' }), /Drawing a new material/)
  // A failure says what happened, what survived it and one thing to do next.
  // shared/aiengine/image_api.py USED_UP: no provider, credit or money words.
  const failed = render({ name: 'generate_material', status: 'error', result: {
    error: "This month's Randall usage is used up, so no image was generated.", diagnostic: 'image provider HTTP 402' } })
  assert.match(failed, /role="alert"[\s\S]*Randall usage is used up, so no image was generated/)
  assert.doesNotMatch(failed, /HTTP 402|image provider/)
  assert.match(failed, /Everything finished before this is kept/)
  assert.match(failed, /Tell Randall what to try instead/)
})

test('a refused material says why in one plain sentence instead of the generic failure', () => {
  // assistant/refusals.py: the turn's images were used up before this call was sent.
  const sentence = 'This request already generated its three images; ask again in a new message to make more.'
  const html = render({ name: 'generate_material', status: 'error', result: {
    error: sentence, refusal: 'image_allowance', next: 'Model-only: do not call generate_material again now.' } })
  assert.match(html, /role="alert"[\s\S]*already generated its three images; ask again in a new message to make more/)
  assert.match(html, /Everything finished before this is kept/)
  assert.doesNotMatch(html, /could not complete|backend log|Tell Randall what to try instead|try this again/)
  assert.doesNotMatch(html, /Model-only/)
  const limit = render({ name: 'generate_material', status: 'error', result: { refusal: 'spending_limit',
    error: 'This request reached its usage limit, so this step did not run; send a new message to carry on.' } })
  assert.match(limit, /reached its usage limit, so this step did not run; send a new message to carry on/)
  assert.doesNotMatch(limit, /could not complete|backend log|\$/)
})

test('an unexpected failure keeps the generic sentence, and its detail stays off the card', () => {
  const html = render({ name: 'generate_material', status: 'error', result: {
    error: 'The tool could not complete. Your request was not reported as successful; check the backend log.',
    diagnostic: 'RuntimeError: internal detail' } })
  assert.match(html, /The tool could not complete/)
  assert.match(html, /Tell Randall what to try instead/)
  assert.doesNotMatch(html, /RuntimeError|internal detail/)
})

test('mesh selection and repair evidence stays in model rows without texture controls', () => {
  // The labels are the user's words now: "mesh selection" and "revised draft"
  // are the pipeline's names for these steps, not anybody else's.
  for (const [name, operation, label, progress] of [
    ['model_mesh', 'mesh', 'Which parts of the model to keep', 'Choosing which parts to keep'],
    ['model_revise', 'revise', 'The repaired draft', 'Repairing the costume'],
  ]) {
    const html = render({ name, status: 'done', result: { operation, reading: true, files: [{ ...file, preview_only: true }] } })
    assert.match(html, new RegExp(label))
    assert.match(html, /<details[^>]*>[\s\S]*<img[\s\S]*<\/details>/)
    assert.doesNotMatch(html, /<details[^>]*\sopen|Use on selected texture/)
    assert.match(render({ name, status: 'running' }), new RegExp(progress))
  }
})

test('a stored chat from the retired first import shows its export as a plain label', () => {
  // The first model import returned `operation: 'export'` results. Nothing
  // produces them now, but stored chats still hold them: they render as the
  // step's label and its file, not as a result card.
  const html = render({ name: 'model_candidate', status: 'done', result: { operation: 'export', file_id: 'f1',
    warnings: ['The file did not read back the same.'],
    files: [{ file_id: 'f1', name: 'PlFxNr.dat', extension: '.dat', size: 2048 }] } })
  assert.match(html, /class="assistant-file-label">The costume file</)
  assert.match(html, /PlFxNr\.dat/)
  assert.doesNotMatch(html, /flagged a few things|ready to look at|did not read back/)
})

test('a retexture saved when its turn ended says saved or updated, and shows its progress line while it runs', () => {
  // backend randall/recolor/autosave.py: the receipt a save makes, its result marked `autosave`.
  const costume = autosave => ({ name: 'save_mod_copy', status: 'done', result: { autosave, vault_changed: true,
    note: 'Saved automatically when the turn ended.', items: [], files: [] } })
  const saved = render(costume('saved'))
  assert.match(saved, /Saved to your vault/)
  assert.match(saved, /role="status">Saved to your vault automatically</)
  assert.doesNotMatch(saved, /Edited copy added to vault/)
  const updated = render(costume('updated'))
  assert.match(updated, /Updated in your vault/)
  assert.match(updated, /role="status">Your vault copy now has this version</)
  // A save asked for keeps its own words.
  assert.match(render({ name: 'save_mod_copy', status: 'done', result: { vault_changed: true, items: [], files: [] } }),
    /role="status">Edited copy added to vault</)
  const stage = render({ name: 'stage_lab', status: 'done', arguments: { action: 'save' }, result: { autosave: 'updated',
    vault_changed: true, variantId: 'dreamland-candy-1a2b', folder: 'dreamland', stageCode: 'GrOp', name: 'Dreamland - Candy',
    files: [{ file_id: 'shot', name: 'Updated in vault.png', extension: '.png', size: 100 }] } })
  assert.match(stage, /Updated in your vault/)
  assert.match(stage, /Your vault copy now has this version/)
  assert.match(render({ name: 'stage_lab', status: 'running', result: { progress_label: 'Saving the stage to your vault' } }),
    /Saving the stage to your vault/)
  // Not saved: the plain sentence, and nothing says it is in the vault.
  const failed = render({ name: 'save_mod_copy', status: 'error', result: { refusal: 'not_saved',
    error: 'Not saved to your vault: the vault could not be written (OSError). Your edits are kept, and the next message tries again.' } })
  assert.match(failed, /role="alert"[\s\S]*Not saved to your vault: the vault could not be written/)
  assert.doesNotMatch(failed, /Saved to your vault|added to vault|Tell Randall what to try instead/)
})
