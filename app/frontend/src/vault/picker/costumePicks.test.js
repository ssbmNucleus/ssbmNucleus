import assert from 'node:assert/strict'
import test from 'node:test'
import { ROSTER, costumeOptions, fighterOptions, filterOptions, pickLabel, pickValue, rosterOf, stockCostumes, vaultCostumes } from './costumePicks.js'

const METADATA = { characters: {
  Fox: { skins: [
    { id: 'fox-blue', color: 'Blue Hoodie', csp_filename: 'fox-blue_csp.png' },
    { id: 'fox-raw', name: 'raw-name' },
    { id: 'fox-nocsp', color: 'No portrait', has_csp: false },
    { id: 'nana-hidden', color: 'Hidden', visible: false },
    { color: 'no id' },
  ] },
  'Mr. Game & Watch': { skins: [{ id: 'gw1', color: 'Black' }] },
} }
const STOCK_ROWS = [
  { code: 'PlFxNr', colorCode: 'Nr', colorName: 'Default', hasCsp: true, hasStock: true },
  { code: 'PlFxOr', colorCode: 'Or', colorName: 'Orange', hasCsp: false, hasStock: true },
  { colorCode: 'La' },
]

test('the roster is the Vault’s 26 fighters by name, narrowed by a served list', () => {
  assert.equal(ROSTER.length, 26)
  assert.deepEqual(ROSTER, [...ROSTER].sort())
  assert.ok(ROSTER.includes('Ice Climbers') && ROSTER.includes('Mr. Game & Watch'))
  const importable = rosterOf({ exclude: ['Ice Climbers'] })
  assert.equal(importable.length, 25)
  assert.ok(!importable.includes('Ice Climbers'))
  // The backend's list wins, in roster order; a name the roster lacks is ignored.
  assert.deepEqual(rosterOf({ only: ['Marth', 'Fox', 'Goku', 'Ice Climbers'], exclude: ['Ice Climbers'] }), ['Fox', 'Marth'])
  assert.deepEqual(rosterOf({ only: [] }), ROSTER, 'an empty served list is no list')
})

test('vault costumes are the visible skins with their portraits', () => {
  assert.deepEqual(vaultCostumes(METADATA, 'Fox'), [
    { kind: 'vault', character: 'Fox', id: 'fox-blue', name: 'Blue Hoodie', image: '/storage/Fox/fox-blue_csp.png' },
    { kind: 'vault', character: 'Fox', id: 'fox-raw', name: 'raw-name', image: '/storage/Fox/fox-raw_csp.png' },
    { kind: 'vault', character: 'Fox', id: 'fox-nocsp', name: 'No portrait', image: null },
  ])
  assert.equal(vaultCostumes(METADATA, 'Mr. Game & Watch')[0].image, '/storage/Mr.%20Game%20%26%20Watch/gw1_csp.png')
  assert.deepEqual(vaultCostumes(METADATA, 'Marth'), [])
  assert.deepEqual(vaultCostumes(null, 'Fox'), [])
})

test('stock costumes come from the vanilla listing, in its order', () => {
  assert.deepEqual(stockCostumes(STOCK_ROWS, 'Fox'), [
    { kind: 'stock', character: 'Fox', code: 'PlFxNr', color: 'Nr', name: 'Default', image: '/vanilla/Fox/PlFxNr/csp.png' },
    { kind: 'stock', character: 'Fox', code: 'PlFxOr', color: 'Or', name: 'Orange', image: null },
  ])
  assert.deepEqual(stockCostumes(undefined, 'Fox'), [])
})

test('options put the vault first, badge the stock slots and filter by name', () => {
  const vault = vaultCostumes(METADATA, 'Fox'), stock = stockCostumes(STOCK_ROWS, 'Fox')
  const options = costumeOptions(vault, stock, path => `http://b${path}`)
  assert.deepEqual(options.map(o => o.value), ['v:fox-blue', 'v:fox-raw', 'v:fox-nocsp', 's:PlFxNr', 's:PlFxOr'])
  assert.equal(options[0].icon, 'http://b/storage/Fox/fox-blue_csp.png')
  assert.equal(options[2].icon, undefined)
  assert.deepEqual(options.map(o => o.badge), [undefined, undefined, undefined, 'Stock', 'Stock'])
  assert.deepEqual(filterOptions(options, '  ORANGE ').map(o => o.value), ['s:PlFxOr'])
  assert.equal(filterOptions(options, '').length, 5)
  const fighters = fighterOptions(['Fox', 'Marth'], { metadata: METADATA, counts: true })
  assert.deepEqual(fighters, [
    { value: 'Fox', label: 'Fox', icon: '/vanilla/Fox/css_icon.png', badge: '3' },
    { value: 'Marth', label: 'Marth', icon: '/vanilla/Marth/css_icon.png' },
  ])
  assert.equal(fighterOptions(['Fox'], { metadata: METADATA })[0].badge, undefined, 'no counts in fighter-only mode')
})

test('a pick has one grid value and one label', () => {
  const [blue] = vaultCostumes(METADATA, 'Fox'), [, orange] = stockCostumes(STOCK_ROWS, 'Fox')
  assert.equal(pickValue(blue), 'v:fox-blue')
  assert.equal(pickValue(orange), 's:PlFxOr')
  assert.equal(pickValue({ kind: 'fighter', character: 'Fox' }), 'Fox')
  assert.equal(pickValue(null), '')
  assert.equal(pickLabel(blue), 'Fox · Blue Hoodie')
  assert.equal(pickLabel(orange), 'Fox · Orange (stock)')
  assert.equal(pickLabel({ kind: 'fighter', character: 'Marth' }), 'Marth')
  assert.equal(pickLabel(null), '')
})
