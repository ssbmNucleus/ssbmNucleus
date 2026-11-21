import { useState, useId } from 'react'
import { effectReference } from './effectReferences'
import LiveEffectPictogram from './LiveEffectPictogram'
import './VisualEffectEditor.css'

// Selection only changes the inspector. Each editor owns its complete recipe
// state, including values in parts that are not currently visible.
export default function VisualEffectEditor({ effectId, character, parts, initialPart, renderControls, wholeEffect, previewColors }) {
  const [selection, setSelection] = useState(initialPart || parts[0]?.id)
  const headingId = useId()
  const clipId = `${headingId}-image`
  const selected = parts.find(part => part.id === selection) || parts[0]
  if (!selected) return null
  const reference = effectReference(effectId, selected, character)
  const [x, y, width, height] = (reference?.viewBox || '0 0 112 112').split(' ').map(Number)
  return (
    <section className="visual-effect-editor" aria-label="Edit effect parts">
      <div className="visual-effect-layout">
        <div className="visual-effect-picture">
          <div className="visual-effect-instruction">Click a shape to edit its colors</div>
          <LiveEffectPictogram effectId={effectId} character={character} parts={parts}
            selectedId={selected.id} onSelect={setSelection} colors={previewColors} />
          <p className="visual-effect-caption">{selected.label} selected · colors update live</p>
        </div>
        <div className="visual-effect-inspector" aria-label="Part colors">
          <div className="visual-effect-selected-heading">
            {parts.length > 1 && <label htmlFor={headingId}>Editing</label>}
            {parts.length > 1 ? <select id={headingId} aria-label="Choose effect part" value={selected.id}
              onChange={event => setSelection(event.target.value)}>
              {parts.map(part => <option key={part.id} value={part.id}>{part.label}</option>)}
            </select> : <h3 id={headingId}>{selected.label}</h3>}
          </div>
          <div className="visual-effect-group-controls" aria-label={selected.label}>
            {selected.description && <p>{selected.description}</p>}
            {renderControls(selected)}
          </div>
          {reference && <figure className="visual-effect-reference">
            <figcaption>In game{reference.outline || reference.point ? ' - selected part highlighted' : ' - effect reference'}</figcaption>
            <svg viewBox={reference.viewBox || '0 0 112 112'} aria-label={`${selected.label}: in-game reference`}>
              <defs><clipPath id={clipId}><rect x={x} y={y} width={width} height={height} /></clipPath></defs>
              <g clipPath={`url(#${clipId})`}>
                <image href={reference.src} width={reference.viewBox ? 1280 : 112} height={reference.viewBox ? 960 : 112} />
                {reference.outline ? <path d={reference.outline} className="effect-reference-highlight" data-highlight={selected.id} />
                  : reference.point && <circle cx={reference.point[0]} cy={reference.point[1]} r="40" className="effect-reference-highlight" data-highlight={selected.id} />}
              </g>
            </svg><p>{reference.caption}</p>
          </figure>}
        </div>
      </div>
      {wholeEffect && <details className="visual-effect-whole"><summary>Recolor whole effect</summary>{wholeEffect}</details>}
    </section>
  )
}
