// Pair texture indices are local to their DAT. Never use the list position on the wire.
export const textureKey = (texture) => texture?.memberId
  ? `${texture.memberId}:${texture.index}` : String(texture?.index)

export const textureAddress = (key) => {
  const match = /^(popo|nana):(\d+)$/.exec(String(key))
  if (match) return { memberId: match[1], index: Number(match[2]) }
  if (!/^\d+$/.test(String(key))) throw new Error('Invalid paint texture address')
  return { index: Number(key) }
}

export function normalizePaintTextures(textures, paired = false) {
  const seen = new Set()
  return (textures || []).map((texture, position) => {
    const row = { ...texture, index: texture.index ?? position }
    if (!Number.isInteger(row.index) || row.index < 0 ||
        (paired && !['popo', 'nana'].includes(row.memberId))) {
      throw new Error('Viewer returned an invalid texture owner')
    }
    row.textureId = textureKey(row)
    if (seen.has(row.textureId)) throw new Error('Viewer returned duplicate texture IDs')
    seen.add(row.textureId)
    return row
  })
}

export const isCurrentTextureReply = (message, { sessionId, requestId, textureId }) =>
  message.sessionId === sessionId && message.requestId === requestId &&
  textureKey(message) === textureId

export const isCurrentPaintTarget = (captured, current) => captured.generation === current.generation &&
  captured.textureId === current.textureId && captured.selection === current.selection

/**
 * Does the paint canvas need repainting out of `editedTextures`?
 *
 * The canvas publishes its own pixels after every stroke, which lands back in
 * `editedTextures` and re-runs the load effect. Repainting there is not merely
 * wasted work: it drops canvas ownership until the PNG decodes, and painting,
 * undo and redo are all gated on ownership -- so a stroke started or an undo
 * clicked inside that gap is silently dropped. That is why undo felt like it
 * did nothing.
 *
 * `publishedData` is what the canvas itself last published FOR THIS texture, so
 * an edit it already shows is skipped while an outside write -- a palette
 * recolor, which rewrites the flattened texture without ever touching the
 * canvas -- still repaints (and, upstream, reflattens the layer stack).
 */
export const shouldReloadPaintCanvas = ({ textureId, canvasOwner, editedData, publishedData }) => {
  if (!textureId || canvasOwner !== textureId) return true   // canvas holds another texture, or none
  return editedData !== publishedData
}

export const texturesInPaintScope = (textures, scope) => textures.filter(texture =>
  !texture.memberId || scope === 'both' || texture.memberId === scope)

export function requireCompletePairSave(result) {
  if (result?.success === false || result?.imported_count !== 2 || result?.pairing_complete !== true) {
    throw new Error('The Vault did not confirm both climbers and their pair links. Your edits are retained; check the Vault before retrying.')
  }
}

export function capturePaintPairExport(members, response) {
  if (!Array.isArray(response) || response.length !== 2) {
    throw new Error('The viewer did not export both climbers; no pair was saved.')
  }
  const ids = new Set(response.map(member => member.memberId))
  if (ids.size !== 2) throw new Error('The viewer returned duplicate climber exports.')
  return members.map(member => {
    const exported = response.find(entry => entry.memberId === member.memberId)
    if (!exported?.data) throw new Error(`Could not export ${member.name}; no pair was saved.`)
    return { ...member, datBase64: exported.data }
  })
}
