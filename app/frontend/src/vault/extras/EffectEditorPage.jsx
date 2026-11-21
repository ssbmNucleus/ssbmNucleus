/**
 * EffectEditorPage - the full-page editor for ONE move of ONE character.
 *
 * A move (Up-B, Fireball, Falcon Punch, ...) is one saved mod. The page is a
 * scrollable list of rows, one per visible part of the move: each row has
 * its own live pictogram (the whole move drawn with that part highlighted),
 * that part's color pickers, and the in-game reference where one exists.
 * Rows come from the move's own layers (`deriveLayerGroups`, or the curated
 * Up-B rows), plus the move's nested parts (`getUnitParts`: flight puff
 * texture, charge flames, fireball aura, ...) placed among them. One name,
 * one Save, one Delete.
 *
 * Saves the same `/storage/extras/create` recipe the old modals did:
 * primary layers in their native formats, the legacy nested texture (`fire`)
 * for Up-B / Falcon Punch, and `parts[<part id>]` for the nested parts.
 *
 * Bespoke effects with their own storage formats and extra UI (laser,
 * side-B, shine + image tab, sword, blaster flash) keep their editors;
 * see isPageEditable.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../shared/transport/api'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { hexToRgby, rgbyToHex, formatRgby } from '../lib/rgbyColor'
import { relativeRecolorLayers, resolveDominantHue } from '../lib/relativeRecolor'
import { getExtraType, getUnitParts } from '../../shared/data/extraTypes'
import { ColorRow, PresetRow, deriveLayerGroups } from './EditorControls'
import LiveEffectPictogram from './LiveEffectPictogram'
import { effectReference } from './effectReferences'
import { serializeEditorColors, loadCurrentTextureColor } from './editorRecipe.js'
import { readPartColors, serializePartColors, flattenPartColors, fanOutPart, isTexturePart, partPreviewKey } from './unitParts.js'
import { upbRows } from './upbParts.js'
import { SaveIcon } from '../../shared/ui/Icons'
import './EffectEditorPage.css'

// Legacy nested texture recipes stored INSIDE the move's mod (mirrors the
// backend's SIBLING_TEXTURE_EXTRAS): the key in modifications and the
// texture extra whose current color seeds a new mod.
const SIBLING_TEXTURE = {
  upb: { key: 'fire', textureType: 'upb_texture', label: 'Flame Texture', description: 'Firefox / Firebird streamer texture color' },
  falcon_punch: { key: 'fire', textureType: 'punch_texture', label: 'Fire Texture', description: 'Punch fire / bird texture color' },
}

const BESPOKE = new Set(['laser', 'sideb', 'shine', 'sword', 'laser_ring'])

/** Which extra types this page edits (the rest keep their bespoke modals). */
export function isPageEditable(extraType) {
  if (!extraType) return false
  if (extraType.type === 'model' || extraType.format === 'texture_region') return false
  return !BESPOKE.has(extraType.id)
}

const strip = hex => String(hex || '').replace('#', '').toUpperCase()

function formatOf(extraType, key) {
  const prop = extraType.properties?.find(p => p.id === key)
  return prop?.format || extraType.offsets?.[key]?.format || 'RGB'
}

function toDisplayHex(value, format) {
  if (format === 'RGBY') return rgbyToHex(value || 'FE60')
  const rgb = strip(value)
  return `#${rgb.length >= 6 ? rgb.slice(0, 6) : 'FFFFFF'}`
}

function fromDisplayHex(hex, format) {
  return format === 'RGBY' ? hexToRgby(hex) : strip(hex)
}

/** Every primary layer explicitly initialized: saved value > vanilla > summary vanilla. */
function initialPrimaryColors(extraType, mod) {
  const vanilla = extraType.vanilla || {}
  const saved = mod?.modifications || {}
  const keys = [...new Set([...Object.keys(extraType.offsets || {}),
    ...(extraType.properties || []).map(p => p.id)])]
  const out = {}
  for (const key of keys) {
    const summary = key.endsWith('_c2') ? vanilla.color2 : vanilla.color1
    out[key] = saved[key]?.color || vanilla[key] || summary
      || (formatOf(extraType, key) === 'RGBY' ? 'FE60' : 'FFFFFF')
  }
  return out
}

/** The rows of the page for this move + character. */
function buildRows(extraType, partTypes) {
  if (extraType.id === 'upb') {
    return upbRows(partTypes).map(row => ({
      ...row,
      controls: row.controls.map(c => c.texture
        ? { ...c, sibling: true }
        : c),
    }))
  }
  const rows = []
  const groups = deriveLayerGroups(extraType)
  for (const group of groups) {
    rows.push({
      id: group.id, label: group.label, section: extraType.name,
      controls: group.controls.map(c => ({ key: c.keys[0], keys: c.keys, label: c.label, description: c.description })),
    })
  }
  const sibling = SIBLING_TEXTURE[extraType.id]
  if (sibling) {
    rows.push({ id: '__fire', label: sibling.label, section: extraType.name,
      controls: [{ key: sibling.key, sibling: true, label: 'Color', description: sibling.description }] })
  }
  for (const part of partTypes) {
    if (isTexturePart(part)) {
      const prop = part.properties?.[0] || { id: 'color1', name: 'Color' }
      rows.push({ id: `part:${part.id}`, partId: part.id, label: part.name, section: part.name,
        description: part.description,
        ref: { effectId: part.id, partId: '*' },
        controls: [{ part: part.id, key: prop.id, label: prop.name, description: prop.description }] })
      continue
    }
    for (const group of deriveLayerGroups(part)) {
      rows.push({ id: `part:${part.id}:${group.id}`, partId: part.id, section: part.name,
        label: group.id === '__main' ? part.name : `${part.name} · ${group.label}`,
        ref: { effectId: part.id, partId: group.id },
        controls: group.controls.map(c => ({ part: part.id, key: c.keys[0], keys: c.keys, label: c.label, description: c.description })),
      })
    }
  }
  return rows
}

export default function EffectEditorPage({ character, extraType, editingMod, onBack, onSaved, onDeleted }) {
  const partTypes = useMemo(() => getUnitParts(character, extraType.id), [character, extraType.id])
  const rows = useMemo(() => buildRows(extraType, partTypes), [extraType, partTypes])
  const sibling = SIBLING_TEXTURE[extraType.id]

  const [name, setName] = useState(editingMod?.name || '')
  const [colors, setColors] = useState(() => initialPrimaryColors(extraType, editingMod))
  const [partColors, setPartColors] = useState(() => readPartColors(editingMod, partTypes))
  const [textureColor, setTextureColor] = useState(() => strip(editingMod?.modifications?.[sibling?.key]?.color) || 'FF3300')
  const [loadingTexture, setLoadingTexture] = useState(false)
  const [wholeColor, setWholeColor] = useState(() => `#${strip(extraType.vanilla?.color1 || extraType.vanilla?.tip && rgbyToHex(extraType.vanilla.tip) || 'FF6600').slice(0, 6)}`)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState(null)
  const textureRevision = useRef(0)
  const rowRefs = useRef({})

  // A new mod's nested texture starts from what the project currently has.
  useEffect(() => {
    if (!sibling || editingMod?.modifications?.[sibling.key]?.color) return
    const owner = getExtraType(character, sibling.textureType)?.owner || character
    const revision = ++textureRevision.current
    setLoadingTexture(true)
    return loadCurrentTextureColor(api.get(`/storage/textures/current/${owner}/${sibling.textureType}`), {
      isCurrent: () => textureRevision.current === revision,
      onValue: data => { if (data.color) setTextureColor(strip(data.color)) },
      onError: err => console.warn('[EffectEditorPage] texture color:', err),
      onSettled: () => setLoadingTexture(false),
    })
  }, [character, sibling, editingMod])

  const changeTexture = hex => { textureRevision.current += 1; setLoadingTexture(false); setTextureColor(strip(hex)) }
  const setPrimary = (keys, format, hex) => setColors(prev => {
    const next = { ...prev }
    const value = fromDisplayHex(hex, format)
    for (const key of keys) next[key] = value
    return next
  })
  const setPart = (partId, keys, hex) => setPartColors(prev => ({
    ...prev, [partId]: { ...prev[partId], ...Object.fromEntries(keys.map(k => [k, strip(hex)])) },
  }))

  // Whole-effect recolor: primary layers keep their relative brightness
  // (Up-B fans one color to every layer in its native format, as before),
  // the nested texture takes the color, parts follow their own rule.
  const applyWhole = hex => {
    const rgb = strip(hex)
    setWholeColor(`#${rgb}`)
    setColors(prev => {
      const keys = Object.keys(prev)
      if (extraType.id === 'upb') {
        return Object.fromEntries(keys.map(key => [key, formatOf(extraType, key) === 'RGBY' ? hexToRgby(`#${rgb}`) : rgb]))
      }
      const recolored = relativeRecolorLayers(`#${rgb}`, extraType.vanilla || {}, resolveDominantHue(extraType), keys)
      const next = { ...prev }
      for (const key of keys) next[key] = strip(recolored[key] || rgb)
      return next
    })
    if (sibling) changeTexture(rgb)
    setPartColors(prev => Object.fromEntries(partTypes.map(t => [t.id, { ...prev[t.id], ...fanOutPart(`#${rgb}`, t) }])))
  }

  // One flat color map for every pictogram on the page.
  const preview = useMemo(() => {
    const flat = {}
    for (const [key, value] of Object.entries(colors)) flat[key] = formatOf(extraType, key) === 'RGBY' ? rgbyToHex(value) : value
    if (sibling) flat[sibling.key] = textureColor
    if (extraType.id === 'upb') flat.fire = textureColor
    Object.assign(flat, flattenPartColors(partColors))
    return flat
  }, [colors, textureColor, partColors, sibling, extraType])

  const previewKey = control => control.part ? partPreviewKey(control.part, control.key) : control.key
  const pictoParts = useMemo(() => rows.map(row => ({
    id: row.id, label: row.label, controls: row.controls.map(c => ({ key: previewKey(c) })),
  })), [rows])

  const scrollToRow = id => rowRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'center' })

  const handleSave = async () => {
    if (!name.trim()) { setError('Give the mod a name first'); return }
    setSaving(true)
    setError(null)
    try {
      const modifications = serializeEditorColors(colors, editingMod?.modifications)
      if (sibling) modifications[sibling.key] = { color: textureColor }
      if (partTypes.length) modifications.parts = serializePartColors(partColors, partTypes)
      else delete modifications.parts
      const body = { character, extraType: extraType.id, name: name.trim(), modifications }
      if (editingMod) body.modId = editingMod.id
      const data = await api.post('/storage/extras/create', body)
      playSound('newSkin')
      onSaved?.(data.mod)
    } catch (err) {
      playSound('error')
      setError(err.data?.error || err.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editingMod) return
    if (!await appConfirm(`Delete "${editingMod.name}"?`, { title: `Delete ${extraType.name} Mod`, confirmText: 'Delete' })) return
    setDeleting(true)
    try {
      await api.post('/storage/extras/delete', { character, extraType: extraType.id, modId: editingMod.id })
      playSound('boop')
      onDeleted?.(editingMod.id)
    } catch (err) {
      setError(`Delete failed: ${err.message}`)
      setDeleting(false)
    }
  }

  const sharedNote = extraType.shared && extraType.sharedWith?.length
    ? (extraType.sharedWith.length > 3 ? 'Shared with many characters'
      : `Shared by ${[extraType.owner, ...extraType.sharedWith].filter(Boolean).join(' and ')}`)
    : null

  // Group rows by section, keeping first-seen order.
  const sections = []
  for (const row of rows) {
    let section = sections.find(s => s.label === row.section)
    if (!section) { section = { label: row.section, rows: [] }; sections.push(section) }
    section.rows.push(row)
  }

  return (
    <div className="effect-page">
      <div className="effect-page-head">
        <button className="back-button" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); onBack() }}>
          ← {character} Extras
        </button>
        <div className="effect-page-title">
          <h2>{extraType.name}<span className="effect-page-char">{character}</span></h2>
          {sharedNote && <span className="effect-page-shared">{sharedNote}</span>}
        </div>
        <input
          className="effect-page-name"
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder={`Name this ${extraType.name} mod…`}
          aria-label="Mod name"
        />
        <div className="effect-page-actions">
          {editingMod && (
            <button className="laser-editor-delete" onClick={handleDelete} disabled={saving || deleting}>
              {deleting ? 'Deleting…' : 'Delete'}
            </button>
          )}
          <button className="laser-editor-save" onClick={handleSave} disabled={saving || deleting}>
            <SaveIcon /><span>{saving ? 'Saving…' : editingMod ? 'Save' : 'Save Mod'}</span>
          </button>
        </div>
      </div>

      {error && <div className="laser-editor-error">{error}</div>}

      <div className="effect-page-whole">
        <ColorRow size="lg" label="Recolor whole effect" hex={wholeColor}
          description="One color for every part below, keeping each part's relative brightness"
          onChange={applyWhole} />
        <PresetRow onPick={applyWhole} activeHex={wholeColor} />
      </div>

      {sections.map(section => (
        <section key={section.label} className="effect-page-section">
          {sections.length > 1 && <h3 className="effect-page-section-title">{section.label}</h3>}
          {section.rows.map(row => {
            const refType = row.ref?.effectId || extraType.id
            const reference = effectReference(refType, { id: row.ref?.partId || row.id, label: row.label, controls: row.controls }, character)
            const [x, y, w, h] = (reference?.viewBox || '0 0 112 112').split(' ').map(Number)
            return (
              <div key={row.id} className="effect-page-row" ref={el => { rowRefs.current[row.id] = el }}>
                <div className="effect-page-row-picto">
                  <LiveEffectPictogram effectId={extraType.id} character={character} parts={pictoParts}
                    selectedId={row.id} onSelect={scrollToRow} colors={preview} />
                </div>
                <div className="effect-page-row-controls">
                  <h4>{row.label}</h4>
                  {row.description && <p className="effect-page-row-desc">{row.description}</p>}
                  {row.controls.map(control => {
                    if (control.sibling) {
                      return <ColorRow key="fire" label={loadingTexture ? `${control.label} (loading…)` : control.label}
                        description={control.description} hex={`#${textureColor}`} onChange={changeTexture} />
                    }
                    if (control.part) {
                      const keys = control.keys || [control.key]
                      return <ColorRow key={`${control.part}:${control.key}`} label={control.label} description={control.description}
                        hex={`#${strip(partColors[control.part]?.[control.key] || 'FFFFFF').slice(0, 6)}`}
                        onChange={hex => setPart(control.part, keys, hex)} />
                    }
                    const keys = control.keys || [control.key]
                    const format = formatOf(extraType, control.key)
                    const prop = extraType.properties?.find(p => p.id === control.key)
                    return <ColorRow key={control.key} label={control.label}
                      description={control.description ?? prop?.description}
                      hex={toDisplayHex(colors[control.key], format)}
                      readout={format === 'RGBY' ? `RGBY ${formatRgby(colors[control.key] || 'FE60')}` : null}
                      onChange={hex => setPrimary(keys, format, hex)} />
                  })}
                  {reference && (
                    <figure className="effect-page-reference">
                      <svg viewBox={reference.viewBox || '0 0 112 112'} aria-label={`${row.label}: in-game reference`}>
                        <defs><clipPath id={`clip-${row.id.replace(/[^a-z0-9]/gi, '_')}`}><rect x={x} y={y} width={w} height={h} /></clipPath></defs>
                        <g clipPath={`url(#clip-${row.id.replace(/[^a-z0-9]/gi, '_')})`}>
                          <image href={reference.src} width={reference.viewBox ? 1280 : 112} height={reference.viewBox ? 960 : 112} />
                          {reference.outline ? <path d={reference.outline} className="effect-reference-highlight" />
                            : reference.point && <circle cx={reference.point[0]} cy={reference.point[1]} r="40" className="effect-reference-highlight" />}
                        </g>
                      </svg>
                      <figcaption>{reference.caption}</figcaption>
                    </figure>
                  )}
                </div>
              </div>
            )
          })}
        </section>
      ))}
    </div>
  )
}
