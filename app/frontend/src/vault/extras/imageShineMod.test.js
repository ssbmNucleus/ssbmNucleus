import test from 'node:test'
import assert from 'node:assert/strict'
import { isImageShineMod, supportsImageMod } from './imageShineMod.js'

test('image mods are recognized from every shape the backend writes', () => {
  // the import route's tag
  assert.equal(isImageShineMod({ format: 'effect_model' }), true)
  assert.equal(isImageShineMod({ type: 'effect_model' }), true)
  // a pre-image-format website import, healed by derive_modifications_from_dat
  assert.equal(isImageShineMod({ modifications: { image: { width: 256 } } }), true)
})

test('color mods and missing mods are not image mods', () => {
  assert.equal(isImageShineMod(null), false)
  assert.equal(isImageShineMod(undefined), false)
  assert.equal(isImageShineMod({}), false)
  assert.equal(isImageShineMod({ type: 'model', modifications: {} }), false)
  // a real gradient mod: colors, no image key
  assert.equal(isImageShineMod({
    modifications: { primary: { color: '0FF0' }, secondary: { color: '0A45' } },
  }), false)
})

test('image support is read from the type config, never assumed by id', () => {
  assert.equal(supportsImageMod({ id: 'shine', imageModel: { width: 256 } }), true)
  assert.equal(supportsImageMod({ id: 'shine' }), false)
  assert.equal(supportsImageMod(null), false)
})
