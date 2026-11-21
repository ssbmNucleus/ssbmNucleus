import test from 'node:test'
import assert from 'node:assert/strict'
import { groupPortraits } from './cspPortraits.js'

const skin = (overrides = {}) => ({
  id: 'fox1', has_csp: true, cspUrl: '/storage/Fox/fox1_csp.png',
  has_hd_csp: false, active_csp_id: null, ...overrides,
})

const alt = (id, poseName, isHd = false) => ({ id, url: `/storage/Fox/${id}.png`, poseName, isHd })

test('original is the only card and active when there are no alternates', () => {
  const cards = groupPortraits(skin({ has_hd_csp: true }), [])
  assert.equal(cards.length, 1)
  assert.deepEqual(cards[0], {
    key: 'original', kind: 'original', label: 'Original',
    url: '/storage/Fox/fox1_csp.png', hasHd: true, isActive: true, sdId: null, hdId: null,
  })
})

test('SD + HD alternates with the same pose fold into one card; active follows active_csp_id', () => {
  const alts = [alt('a1', 'jump'), alt('a1_hd', 'jump', true), alt('b1', 'crouch')]
  const cards = groupPortraits(skin({ active_csp_id: 'a1' }), alts)
  assert.deepEqual(cards.map((c) => [c.kind, c.label, c.hasHd, c.isActive, c.sdId, c.hdId]), [
    ['original', 'Original', false, false, null, null],
    ['alt', 'jump', true, true, 'a1', 'a1_hd'],
    ['alt', 'crouch', false, false, 'b1', null],
  ])
  // the card image is the SD member, never the HD one
  assert.equal(cards[1].url, '/storage/Fox/a1.png')
})

test('a legacy active_csp_id pointing at the HD member still marks the group active', () => {
  const alts = [alt('a1', 'jump'), alt('a1_hd', 'jump', true)]
  const cards = groupPortraits(skin({ active_csp_id: 'a1_hd' }), alts)
  assert.equal(cards[0].isActive, false)
  assert.equal(cards[1].isActive, true)
})

test('pose-less uploads never cross-match each other, and an HD-only orphan still gets a card', () => {
  const alts = [alt('u1', null), alt('u2', null), alt('u3_hd', null, true)]
  const cards = groupPortraits(skin(), alts)
  assert.deepEqual(cards.slice(1).map((c) => [c.label, c.sdId, c.hdId, c.hasHd]), [
    ['Custom', 'u1', null, false],
    ['Custom', 'u2', null, false],
    ['Custom', null, 'u3_hd', true],
  ])
  assert.equal(new Set(cards.map((c) => c.key)).size, cards.length, 'keys are unique')
})

test('a skin with no portrait yields no original card; null skin yields nothing', () => {
  assert.equal(groupPortraits(skin({ has_csp: false }), [alt('a1', 'jump')]).length, 1)
  assert.deepEqual(groupPortraits(null, [alt('a1', 'jump')]), [])
})
