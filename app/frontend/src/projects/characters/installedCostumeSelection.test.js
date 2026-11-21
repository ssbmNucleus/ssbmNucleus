import test from 'node:test'
import assert from 'node:assert/strict'
import {
  installedCostumeKey as key,
  parseInstalledCostumeKey,
  selectionAfterRemove,
  selectionAfterMove,
} from './installedCostumeSelection.js'

// Which costumes (by name) a selection points at in a given slot list.
const pointsAt = (selected, fighter, list) => [...selected]
  .map(parseInstalledCostumeKey)
  .filter(k => k.fighterName === fighter)
  .map(k => list[k.costumeIndex])
  .sort()

const splice = (list, from, to) => {
  const next = [...list]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next
}

test('deleting an earlier costume keeps the selection on the same skins', () => {
  const before = ['A', 'B', 'C', 'D', 'E']
  const selected = new Set([key('Fox', 2), key('Fox', 4)]) // C and E
  const after = before.filter((_, i) => i !== 1)            // delete B
  const next = selectionAfterRemove(selected, 'Fox', 1)
  assert.deepEqual(pointsAt(next, 'Fox', after), ['C', 'E'])
})

test('deleting a selected costume drops it and shifts later ones', () => {
  const before = ['A', 'B', 'C', 'D']
  const selected = new Set([key('Fox', 0), key('Fox', 1), key('Fox', 3)])
  const after = before.filter((_, i) => i !== 1)
  const next = selectionAfterRemove(selected, 'Fox', 1)
  assert.deepEqual(pointsAt(next, 'Fox', after), ['A', 'D'])
  assert.equal(next.size, 2)
})

test('deleting a later costume leaves earlier selections alone', () => {
  const selected = new Set([key('Fox', 0), key('Fox', 2)])
  const next = selectionAfterRemove(selected, 'Fox', 3)
  assert.deepEqual([...next].sort(), [key('Fox', 0), key('Fox', 2)].sort())
})

test('deleting never touches another fighter\'s selection', () => {
  const selected = new Set([key('Zelda', 3), key('Sheik', 3)])
  const next = selectionAfterRemove(selected, 'Zelda', 1)
  assert.ok(next.has(key('Sheik', 3)))
  assert.ok(next.has(key('Zelda', 2)))
  assert.equal(next.size, 2)
})

test('dragging a costume keeps the selection on the same skins', () => {
  const before = ['A', 'B', 'C', 'D', 'E', 'F']
  const selected = new Set([key('Fox', 0), key('Fox', 2), key('Fox', 5)]) // A, C, F
  for (const [from, to] of [[0, 4], [4, 0], [5, 1], [1, 5], [2, 3], [3, 2], [2, 2]]) {
    const after = splice(before, from, to)
    const next = selectionAfterMove(selected, 'Fox', from, to)
    assert.deepEqual(pointsAt(next, 'Fox', after), ['A', 'C', 'F'], `move ${from}->${to}`)
    assert.equal(next.size, 3)
  }
})

test('dragging one fighter\'s row never touches another fighter\'s selection', () => {
  const selected = new Set([key('Sheik', 0)])
  const next = selectionAfterMove(selected, 'Zelda', 0, 3)
  assert.deepEqual([...next], [key('Sheik', 0)])
})

test('several drags in a row keep tracking the same skins', () => {
  let list = ['A', 'B', 'C', 'D', 'E']
  let selected = new Set([key('Fox', 1), key('Fox', 3)]) // B, D
  for (const [from, to] of [[4, 0], [2, 4], [0, 3]]) {
    list = splice(list, from, to)
    selected = selectionAfterMove(selected, 'Fox', from, to)
  }
  assert.deepEqual(pointsAt(selected, 'Fox', list), ['B', 'D'])
})

test('unchanged selections return the same Set', () => {
  const selected = new Set([key('Fox', 0)])
  assert.equal(selectionAfterRemove(selected, 'Fox', 3), selected)
  assert.equal(selectionAfterMove(selected, 'Falco', 0, 2), selected)
})
