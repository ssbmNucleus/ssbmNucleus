import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const data = JSON.parse(readFileSync(new URL('./rngInputTails.json', import.meta.url), 'utf8'))

test('covers all 27 vanilla internal kinds, with explicit unknowns', () => {
  assert.equal(data.schema, 1)
  assert.deepEqual(Object.keys(data.tails), Array.from({ length: 27 }, (_, cid) => String(cid)))
  for (const states of Object.values(data.tails)) {
    for (const [action, draws] of Object.entries(states)) {
      assert.match(action, /^\d+$/)
      assert.ok(draws === null || (Number.isSafeInteger(draws) && draws >= 0))
    }
  }
  assert.ok(data.special.some(({ cid, action, rule }) => cid === '*' && action === '*' && rule.includes('UNKNOWN')))
})

test('FoD: Marth action 212 consumes three draws (vanilla Catch; roll is 233)', () => {
  assert.equal(data.tails['18']['212'], 3)
  assert.equal(data.tails['18']['233'], 3)
  assert.ok(data.special.some(({ cid, action, rule }) => cid === 18 && action === 212 && rule.includes('Catch')))
})

test('FoD: Marth SpecialAirS1 358 consumes three draws', () => {
  assert.equal(data.tails['18']['358'], 3)
})

test('FoD: Pichu SpecialAirHiStart 356 consumes three draws', () => {
  assert.equal(data.tails['23']['356'], 3)
})

test('Nana has her own reviewed script counts despite sharing Popo animations', () => {
  assert.equal(data.tails['11']['233'], 3)
  assert.equal(data.tails['11']['23'], 0)
  assert.ok(data.special.some(({ cid, rule }) => cid === 11 && rule.includes('PlNn.dat')))
})

test('entry wrappers include commands after an expiring frame-one timer', () => {
  assert.equal(data.tails['18']['60'], 3)
  for (let action = 355; action <= 372; action++) {
    assert.equal(data.tails['24'][action], 4) // Judge selection + immediate GFX.
  }
})

test('native startup RNG is distinguished from deferred item RNG', () => {
  assert.equal(data.tails['17']['343'], 1)
  assert.equal(data.tails['17']['349'], 1)
  assert.equal(data.tails['9']['352'], 0) // Turnip accessory callback runs later.
  assert.equal(data.tails['21']['343'], 3) // Pill color is selected later.
})

test('runtime-dependent and unreviewed counts remain unknown', () => {
  for (const action of [349, 350, 351]) assert.equal(data.tails['9'][action], null)
  assert.equal(data.tails['13']['355'], null)
  assert.equal(data.tails['4']['393'], null)
  assert.equal(data.tails['18']['219'], null)
  for (const entry of data.special) {
    assert.deepEqual(Object.keys(entry), ['cid', 'action', 'rule', 'source'])
    assert.ok(entry.rule.length > 0 && entry.source.length > 0)
  }
})
