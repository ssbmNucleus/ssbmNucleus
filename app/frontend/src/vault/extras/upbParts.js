// Fox / Falco Up-B: the rows of the full-page editor and the parts the
// pictogram can highlight. Presentation only — control keys name the Up-B
// recipe's own layers, `part` keys name a nested part's layers (see
// shared/data/extraTypes.js getUnitParts). Bindings never define a new payload.
export const UPB_CONTROL_SECTIONS = [
  { id: 'startup', label: 'Startup', parts: [
    { id: 'startup', label: 'Rings & Lines', controls: [
      { key: 'rings', label: 'Rings' }, { key: 'charge_lines', label: 'Lines' },
    ] },
  ] },
  { id: 'flight', label: 'Flight', parts: [
    { id: 'main_flame', label: 'Main Flame', controls: [
      { key: 'tip', label: 'Tip' }, { key: 'body', label: 'Body Glow' },
      { key: 'fire', label: 'Flame Texture', texture: true },
    ] },
    { id: 'flight_puffs', label: 'Fire Puffs', controls: [
      { key: 'trail', label: 'Trail Fire' }, { key: 'small_trail', label: 'Small Puffs' },
    ] },
    { id: 'travel_sparkles', label: 'Travel Sparkles', controls: [
      { key: 'dots', label: 'Square Dots' }, { key: 'flare', label: 'Motion Flare' },
    ] },
  ] },
]

// The Up-B page in row order, with the nested parts placed where they belong
// in the move: charge flames next to the startup rings, the flight puff
// texture beside the puff particle colors. `partTypes` = getUnitParts(...).
export function upbRows(partTypes) {
  const has = id => partTypes.some(t => t.id === id)
  const rows = [
    { section: 'Charge', id: 'startup', label: 'Startup Rings & Lines', scene: 'startup',
      controls: UPB_CONTROL_SECTIONS[0].parts[0].controls },
  ]
  if (has('charge_flames')) {
    rows.push({ section: 'Charge', id: 'charge_flames', label: 'Rising Flames', scene: 'startup',
      description: "Fox's broad flame puffs and thin wisps while charging.",
      controls: [
        { part: 'charge_flames', key: 'flame_c1', label: 'Flame Core' },
        { part: 'charge_flames', key: 'flame_c2', label: 'Flame Tint' },
        { part: 'charge_flames', key: 'wisp_c1', label: 'Wisp Core' },
        { part: 'charge_flames', key: 'wisp_c2', label: 'Wisp Tint' },
      ] })
  }
  const [mainFlame, puffs, sparkles] = UPB_CONTROL_SECTIONS[1].parts
  rows.push({ section: 'Flight', id: 'main_flame', label: 'Main Flame', scene: 'flight', controls: mainFlame.controls })
  rows.push({ section: 'Flight', id: 'flight_puffs', label: 'Fire Puffs', scene: 'flight',
    controls: [
      ...puffs.controls,
      ...(has('upb_charge_fire') ? [{ part: 'upb_charge_fire', key: 'color1', label: 'Puff Texture',
        description: 'The fire-puff bitmap; the trail colors tint it too' }] : []),
    ] })
  rows.push({ section: 'Flight', id: 'travel_sparkles', label: 'Travel Sparkles', scene: 'flight', controls: sparkles.controls })
  return rows
}
