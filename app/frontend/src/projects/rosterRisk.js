// This is the total native Project.Fighters table, not the visible CSS grid.
// list-fighters emits one entry per internal ID, including Nana and the six
// special fighters. The historical 63/64 roster comparison used this count
// (33 entries for vanilla). It does not establish a universal engine limit.
export const REPORTED_SLIPPI_ROSTER_THRESHOLD = 63

export function rosterEntryCount(fighters) {
  if (!Array.isArray(fighters) || fighters.length === 0) return null
  const ids = fighters.map(fighter => fighter?.internalId)
  if (ids.some(id => !Number.isInteger(id) || id < 0) || new Set(ids).size !== ids.length) return null
  return ids.length
}

export function rosterRisk(fighters, additions = 0) {
  const count = rosterEntryCount(fighters)
  const selected = Number.isInteger(additions) && additions > 0 ? additions : 0
  // AddFighterCommand inserts a reserved NONE entry before a new fighter at
  // internal ID 34 (total count 40, since the six special fighters are last).
  // Batch installs call that same method, so a large batch can cross this slot.
  const reserved = count !== null && count <= 40 && count + selected > 40 ? 1 : 0
  const projected = count === null ? null : count + selected + reserved
  return { count, selected, projected, warn: projected !== null && projected > REPORTED_SLIPPI_ROSTER_THRESHOLD }
}
