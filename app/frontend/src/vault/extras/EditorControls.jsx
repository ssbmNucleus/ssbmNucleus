import { useId } from 'react'
import { pictogramSrc, controlPictogramSrc } from './pictograms'
import LayerPictogram from './LayerPictogram'

/**
 * EditorControls - shared building blocks for the extras mod-creation editors
 * (EffectEditorPage + the bespoke Laser/UpB/Shine/Sword/SideB/LaserRing
 * editors). 2026-07 redesign:
 *
 *  - ColorRow / LayerSwatch: the "current color" control is a large, obviously
 *    clickable swatch (hover ring + corner edit badge + tooltip) that opens the
 *    native full color picker. No more bare <input type=color> square.
 *  - PresetRow: ONE preset strip per editor (replaces both the per-picker
 *    10-swatch strips and the bottom "Quick presets" row, which duplicated
 *    each other confusingly). A preset recolors the WHOLE effect via the
 *    editor's fan-out (relative-recolor macro / bespoke native-format fanOut).
 *  - deriveLayerGroups: turns an extraType's wired offsets into per-ELEMENT
 *    layer groups for Advanced mode (front / trail / dots / hit_smoke ... --
 *    the pictogram granularity), instead of only the Primary/Secondary
 *    summary properties.
 *
 * All components speak display hex ("#RRGGBB"); callers convert to/from their
 * storage format (RGB "RRGGBB", RGBY, ...) so save shapes stay byte-identical.
 */

// One shared preset palette. Bespoke editors map hex -> native format in
// their fanOut; DualColor feeds it to the relative-recolor macro.
export const COLOR_PRESETS = [
  { name: 'Red', hex: '#FF0000' },
  { name: 'Blue', hex: '#0066FF' },
  { name: 'Green', hex: '#00FF00' },
  { name: 'Yellow', hex: '#FFFF00' },
  { name: 'Magenta', hex: '#FF00FF' },
  { name: 'Cyan', hex: '#00FFFF' },
  { name: 'Orange', hex: '#FF6600' },
  { name: 'Purple', hex: '#9900FF' },
  { name: 'White', hex: '#FFFFFF' },
  { name: 'Pink', hex: '#FF66CC' }
]

function normHex(hex) {
  if (!hex) return '#FFFFFF'
  const h = hex.startsWith('#') ? hex : `#${hex}`
  return h.length >= 7 ? h.slice(0, 7).toUpperCase() : '#FFFFFF'
}

// Small pencil/edit glyph for the swatch corner badge.
function EditBadge() {
  return (
    <span className="extra-swatch-edit" aria-hidden="true">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
        <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
      </svg>
    </span>
  )
}

/**
 * LayerSwatch - the clickable current-color swatch. The native color input is
 * stretched invisibly over the whole control so clicking ANYWHERE on the
 * swatch opens the full picker; we draw our own fill + edit badge on top.
 */
export function LayerSwatch({ hex, onChange, label = 'Effect color', describedBy, size = 'md' }) {
  const display = normHex(hex)
  return (
    <label className={`extra-swatch extra-swatch-${size}`} title={`Choose ${label}`}>
      <input
        type="color"
        aria-label={label}
        aria-describedby={describedBy}
        value={display}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
      />
      <span className="extra-swatch-fill" style={{ background: display }} />
      <EditBadge />
    </label>
  )
}

/**
 * ColorRow - a full labeled color control: optional pictogram, label +
 * description, the LayerSwatch, and a monospace readout (hex + optional
 * native-format line). `size` bumps the swatch for the Simple-mode hero row.
 */
export function ColorRow({ label, description, hex, onChange, readout, picto, accessibleLabel, size = 'md' }) {
  const display = normHex(hex)
  const descriptionId = useId()
  return (
    <div className={`extra-color-row extra-color-row-${size}`}>
      {picto && (
        <LayerPictogram src={picto} label={accessibleLabel || label} />
      )}
      <div className="extra-color-row-text">
        <span className="extra-color-row-label">{label}</span>
        {description && <span id={descriptionId} className="extra-color-row-desc">{description}</span>}
      </div>
      <div className="extra-color-row-value">
        <span className="extra-color-row-hex">{display}</span>
        {readout && <span className="extra-color-row-readout">{readout}</span>}
      </div>
      <LayerSwatch hex={display} onChange={onChange} size={size}
        label={accessibleLabel || label || 'Effect color'}
        describedBy={description ? descriptionId : undefined} />
    </div>
  )
}

/**
 * PresetRow - the single unified preset strip. `onPick(hex)` should recolor
 * the WHOLE effect (both modes), e.g. the relative-recolor macro / bespoke
 * fanOut. Rendered once per editor, right under the mode toggle.
 */
export function PresetRow({ onPick, activeHex }) {
  const active = activeHex ? normHex(activeHex) : null
  return (
    <div className="extra-preset-row">
      <span className="extra-preset-row-label">Presets</span>
      <div className="extra-preset-row-swatches">
        {COLOR_PRESETS.map((preset) => (
          <button
            key={preset.name}
            type="button"
            className={`laser-preset ${active === preset.hex ? 'active' : ''}`}
            style={{ backgroundColor: preset.hex }}
            onClick={() => onPick(preset.hex)}
            title={`${preset.name} — recolors the whole effect`}
            aria-label={`Apply ${preset.name.toLowerCase()} preset to the whole effect`}
            aria-pressed={active === preset.hex}
          />
        ))}
      </div>
    </div>
  )
}

// ── Layer-group derivation (Advanced mode granularity) ─────────────────────
//
// Advanced mode shows HUMAN elements, not raw offsets. The wired layer keys
// fall into two kinds:
//  - semantic keys named at WIRE time from identified in-game elements
//    (front / trail / hit_smoke / hand_smoke_a ...) -> each cleaned element
//    becomes ONE card, with its lettered/numbered variants MERGED (a Core
//    picker drives every _c1 record of the element at once);
//  - script-discriminator keys (fb_s5_a, s12_b ...) whose only identity is
//    "part of the whole effect" -> they collapse into the Main Colors pair
//    (Primary drives them + color1, Secondary likewise), which is exactly
//    the identified granularity and matches the legacy save-time fan-out.

const CORE_SUFFIX_RE = /_(c1|core)$/
const TINT_SUFFIX_RE = /_(c2|glow)$/

// Discriminator tokens carry no human meaning: single letters (a/b/c/x),
// script numbers (s5, s11), bare numbers / hex-block ids (07, 42), record
// suffixes (c1/c2).
const DROP_TOKEN_RE = /^(?:s\d+[a-z]?|\d+|[a-z]|c\d)$/i

// Small honest expansions for WIRE-time shorthand.
const ABBREV = {
  gnd: 'Ground',
  elec: 'Electric',
  psimag: 'PSI Magnet',
  fsmash: 'F-Smash',
  torn: 'Tornado',
  mat: 'Flare Burst',
  hitspark: 'Hit Spark'
}

// Clean a raw layer base into a human element label ('' = no identity left,
// i.e. a pure script-discriminator key that belongs to Main Colors).
function cleanElementLabel(base) {
  const words = []
  for (let tok of base.split('_')) {
    if (DROP_TOKEN_RE.test(tok)) continue
    tok = tok.replace(/\d+$/, '') // ripple1 -> ripple, flare1 -> flare
    if (!tok) continue
    if (ABBREV[tok.toLowerCase()]) {
      words.push(ABBREV[tok.toLowerCase()])
      continue
    }
    if (tok.length <= 2) continue // leftover abbreviations (fb, in, ...)
    words.push(tok[0].toUpperCase() + tok.slice(1))
  }
  return words.join(' ')
}

/**
 * deriveLayerGroups(extraType) -> [{ id, label, picto, controls }] where each
 * control is { id, label, description, keys, picto, accessibleLabel } -- ONE picker driving every
 * listed layer key (so "Trail / Core" recolors all trail core records at
 * once, and "Main Colors / Primary" drives color1 plus every native core
 * record, keeping the live preview + save fan-out in sync).
 */
export function deriveLayerGroups(extraType) {
  if (!extraType) return []
  const props = extraType.properties || []
  const propById = Object.fromEntries(props.map((p) => [p.id, p]))
  const offsetKeys = Object.keys(extraType.offsets || {})

  // The real wired layers; fall back to properties for offset-less extras
  // (texture_recolor etc.), and keep any labeled prop key visible.
  const keys = [...new Set([
    ...offsetKeys,
    ...props.map((p) => p.id)
  ])]

  // Bucket keys into elements.
  const elements = new Map() // label -> { label, coreKeys, tintKeys, rawBases }
  const mainCore = []
  const mainTint = []
  const bucket = (label) => {
    if (!elements.has(label)) {
      elements.set(label, { label, coreKeys: [], tintKeys: [], rawBases: [] })
    }
    return elements.get(label)
  }

  for (const key of keys) {
    if (key === 'color1') { mainCore.unshift(key); continue }
    if (key === 'color2') { mainTint.unshift(key); continue }

    const isTint = TINT_SUFFIX_RE.test(key)
    const base = key.replace(CORE_SUFFIX_RE, '').replace(TINT_SUFFIX_RE, '')
    // A key with its own identified property label always stays visible,
    // even if the raw name is short (sing_notes note pairs etc.).
    const label = cleanElementLabel(base)

    if (!label && !propById[key]) {
      // Pure script-discriminator layer -> collapses into Main Colors.
      ;(isTint ? mainTint : mainCore).push(key)
      continue
    }
    const el = bucket(label || propById[key].name)
    ;(isTint ? el.tintKeys : el.coreKeys).push(key)
    el.rawBases.push(base)
  }

  // Summary pickers are macros over native channels. Every native value is
  // initialized explicitly by the editor, so changing only color1/color2
  // would lose to those values at save time and leave the effect unchanged.
  // Keep the individual element rows for edits after applying the macro.
  if (mainCore.includes('color1')) {
    mainCore.push(...offsetKeys.filter((key) => CORE_SUFFIX_RE.test(key)
      && !mainCore.includes(key)))
  }
  if (mainTint.includes('color2')) {
    mainTint.push(...offsetKeys.filter((key) => TINT_SUFFIX_RE.test(key)
      && !mainTint.includes(key)))
  }
  // A summary with no native target is a preview-only no-op. Offset-less
  // texture extras still use their property directly and retain that row.
  if (offsetKeys.length) {
    if (!mainCore.some((key) => offsetKeys.includes(key))) mainCore.length = 0
    if (!mainTint.some((key) => offsetKeys.includes(key))) mainTint.length = 0
  }

  const groups = []

  // Main Colors first (whenever the summary pair exists).
  if (mainCore.length || mainTint.length) {
    const controls = []
    if (mainCore.length) {
      controls.push({
        id: 'main_core',
        label: propById.color1?.name || 'Primary',
        description: propById.color1?.description,
        keys: mainCore
      })
    }
    if (mainTint.length) {
      controls.push({
        id: 'main_tint',
        label: propById.color2?.name || 'Secondary',
        description: propById.color2?.description,
        keys: mainTint
      })
    }
    groups.push({
      id: '__main',
      label: 'Main Colors',
      picto: pictogramSrc(extraType.id, 'color1'),
      controls
    })
  }

  for (const el of elements.values()) {
    const controls = []
    const propFor = (ks) => (ks.length === 1 ? propById[ks[0]] : null)
    if (el.coreKeys.length) {
      const p = propFor(el.coreKeys)
      controls.push({
        id: `${el.label}_core`,
        label: p?.name || (el.tintKeys.length ? 'Core' : 'Color'),
        description: p?.description,
        keys: el.coreKeys
      })
    }
    if (el.tintKeys.length) {
      const p = propFor(el.tintKeys)
      controls.push({
        id: `${el.label}_tint`,
        label: p?.name || 'Tint',
        description: p?.description,
        keys: el.tintKeys
      })
    }
    // Prefer an explicit element guide over a legacy whole-effect crop.
    // Core and Tint can color the same element without separate spatial parts.
    let picto = null
    for (const k of [...el.rawBases, ...el.coreKeys, ...el.tintKeys, ...el.rawBases.map((b) => `${b}_c1`)]) {
      picto = pictogramSrc(extraType.id, k)
      if (picto) break
    }
    groups.push({ id: el.label, label: el.label, picto, controls })
  }

  // Overview crops stay on the card. An isolated layer reference belongs on
  // its specific control, and never appears again on the same card header.
  for (const group of groups) {
    const shown = new Set()
    for (const control of group.controls) {
      const src = controlPictogramSrc(extraType.id, control.keys)
      control.picto = src && !shown.has(src) ? src : null
      control.accessibleLabel = `${group.label}: ${control.label}`
      if (control.picto) {
        shown.add(src)
        if (group.picto === src) group.picto = null
      }
    }
  }
  return groups
}
