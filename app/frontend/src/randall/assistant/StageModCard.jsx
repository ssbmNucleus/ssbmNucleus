import { useContext, useState } from 'react'
import { EditorContext } from '../../shared/lib/EditorContext'
import { backendMediaUrl } from '../../shared/config/config'

export default function StageModCard({ item }) {
  const editor = useContext(EditorContext)
  const [failedImages, setFailedImages] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const image = [item.image, item.fallback_image].find(url => url && !failedImages.includes(url))
  const open = async edit => {
    setBusy(true); setError('')
    try { await editor.openStageVault(item, edit) }
    catch (err) { setError(err.message || 'This stage could not be opened.') }
    finally { setBusy(false) }
  }
  return <article className="assistant-vault-card assistant-stage-card">
    <button type="button" className="assistant-vault-open" disabled={busy || item.unavailable || !editor?.openStageVault}
      onClick={() => open(false)} aria-label={`Open ${item.name} in vault`}>
      {image ? <img src={backendMediaUrl(image)} alt="" onError={() => setFailedImages(values => [...values, image])} />
        : <span className="assistant-vault-no-image">No preview</span>}
      <span><strong>{item.name}</strong><small>{item.stage || item.stageCode}</small></span>
    </button>
    <button type="button" className="assistant-vault-edit" disabled={busy || item.unavailable || !editor?.openStageVault}
      aria-label={`Edit ${item.name} in Stage Creator`} onClick={() => open(true)}>Edit</button>
    {error && <p className="assistant-error" role="alert">{error}</p>}
  </article>
}
