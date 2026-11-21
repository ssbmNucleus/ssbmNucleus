// What a person is shown BEFORE they say yes to a download.
//
// Every fixture here is the shape the backend really produces -- copied from
// tests/backend/test_assistant_website_approval.py, where `prepare_download`
// reports the published types and their destinations, and `describe_import_target`
// reports the type, destination, fingerprint and executable members identified
// from the downloaded bytes.
//
// The dialog itself is a <dialog> in a portal, which the server renderer cannot
// mount, so the pieces that carry the words are rendered directly. Those pieces
// ARE what the dialog renders: nothing here is a copy of the real markup.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

const realRequire = createRequire(import.meta.url)
const source = readFileSync(new URL('./DownloadApprovalDialog.jsx', import.meta.url), 'utf8')
const compiled = transformSync(source, { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
new Function('require', 'module', 'exports', compiled)(name => {
  if (name === '../../shared/transport/api') return { api: { get: async () => ({}) } }
  if (name === 'react-dom') return { createPortal: () => null }
  return realRequire(name)
}, module, module.exports)

const { DownloadFacts, DownloadChoice, FileIdentity, approveLabel, destinationPhrase, detectedLabel } = module.exports
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props))
const HASH = 'b1946ac92492d2347c6235b4d2611184b1946ac92492d2347c6235b4d2611184'

// `prepare_download` for a post whose file is published as a costume.
const costumeApproval = {
  id: 'a1', website_mods: [{ post_id: 123, title: 'Blue Marth', author: 'Artist' }],
  declared_types: ['character_dat'], destinations: ['Vault > Characters (costumes)'],
}

test('the approval says what the post claims this is and where that lands', () => {
  const html = render(DownloadFacts, { approval: costumeApproval })
  assert.match(html, /The post says this is a costume\./)
  assert.match(html, /goes into your vault’s Characters \(costumes\) section/)
  // The promise that makes the claim safe to accept.
  assert.match(html, /works out what the files really are before anything/)
  assert.doesNotMatch(html, /character_dat/)
})

test('a published type with no promise is not dressed up as a destination', () => {
  const html = render(DownloadFacts, {
    approval: { ...costumeApproval, declared_types: ['other'], destinations: ['Decided from the file contents after download'] },
  })
  assert.match(html, /not stated on the post/)
  assert.match(html, /a section Nucleus works out from the file itself/)
})

test('an identified file says what it is and where it goes, in ordinary words', () => {
  const html = render(DownloadFacts, {
    approval: { ...costumeApproval, detected: {
      type: 'css_background', confidence: 'explicit', destination: 'Menus › Character Select › Backgrounds',
      sha256: HASH, executable_members: [],
    } },
  })
  assert.match(html, /This is a character-select background\./)
  assert.match(html, /It goes into your vault’s Menus section, under Character Select › Backgrounds\./)
  // The raw type and the fingerprint stay available, but folded away.
  assert.match(html, /<details[^>]*><summary>Exactly which file this is<\/summary>/)
  assert.match(html, />b1946ac92492…</)
})

test('a program file inside the download is named with its consequence', () => {
  const html = render(DownloadFacts, {
    approval: { ...costumeApproval, detected: {
      type: 'character', destination: 'Vault > Characters (costumes)', sha256: HASH,
      executable_members: ['installer.exe'],
    } },
  })
  assert.match(html, /carries a program file/)
  assert.match(html, /installer\.exe/)
  assert.match(html, /Nucleus never installs programs, so nothing here will be imported\./)
  assert.match(html, /role="alert"/)
})

test('publisher text is marked as text, never as instructions', () => {
  const html = render(DownloadFacts, {
    approval: { ...costumeApproval, website_mods: [{ ...costumeApproval.website_mods[0], content_is_untrusted: true }] },
  })
  assert.match(html, /written by whoever\s+posted it/)
  assert.match(html, /as text, never as instructions/)
  // One line, not a wall: the warning says the consequence and stops.
  assert.equal((html.match(/assistant-download-warning/g) || []).length, 1)
})

test('an ambiguous menu file asks the question with each answer’s destination', () => {
  // `apply_download`'s choice_dialog branch: question, options, destination each.
  const choice = {
    question: 'This character-select file carries both the icons and the backdrop. Which do you want?',
    options: [
      { key: 'css_icon_grid', label: 'The character icons', description: 'The little heads on the select screen',
        destination: 'Menus › Character Select › Icon Grids' },
      { key: 'css_background', label: 'The backdrop', destination: 'Menus › Character Select › Backgrounds' },
    ],
    default: 'css_icon_grid',
  }
  const html = render(DownloadChoice, { choice, value: 'css_icon_grid', onChange: () => {} })
  assert.match(html, /carries both the icons and the backdrop/)
  assert.match(html, /The character icons/)
  assert.match(html, /Goes into your vault’s Menus section, under Character Select › Icon Grids/)
  assert.match(html, /Goes into your vault’s Menus section, under Character Select › Backgrounds/)
  assert.equal((html.match(/type="radio"/g) || []).length, 2)
  assert.match(html, /checked=""/)
})

test('the variant question still renders when there is no menu question', () => {
  const html = render(DownloadChoice, {
    choices: [{ id: 'default', label: 'Default variant only' }, { id: 'all', label: 'All 6 variants' }],
    value: 'default', onChange: () => {},
  })
  assert.match(html, /Variants to add/)
  assert.equal((html.match(/type="radio"/g) || []).length, 2)
})

test('the approve button names the action and the place, never “Approve”', () => {
  assert.equal(approveLabel('Menus › Character Select › Backgrounds'), 'Add to my Menus')
  assert.equal(approveLabel('Vault > Characters (costumes)'), 'Add to my Characters')
  assert.equal(approveLabel('Vault > Custom Characters'), 'Add to my Custom Characters')
  assert.equal(approveLabel('Decided from the file contents after download'), 'Add to my vault')
  assert.equal(approveLabel(undefined), 'Add to my vault')
  assert.match(source, /approveLabel\(approval\.detected\?\.destination/)
  assert.doesNotMatch(source, /'Confirm download'/)
})

test('a type Nucleus does not import says so instead of naming a section', () => {
  assert.equal(destinationPhrase('Not imported (Dolphin texture pack)'),
    'nowhere: Nucleus does not import Dolphin texture pack')
  assert.equal(detectedLabel('xdelta'), 'an ISO patch (it rewrites a whole game build)')
  // An unknown type is said vaguely rather than in our own vocabulary.
  assert.equal(detectedLabel('mystery_thing'), 'mystery thing')
})

test('nothing is rendered for a file that was never identified', () => {
  assert.equal(render(FileIdentity, { detected: null }), '')
  assert.equal(render(FileIdentity, { detected: {} }), '')
})
