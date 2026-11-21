import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../shared/transport/api'
import { BACKEND_URL } from '../../shared/config/config'

export default function CloudActivitySection({ ready, running }) {
  const [activity, setActivity] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const requestId = useRef(0)
  const wasRunning = useRef(running)
  const load = useCallback(async ({ kind, cursor, refresh = false } = {}) => {
    const id = ++requestId.current
    setLoading(true)
    setError('')
    const params = new URLSearchParams()
    if (kind) params.set('kind', kind)
    if (cursor) params.set('cursor', cursor)
    if (refresh) params.set('refresh', '1')
    try {
      const data = await api.get(`${BACKEND_URL}/api/nucleome/vault/activity?${params}`)
      if (id !== requestId.current) return
      setActivity(previous => {
        if (!kind || !previous) return data
        const field = kind === 'uploads' ? 'upload_history' : 'shared_links'
        const key = kind === 'uploads' ? 'day' : 'url'
        const rows = new Map(previous[field].map(row => [row[key], row]))
        for (const row of data[field]) rows.set(row[key], row)
        return { ...previous, [field]: [...rows.values()], [`next_${kind}`]: data[`next_${kind}`] }
      })
    } catch {
      if (id === requestId.current) setError('Could not load activity. Try again shortly.')
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [])
  useEffect(() => {
    setActivity(null)
    setError('')
    setLoading(false)
    if (ready) load()
    return () => { requestId.current += 1 }
  }, [ready, load])
  useEffect(() => {
    const finished = wasRunning.current && !running
    wasRunning.current = running
    if (ready && finished) load({ refresh: true })
  }, [ready, running, load])
  return <section className="settings-section cloud-activity-card">
    <div className="cloud-activity-heading">
      <h3>Cloud activity</h3>
      <button className="iso-browse-button" disabled={!ready || loading} onClick={() => load({ refresh: true })}>Refresh</button>
    </div>
    {!ready ? <p className="vault-empty">Link Patreon to see your uploads and shared links.</p> : <>
      {loading && <p role="status" className="vault-empty">Loading…</p>}
      {error && <p role="alert" className="vault-error">{error}</p>}
      {activity && <>
        <h4>Uploads</h4>
        <ul className="vault-history-list">{activity.upload_history.map(entry => <li key={entry.day}>
          <time dateTime={entry.day}>{new Date(`${entry.day}T12:00:00`).toLocaleDateString()}</time>
          <span>{entry.games.toLocaleString()} replays</span>
        </li>)}</ul>
        {!activity.upload_history.length && <p className="vault-empty">No uploads.</p>}
        {activity.next_uploads && <button className="iso-browse-button" disabled={loading}
          onClick={() => load({ kind: 'uploads', cursor: activity.next_uploads })}>Load more uploads</button>}
        <h4>Shared replays</h4>
        <ul className="vault-history-list">{activity.shared_links.map(entry => <li key={entry.url}>
          <a href={entry.url} target="_blank" rel="noopener noreferrer">{entry.players.map(p => p.name || p.code || 'Player').join(' vs ') || 'Replay'}</a>
          {entry.start_at && <time dateTime={entry.start_at}>{new Date(entry.start_at).toLocaleDateString()}</time>}
        </li>)}</ul>
        {!activity.shared_links.length && <p className="vault-empty">No shared replays.</p>}
        {activity.next_shares && <button className="iso-browse-button" disabled={loading}
          onClick={() => load({ kind: 'shares', cursor: activity.next_shares })}>Load more shared replays</button>}
      </>}
    </>}
  </section>
}
