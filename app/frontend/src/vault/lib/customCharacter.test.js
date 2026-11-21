import test from 'node:test'
import assert from 'node:assert/strict'

import { getCostumeTeamColors, normalizeCharacterName, resolveBaseCharacter } from './customCharacter.js'

test('normalizeCharacterName folds case, spelled-out "and", and punctuation', () => {
  assert.equal(normalizeCharacterName('C. Falcon'), 'cfalcon')
  assert.equal(normalizeCharacterName('Mr. Game & Watch'), 'mrgame&watch')
  assert.equal(normalizeCharacterName('Game and Watch'), 'game&watch')
  assert.equal(normalizeCharacterName('  Young  Link '), 'younglink')
  assert.equal(normalizeCharacterName(''), '')
  assert.equal(normalizeCharacterName(null), '')
  assert.equal(normalizeCharacterName(undefined), '')
})

test('resolveBaseCharacter passes through exact vanilla keys', () => {
  assert.equal(resolveBaseCharacter('Fox'), 'Fox')
  assert.equal(resolveBaseCharacter('C. Falcon'), 'C. Falcon')
  assert.equal(resolveBaseCharacter('Mr. Game & Watch'), 'Mr. Game & Watch')
})

test('resolveBaseCharacter trims before matching', () => {
  assert.equal(resolveBaseCharacter('  Fox  '), 'Fox')
})

test('resolveBaseCharacter maps internal/alias names', () => {
  assert.equal(resolveBaseCharacter('captain'), 'C. Falcon')
  assert.equal(resolveBaseCharacter('Falcon'), 'C. Falcon')
  assert.equal(resolveBaseCharacter('clink'), 'Young Link')
  assert.equal(resolveBaseCharacter('donkey'), 'DK')
  assert.equal(resolveBaseCharacter('drmario'), 'Dr. Mario')
  assert.equal(resolveBaseCharacter('emblem'), 'Roy')
  assert.equal(resolveBaseCharacter('ganon'), 'Ganondorf')
  assert.equal(resolveBaseCharacter('koopa'), 'Bowser')
  assert.equal(resolveBaseCharacter('mars'), 'Marth')
  assert.equal(resolveBaseCharacter('purin'), 'Jigglypuff')
  assert.equal(resolveBaseCharacter('seak'), 'Sheik')
  // Both Ice Climbers halves collapse onto the pair
  assert.equal(resolveBaseCharacter('popo'), 'Ice Climbers')
  assert.equal(resolveBaseCharacter('nana'), 'Ice Climbers')
})

test('resolveBaseCharacter alias lookup is case/punctuation insensitive', () => {
  assert.equal(resolveBaseCharacter('Captain Falcon'), 'C. Falcon')
  assert.equal(resolveBaseCharacter('Donkey Kong'), 'DK')
  assert.equal(resolveBaseCharacter('Game & Watch'), 'Mr. Game & Watch')
  assert.equal(resolveBaseCharacter('game and watch'), 'Mr. Game & Watch')
  assert.equal(resolveBaseCharacter('G&W'), 'Mr. Game & Watch')
})

test('resolveBaseCharacter falls back to a normalized scan of vanilla keys', () => {
  // Not an alias: matched by normalizing every DEFAULT_CHARACTERS key.
  assert.equal(resolveBaseCharacter('c falcon'), 'C. Falcon')
  assert.equal(resolveBaseCharacter('dr mario'), 'Dr. Mario')
  assert.equal(resolveBaseCharacter('young link'), 'Young Link')
  assert.equal(resolveBaseCharacter('ICE CLIMBERS'), 'Ice Climbers')
})

test('resolveBaseCharacter returns null for empty or unknown names', () => {
  assert.equal(resolveBaseCharacter(''), null)
  assert.equal(resolveBaseCharacter('   '), null)
  assert.equal(resolveBaseCharacter(null), null)
  assert.equal(resolveBaseCharacter(undefined), null)
  assert.equal(resolveBaseCharacter('Nonexistent Guy'), null)
})

test('getCostumeTeamColors is empty without a team_colors map', () => {
  assert.deepEqual(getCostumeTeamColors(null, 0), [])
  assert.deepEqual(getCostumeTeamColors(undefined, 0), [])
})

test('getCostumeTeamColors lists the teams pointing at an index, in R/B/G order', () => {
  const tc = { red: 1, blue: 2, green: 3 }
  assert.deepEqual(getCostumeTeamColors(tc, 0), [])
  assert.deepEqual(getCostumeTeamColors(tc, 1), ['red'])
  assert.deepEqual(getCostumeTeamColors(tc, 2), ['blue'])
  assert.deepEqual(getCostumeTeamColors(tc, 3), ['green'])
})

test('getCostumeTeamColors reports every team sharing one costume', () => {
  assert.deepEqual(getCostumeTeamColors({ green: 0, red: 0, blue: 0 }, 0), ['red', 'blue', 'green'])
})

test('getCostumeTeamColors matches index 0 strictly (not falsy-equal)', () => {
  assert.deepEqual(getCostumeTeamColors({ red: 0 }, 0), ['red'])
  assert.deepEqual(getCostumeTeamColors({ red: null }, 0), [])
  assert.deepEqual(getCostumeTeamColors({ red: '0' }, 0), [])
})
