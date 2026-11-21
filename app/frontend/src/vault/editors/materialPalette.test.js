import test from 'node:test'
import assert from 'node:assert/strict'
import { materialSamples, materialAdjustments } from './materialPalette.js'
import { analyzeTextureColors, applyGroupAdjustments } from './colorUtils.js'

globalThis.ImageData = class { constructor(data, width, height) { Object.assign(this, { data, width, height }) } }

test('material-only colors join texture groups, preserve alpha and reset absolutely', () => {
  const samples = materialSamples([{ id: 'mesh', fields: [
    { key: 'diffuse', kind: 'color', value: '#ff000000' },
    { key: 'texture:0:constant', kind: 'color', value: '#00ff0044' },
    { key: 'alpha', kind: 'number', value: 0.4 },
  ] }])
  assert.equal(Object.keys(samples.fields).length, 2)
  const originals = { ...samples.originals, texture: samples.originals['material:0'] }
  const { groups, pixelMap } = analyzeTextureColors(originals, 8)
  assert.equal(groups.length, 2, 'A color used only by a material must remain selectable')
  const shifted = groups.map(g => ({ ...g, hueShift: 120 }))
  const edits = materialAdjustments(originals, samples.fields, pixelMap, shifted)
  assert.equal(edits[0].value, '#00ff0000')
  assert.equal(edits[1].value, '#0000ff44')
  assert.deepEqual(Array.from(applyGroupAdjustments(originals.texture, pixelMap.texture, shifted).data.slice(0, 3)), [0, 255, 0])
  assert.deepEqual(materialAdjustments(originals, samples.fields, pixelMap, groups).map(e => e.value), ['#ff000000', '#00ff0044'])
  assert.deepEqual(materialAdjustments(originals, samples.fields, pixelMap, shifted), edits, 'Repeated shifts must not accumulate')
})
