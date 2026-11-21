import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export default function SlippiApprovalDialog({ approval, mod, onDecision }) {
  const dialog = useRef(null)
  const [sending, setSending] = useState(null)
  const [failedImage, setFailedImage] = useState(null)
  const [error, setError] = useState('')
  const [offset, setOffset] = useState(0)
  const costumes = approval.unsafe_costumes || []
  const image = approval.mod_image || mod?.image || mod?.images?.[0]
  const unverified = costumes.some(costume => costume.unverified)
  useEffect(() => {
    const element = dialog.current
    element.showModal()
    element.querySelector('h2')?.focus({ preventScroll: true })
    return () => element.close()
  }, [])
  const decide = async (decision, choice) => {
    if (sending) return
    setSending(choice || 'deny'); setError('')
    try { await onDecision(approval.id, decision, decision === 'approve' ? choice : undefined) }
    catch (err) { setError(err.message) }
    finally { setSending(null) }
  }
  return createPortal(<dialog ref={dialog} className="assistant-download-dialog assistant-slippi-dialog" aria-labelledby="slippi-review-title"
    onCancel={event => { event.preventDefault(); decide('deny') }}>
    <header><h2 id="slippi-review-title" tabIndex={-1}>Fix for Slippi?</h2>
      <button className="download-review-close" aria-label="Cancel import" disabled={!!sending} onClick={() => decide('deny')}>×</button></header>
    {image && failedImage !== image
      ? <img className="slippi-review-image" src={image} alt={`${approval.mod_title} preview`} onError={() => setFailedImage(image)} />
      : <div className="slippi-review-image slippi-review-missing">No preview available</div>}
    <div className="slippi-review-caption"><strong>{approval.mod_title}</strong>
      <p>{unverified ? 'Slippi safety could not be verified.' : `${costumes.length} costume${costumes.length === 1 ? ' isn’t' : 's aren’t'} Slippi safe.`}</p></div>
    {costumes.length > 1 && <ul className="slippi-review-costumes">{costumes.slice(offset, offset + 20).map((costume, index) => <li key={offset + index}>
      <span>{costume.name.split(/[\\/]/).pop()}</span><small>{costume.character}</small>
    </li>)}</ul>}
    {costumes.length > 20 && <nav className="download-review-pages" aria-label="Unsafe costume pages">
      <button disabled={!offset} onClick={() => setOffset(offset - 20)}>Previous</button>
      <span>{offset + 1}–{Math.min(offset + 20, costumes.length)} of {costumes.length}</span>
      <button disabled={offset + 20 >= costumes.length} onClick={() => setOffset(offset + 20)}>Next</button>
    </nav>}
    {error && <p className="assistant-error" role="alert">{error}</p>}
    <footer>
      {approval.choices.some(option => option.id === 'import_as_is') && <button disabled={!!sending} onClick={() => decide('approve', 'import_as_is')}>
        {sending === 'import_as_is' ? 'Adding…' : 'Add without fixing'}</button>}
      {approval.choices.some(option => option.id === 'fix') && <button className="download-review-confirm" disabled={!!sending} onClick={() => decide('approve', 'fix')}>
        {sending === 'fix' ? 'Confirming…' : 'Fix and add to vault'}</button>}
    </footer>
  </dialog>, document.body)
}
