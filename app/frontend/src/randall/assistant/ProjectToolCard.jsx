import { useState } from 'react'
import { api } from '../../shared/transport/api'
import { backendMediaUrl } from '../../shared/config/config'
import { phraseFor } from './activity'
import { FailureNotice, SafetyLabel } from './TaskCards'

export default function ProjectToolCard({ tool, onDecision, onOpenProject }) {
  const [sending, setSending] = useState(false), [error, setError] = useState('')
  const result = tool.result || {}, review = tool.approval
  const pending = review?.status === 'pending'
  const decide = async decision => {
    if (sending) return
    setSending(true); setError('')
    try { await onDecision(review.id, decision) }
    catch (err) { setError(err.message) }
    finally { setSending(false) }
  }
  const open = async project => {
    setSending(true); setError('')
    try {
      await api.post('/project/open', { projectPath: project.path })
      window.dispatchEvent(new Event('nucleus:project-changed'))
      onOpenProject?.()
    } catch (err) { setError(err.message) }
    finally { setSending(false) }
  }
  const projects = result.projects || (result.project ? [result.project] : [])
  const items = pending ? review.items : result.installed_items
  const running = tool.status === 'running'
  if (running) return <div className="assistant-csp-activity" role="status">
    <span>{phraseFor(tool.name).working}</span>
    <span className="assistant-work-pulse" aria-hidden="true"><i /></span>
  </div>
  return <section className={`assistant-project ${pending ? 'assistant-approval is-pending' : ''}`} aria-label={pending ? 'Project approval' : 'Project result'}>
    {pending && <><h3>{review.title}</h3><p>{review.project_action === 'create' ? review.base_name : 'Add as new costume slots'}</p></>}
    {projects.map(project => <div className="assistant-project-heading" key={project.id}>
      <div><strong>{project.name}</strong><small>{result.project_action === 'created' ? 'Build started'
        : result.project_action === 'installed' ? `${result.installed_count} costume${result.installed_count === 1 ? '' : 's'} added to this build`
        : project.current ? 'The build you are working on' : 'A build'}</small></div>
      <button type="button" className="assistant-secondary" disabled={sending} onClick={() => open(project)}>Open project</button>
    </div>)}
    {/* "Installed" means the game you play changed AND was checked. Adding
        costumes to a build is neither, so the card says what it did and what
        still has to happen. */}
    {result.project_action === 'installed' && <p className="assistant-task-scope">
      These are the ingredients for that build. Your playable game does not change until the build is made.</p>}
    {items?.length > 0 && <div className="assistant-project-items">{items.map(item => <div key={`${item.character}:${item.id}`}>
      {item.image && <img src={backendMediaUrl(item.image)} alt="" />}
      <span><strong>{item.name}</strong><small>{item.character}{item.variant ? ` · ${item.variant}` : ''}</small>
        <SafetyLabel item={item} compact /></span>
    </div>)}</div>}
    {result.failed?.length > 0 && <details open><summary>{result.failed.length} could not be added</summary>
      <ul>{result.failed.map((row, index) => <li key={index}>{row.name || row.id}: {row.error}</li>)}</ul></details>}
    {result.fighters?.length > 0 && <p className="assistant-muted">{result.fighters.length} fighters · {result.fighters.reduce((sum, f) => sum + f.costume_count, 0)} costumes</p>}
    {result.projects?.length === 0 && <p>You have no builds yet. A build is your own modded copy of Melee —
      Randall can start one from your clean game file.</p>}
    {result.unavailable?.length > 0 && <p role="alert">Could not read: {result.unavailable.join(', ')}</p>}
    {pending && <div className="assistant-approval-actions">
      <button type="button" className="assistant-approve" disabled={sending} onClick={() => decide('approve')}>{review.confirm_label}</button>
      <button type="button" className="assistant-secondary" disabled={sending} onClick={() => decide('deny')}>Cancel</button>
    </div>}
    {!pending && !projects.length && !result.error && review
      && <FailureNotice tool={{ name: tool.name, status: { denied: 'denied', cancelled: 'cancelled', expired: 'expired', interrupted: 'interrupted' }[review.status] || 'cancelled', result }} />}
    {(error || result.error) && <FailureNotice tool={{ name: tool.name, status: 'error', result: { error: error || result.error } }} />}
  </section>
}
