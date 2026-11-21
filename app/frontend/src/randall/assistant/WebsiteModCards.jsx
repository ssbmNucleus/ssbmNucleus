import { useEffect, useRef, useState } from 'react'
import { api } from '../../shared/transport/api'
import { getAccessToken } from '../../shared/account/account'
import { useAutoAnimate } from '@formkit/auto-animate/react'
import { DownloadActivity } from './DownloadProgress'

function ModGallery({ mod }) {
  const images = [...new Set(mod.images?.length ? mod.images : [mod.image])]
    .filter(src => typeof src === 'string' && src.startsWith('https://media.ssbmnucleus.net/'))
  const [index, setIndex] = useState(0)
  const [failed, setFailed] = useState([])
  const [transition, setTransition] = useState(null)
  const touch = useRef(null)
  const available = images.filter(src => !failed.includes(src))
  const current = index % (available.length || 1)
  const move = direction => {
    if (available.length < 2) return
    setTransition({ image: available[current], direction })
    setIndex((current + available.length + direction) % available.length)
  }
  useEffect(() => {
    for (const offset of [-1, 1]) {
      const src = available[(current + available.length + offset) % available.length]
      if (src) { const preload = new Image(); preload.src = src }
    }
  }, [current, available.join('|')])
  return <div className={`assistant-mod-image ${transition ? `is-sliding-${transition.direction > 0 ? 'next' : 'previous'}` : ''}`}
    aria-label={`${mod.title} screenshots`} role="group" tabIndex={available.length > 1 ? 0 : undefined}
    onKeyDown={event => { if (['ArrowLeft', 'ArrowRight'].includes(event.key)) { event.preventDefault(); move(event.key === 'ArrowRight' ? 1 : -1) } }}
    onPointerDown={event => { if (event.pointerType === 'touch') touch.current = event.clientX }}
    onPointerUp={event => { if (touch.current !== null && Math.abs(event.clientX - touch.current) > 35) move(event.clientX < touch.current ? 1 : -1); touch.current = null }}
    onPointerCancel={() => { touch.current = null }}>
    {transition && <img key={transition.image} className="assistant-gallery-outgoing" src={transition.image} alt="" aria-hidden="true"
      onAnimationEnd={() => setTransition(null)} />}
    {available.length ? <img key={available[current]} className="assistant-gallery-current" src={available[current]}
      alt={`${mod.title}, screenshot ${current + 1}`} loading="lazy"
      onError={() => { setFailed(previous => [...previous, available[current]]); setTransition(null) }} />
      : <div className="assistant-mod-placeholder">No preview available</div>}
    {available.length > 1 && <div className="assistant-mod-gallery-controls">
      <button aria-label={`Previous screenshot of ${mod.title}`} onClick={() => move(-1)}>‹</button>
      <span aria-live="polite">{current + 1} / {available.length}</span>
      <button aria-label={`Next screenshot of ${mod.title}`} onClick={() => move(1)}>›</button>
    </div>}
  </div>
}

function ModLikes({ mod, account }) {
  const [state, setState] = useState({ like_count: mod.like_count, liked: false })
  const [loading, setLoading] = useState(Boolean(account))
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const request = async (route, body = {}) => {
    const account_token = await getAccessToken(account?.id)
    if (!account_token) throw new Error('Sign in to your Nucleus account to like mods.')
    return api.post(`/api/assistant/website/${route}`, { post_id: mod.post_id, account_token, ...body })
  }
  useEffect(() => {
    let active = true
    setState({ like_count: mod.like_count, liked: false }); setError('')
    if (!account) { setLoading(false); return }
    setLoading(true)
    request('like-status').then(data => { if (active) setState(data) })
      .catch(err => { if (active) setError(err.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [mod.post_id, mod.like_count, account?.id])
  const toggle = async () => {
    if (!account || sending || loading) return
    setSending(true); setError('')
    try { setState(await request('like', { liked: !state.liked })) }
    catch (err) { setError(err.message) }
    finally { setSending(false) }
  }
  return <>
    <button className={`assistant-mod-like ${state.liked ? 'is-liked' : ''}`} aria-pressed={state.liked}
      aria-label={account ? `${state.liked ? 'Unlike' : 'Like'} ${mod.title}` : `Sign in to Nucleus to like ${mod.title}`}
      title={account ? (state.liked ? 'Unlike' : 'Like') : 'Sign in to your Nucleus account to like mods'}
      disabled={!account || loading || sending} onClick={toggle}>
      <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" fill={state.liked ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.7" /></svg>
      {Number.isFinite(state.like_count) ? state.like_count.toLocaleString() : '—'}
    </button>
    {error && <span className="assistant-mod-like-error" role="alert">{error}</span>}
  </>
}

// --- a broadened search is not a match ---------------------------------------
// When the exact words found nothing the backend runs weaker searches and says
// which one produced these mods (`relaxed`, and `alternative_match` on every
// card it returned). Without this, a fallback result is indistinguishable from
// an exact hit, which is the difference between "here is your Halo stage" and
// "here is a stage select screen by somebody else".

const sentenceList = items => items.length > 1
  ? `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}` : String(items[0] || '')

/** The words and filters of one search, as the user would say them. */
export function searchPhrase(filters) {
  if (!filters) return 'what you asked for'
  const parts = []
  const tags = (filters.tags || []).filter(Boolean)
  if (filters.query?.trim()) parts.push(`'${filters.query.trim()}'`)
  if (tags.length === 1) parts.push(`the tag ${tags[0]}`)
  else if (tags.length > 1) parts.push(`the tags ${sentenceList(tags)}`)
  if (filters.character?.trim()) parts.push(`the character ${filters.character.trim()}`)
  if (filters.author?.trim()) parts.push(`the author ${filters.author.trim()}`)
  return parts.length ? sentenceList(parts) : 'what you asked for'
}

/** One line of qualification above the cards, or null for an exact search. */
export function relaxedLine(result) {
  const relaxed = result?.relaxed
  if (!relaxed || !relaxed.matched) return null
  const asked = searchPhrase(result.original_filters || relaxed.requested)
  const shown = searchPhrase(result.filters)
  const dropped = (relaxed.dropped_filters || []).filter(Boolean)
  const droppedLine = dropped.length
    ? ` The ${dropped.join(' and ')} filter${dropped.length === 1 ? ' was' : 's were'} dropped to find these.` : ''
  return `Showing ${shown} instead of ${asked}; nothing matched the exact words.${droppedLine}`
}

function DownloadControls({ mod, onDownload, busy }) {
  const [scope, setScope] = useState(mod.default_file_id ? 'default' : 'all')
  return <>
    {mod.default_file_id && <fieldset className="assistant-download-choices" disabled={busy}>
      <legend>Variants to add</legend>
      <label><input type="radio" name={`mod-scope-${mod.post_id}`} checked={scope === 'default'} onChange={() => setScope('default')} />Default variant only</label>
      <label><input type="radio" name={`mod-scope-${mod.post_id}`} checked={scope === 'all'} onChange={() => setScope('all')} />All {mod.variant_count} variants</label>
    </fieldset>}
    <button className="assistant-mod-download" disabled={busy}
      onClick={() => onDownload(mod, scope === 'default' ? mod.default_file_id : undefined)}>Download</button>
  </>
}

export default function WebsiteModCards({ mods = [], cards = mods.map(mod => ({ mod })), onDecision, onDownload, onDownloadMany, busy, account, directDownload, search }) {
  const [animateRef] = useAutoAnimate({ duration: 260, easing: 'cubic-bezier(.22,.61,.36,1)' })
  const available = cards.filter(card => !card.inVault && (card.mod.can_download || card.mod.default_file_id)).map(card => card.mod)
  const qualification = relaxedLine(search)
  return <>{qualification && <p className="assistant-search-relaxed" role="status">{qualification}</p>}
    {available.length > 1 && onDownloadMany && <button className="assistant-secondary assistant-bulk-download" disabled={busy} onClick={() => onDownloadMany(available)}>Download all ({available.length})</button>}
    <div ref={animateRef} className="assistant-website-mods">{cards.map(({ mod, download, inVault }) => {
    const approval = download?.approval
    const pending = approval?.status === 'pending'
    const downloading = approval?.status === 'approved' && ['running', 'awaiting_approval'].includes(download?.status)
    return <article className="assistant-website-mod" key={mod.post_id} data-post-id={mod.post_id}>
      <ModGallery key={`${mod.post_id}:${(mod.images || [mod.image]).join('|')}`} mod={mod} />
      <div className="assistant-mod-body">
        <h3>{mod.title}</h3>
        <p className="assistant-mod-author">by {mod.credit || mod.author}</p>
        {mod.alternative_match && <p className="assistant-mod-alternative">
          <span>Alternative match</span> Found by searching {mod.alternative_match}, not the words you used.</p>}
        <div className="assistant-mod-counts">
          <ModLikes key={`${mod.post_id}:${account?.id || 'signed-out'}`} mod={mod} account={account} />
          <span>{Number.isFinite(mod.download_count) ? mod.download_count.toLocaleString() : '—'} downloads</span>
        </div>
        {Number.isInteger(mod.post_id) && mod.post_id > 0 && <a className="assistant-mod-link"
          href={`https://ssbmnucleus.net/post/${mod.post_id}`} target="_blank" rel="noopener noreferrer">View on website ↗</a>}
        {pending ? <p className="assistant-mod-download-state" role="status">Waiting for confirmation</p>
          : download?.status === 'queued' ? <p className="assistant-mod-download-state" role="status">Queued</p>
          : downloading ? <DownloadActivity />
          : directDownload === mod.post_id ? <DownloadActivity preparing />
          : inVault ? <p className="assistant-mod-download-state" role="status">✓ In vault</p>
          : onDownload && <DownloadControls key={`${mod.post_id}:${mod.default_file_id || 'all'}`} mod={mod} onDownload={onDownload} busy={busy} />}
      </div>
    </article>
  })}</div></>
}
