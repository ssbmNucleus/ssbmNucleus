import { applyGroupAdjustments } from './colorUtils.js'

// A descriptor color gets the minimum palette weight (100 samples), so colors
// used only by materials are not discarded as tiny texture noise. Alpha is not
// a visibility test for material RGB; preserve it separately from the samples.
export function materialSamples(materials) {
  const originals = {}, fields = {}
  for (const material of materials) for (const field of material.fields) {
    if (field.kind !== 'color') continue
    if (Object.keys(fields).length >= 4096) throw new Error('Too many material colors for one palette')
    const key = `material:${Object.keys(fields).length}`
    const rgb = field.value.slice(1, 7).match(/../g).map(v => parseInt(v, 16))
    const data = new Uint8ClampedArray(400)
    for (let i = 0; i < 400; i += 4) data.set([...rgb, 255], i)
    originals[key] = new ImageData(data, 100, 1)
    fields[key] = { id: material.id, field: field.key, alpha: field.value.slice(7) }
  }
  return { originals, fields }
}

export function materialAdjustments(originals, fields, maps, groups) {
  return Object.entries(fields).map(([key, field]) => {
    const result = applyGroupAdjustments(originals[key], maps[key], groups)
    const rgb = Array.from(result.data.slice(0, 3), v => v.toString(16).padStart(2, '0')).join('')
    return { id: field.id, field: field.field, value: `#${rgb}${field.alpha}` }
  })
}
