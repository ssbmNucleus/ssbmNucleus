import { useMemo, useState } from 'react'
import { ANIM_CATEGORIES, getAnimCategory, getAnimDisplayName } from '../characters/poses/animData'
import { playSound, playHoverSound } from '../../shared/audio/sounds'

// Collapsible animation player floating over the Skin Creator's 3D preview.
// Collapsed it is a small pill (showing the current animation); expanded it
// lists the character's AJ animations by category with play/pause + scrubber.
// `data-viewer-ignore` keeps drags/wheel inside it from orbiting the camera.
export default function ViewerAnimPopover({ animations, selectedAnim, state, onLoad, onToggle, onSetFrame }) {
  const [open, setOpen] = useState(false)
  const [category, setCategory] = useState('All')
  const [query, setQuery] = useState('')

  const categories = useMemo(() => {
    const present = new Set(animations.map(getAnimCategory))
    return ['All', ...Object.keys(ANIM_CATEGORIES).filter(c => present.has(c)), ...(present.has('Other') ? ['Other'] : [])]
  }, [animations])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return animations.filter(symbol =>
      (category === 'All' || getAnimCategory(symbol) === category) &&
      (!q || symbol.toLowerCase().includes(q) || getAnimDisplayName(symbol).toLowerCase().includes(q)))
  }, [animations, category, query])

  const frameCount = Math.max(0, state.frameCount || 0)
  const hasAnim = Boolean(selectedAnim) && frameCount > 0
  const lastFrame = Math.max(0, frameCount - 1)
  const frame = Math.min(Math.max(0, Math.round(state.frame || 0)), lastFrame)

  return (
    <div className={`viewer-anim${open ? ' is-open' : ''}`} data-viewer-ignore>
      <button
        type="button"
        className="viewer-anim-toggle"
        aria-expanded={open}
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('boop'); setOpen(o => !o) }}
        title="Play the character's animations on the model"
      >
        <span className="viewer-anim-toggle-icon">{open ? '▾' : '▸'}</span>
        {hasAnim && !open ? getAnimDisplayName(selectedAnim) : 'Animations'}
      </button>
      {open && (
        <div className="viewer-anim-panel">
          <div className="viewer-anim-filters">
            <select aria-label="Animation category" value={category} onChange={e => setCategory(e.target.value)}>
              {categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <input
              type="search"
              aria-label="Search animations"
              placeholder="Search…"
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
          </div>
          <div className="viewer-anim-list" role="listbox" aria-label="Animations">
            {visible.map(symbol => (
              <button
                type="button"
                key={symbol}
                role="option"
                aria-selected={symbol === selectedAnim}
                className={`viewer-anim-item${symbol === selectedAnim ? ' is-selected' : ''}`}
                onClick={() => { playSound('boop'); onLoad(symbol) }}
                title={symbol}
              >
                {getAnimDisplayName(symbol)}
              </button>
            ))}
            {!visible.length && <div className="viewer-anim-empty">No animations match</div>}
          </div>
          <div className="viewer-anim-transport">
            <button
              type="button"
              className="viewer-anim-play"
              onClick={() => { playSound('boop'); onToggle() }}
              disabled={!hasAnim}
              aria-label={state.playing ? 'Pause' : 'Play'}
              title={state.playing ? 'Pause' : 'Play'}
            >
              {state.playing ? '❚❚' : '▶'}
            </button>
            <input
              type="range"
              aria-label="Animation frame"
              min="0"
              max={lastFrame}
              value={frame}
              onChange={e => onSetFrame(Number(e.target.value))}
              disabled={!hasAnim}
            />
            <span className="viewer-anim-frame">{hasAnim ? `${frame} / ${lastFrame}` : '–'}</span>
          </div>
        </div>
      )}
    </div>
  )
}
