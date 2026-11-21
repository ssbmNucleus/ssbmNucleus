import { useEffect, useMemo, useRef, useState } from 'react'
import GalleryGrid, { searchBoxKeys } from '../../shared/ui/GalleryGrid'
import { api } from '../../shared/transport/api'
import { backendMediaUrl } from '../../shared/config/config'
import { playSound } from '../../shared/audio/sounds'
import { filterOptions } from './costumePicks'
import { stageOptions, stagePickValue, stageRows, stockStage, variantOptions, vaultStageVariants } from './stagePicks'
import './CostumePicker.css'

/** Every vault stage variant, as the Vault's stage list serves it. Not cached: a Stage Lab save adds one. */
export function fetchStageVariants() {
  return api.get('/das/storage/variants').then((data) => data?.variants || [])
}

/**
 * Pick a stage, then one of its vault variants or the stock stage: CostumePicker's
 * pattern (GalleryGrid, the same layout and keyboard model: arrows move, Enter
 * picks, Escape goes back a step, then `onCancel`) for the "Retexture a stage"
 * starting point, in the same popover.
 *
 * stages       the stages to offer: status.recolor_stages ({code, name, folder, legal, art})
 * value        the current pick or null; onChange(pick) receives a new one (stagePicks.js):
 *                {kind: 'stage', stage, stageName, id, name, image}           a vault variant
 *                {kind: 'stage', stage, stageName, vanilla: true, name, image} the stock stage
 * loadVariants () -> Promise of the vault's stage variant rows; the default asks the backend
 * autoFocus    focus the search box when a step opens
 */
export default function StagePicker({
  stages, value = null, onChange, onCancel, loadVariants = fetchStageVariants, autoFocus = false, media = backendMediaUrl,
}) {
  const [stage, setStage] = useState(value?.kind === 'stage' && value.stage ? value.stage : null)
  const [query, setQuery] = useState('')
  const [variants, setVariants] = useState({ state: 'loading', rows: [] })
  const searchRef = useRef(null)
  const gridRef = useRef(null)
  // Read through a ref: a caller's inline loader must not refetch on every render.
  const loader = useRef(loadVariants)
  loader.current = loadVariants

  useEffect(() => {
    let current = true
    Promise.resolve().then(() => loader.current())
      .then((rows) => { if (current) setVariants({ state: 'ready', rows: Array.isArray(rows) ? rows : [] }) })
      .catch(() => { if (current) setVariants({ state: 'missing', rows: [] }) })
    return () => { current = false }
  }, [])

  useEffect(() => {
    if (autoFocus) searchRef.current?.focus()
  }, [autoFocus, stage])

  const rows = useMemo(() => stageRows(stages), [stages])
  const chosen = rows.find((row) => row.code === stage) || null
  const vault = useMemo(() => (chosen ? vaultStageVariants(variants.rows, chosen) : []), [chosen, variants.rows])
  const stock = chosen ? stockStage(chosen) : null
  const options = chosen ? variantOptions(vault, stock, media) : stageOptions(rows, variants.rows, media)
  const shown = filterOptions(options, query)
  const picked = chosen
    ? (value?.stage === chosen.code ? stagePickValue(value) : '')
    : (value?.kind === 'stage' ? value.stage : '')

  const back = () => { setStage(null); setQuery(''); searchRef.current?.focus() }
  const escape = () => { if (chosen) back(); else onCancel?.() }
  const pick = (next) => {
    playSound('boop')
    if (!chosen) {
      // The picked cell unmounts with the step: keep keyboard focus in the picker.
      setStage(next); setQuery(''); requestAnimationFrame(() => searchRef.current?.focus())
      return
    }
    const found = [...vault, stock].find((item) => item && stagePickValue(item) === next)
    if (found) onChange?.(found)
  }

  const what = chosen ? `${chosen.name} variants` : 'stages'
  return (
    <div className={`costume-picker costume-picker--${chosen ? 'variants' : 'stages'}`}>
      <div className="costume-picker-head">
        {chosen
          ? <>
              <button type="button" className="costume-picker-back" onClick={back} aria-label="Back to stages">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                Stages
              </button>
              <strong>{chosen.name}</strong>
            </>
          : <strong>Pick a stage</strong>}
      </div>
      <input
        ref={searchRef}
        type="search"
        className="gallery-search"
        aria-label={`Search ${what}`}
        placeholder={chosen ? `Search ${chosen.name} variants…` : 'Search stages…'}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => searchBoxKeys(event, gridRef.current, escape)}
      />
      {chosen && variants.state === 'ready' && vault.length === 0 && !query && (
        <p className="costume-picker-note">No {chosen.name} variants in your vault yet. Start from the stock stage.</p>
      )}
      {shown.length > 0 && (
        <GalleryGrid
          navigable
          gridRef={gridRef}
          className={chosen ? 'gallery-grid--landscape' : 'gallery-grid--landscape gallery-grid--fit'}
          label={chosen ? `${chosen.name} variants` : 'Stages'}
          options={shown}
          value={picked}
          onPick={pick}
          onEscape={escape}
        />
      )}
      {query && shown.length === 0 && options.length > 0 && <div className="gallery-empty">Nothing matches “{query}”</div>}
      {!rows.length && (
        <p className="costume-picker-note">No stages to pick from in this build. You can still name the stage in words.</p>
      )}
      {chosen && variants.state === 'loading' && <p className="costume-picker-note" role="status">Loading your stage variants…</p>}
      {chosen && variants.state === 'missing' && (
        <p className="costume-picker-note">Your vault's stage variants could not be loaded. You can start from the stock stage.</p>
      )}
    </div>
  )
}
