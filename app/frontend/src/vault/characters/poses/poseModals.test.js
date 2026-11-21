import test from 'node:test'
import assert from 'node:assert/strict'

import { isTextEntry, poseManagerEscape, skinSelectorEscape } from './poseModalKeys.js'
import { skinCspVersion } from './poseSkinCards.js'

test('Escape closes the Pose Manager and Generate CSPs, innermost first (0.9.0 hand-check)', () => {
  assert.equal(poseManagerEscape({ key: 'Escape' }), 'close')
  assert.equal(poseManagerEscape({ key: 'Enter' }), null)
  assert.equal(poseManagerEscape({ key: 'Escape', modelMenuOpen: true, creating: true }), 'menu')
  assert.equal(poseManagerEscape({ key: 'Escape', creating: true }), 'library', 'Create Pose steps back to the list')
  // Generate CSPs on top answers it; the Pose Manager underneath stays
  assert.equal(poseManagerEscape({ key: 'Escape', skinSelectorOpen: true }), null)
  assert.equal(skinSelectorEscape({ key: 'Escape' }), 'close')
  assert.equal(skinSelectorEscape({ key: 'Escape', generating: true }), null, 'not while it renders')
})

test('a hidden modal, a dialog on top or a text field in Create Pose keep the modal open', () => {
  assert.equal(poseManagerEscape({ key: 'Escape', hidden: true }), null, 'hidden behind another tab')
  assert.equal(skinSelectorEscape({ key: 'Escape', hidden: true }), null)
  assert.equal(poseManagerEscape({ key: 'Escape', defaultPrevented: true }), null, 'an app dialog took it')
  assert.equal(skinSelectorEscape({ key: 'Escape', defaultPrevented: true }), null)
  assert.equal(poseManagerEscape({ key: 'Escape', creating: true, typing: true }), null, 'naming the pose')
  assert.equal(poseManagerEscape({ key: 'Escape', typing: true }), 'close', 'the list has nothing to lose')
})

test('a text field is any input you type into, not a button or checkbox', () => {
  assert.equal(isTextEntry({ tagName: 'INPUT', type: 'text' }), true)
  assert.equal(isTextEntry({ tagName: 'input' }), true)
  assert.equal(isTextEntry({ tagName: 'INPUT', type: 'search' }), true)
  assert.equal(isTextEntry({ tagName: 'TEXTAREA' }), true)
  assert.equal(isTextEntry({ tagName: 'DIV', isContentEditable: true }), true)
  assert.equal(isTextEntry({ tagName: 'INPUT', type: 'checkbox' }), false)
  assert.equal(isTextEntry({ tagName: 'INPUT', type: 'range' }), false)
  assert.equal(isTextEntry({ tagName: 'BUTTON' }), false)
  assert.equal(isTextEntry(null), false)
})

test("a Generate CSPs card's picture URL changes when the pose is rendered again (0.9.0 hand-check)", () => {
  const skin = (timestamp) => ({
    cspUrl: '/storage/Fox/fox-red_csp_alt_3.png',
    alternateCsps: [
      { id: 'alt_1_3', url: '/storage/Fox/fox-red_csp_alt_3.png', pose_name: 'jump', timestamp },
      { id: 'alt_1_3_hd', url: '/storage/Fox/fox-red_csp_alt_3_hd.png', pose_name: 'jump', timestamp: 'other' },
    ],
  })
  // the same file is rewritten; its alternate's timestamp is what changes
  assert.equal(skinCspVersion(skin('2026-11-20T10:00:00')), '2026-11-20T10:00:00')
  assert.notEqual(skinCspVersion(skin('2026-11-20T10:00:00')), skinCspVersion(skin('2026-11-20T10:05:00')))
  // the original portrait and a skin without one carry no version
  assert.equal(skinCspVersion({ cspUrl: '/storage/Fox/fox-red_csp.png', alternateCsps: [] }), undefined)
  assert.equal(skinCspVersion({ cspUrl: null }), undefined)
  assert.equal(skinCspVersion(undefined), undefined)
})
