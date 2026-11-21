// The texture strip's sections. A fighter costume holds two models -- the one a
// match shows and a low-poly copy -- and the viewer lists both models' textures
// in one row. The backend reads which model draws each texture from the
// fighter's own lookup tables (shared/rendering/lowpoly.texture_models) and
// hands it over with the viewer paths as `textureModels`: one row per texture of
// the costume's model, in the viewer's order. The viewer may list more material
// textures after those -- another root of the costume it also draws, like
// Jigglypuff's hats -- which no lookup table covers: they belong to the Model.

export const TEXTURE_SECTIONS = [
  { id: 'model', label: 'Model' },
  { id: 'low', label: 'Low-poly model' },
  { id: 'animated', label: 'Animated' },
]

const MODELS = new Set(['high', 'low', 'both'])

// { memberId or '': rows } for one viewer launch: a paint pair's members carry
// their own rows (each climber is its own DAT and fighter), a single costume
// carries them on the paths response itself.
export function launchTextureModels(data, pair) {
  if (pair) return Object.fromEntries(pair.map(member => [member.memberId, member.textureModels ?? null]))
  return { '': data?.textureModels ?? null }
}

// One group's entries ([{ texture, position }] in list order, position being the
// strip's list index) as sections: [{ id, label, entries: [{ texture, position,
// model }] }], every section present even when empty. Null when the models are
// unknown or do not line up with what the viewer listed (fewer textures, or any
// size differing): the strip then shows its single list rather than a wrong split.
export function sectionTextures(entries, models) {
  if (!Array.isArray(models) || !models.length) return null
  const base = entries.filter(({ texture }) => !texture.matAnim && !texture.extra)
  if (base.length < models.length) return null
  const modelOf = new Map()
  for (let i = 0; i < models.length; i++) {
    const { texture } = base[i]
    const row = models[i]
    if (!row || !MODELS.has(row.model) || row.width !== texture.width || row.height !== texture.height) return null
    modelOf.set(texture, row.model)
  }
  const sections = TEXTURE_SECTIONS.map(section => ({ ...section, entries: [] }))
  const [model, low, animated] = sections
  for (const entry of entries) {
    if (entry.texture.matAnim) { animated.entries.push({ ...entry, model: 'matanim' }); continue }
    // Past the rows, or an extra root the viewer does not draw: the model's own.
    const which = modelOf.get(entry.texture) ?? 'high'
    ;(which === 'low' ? low : model).entries.push({ ...entry, model: which })
  }
  return sections
}
