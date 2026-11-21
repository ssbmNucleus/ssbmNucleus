import { useState } from 'react'
import WebsiteModCards from './WebsiteModCards'

const OUTCOMES = { approved: 'Approved', denied: 'Declined', expired: 'Expired',
  cancelled: 'Cancelled', interrupted: 'Interrupted' }

export default function ApprovalCard({ approval, onDecision, inline = false }) {
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [choice, setChoice] = useState(approval.choice || approval.default_choice || '')
  const pending = approval.status === 'pending'
  const website = approval.website_mods?.length > 0
  const decide = async decision => {
    if (sending || !pending) return
    setSending(true); setError('')
    try { await onDecision(approval.id, decision, decision === 'approve' && approval.choices?.length ? choice : undefined) }
    catch (err) { setError(err.message || 'Could not send your decision. Try again.') }
    finally { setSending(false) }
  }
  return <section className={`assistant-approval ${inline ? 'assistant-approval--inline' : ''} ${pending ? 'is-pending' : ''}`} aria-label="Action approval">
    {!inline && <div className="assistant-approval-status" role="status">{pending ? 'Your approval needed' : OUTCOMES[approval.status] || approval.status}</div>}
    {!inline && (website ? <WebsiteModCards mods={approval.website_mods} /> : <h3>{approval.title}</h3>)}
    {!website && <p>{approval.description}</p>}
    {website && approval.website_mods[0]?.selected_file && <p className="assistant-download-variant">
      {(() => { const file = approval.website_mods[0].selected_file; return [file.character, file.color].filter(Boolean).join(' · ') || file.name })()}
    </p>}
    {approval.changes?.length > 0 && <details open={approval.changes.length <= 5}>
      <summary>{approval.changes.length} proposed change{approval.changes.length === 1 ? '' : 's'}</summary>
      <ul className="assistant-approval-changes">{approval.changes.map((change, index) => <li key={index}>
        <strong>{change.item}</strong><span>{change.from} → {change.to}</span>
      </li>)}</ul>
    </details>}
    {!website && <p className="assistant-approval-consequence">{approval.consequence}</p>}
    {!website && <details><summary>Tool details</summary><code>{approval.tool}</code><pre>{JSON.stringify(approval.arguments, null, 2)}</pre></details>}
    {approval.choices?.length > 0 && <fieldset className="assistant-download-choices" disabled={sending || !pending}>
      <legend>Variants to add</legend>
      {approval.choices.map(option => <label key={option.id}>
        <input type="radio" name={`download-scope-${approval.id}`} value={option.id}
          checked={(approval.choice || choice) === option.id} onChange={() => setChoice(option.id)} />
        {option.label}
      </label>)}
    </fieldset>}
    {pending && <>
      <div className="assistant-approval-actions">
        <button type="button" className="assistant-approve" disabled={sending} onClick={() => decide('approve')}>{approval.confirm_label || 'Approve once'}</button>
        <button type="button" className="assistant-secondary" disabled={sending} onClick={() => decide('deny')}>Decline</button>
      </div>
      {!website && <small>Only this action. Expires at {new Date(approval.expires_at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}.</small>}
    </>}
    {error && <p className="assistant-error" role="alert">{error}</p>}
  </section>
}
