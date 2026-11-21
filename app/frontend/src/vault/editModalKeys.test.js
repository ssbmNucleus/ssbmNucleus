import test from 'node:test'
import assert from 'node:assert/strict'

import { editModalEscape, titleEscapeReverts } from './editModalKeys.js'

test('Escape closes the edit modal, as the other modals do', () => {
  // 0.9.0 smoke test: Escape in the name field (unchanged) left the modal open
  assert.equal(editModalEscape({ key: 'Escape' }), 'close')
  assert.equal(editModalEscape({ key: 'Enter' }), null)
  assert.equal(titleEscapeReverts('Clank', 'Clank'), false, 'an unchanged name lets Escape close the modal')
  assert.equal(titleEscapeReverts('Clank ', 'Clank'), false)
})

test('an unsaved name, an open list, a dialog on top or another tab keep the modal open', () => {
  assert.equal(titleEscapeReverts('Clank 2', 'Clank'), true, 'the name field reverts first')
  assert.equal(editModalEscape({ key: 'Escape', defaultPrevented: true }), null, 'the name field took it')
  assert.equal(editModalEscape({ key: 'Escape', posesOpen: true }), 'poses')
  assert.equal(editModalEscape({ key: 'Escape', safetyOpen: true }), 'safety')
  assert.equal(editModalEscape({ key: 'Escape', covered: true, posesOpen: true }), null, 'the dialog on top answers it')
  assert.equal(editModalEscape({ key: 'Escape', hidden: true }), null, 'hidden behind another tab')
})
