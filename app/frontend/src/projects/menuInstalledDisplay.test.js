import test from 'node:test'
import assert from 'node:assert/strict'
import { installedPreviewCandidates, partialIconText, slotDisplay, CHECKED_SLOTS } from './menuInstalledDisplay.js'

test('snapshot first, then the vault URLs', () => {
  assert.deepEqual(installedPreviewCandidates({
    snapshotUrl: '/api/mex/menus/installed/preview/hud/ready_go?v=1',
    screenshotUrl: '/storage/menus/x/shot.png',
    imageUrl: '/api/mex/menus/percent/image/abc',
  }), [
    '/api/mex/menus/installed/preview/hud/ready_go?v=1',
    '/storage/menus/x/shot.png',
    '/api/mex/menus/percent/image/abc',
  ])
})

test('older records without a snapshot keep their vault URL', () => {
  assert.deepEqual(installedPreviewCandidates({ imageUrl: '/api/mex/menus/pause/image/p1' }),
    ['/api/mex/menus/pause/image/p1'])
})

test('nothing to show falls back to the placeholder', () => {
  assert.deepEqual(installedPreviewCandidates({ name: 'Grid' }), [])
  assert.deepEqual(installedPreviewCandidates(null), [])
  assert.deepEqual(installedPreviewCandidates({ imageUrl: '' }), [])
})

test('duplicate URLs are tried once', () => {
  assert.deepEqual(installedPreviewCandidates({ screenshotUrl: '/a.png', imageUrl: '/a.png' }), ['/a.png'])
})

test('partial icon installs say how many landed', () => {
  assert.equal(partialIconText({ icons_installed: ['Mario', 'Fox'], icons_total: 26 }), '2 of 26 icons installed')
  assert.equal(partialIconText({ icons_installed: Array(26).fill('x'), icons_total: 26 }), null)
  assert.equal(partialIconText({ icons_installed: ['Mario'] }), null)
  assert.equal(partialIconText({ icon_count: 26 }), null)
  assert.equal(partialIconText(undefined), null)
})

test('HUD slot: no check result shows the record as before', () => {
  assert.deepEqual(slotDisplay({ name: 'Melee Bold' }, undefined), { kind: 'mod', note: null })
  assert.deepEqual(slotDisplay(undefined, undefined), { kind: 'vanilla', note: null })
})

test('HUD slot: file matches the recorded mod', () => {
  assert.deepEqual(slotDisplay({ name: 'Melee Bold' }, { state: 'installed' }), { kind: 'mod', note: null })
  assert.deepEqual(slotDisplay({ name: 'Old' }, { state: 'installed', unverified: true }), { kind: 'mod', note: null })
})

test('HUD slot: vanilla file, with and without a stale record', () => {
  assert.deepEqual(slotDisplay(undefined, { state: 'vanilla', stale: false }), { kind: 'vanilla', note: null })
  const d = slotDisplay({ name: 'Melee Bold' }, { state: 'vanilla', stale: true })
  assert.equal(d.kind, 'vanilla')
  assert.match(d.note, /Melee Bold/)
})

test('HUD slot: custom file nobody recorded, or one that no longer matches the record', () => {
  const unknown = slotDisplay(undefined, { state: 'custom', stale: false })
  assert.equal(unknown.kind, 'custom')
  assert.match(unknown.note, /outside Nucleus/)
  const mismatch = slotDisplay({ name: 'Melee Bold' }, { state: 'custom', stale: true })
  assert.equal(mismatch.kind, 'custom')
  assert.match(mismatch.note, /no longer matches Melee Bold/)
})

test('every checked slot belongs to the menu it is fetched with', () => {
  for (const [menu, keys] of Object.entries(CHECKED_SLOTS)) {
    for (const key of keys) assert.equal(key.split(':')[0], menu)
  }
  assert.deepEqual(Object.keys(CHECKED_SLOTS).sort(), ['css', 'hud', 'sss'])
})
