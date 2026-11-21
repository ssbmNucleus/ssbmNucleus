// Pure helpers for the In-ISO costume selection (keys are [fighter, slotIndex]).
export const installedCostumeKey = (fighterName, costumeIndex) => JSON.stringify([fighterName, costumeIndex])

export const parseInstalledCostumeKey = (key) => {
  try {
    const [fighterName, costumeIndex] = JSON.parse(key)
    if (typeof fighterName !== 'string' || !Number.isInteger(costumeIndex)) return null
    return { fighterName, costumeIndex }
  } catch (err) {
    console.error('Invalid installed costume key:', key, err)
    return null
  }
}

// Selection keys are slot numbers, so every change that renumbers slots must
// renumber the selection too -- otherwise a selected skin silently becomes its
// neighbour and "Delete Selected" removes the wrong costume.
//
// Both helpers only touch `fighterName`'s keys and return the original Set
// when nothing changed (lets React skip the re-render).
function remapFighter(selected, fighterName, mapIndex) {
  let changed = false
  const next = new Set()
  for (const key of selected) {
    const item = parseInstalledCostumeKey(key)
    if (!item || item.fighterName !== fighterName) {
      next.add(key)
      continue
    }
    const index = mapIndex(item.costumeIndex)
    if (index === item.costumeIndex) {
      next.add(key)
    } else {
      changed = true
      if (index !== null) next.add(installedCostumeKey(fighterName, index))
    }
  }
  return changed ? next : selected
}

// Slot `removedIndex` was deleted: drop it and pull every later slot up by one.
export function selectionAfterRemove(selected, fighterName, removedIndex) {
  return remapFighter(selected, fighterName, i => {
    if (i === removedIndex) return null
    return i > removedIndex ? i - 1 : i
  })
}

// Slot `fromIndex` was moved to `toIndex` (array splice, as the drag-drop does).
export function selectionAfterMove(selected, fighterName, fromIndex, toIndex) {
  if (fromIndex === toIndex) return selected
  return remapFighter(selected, fighterName, i => {
    if (i === fromIndex) return toIndex
    if (fromIndex < toIndex && i > fromIndex && i <= toIndex) return i - 1
    if (fromIndex > toIndex && i >= toIndex && i < fromIndex) return i + 1
    return i
  })
}
