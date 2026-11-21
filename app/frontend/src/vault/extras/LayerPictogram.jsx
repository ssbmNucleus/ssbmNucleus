import { useRef, useState } from 'react'
import { pictogramDetails } from './pictograms'

export default function LayerPictogram({ src, label }) {
  const dialog = useRef(null)
  const [failed, setFailed] = useState(null)
  if (!src || failed === src) return null
  const reference = pictogramDetails(src)
  const title = `${reference.label} for ${label}`
  return <>
    <button type="button" className={`layer-pictogram-button layer-pictogram-${reference.kind}`}
      title={title} aria-label={`Inspect ${title}`}
      onClick={() => dialog.current?.showModal()}>
      <img className="layer-pictogram" src={src} alt="" onError={() => setFailed(src)} />
      <span className="layer-pictogram-expand" aria-hidden="true">↗</span>
      <span className="layer-pictogram-kind" aria-hidden="true">{reference.kind === 'overview' ? 'Effect' : 'Layer'}</span>
    </button>
    <dialog ref={dialog} className="layer-pictogram-dialog"
      aria-label={title} onClick={e => {
        if (e.target === e.currentTarget) e.currentTarget.close()
      }}>
      <div className="layer-pictogram-detail">
        <header><div><strong>{label}</strong><span className="layer-pictogram-reference-kind">{reference.label}</span></div><button type="button" autoFocus
          aria-label="Close reference" onClick={() => dialog.current.close()}>×</button></header>
        <img src={src} alt={title} />
        <p>{reference.caption}</p>
      </div>
    </dialog>
  </>
}
