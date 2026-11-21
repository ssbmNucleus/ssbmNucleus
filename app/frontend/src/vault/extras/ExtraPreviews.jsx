/**
 * Extra preview components -- pure presentational (props -> JSX, no state,
 * no hooks, no API calls). Rendered by three surfaces:
 *   - vault/extras/ExtraCards.jsx     (vault extras cards)
 *   - upload/UploadPage.jsx           (upload thumbnails)
 *   - projects/characters/ExtrasView.jsx (Character Mode extras panel)
 *
 * Merged from the near-duplicate Character Mode ExtraPreviews.jsx
 * copy on 2026-08-22 (that file is deleted; this one is now the only copy).
 * Equivalence was proved by rendering every export against 194 fixtures --
 * every extra type in shared/data/extraTypes.js plus edge cases -- through
 * renderToStaticMarkup and diffing the HTML. The real deltas and how they
 * were resolved:
 *
 * 1. Root width. The mex copy set inline `width: '100%'` on all 52 preview
 *    roots; this copy relied on `.extra-mod-image-container .laser-*-preview`
 *    in StorageViewer.css. Both consumers put the root in a flex/grid box, but
 *    UploadPage.css sizes it with `.upload-thumb-extra > * { width: 80px }`,
 *    which an inline width would override and shrink. `minWidth: '100%'` gives
 *    the same fill as the mex copy inside `.costume-preview`/
 *    `.extra-mod-image-container`, and is a guaranteed no-op on UploadPage
 *    (every .upload-thumb box is <= 54px, so the 80px CSS width always wins).
 * 2. className hooks (`laser-beam-preview`, `sideb-preview`, ...) kept from
 *    this copy -- StorageViewer.css targets them; they are inert elsewhere.
 * 3. `justifyContent: 'center'` on the laser/side-B roots kept from this copy:
 *    those children are absolutely positioned, so it changes no layout, and it
 *    matches every sibling preview.
 * 4. LaserRingPreview geometry (66/44/34 px rings, 8px drop-shadow) kept from
 *    this copy over the mex copy's larger 76/50/38 + 10px: two of the three
 *    surfaces already render these numbers, so keeping them changes the least.
 * 5. SVG def ids: `sw-*` / `shieldBubble` kept from this copy. The mex copy's
 *    `swc-*` / `cmShieldBubble` prefixes only existed to avoid id collisions
 *    while both copies could render on one page -- moot with one copy.
 * 6. ModelPreview label: the mex copy's unconditional '3D Model' kept over
 *    this copy's `mod.model_file ? '3D Model' : 'No model'`. ExtrasView's
 *    "Currently in MEX" card passes `{ name: 'Current' }` with no model_file
 *    and would be mislabelled "No model"; storage mods always carry
 *    model_file (uploadCatalog.js), so the conditional never fired here.
 *    This copy's ellipsis styles on that label are kept.
 * 7. ShieldTexturePreview owner: `extraType?.owner || character` (this copy's
 *    superset -- the mex copy had no `character` prop, and does not pass one).
 * 8. Optional chaining on `extraType` in the dispatcher taken from the mex
 *    copy (it tolerates a missing extraType; this copy threw).
 * 9. `currentColorsToMods` existed only in the mex copy; brought over verbatim
 *    (ExtrasView imports it).
 * 10. The mex copy's `console.warn` for unknown extra types was dropped -- the
 *    vault renders many cards at once and the fallback is intentional.
 */
import { isImageShineMod, supportsImageMod } from './imageShineMod'
import { LaserBeamPreview, SideBPreview, UpBPreview, ShinePreview, LaserRingPreview, SwordPreview } from './previews/BespokePreviews'
import { DualColorPreview } from './previews/DualColorPreview'
import { SingNotesPreview } from './previews/SingNotesPreview'
import { ModelPreview, ShieldTexturePreview, ImageEffectPreview } from './previews/AssetPreviews'

// The per-type previews live in ./previews/; this module stays the one import
// point (ExtraPreview dispatches to them) and re-exports them unchanged.
export { LaserBeamPreview, SideBPreview, UpBPreview, ShinePreview, LaserRingPreview, SwordPreview, DualColorPreview, SingNotesPreview, ModelPreview, ShieldTexturePreview, ImageEffectPreview }

/**
 * ExtraPreview - Renders appropriate preview based on extra type
 */
export function ExtraPreview({ extraType, modifications, mod, character, compact = false }) {
  // Model types use ModelPreview
  if (extraType?.type === 'model' || mod?.modifications?.sideb_model) {
    return <ModelPreview extraType={extraType} mod={mod} compact={compact} />
  }
  // An image mod on a color extra (image shines): show its picture, not a
  // gradient it does not have. Keyed off the mod, not the type -- the same
  // extra also holds ordinary color mods.
  if (supportsImageMod(extraType) && isImageShineMod(mod)) {
    return <ImageEffectPreview extraType={extraType} mod={mod} character={character} compact={compact} />
  }
  // texture_region extras (common_shield) show the mod's decoded texture
  if (extraType?.format === 'texture_region') {
    return <ShieldTexturePreview extraType={extraType} mod={mod} character={character} compact={compact} />
  }
  if (extraType?.id === 'sideb') {
    return <SideBPreview modifications={modifications} compact={compact} />
  }
  if (extraType?.id === 'upb') {
    return <UpBPreview modifications={modifications} compact={compact} />
  }
  if (extraType?.id === 'shine') {
    return <ShinePreview modifications={modifications} compact={compact} />
  }
  if (extraType?.id === 'laser_ring') {
    return <LaserRingPreview modifications={modifications} compact={compact} />
  }
  if (extraType?.id === 'sword') {
    return <SwordPreview modifications={modifications} compact={compact} />
  }
  // Jigglypuff Sing notes -- 6 independent per-note colors, not a
  // color1/color2 pair, so it gets its own preview (not DualColorPreview).
  if (extraType?.id === 'sing_notes') {
    return <SingNotesPreview modifications={modifications} compact={compact} />
  }
  // 2-color effects (punch, kick, raptor boost, thunder, fireball, shadow ball, pk_thunder, up-smash swirl, Samus screw attack/missile/charge shot/charge ball, Luigi fireball/smoke/cyclone, Mario/Doc fireball/aura/cape/tornado/coins, Pikachu thunder jolt/fsmash, Ness PSI magnet/PK thunder/PK fire)
  if (['falcon_punch', 'falcon_kick', 'raptor_boost', 'warlock_punch', 'wizards_foot', 'gerudo_dragon', 'kirby_stone', 'ice_shot', 'thunder', 'pk_thunder', 'fireball', 'shadow_ball', 'upsmash', 'screw_attack', 'missile', 'charge_shot', 'charge_ball', 'upb_charge_fire', 'charge_flames', 'breath_texture', 'common_fire', 'common_flash', 'common_electric', 'thunder_jolt_spark', 'jab_finisher_spark', 'luigi_fireball', 'luigi_fireball_smoke', 'luigi_cyclone', 'luigi_hitspark', 'mario_fireball', 'mario_fireball_aura', 'cape_sparkles', 'mario_cape', 'doc_cape', 'mario_tornado', 'mario_coins', 'pikachu_thunder_jolt_air', 'pikachu_thunder_jolt_ground', 'pikachu_fsmash', 'ness_psi_magnet', 'ness_pk_thunder', 'ness_pk_fire', 'zelda_farore', 'zelda_transform', 'spin_attack_trail', 'bowser_fire_breath', 'kirby_copy_ganon', 'kirby_copy_iceclimbers', 'kirby_copy_bowser', 'kirby_copy_luigi', 'kirby_copy_mario'].includes(extraType?.id)) {
    return <DualColorPreview extraType={extraType} modifications={modifications} compact={compact} />
  }
  // Default to laser preview
  return <LaserBeamPreview modifications={modifications} compact={compact} />
}

// Convert currentColors (object from API) to modifications format for preview
export function currentColorsToMods(colors) {
  if (!colors) return null
  const mods = {}
  for (const [key, value] of Object.entries(colors)) {
    mods[key] = { color: value }
  }
  // Fan-out extras (offsets keyed per-layer like `fb_s7_a_c1`/`fb_s7_a_c2`)
  // have no color1/color2 summary keys in the current-colors response, but
  // DualColorPreview draws from exactly those — without a synthesized summary
  // the "Currently in MEX" card silently falls back to white/blue no matter
  // what is installed. Pick the most saturated per-layer value so vanilla
  // shows its real hue despite FFFFFF "intensity" layers; Simple-mode installs
  // write one color to every _c1/_c2 layer, so the pick is exact there.
  const saturation = (hex) => {
    if (typeof hex !== 'string' || hex.length < 6) return -1
    const ch = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16))
    return ch.some(Number.isNaN) ? -1 : Math.max(...ch) - Math.min(...ch)
  }
  const mostSaturated = (suffix) => Object.keys(colors)
    .filter(k => k.endsWith(suffix) && saturation(colors[k]) >= 0)
    .sort((a, b) => saturation(colors[b]) - saturation(colors[a]))[0]
  for (const [summary, suffix] of [['color1', '_c1'], ['color2', '_c2']]) {
    if (!mods[summary]) {
      const key = mostSaturated(suffix)
      if (key) mods[summary] = { color: colors[key] }
    }
  }
  return mods
}
