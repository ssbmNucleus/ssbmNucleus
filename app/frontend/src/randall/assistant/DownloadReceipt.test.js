// What a person is shown AFTER a download, including the two cases where
// nothing landed. The fixtures are the result shapes from
// tests/backend/test_assistant_website_approval.py: the detected type and
// destination on a receipt, the ledger's repeat result, the scope refusals, and
// `apply_download`'s choice_dialog branch.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

const realRequire = createRequire(import.meta.url)
const load = (file, resolve) => {
  const built = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', built)(
    name => resolve(name) || realRequire(name), mod, mod.exports)
  return mod.exports
}
const dialog = load('./DownloadApprovalDialog.jsx', name => name === '../../shared/transport/api'
  ? { api: { get: async () => ({}) } } : name === 'react-dom' ? { createPortal: () => null } : null)
const receipts = load('./downloadReceipts.js', () => null)
const module = load('./DownloadReceipt.jsx', name => {
  if (name === '../../shared/config/config') return { backendMediaUrl: value => value }
  if (name === './downloadReceipts') return receipts
  if (name === './StageModCard') return { __esModule: true, default: () => null }
  if (name === './DownloadApprovalDialog') return dialog
  return null
})

const render = result => renderToStaticMarkup(
  React.createElement(module.default, { result, onOpenVault: () => {} }))
const HASH = 'b1946ac92492d2347c6235b4d2611184b1946ac92492d2347c6235b4d2611184'
const mod = { post_id: 123, title: 'Halo CSS', image: '/x.png', tags: ['Assets/Other'] }

test('a menu file receipt says what landed and where it landed', () => {
  const html = render({
    website_mods: [mod], imported_count: 1, skipped_count: 0, vault_changed: true,
    note: 'Imported CSS background',
    detected: { type: 'css_background', confidence: 'explicit', sha256: HASH,
      destination: 'Menus › Character Select › Backgrounds', executable_members: [] },
  })
  assert.match(html, /Added to vault/)
  assert.match(html, /Added to your vault’s Menus section, under Character Select › Backgrounds\./)
  assert.match(html, /Exactly which file was added/)
  assert.match(html, />b1946ac92492…</)
})

test('a repeat of a finished download never claims the vault changed', () => {
  // The ledger returns the stored result with the counts it had the first time.
  const html = render({
    website_mods: [mod], imported_count: 1, skipped_count: 0, vault_changed: false,
    repeat_of_completed_download: true,
    note: 'This exact download already completed and its item is in your vault, so it was not '
      + 'downloaded again. Import the file yourself if you really want a second copy.',
    detected: { type: 'css_background', sha256: HASH, destination: 'Menus › Character Select › Backgrounds' },
  })
  assert.match(html, /Already in your vault/)
  assert.doesNotMatch(html, /Added to vault/)
  assert.match(html, /It is in your vault’s Menus section, under Character Select › Backgrounds\./)
  assert.match(html, /already completed and its item is in your vault/)
})

test('costumes the importer itself skipped are called out as already owned', () => {
  const html = render({
    website_mods: [mod], imported_count: 1, skipped_count: 2, vault_changed: true,
    imported_items: [{ id: 'c1', character: 'Marth', name: 'Blue Marth', kind: 'costume' }],
    note: 'ok',
  })
  assert.match(html, /2 already in your vault/)
})

test('a published costume that is really a fighter package is refused, in plain words', () => {
  const html = render({
    website_mods: [mod], imported_count: 0, vault_changed: false, approval_status: 'denied',
    declared_types: ['character_dat'],
    error: 'The post publishes this as character_dat, but the downloaded file is custom_character '
      + 'and would land in Vault > Custom Characters. Nothing was imported - inspect the mod and '
      + 'download it again if that is really what you want.',
    note: 'Nothing was imported. The downloaded files are not what this post said they are, so the '
      + 'approval you gave does not cover them.',
    detected: { type: 'custom_character', destination: 'Vault > Custom Characters', sha256: HASH,
      executable_members: [] },
  })
  assert.match(html, /Nothing was added to your vault\./)
  assert.match(html, /This file is a whole custom character, not a costume as the post said\./)
  assert.match(html, /belongs in your vault’s Custom Characters section/)
  assert.match(html, /the approval you gave does not cover them/)
  // The backend's own sentence is kept, but it is not the headline: it names
  // internal types the user has never seen.
  assert.match(html, /What Nucleus found in the file/)
  assert.match(html, /but the downloaded file is custom_character/)
  assert.match(html, /role="alert"/)
})

test('an executable member is refused with its consequence, not a scare wall', () => {
  const html = render({
    website_mods: [mod], imported_count: 0, vault_changed: false, approval_status: 'denied',
    error: 'This download contains program files (installer.exe). Nucleus never installs those, '
      + 'so nothing was imported.',
    detected: { type: 'character', destination: 'Vault > Characters (costumes)', sha256: HASH,
      executable_members: ['installer.exe'] },
  })
  assert.match(html, /Nothing was added to your vault\./)
  assert.match(html, /carries a program file/)
  assert.match(html, /installer\.exe/)
  assert.match(html, /Nucleus never installs programs, so nothing was imported\./)
  assert.doesNotMatch(html, /Added to vault/)
})

test('a file that can be imported in more than one way shows each answer’s destination', () => {
  const html = render({
    website_mods: [mod], imported_count: 0, vault_changed: false, choice_required: true,
    choice: {
      question: 'This character-select file carries both the icons and the backdrop. Which do you want?',
      options: [
        { key: 'css_icon_grid', label: 'The character icons', description: 'The little heads',
          destination: 'Menus › Character Select › Icon Grids' },
        { key: 'css_background', label: 'The backdrop', description: '',
          destination: 'Menus › Character Select › Backgrounds' },
      ],
      default: 'css_icon_grid',
    },
    note: 'Nothing was imported yet: this file can be imported in more than one way and needs your '
      + 'answer. Choose an option and download it again.',
  })
  assert.match(html, /Nothing was added yet: this file can be used in more than one way\./)
  assert.match(html, /carries both the icons and the backdrop/)
  assert.match(html, /Goes into your vault’s Menus section, under Character Select › Icon Grids/)
  assert.match(html, /Goes into your vault’s Menus section, under Character Select › Backgrounds/)
  assert.match(html, /Choose an option and download it again\./)
})
