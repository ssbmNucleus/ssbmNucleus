import assert from 'node:assert/strict'
import test from 'node:test'
import { rosterEntryCount, rosterRisk } from './rosterRisk.js'

const roster = size => Array.from({ length: size }, (_, internalId) => ({ internalId, name: `Fighter ${internalId}` }))

test('63/64 boundary counts the whole native table, including partners, specials and NONE', () => {
  const fighters = roster(64)
  for (const [index, name] of ['Zelda', 'Sheik', 'Nana', 'NONE', 'Master Hand', 'Sandbag'].entries()) fighters[index].name = name
  assert.equal(rosterEntryCount(fighters), 64)
  assert.equal(rosterRisk(fighters).warn, true)
  assert.equal(rosterRisk(fighters.slice(0, 63)).warn, false)
  assert.equal(rosterRisk(roster(33)).warn, false)
})

test('projected batches warn before crossing the threshold; selection and removal recompute', () => {
  assert.deepEqual(rosterRisk(roster(62), 2), { count: 62, selected: 2, projected: 64, warn: true })
  assert.equal(rosterRisk(roster(62), 1).warn, false)
  assert.equal(rosterRisk(roster(64), 0).warn, true)
  assert.equal(rosterRisk(roster(63), 0).warn, false)
  assert.equal(rosterRisk(roster(63), -1).projected, 63)
})

test('a batch crossing internal slot 34 includes the native NONE placeholder', () => {
  assert.equal(rosterRisk(roster(33), 7).projected, 40)
  assert.equal(rosterRisk(roster(40), 1).projected, 42)
  assert.equal(rosterRisk(roster(33), 29).projected, 63)
  assert.equal(rosterRisk(roster(33), 30).projected, 64)
  assert.equal(rosterRisk(roster(41), 22).projected, 63)
  assert.equal(rosterRisk(roster(40), 0).projected, 40)
  const afterRemoval = roster(40)
  afterRemoval[34].name = 'NONE'
  assert.equal(rosterRisk(afterRemoval, 1).projected, 42, 'native insertion checks count, even if an older reserved entry remains')
})

test('unknown or malformed counts are never presented as a verified small roster', () => {
  for (const input of [undefined, null, [], {}, [null], [{ name: 'Mario' }], [{ internalId: -1 }], [{ internalId: 0 }, { internalId: 0 }]]) {
    assert.equal(rosterEntryCount(input), null)
    assert.deepEqual(rosterRisk(input, 3), { count: null, selected: 3, projected: null, warn: false })
  }
})
