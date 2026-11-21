import test from 'node:test'
import assert from 'node:assert/strict'
import { getExtraTypes, getUnitParts, getExtraType } from '../../shared/data/extraTypes.js'
import { readPartColors, serializePartColors, flattenPartColors, fanOutPart, partKeys } from './unitParts.js'

test('parts never appear on their own in a character menu, only inside their unit', () => {
  for (const character of ['Fox', 'Falco', 'Mario', 'Luigi', 'Bowser', 'Samus']) {
    const ids = getExtraTypes(character).map(t => t.id)
    for (const part of ['upb_charge_fire', 'charge_flames', 'mario_fireball_aura',
      'luigi_fireball_smoke', 'breath_texture', 'charge_ball']) {
      assert.ok(!ids.includes(part), `${character} lists ${part}`)
    }
  }
  assert.deepEqual(getUnitParts('Fox', 'upb').map(t => t.id), ['upb_charge_fire', 'charge_flames'])
  assert.deepEqual(getUnitParts('Falco', 'upb').map(t => t.id), ['upb_charge_fire'])
  assert.deepEqual(getUnitParts('Samus', 'charge_shot').map(t => t.id), ['charge_ball'])
  assert.deepEqual(getUnitParts('Fox', 'laser'), [])
})

test('part colors load from the saved recipe and fall back to vanilla', () => {
  const parts = getUnitParts('Fox', 'upb')
  const fresh = readPartColors(null, parts)
  assert.equal(fresh.upb_charge_fire.color1, getExtraType('Fox', 'upb_charge_fire').vanilla.color1)
  assert.equal(fresh.charge_flames.flame_c1, getExtraType('Fox', 'charge_flames').vanilla.flame_c1)
  const mod = { modifications: { tip: { color: 'F800' }, parts: {
    charge_flames: { flame_c1: { color: '0000ff' } } } } }
  const loaded = readPartColors(mod, parts)
  assert.equal(loaded.charge_flames.flame_c1, '0000FF')
  assert.equal(loaded.charge_flames.wisp_c1, getExtraType('Fox', 'charge_flames').vanilla.wisp_c1)
})

test('serialize writes every part layer in the backend recipe shape', () => {
  const parts = getUnitParts('Fox', 'upb')
  const out = serializePartColors({
    upb_charge_fire: { color1: '#00ff00' },
    charge_flames: { flame_c1: '0000FF', flame_c2: '000088', wisp_c1: '00FFFF', wisp_c2: '008888' },
  }, parts)
  assert.deepEqual(out.upb_charge_fire, { color1: { color: '00FF00' } })
  assert.deepEqual(Object.keys(out.charge_flames).sort(), partKeys(getExtraType('Fox', 'charge_flames')).sort())
  assert.equal(out.charge_flames.wisp_c2.color, '008888')
})

test('a whole-effect color reaches parts: textures take it, layers keep relative brightness', () => {
  const texture = fanOutPart('#00FF00', getExtraType('Fox', 'upb_charge_fire'))
  assert.deepEqual(texture, { color1: '00FF00' })
  const flames = fanOutPart('#0000FF', getExtraType('Fox', 'charge_flames'))
  assert.deepEqual(Object.keys(flames).sort(), ['flame_c1', 'flame_c2', 'wisp_c1', 'wisp_c2'])
  for (const value of Object.values(flames)) assert.match(value, /^[0-9A-F]{6}$/)
  assert.notEqual(flames.flame_c1, flames.flame_c2, 'core and tint keep their own brightness')
})

test('flattened preview keys are namespaced per part', () => {
  assert.deepEqual(flattenPartColors({ charge_flames: { flame_c1: '0000FF' } }),
    { p_charge_flames_flame_c1: '0000FF' })
})
