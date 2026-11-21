import { useState } from 'react'
import { backendMediaUrl } from '../../shared/config/config'

function PortraitIcon() {
  return <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4" y="3" width="16" height="18" rx="4" />
    <circle cx="12" cy="9" r="2.5" /><path d="M7.5 17c.6-4 8.4-4 9 0" />
  </svg>
}

export default function PortraitActivity({ tool }) {
  const [failedImage, setFailedImage] = useState(null)
  const result = tool.result || {}
  const running = tool.status === 'running'
  const error = result.error || (result.image && failedImage === result.image ? 'Could not load the CSP preview.' : null)
  if (error || tool.status === 'error') return <div className="assistant-csp-error" role="alert">
    <PortraitIcon /><div><strong>Couldn’t make the character-select portrait</strong>
      <p>{error || 'The picture did not render.'}</p>
      <p className="assistant-settled-next">Your skin is unchanged. Ask Randall to try the portrait again.</p></div>
  </div>
  if (result.image) return <figure className="assistant-csp-preview">
    <img src={backendMediaUrl(result.image)} alt="New costume CSP preview" onError={() => setFailedImage(result.image)} />
    <figcaption><PortraitIcon />Character-select portrait</figcaption>
  </figure>
  const label = running ? 'Making the character-select portrait'
    : { cancelled: 'Portrait stopped', interrupted: 'Portrait interrupted' }[tool.status]
      || 'No portrait was made'
  return <div className={`assistant-csp-activity${running ? ' is-running' : ''}`} role="status">
    <PortraitIcon /><span>{label}</span>
    {running && <span className="assistant-work-pulse" aria-hidden="true"><i /></span>}
  </div>
}
