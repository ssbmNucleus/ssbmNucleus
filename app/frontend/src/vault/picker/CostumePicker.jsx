import { useEffect, useMemo, useRef, useState } from 'react'
import GalleryGrid, { searchBoxKeys } from '../../shared/ui/GalleryGrid'
import { api } from '../../shared/transport/api'
import { backendMediaUrl } from '../../shared/config/config'
import { playSound } from '../../shared/audio/sounds'
import { AI_VALUE, ROSTER, aiPick, costumeOptions, cssIconPath, fighterOptions, filterOptions, pickValue, stockCostumes, vaultCostumes } from './costumePicks'
import './CostumePicker.css'

// Stock slots per fighter, fetched once per session (they come from the user's
// extracted ISO and do not change while the app runs). A failure is not kept.
const stockLists = new Map()
export function fetchStockCostumes(character) {
  if (!stockLists.has(character)) {
    stockLists.set(character, api.get(`/api/mex/vanilla/costumes/${encodeURIComponent(character)}`)
      .then((data) => data?.costumes || [])
      .catch((error) => { stockLists.delete(character); throw error }))
  }
  return stockLists.get(character)
}

/**
 * Pick a fighter, then (mode 'costume') one of that fighter's costumes: the
 * vault's first, then the stock color slots. The Tracker's watch-with-mods grid
 * (GalleryGrid) with its keyboard model on: arrows move, Enter picks, Escape goes
 * back a step (then `onCancel`). It fills its host: Randall's starting-pick
 * popover (randall/assistant/StartPicker.jsx), which draws the surface.
 *
 * mode      'costume' (fighter, then costume) or 'fighter' (fighter only)
 * metadata  the vault metadata ({characters: {Fox: {skins: [...]}}}), as App loads it
 * fighters  the roster to offer, in order (default: the 26 Melee fighters)
 * value     the current pick or null; onChange(pick) receives a new one:
 *             {kind: 'vault', character, id, name, image}
 *             {kind: 'stock', character, code, color, name, image}
 *             {kind: 'fighter', character, image}
 *           (`image` is backend-relative)
 * loadStock (character) -> Promise of the stock rows; the default asks the backend
 * autoFocus focus the search box when a step opens
 */
export default function CostumePicker({
  mode = 'costume', metadata, fighters = ROSTER, value = null, onChange, onCancel,
  loadStock = fetchStockCostumes, autoFocus = false, media = backendMediaUrl,
}) {
  const [fighter, setFighter] = useState(mode === 'costume' && value?.character ? value.character : null)
  const [query, setQuery] = useState('')
  const [stock, setStock] = useState({ character: null, state: 'idle', rows: [] })
  const searchRef = useRef(null)
  const gridRef = useRef(null)
  const choosingCostume = mode === 'costume' && Boolean(fighter)
  // Read through a ref: a caller's inline loader must not refetch on every render.
  const loader = useRef(loadStock)
  loader.current = loadStock

  useEffect(() => {
    if (!choosingCostume) return undefined
    let current = true
    setStock({ character: fighter, state: 'loading', rows: [] })
    Promise.resolve().then(() => loader.current(fighter))
      .then((rows) => { if (current) setStock({ character: fighter, state: 'ready', rows }) })
      .catch(() => { if (current) setStock({ character: fighter, state: 'missing', rows: [] }) })
    return () => { current = false }
  }, [choosingCostume, fighter])

  useEffect(() => {
    if (autoFocus) searchRef.current?.focus()
  }, [autoFocus, fighter])

  const vault = useMemo(() => (choosingCostume ? vaultCostumes(metadata, fighter) : []), [choosingCostume, metadata, fighter])
  const stockPicks = stock.character === fighter ? stockCostumes(stock.rows, fighter) : []
  const options = choosingCostume
    ? costumeOptions(vault, stockPicks, media)
    : fighterOptions(fighters, { metadata, counts: mode === 'costume', url: media, auto: mode === 'fighter' })
  const shown = filterOptions(options, query)
  const picked = choosingCostume
    ? (value?.character === fighter ? pickValue(value) : '')
    : (value?.auto ? AI_VALUE : (value?.character || ''))

  const back = () => { setFighter(null); setQuery(''); searchRef.current?.focus() }
  const escape = () => { if (choosingCostume) back(); else onCancel?.() }
  const pick = (picked) => {
    playSound('boop')
    if (!choosingCostume) {
      if (mode === 'fighter' && picked === AI_VALUE) onChange?.(aiPick())
      else if (mode === 'fighter') onChange?.({ kind: 'fighter', character: picked, image: cssIconPath(picked) })
      // The picked cell unmounts with the step: keep keyboard focus in the picker.
      else { setFighter(picked); setQuery(''); requestAnimationFrame(() => searchRef.current?.focus()) }
      return
    }
    const chosen = [...vault, ...stockPicks].find((item) => pickValue(item) === picked)
    if (chosen) onChange?.(chosen)
  }
  const searchKeys = (event) => searchBoxKeys(event, gridRef.current, escape)

  const what = choosingCostume ? `${fighter} costumes` : 'fighters'
  return (
    <div className={`costume-picker costume-picker--${choosingCostume ? 'costumes' : 'fighters'}`}>
      <div className="costume-picker-head">
        {choosingCostume
          ? <>
              <button type="button" className="costume-picker-back" onClick={back} aria-label="Back to fighters">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                Fighters
              </button>
              <strong>{fighter}</strong>
            </>
          : <strong>{mode === 'fighter' ? 'Which fighter does it go on?' : 'Pick a fighter'}</strong>}
      </div>
      <input
        ref={searchRef}
        type="search"
        className="gallery-search"
        aria-label={`Search ${what}`}
        placeholder={choosingCostume ? `Search ${fighter} costumes…` : 'Search fighters…'}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={searchKeys}
      />
      {choosingCostume && stock.state !== 'loading' && vault.length === 0 && stockPicks.length > 0 && !query && (
        <p className="costume-picker-note">No {fighter} costumes in your vault yet. Start from a stock one.</p>
      )}
      {shown.length > 0 && (
        <GalleryGrid
          navigable
          gridRef={gridRef}
          className={choosingCostume ? 'gallery-grid--portrait' : 'gallery-grid--icon'}
          label={choosingCostume ? `${fighter} costumes` : 'Fighters'}
          options={shown}
          value={picked}
          onPick={pick}
          onEscape={escape}
        />
      )}
      {query && shown.length === 0 && options.length > 0 && <div className="gallery-empty">Nothing matches “{query}”</div>}
      {choosingCostume && stock.state === 'loading' && <p className="costume-picker-note" role="status">Loading the stock costumes…</p>}
      {choosingCostume && stock.state === 'missing' && (
        <p className="costume-picker-note">
          {vault.length ? 'Stock costumes are not available' : `No ${fighter} costumes in your vault, and the stock ones are not available`}
          : refresh the vanilla assets in Settings. You can still describe the costume in words.
        </p>
      )}
    </div>
  )
}
