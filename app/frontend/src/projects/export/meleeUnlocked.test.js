import test from 'node:test'
import assert from 'node:assert/strict'
import { blockedReason, describe, fighterLists, resultLines, unconfirmedLine } from './meleeUnlocked.js'

const fighters = (buildable, withoutSource = [], unconfirmed = []) => ({
  buildable: buildable.map(name => ({ name })),
  withoutSource: withoutSource.map(name => ({ name })),
  unconfirmed: unconfirmed.map(name => ({ name, origin: 'a download from https://example.invalid/x.zip' })),
})

test('the card asks for the folders that are not set', () => {
  assert.match(blockedReason({ kitPath: '', gccBin: '', fighters: null }), /kit and compiler/)
  assert.match(blockedReason({ kitPath: 'k', gccBin: '', fighters: null }), /compiler folder/)
  assert.match(blockedReason({ kitPath: '', gccBin: 'g', fighters: null }), /kit folder/)
})

test('the card says why there is nothing to build', () => {
  assert.match(blockedReason({ kitPath: 'k', gccBin: 'g', fighters: fighters([]) }), /no custom fighters/)
  assert.match(blockedReason({ kitPath: 'k', gccBin: 'g', fighters: fighters([], ['Clone']) }), /C source/)
  assert.match(blockedReason({ kitPath: 'k', gccBin: 'g', fighters: fighters([], ['Clone'], ['Shulk']) }),
    /confirm the downloaded source of Shulk/)
})

test('the export can run when a fighter has source, or the list is not known yet', () => {
  assert.equal(blockedReason({ kitPath: 'k', gccBin: 'g', fighters: fighters(['Shulk']) }), null)
  assert.equal(blockedReason({ kitPath: 'k', gccBin: 'g', fighters: fighters(['Shulk'], [], ['Wolf']) }), null)
  assert.equal(blockedReason({ kitPath: 'k', gccBin: 'g', fighters: null }), null)
})

test('an older backend without the unconfirmed list still reads', () => {
  assert.deepEqual(fighterLists({ buildable: [{ name: 'Shulk' }] }),
    { buildable: [{ name: 'Shulk' }], unconfirmed: [], withoutSource: [] })
  assert.equal(blockedReason({ kitPath: 'k', gccBin: 'g', fighters: { buildable: [], withoutSource: [] } }),
    'This project has no custom fighters')
})

test('the description counts the fighters and names what stays locked or waits', () => {
  assert.match(describe(null), /Fighter plugins/)
  assert.match(describe(fighters(['Shulk'])), /1 custom fighter,/)
  assert.match(describe(fighters(['Shulk', 'Wolf'], ['Clone'])), /2 custom fighters.*1 fighter without source/)
  assert.match(describe(fighters([], [], ['Wolf'])), /0 custom fighters.*1 fighter with downloaded source waits for your confirmation/)
})

test('an unconfirmed fighter is shown as not built, with where its source came from', () => {
  assert.equal(unconfirmedLine({ name: 'Wolf', origin: 'a download from https://example.invalid/wolf.zip' }),
    'Wolf: not built. Its C source came from a download from https://example.invalid/wolf.zip and has not been confirmed.')
})

test('the result reports what was built, what failed with its last line, what waits and what had no source', () => {
  assert.deepEqual(resultLines({
    folder: 'C:/out/fighters',
    built: [{ name: 'Shulk' }, { name: 'Wolf' }],
    failed: [{ name: 'Bad Port', error: 'fighter.c:3: warning\nfighter.c:9: error: nope\n' }],
    unconfirmed: [{ name: 'Fox Port', reason: 'its C source came from a download from https://x.invalid and has not been confirmed' }],
    withoutSource: [{ name: 'Clone' }],
  }), [
    { kind: 'ok', text: 'Built 2 plugins in C:/out/fighters' },
    { kind: 'error', text: 'Bad Port: fighter.c:9: error: nope' },
    { kind: 'warn', text: 'Fox Port: not built, its C source came from a download from https://x.invalid and has not been confirmed' },
    { kind: 'warn', text: 'No source in the Vault: Clone' },
  ])
  assert.deepEqual(resultLines({ built: [], failed: [], withoutSource: [] }),
    [{ kind: 'warn', text: 'Nothing was built.' }])
})
