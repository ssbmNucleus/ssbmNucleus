import { BACKEND_URL } from '../shared/config/config'
import { EXTRA_TYPES } from '../shared/data/extraTypes'

// extra id -> ExtrasIcons key, from the per-character extra type definitions
const EFFECT_ICON_KEYS = (() => {
  const map = {}
  Object.values(EXTRA_TYPES).forEach(types => (types || []).forEach(type => {
    if (type.id && type.icon && !map[type.id]) map[type.id] = type.icon
  }))
  return map
})()

// Full extra type definition for an effect, so thumbnails can render the same
// colored ExtraPreview the vault's extras page shows. Owner character first,
// then any character (shared/common extras live under their owner).
function findExtraDef(character, effectType) {
  const byId = id => {
    const own = (EXTRA_TYPES[character] || []).find(type => type.id === id)
    if (own) return own
    for (const types of Object.values(EXTRA_TYPES)) {
      const def = (types || []).find(type => type.id === id)
      if (def) return def
    }
    return null
  }
  // Legacy metadata keys predate character-prefixed ids
  // (fireball -> mario_fireball, pk_thunder -> ness_pk_thunder)
  return byId(effectType)
    || byId(`${String(character).toLowerCase().replace(/[^a-z0-9]+/g, '_')}_${effectType}`)
}

export const CATEGORIES = [
  ['Character Costume', 'Character Skins'], ['Stage Skin', 'Stage Skins'],
  ['Effects', 'Effects'], ['Assets/Other', 'Assets / Other'],
  ['Custom Stage', 'Custom Stages'], ['Gameplay Mod', 'Gameplay Mods'], ['Patch', 'Patches']
]

export const CHARACTERS = [
  'Fox', 'Falco', 'Marth', 'Roy', 'Captain Falcon', 'Link', 'Young Link', 'Sheik',
  'Zelda', 'Peach', 'Ice Climbers', 'Pikachu', 'Pichu', 'Mewtwo', 'Jigglypuff',
  'Mario', 'Dr. Mario', 'Luigi', 'Bowser', 'Donkey Kong', 'Yoshi', 'Kirby',
  'Samus', 'Ness', 'Ganondorf', 'Mr. Game And Watch'
]

export const STAGES = [
  'Battlefield', 'Final Destination', 'Pokemon Stadium', 'Dreamland', 'Fountain of Dreams',
  "Yoshi's Story", 'Kongo Jungle', 'Jungle Japes', 'Kongo Falls', 'Brinstar',
  'Brinstar Depths', 'Corneria', 'Venom', 'Green Greens', 'Mute City', 'Big Blue',
  'Great Bay', 'Rainbow Cruise', 'Hyrule Temple', 'Onett', 'Fourside',
  "Princess Peach's Castle", 'Mushroom Kingdom', 'Mushroom Kingdom II', "Yoshi's Island",
  'Yoshi 64', 'Poke Floats', 'Icicle Mountain', 'Flat Zone', 'Other'
]

// Costume slot colors, keyed by the two-letter code at the end of the skin's
// costume_code (e.g. PlKpBk -> bk). Hexes match the website's color badges
// (getColorForBadge).
export const SLOT_COLORS = {
  nr: { name: 'Neutral', hex: '#e5e7eb' },
  re: { name: 'Red', hex: '#dc2626' },
  bu: { name: 'Blue', hex: '#2563eb' },
  gr: { name: 'Green', hex: '#16a34a' },
  ye: { name: 'Yellow', hex: '#eab308' },
  bk: { name: 'Black', hex: '#1f2937' },
  wh: { name: 'White', hex: '#f3f4f6' },
  pi: { name: 'Pink', hex: '#ec4899' },
  or: { name: 'Orange', hex: '#ea580c' },
  la: { name: 'Lavender', hex: '#a855f7' },
  aq: { name: 'Aqua', hex: '#06b6d4' },
  gy: { name: 'Grey', hex: '#6b7280' }
}

export function slotColorFor(costumeCode) {
  const match = /^pl\w{2}(\w{2})$/i.exec(String(costumeCode || ''))
  return match ? SLOT_COLORS[match[1].toLowerCase()] || null : null
}

export const titleCase = (value = '') => value.replace(/[_-]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
const path = (...parts) => parts.map(part => encodeURIComponent(String(part))).join('/')
const asArray = value => Array.isArray(value) ? value : []

export function buildVaultCatalog(metadata) {
  const items = []
  Object.entries(metadata?.characters || {}).forEach(([character, data]) => {
    asArray(data?.skins).forEach(skin => items.push({
      key: `costume:${character}:${skin.id}`, kind: 'costume', type: 'Costume',
      name: skin.color || skin.name || skin.id, parent: character, character,
      filename: skin.filename, category: 'Character Costume',
      slot: slotColorFor(skin.costume_code),
      preview: skin.has_csp ? `${BACKEND_URL}/storage/${path(character, skin.csp_filename || `${skin.id}_csp.png`)}` : null
    }))
    Object.entries(data?.extras || {}).forEach(([effectType, effects]) => {
      asArray(effects).forEach(effect => items.push({
        key: `effect:${character}:${effectType}:${effect.id}`, kind: 'effect', type: 'Effect',
        name: effect.name || effect.id, parent: `${character} / ${titleCase(effectType)}`,
        character, effectType, filename: effect.model_file, category: 'Effects',
        // effect.screenshot is storage-relative ("models/<id>_preview.png") --
        // same base as ExtraPreviews/ShieldTextureEditorModal, no 'extras/' dir
        preview: effect.screenshot ? `${BACKEND_URL}/storage/${path(character, ...String(effect.screenshot).split('/'))}` : null,
        effectIcon: EFFECT_ICON_KEYS[effectType] || 'effect',
        extraDef: findExtraDef(character, effectType),
        modifications: effect.modifications || null, raw: effect
      }))
    })
  })
  Object.entries(metadata?.stages || {}).forEach(([stage, data]) => {
    asArray(data?.variants).forEach(variant => items.push({
      key: `stage:${stage}:${variant.id}`, kind: 'stage', type: 'Stage skin',
      name: variant.name || variant.id, parent: titleCase(stage), stage,
      filename: variant.filename, category: 'Stage Skin',
      preview: variant.has_screenshot && variant.screenshot_filename
        ? `${BACKEND_URL}/storage/das/${path(stage, variant.screenshot_filename)}` : null
    }))
  })
  asArray(metadata?.custom_characters).forEach(char => items.push({
    key: `character:${char.slug}`, kind: 'character', type: 'Custom character',
    name: char.name || char.slug, parent: `${char.costume_count || 0} costumes`,
    filename: 'fighter.zip', category: 'Gameplay Mod',
    preview: char.has_css_icon ? `${BACKEND_URL}/storage/custom_characters/${path(char.slug, 'css_icon.png')}` : null
  }))
  asArray(metadata?.custom_stages).forEach(stage => items.push({
    key: `custom-stage:${stage.slug}`, kind: 'stage', type: 'Custom stage',
    name: stage.name || stage.slug, parent: 'Custom stage',
    filename: stage.dat_files?.join(', '), category: 'Custom Stage',
    preview: stage.has_banner ? `${BACKEND_URL}/storage/custom_stages/${path(stage.slug, 'banner.png')}` : null
  }))
  asArray(metadata?.xdelta).forEach(patch => items.push({
    key: `patch:${patch.id}`, kind: 'patch', type: 'Patch', name: patch.name || patch.id,
    parent: 'XDelta patch', filename: patch.filename, category: 'Patch',
    preview: `${BACKEND_URL}/storage/xdelta/${path(`${patch.id}.png`)}`
  }))
  asArray(metadata?.bundles).forEach(bundle => items.push({
    key: `bundle:${bundle.id}`, kind: 'patch', type: 'Mod bundle', name: bundle.name || bundle.id,
    parent: bundle.size_mb ? `${bundle.size_mb} MB bundle` : 'Nucleus bundle',
    filename: bundle.filename, category: 'Patch',
    preview: `${BACKEND_URL}/storage/bundles/${path(`${bundle.id}.png`)}`
  }))
  return items
}
