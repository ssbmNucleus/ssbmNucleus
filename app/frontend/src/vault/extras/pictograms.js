/**
 * Per-layer pictograms for extras editors.
 *
 * Legacy pictograms are small in-game crops (from tests/artifacts/extras-audit).
 * Many show several recolored layers together; they are effect references,
 * not proof that a particular control changes every pictured element. They
 * live as static assets under frontend/public/extras/pictograms/<extra>_<layer>.png (served at
 * ./extras/pictograms/... like the other public template images), so no bundler
 * import wiring is needed.
 *
 * `pictogramSrc(extraId, layerId)` returns the URL or null. The editor renders
 * a thumbnail when non-null and falls back to the plain row otherwise -- so a
 * layer with no pictogram (or an unbuilt extra) degrades gracefully.
 *
 * REGISTRY: only list layers that actually have a shipped asset. Fan-out
 * missions add their character's layers here after cropping the captures.
 * Source captures for each are documented in the mission report + the
 * editor-polish pattern section of docs/EXTRAS_MISSION_TEMPLATE.md.
 */
const BASE = './extras/pictograms/'

// extraId -> Set of layerIds that have a built pictogram PNG.
//
// Pilot (17) + pictogram fan-out 2026-07-02 (67 more, cropped from the
// tests/artifacts/extras-audit/<Char>-<extra>/ captures the earlier fan-out
// wrongly reported missing -- they live in PROJECT_ROOT.parent, one level
// above the repo dir). Each crop centers the layer's forced anti-color.
// Layers that share ONE anti-color in a whole-effect extra (Bowser fire,
// Kirby stone, ICs ice_shot, Luigi cyclone/fireball(_smoke), Ganon
// warlock/gerudo, common_fire/flash/electric, jolt_spark) get a single
// representative crop keyed to the primary layer; SUMMARY_ALIAS points the
// summary color1/color2 pickers at it.
const HAVE = {
  falcon_punch: ['color1', 'fire', 'color2', 'flare_lines_c2',
                 'flare_small_c1', 'flare_big_c1', 'smoke'],
  falcon_kick: ['color1', 'color2', 'front_c1', 'trail_c1', 'dots_c1'],
  raptor_boost: ['color1', 'color2', 'hit_smoke_c1', 'hit_smoke_c2',
                 'hit_dots_c1', 'hit_mat_c1'],
  screw_attack: ['arc_c1', 'arc_c2'],
  missile: ['contrail_c1', 'backblast_c1'],
  charge_shot: ['needles_c1', 'needles_c2'],
  charge_ball: ['color1'],
  // Mewtwo -- six distinct anti-colors, one crop each.
  shadow_ball: ['color1', 'color2', 'charge_c1', 'charge_c2', 'bolts_c1', 'bolts_c2'],
  upsmash: ['color1', 'color2'],
  // Fox up-B (bespoke editor): only the cleanly-separable layers -- the
  // charging body glow (green) and the ground fire rings (magenta). tip/
  // trail/small_trail overlap the same flame region and were dropped as
  // indistinguishable duplicates.
  upb: ['body', 'rings'],
  laser_ring: ['color1', 'color2'],
  // Pikachu / Pichu.
  thunder: ['color1', 'color2'],   // shared extra id (Pikachu + Pichu)
  pikachu_fsmash: ['fsmash_pre_c1', 'fsmash_pre_c2'],
  pikachu_thunder_jolt_air: ['jolt_air_mid_c1', 'jolt_air_mid_c2'],
  pikachu_thunder_jolt_ground: ['jolt_gnd_a_c1', 'jolt_gnd_a_c2', 'jolt_gnd_head_c1'],
  common_electric: ['elec_s0_a_c1'],
  thunder_jolt_spark: ['jolt_spark_a_c1'],
  // Ness.
  ness_pk_thunder: ['tip_c1', 'ball_flare1_c2'],
  ness_psi_magnet: ['psimag_a_c1', 'psimag_a_c2'],
  ness_pk_fire: ['pillar_ring_in_c1', 'pillar_ring_in_c2'],
  // Mario / Dr. Mario.
  mario_fireball: ['hand_smoke_a_c1', 'ball_particles_a_c1', 'landing_dust_a_c1'],
  mario_fireball_aura: ['aura_07_c1'],
  mario_tornado: ['outer_swirl1_c1', 'ground_ripple1_42_c1'],
  mario_cape: ['cloth_c1'],
  cape_sparkles: ['sparkle_a_c1', 'sparkle_trail_c1'],
  mario_coins: ['color1'],
  doc_cape: ['cloth_c1'],
  // Luigi.
  luigi_cyclone: ['torn_outer_c1'],
  luigi_fireball: ['fb_aura_42_c1'],
  luigi_fireball_smoke: ['fb_smoke_s1_c1'],
  luigi_hitspark: ['hitspark_s11_c1'],
  // Zelda (+ commons owned by Zelda).
  common_fire: ['color1'],
  common_flash: ['color1'],
  zelda_farore: ['farore_c1'],
  zelda_transform: ['transform_c1'],
  // Bowser / Jigglypuff / Ganondorf / Ice Climbers / Kirby.
  bowser_fire_breath: ['fb_s5_a_c1'],
  sing_notes: ['note_red_core', 'note_blue_core', 'note_green_core'],
  warlock_punch: ['punch_a_c1'],
  wizards_foot: ['color1'],
  gerudo_dragon: ['s12_a_c1'],
  ice_shot: ['birth_a_c1'],
  kirby_stone: ['dust_a_c1'],
  // Link / Young Link (shared spin_attack_trail).
  spin_attack_trail: ['color1', 'color2'],
}

// Some editors expose a summary picker keyed color1/color2 that fans out to
// _c1/_c2 offset layers. Map those summary keys to the representative layer
// pictogram so the Advanced summary pickers still get an image.
const SUMMARY_ALIAS = {
  screw_attack: { color1: 'arc_c1', color2: 'arc_c2' },
  missile: { color1: 'contrail_c1', color2: 'backblast_c1' },
  charge_shot: { color1: 'needles_c1', color2: 'needles_c2' },
  // Multi-layer DualColor extras whose editor shows summary color1/color2
  // pickers -- alias to a representative _c1/_c2 crop.
  raptor_boost: { color1: 'color1', color2: 'color2' },
  pikachu_fsmash: { color1: 'fsmash_pre_c1', color2: 'fsmash_pre_c2' },
  pikachu_thunder_jolt_air: { color1: 'jolt_air_mid_c1', color2: 'jolt_air_mid_c2' },
  pikachu_thunder_jolt_ground: { color1: 'jolt_gnd_a_c1', color2: 'jolt_gnd_a_c2' },
  ness_pk_thunder: { color1: 'tip_c1', color2: 'ball_flare1_c2' },
  ness_psi_magnet: { color1: 'psimag_a_c1', color2: 'psimag_a_c2' },
  ness_pk_fire: { color1: 'pillar_ring_in_c1', color2: 'pillar_ring_in_c2' },
  mario_fireball: { color1: 'hand_smoke_a_c1', color2: 'hand_smoke_a_c1' },
  mario_fireball_aura: { color1: 'aura_07_c1', color2: 'aura_07_c1' },
  mario_tornado: { color1: 'outer_swirl1_c1', color2: 'outer_swirl1_c1' },
  mario_cape: { color1: 'cloth_c1', color2: 'cloth_c1' },
  cape_sparkles: { color1: 'sparkle_a_c1', color2: 'sparkle_a_c1' },
  doc_cape: { color1: 'cloth_c1', color2: 'cloth_c1' },
  luigi_cyclone: { color1: 'torn_outer_c1', color2: 'torn_outer_c1' },
  luigi_fireball: { color1: 'fb_aura_42_c1' },
  luigi_fireball_smoke: { color1: 'fb_smoke_s1_c1', color2: 'fb_smoke_s1_c1' },
  luigi_hitspark: { color1: 'hitspark_s11_c1', color2: 'hitspark_s11_c1' },
  common_electric: { color1: 'elec_s0_a_c1', color2: 'elec_s0_a_c1' },
  thunder_jolt_spark: { color1: 'jolt_spark_a_c1', color2: 'jolt_spark_a_c1' },
  zelda_farore: { color1: 'farore_c1', color2: 'farore_c1' },
  zelda_transform: { color1: 'transform_c1', color2: 'transform_c1' },
  bowser_fire_breath: { color1: 'fb_s5_a_c1', color2: 'fb_s5_a_c1' },
  warlock_punch: { color1: 'punch_a_c1', color2: 'punch_a_c1' },
  gerudo_dragon: { color1: 's12_a_c1', color2: 's12_a_c1' },
  ice_shot: { color1: 'birth_a_c1', color2: 'birth_a_c1' },
  kirby_stone: { color1: 'dust_a_c1', color2: 'dust_a_c1' },
}

export function pictogramSrc(extraId, layerId) {
  if (!extraId || !layerId) return null
  if (extraId === 'screw_attack' && ['arc', 'warm_swirl'].includes(layerId)) {
    return `${BASE}screw_attack_${layerId}.svg`
  }
  if (extraId === 'upb_charge_fire' && layerId === 'color1') {
    return `${BASE}upb_charge_fire_color1.svg`
  }
  // Group guides: Core and Tint both affect the highlighted element. Keep
  // these on the Flame/Wisp card rather than implying a separate spatial
  // location for either color operand.
  if (extraId === 'charge_flames' && ['flame', 'wisp'].includes(layerId)) {
    return `${BASE}charge_flames_${layerId}.svg`
  }
  if (extraId === 'sword' && ['inner', 'outer'].includes(layerId)) {
    return `${BASE}sword_${layerId}.svg`
  }
  if (extraId === 'laser' && ['wide', 'thin', 'outline', 'center', 'tip'].includes(layerId)) {
    return `${BASE}laser_${layerId}.svg`
  }
  // Purpose-drawn layer diagrams: the selected component is cyan; context is gray.
  if (extraId === 'shine' && ['hex', 'primary', 'secondary', 'sparkles', 'flash1', 'flash2'].includes(layerId)) {
    return `${BASE}shine_${layerId}.svg`
  }
  const have = HAVE[extraId]
  if (have && have.includes(layerId)) return `${BASE}${extraId}_${layerId}.png`
  const alias = SUMMARY_ALIAS[extraId]?.[layerId]
  if (alias && HAVE[extraId]?.includes(alias)) return `${BASE}${extraId}_${alias}.png`
  return null
}

// An overview is context only. Do not turn a mixed-color crop into an
// isolated layer guide just because its filename contains a native key.
export function effectOverviewSrc(extraId, keys = []) {
  const layer = keys.find(key => HAVE[extraId]?.includes(key)) || HAVE[extraId]?.[0]
  return layer ? `${BASE}${extraId}_${layer}.png` : null
}

// Per-control references require a judged, isolated comparison. The old PNGs
// lack that provenance, including pairs that only differ in framing. Add new
// filenames here only after recording the changed control and capture evidence
// in research/docs-research/effect-maps; HAVE still determines whether an asset exists.
const VERIFIED_LAYER_IMAGES = new Set([])
const SHINE_GUIDES = new Set(['hex', 'primary', 'secondary', 'sparkles', 'flash1', 'flash2']
  .map(key => `shine_${key}.svg`).concat(['wide', 'thin', 'outline', 'center', 'tip'].map(key => `laser_${key}.svg`), ['inner', 'outer'].map(key => `sword_${key}.svg`)))

/** Presentation metadata applies even to legacy callers that pass just a URL. */
export function pictogramDetails(src) {
  const filename = src?.split('/').pop()
  if (['screw_attack_arc.svg', 'screw_attack_warm_swirl.svg'].includes(filename)) {
    return {
      kind: 'diagram',
      label: 'Layer guide',
      caption: 'Cyan highlights the electrical arcs or rotating swirl. Core and Tint both color that element. The arcs appear briefly during the spin. This is a schematic guide.'
    }
  }
  if (filename === 'upb_charge_fire_color1.svg') {
    return {
      kind: 'diagram',
      label: 'Layer guide',
      caption: 'Cyan highlights the fire-puff texture behind the moving fighter. Up-B trail colors also tint these puffs. This is a schematic guide.'
    }
  }
  if (['charge_flames_flame.svg', 'charge_flames_wisp.svg'].includes(filename)) {
    return {
      kind: 'diagram',
      label: 'Layer guide',
      caption: 'Cyan highlights this part of the charging flames. Core and Tint both color the highlighted element. This is a schematic guide.'
    }
  }
  if (SHINE_GUIDES.has(filename)) {
    return {
      kind: 'diagram',
      label: 'Layer guide',
      caption: 'The highlighted part shows the selected layer. This is a schematic guide; use Test in Game to see your current colors.'
    }
  }
  if (VERIFIED_LAYER_IMAGES.has(filename)) {
    return {
      kind: 'layer',
      label: 'Layer reference',
      caption: 'This reference shows the selected layer with example colors. Use Test in Game to see your current colors.'
    }
  }
  return {
    kind: 'overview',
    label: 'Effect reference',
    caption: 'This move is shown with example colors. Several layers appear together. Use Test in Game to check which part this control changes.'
  }
}

/** Only isolated references belong beside an individual Core/Tint control. */
export function controlPictogramSrc(extraId, layerIds) {
  for (const layerId of layerIds) {
    const src = pictogramSrc(extraId, layerId)
    if (src && pictogramDetails(src).kind !== 'overview') return src
  }
  return null
}
