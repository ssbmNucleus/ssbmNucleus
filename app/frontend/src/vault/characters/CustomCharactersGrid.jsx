import { useEffect, useRef, useState } from 'react'
import { backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { useJob, useJobList } from '../../shared/jobs/useJobs'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import NewClimbersModal from './NewClimbersModal'

const SkeletonCard = () => (
  <div className="character-card skeleton-card">
    <div className="character-icon-container">
      <div className="skeleton skeleton-image"></div>
    </div>
    <div className="skeleton skeleton-text" style={{ width: '60%', height: '12px' }}></div>
  </div>
)

/* A built-in fighter that first-run setup staged but never rendered (setup only
   parks the inputs — the CSPs, recolors and stock icons cost minutes). The card
   sits greyed out until it is clicked, then builds itself in the background. */
function PendingBuiltinCard({ builtin, onRefresh }) {
  const [jobId, setJobId] = useState(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState(null)
  const allJobs = useJobList()
  const ownJob = useJob(jobId)
  const job = ownJob || allJobs.find(j => j.kind === 'builtin_character' && j.params?.slug === builtin.slug)
  const handled = useRef(null)
  const running = starting || ['queued', 'running'].includes(job?.status)

  useEffect(() => {
    if (job?.status !== 'done' || handled.current === job.id) return
    handled.current = job.id
    playSound('boop')
    Promise.resolve().then(() => onRefresh?.()).catch(() => setError('Set up, but the list did not reload'))
  }, [job, onRefresh])

  const startSetup = async () => {
    if (running) return
    playSound('boop')
    setStarting(true)
    setError(null)
    try {
      const data = await api.post(`/custom-characters/builtins/${builtin.slug}/setup`)
      setJobId(data.job_id)
    } catch (err) {
      setError(err.status === 409 ? 'Another setup is running — click again after it' : 'Setup failed — click to retry')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div
      className={`character-card pending-builtin${running ? ' setting-up' : ''}`}
      onMouseEnter={playHoverSound}
      onClick={startSetup}
      title={running ? job?.detail || 'Setting up…' : `Set up ${builtin.name}`}
    >
      <div className="character-icon-container">
        {builtin.has_css_icon ? (
          <img
            src={backendMediaUrl(builtin.icon_url)}
            alt={builtin.name}
            className="character-css-icon"
            draggable={false}
            onError={(e) => {
              e.target.style.display = 'none'
              e.target.nextSibling.style.display = 'flex'
            }}
          />
        ) : null}
        <div className="character-placeholder" style={{ display: builtin.has_css_icon ? 'none' : 'flex' }}>
          <span className="character-initial">{builtin.name[0]}</span>
        </div>
        <div className="pending-builtin-overlay">
          {running ? (
            <>
              <span className="pending-builtin-pct">{Math.round((job?.progress || 0) * 100)}%</span>
              <span className="pending-builtin-hint">Setting up…</span>
            </>
          ) : error || ['failed', 'interrupted', 'cancelled'].includes(job?.status) ? (
            <span className="pending-builtin-hint error">
              {error || 'Setup failed — click to retry'}
            </span>
          ) : (
            <span className="pending-builtin-hint">Click to set up</span>
          )}
        </div>
      </div>
      <p className="skin-count">
        {running ? (job?.detail || 'Working…')
          : <><span>{builtin.costume_count}</span> costume{builtin.costume_count !== 1 ? 's' : ''}</>}
      </p>
    </div>
  )
}

/* Entry point for building an "Any Climbers" pair. It sits in this grid rather
   than somewhere of its own because the thing it produces IS a custom
   character — once created it's an ordinary card beside the others. */
function NewClimbersCard({ onClick }) {
  return (
    <div
      className="character-card new-climbers-card"
      onMouseEnter={playHoverSound}
      onClick={onClick}
    >
      <div className="character-icon-container">
        <span className="new-climbers-plus">+</span>
      </div>
      <p className="skin-count">New Climbers</p>
    </div>
  )
}

export default function CustomCharactersGrid({
  customCharacters,
  pendingBuiltins = [],
  isLoading,
  onSelectCharacter,
  onBack,
  onRefresh
}) {
  // Drag-to-reorder state. previewOrder holds the live reordered list while a
  // drag is in flight; once dropped we persist to the backend and refresh.
  const [previewOrder, setPreviewOrder] = useState(null)
  const [reordering, setReordering] = useState(false)
  const [showClimbers, setShowClimbers] = useState(false)
  const draggedSlugRef = useRef(null)
  const justDraggedRef = useRef(false) // suppress the click that follows a drag

  const items = previewOrder || customCharacters

  const handleDragStart = (e, slug) => {
    draggedSlugRef.current = slug
    setPreviewOrder([...customCharacters])
    e.dataTransfer.effectAllowed = 'move'
    // Marking the payload as text/plain is what keeps the global import
    // overlay hidden: ImportFab only reacts to drags carrying 'Files'.
    e.dataTransfer.setData('text/plain', slug)
  }

  const handleDragEnter = (overIndex) => {
    const draggedSlug = draggedSlugRef.current
    if (!draggedSlug) return
    setPreviewOrder((prev) => {
      const list = prev ? [...prev] : [...customCharacters]
      const from = list.findIndex((c) => c.slug === draggedSlug)
      if (from === -1 || from === overIndex) return prev
      const [moved] = list.splice(from, 1)
      list.splice(overIndex, 0, moved)
      return list
    })
  }

  const handleDragEnd = async () => {
    justDraggedRef.current = true
    setTimeout(() => { justDraggedRef.current = false }, 100)

    const draggedSlug = draggedSlugRef.current
    const preview = previewOrder
    draggedSlugRef.current = null

    if (!draggedSlug || !preview) {
      setPreviewOrder(null)
      return
    }

    const fromIndex = customCharacters.findIndex((c) => c.slug === draggedSlug)
    const toIndex = preview.findIndex((c) => c.slug === draggedSlug)
    if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) {
      setPreviewOrder(null)
      return
    }

    setReordering(true)
    try {
      await api.post('/custom-characters/reorder', { fromIndex, toIndex })
      playSound('boop')
      await onRefresh?.()
    } catch (err) {
      console.error('Reorder error:', err)
      alert(`Reorder failed: ${err.message}`)
    } finally {
      setReordering(false)
      setPreviewOrder(null)
    }
  }

  return (
    <div className="grid-wrapper">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <button
          className="mode-btn"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('back'); onBack(); }}
        >
          ← Back to Characters
        </button>
      </div>

      <div
        className="characters-grid custom-characters-grid"
        onDragOver={(e) => { if (draggedSlugRef.current) e.preventDefault() }}
      >
        {isLoading ? (
          Array.from({ length: 8 }).map((_, idx) => (
            <SkeletonCard key={`skeleton-cc-${idx}`} />
          ))
        ) : (
          <NewClimbersCard onClick={() => { playSound('boop'); setShowClimbers(true) }} />
        )}
        {isLoading ? null : items.length === 0 && pendingBuiltins.length === 0 ? (
          <div className="no-skins-message" style={{ width: '100%' }}>
            <p>No custom characters yet. Import a fighter package or scan an ISO.</p>
          </div>
        ) : items.map((char, index) => (
          <div
            key={char.slug}
            className={`character-card${draggedSlugRef.current === char.slug ? ' dragging' : ''}`}
            draggable={!reordering}
            onDragStart={(e) => handleDragStart(e, char.slug)}
            onDragEnter={(e) => { e.preventDefault(); handleDragEnter(index) }}
            onDragOver={(e) => e.preventDefault()}
            onDragEnd={handleDragEnd}
            onMouseEnter={playHoverSound}
            onClick={() => {
              if (justDraggedRef.current) return
              playSound('boop')
              onSelectCharacter(char)
            }}
          >
            <div className="character-icon-container">
              {char.has_css_icon ? (
                <img
                  src={backendMediaUrl(char.icon_url)}
                  alt={char.name}
                  className="character-css-icon"
                  draggable={false}
                  onError={(e) => {
                    e.target.style.display = 'none'
                    e.target.nextSibling.style.display = 'flex'
                  }}
                />
              ) : null}
              <div className="character-placeholder" style={{ display: char.has_css_icon ? 'none' : 'flex' }}>
                <span className="character-initial">{char.name[0]}</span>
              </div>
            </div>
            <p className="skin-count">
              <span>{char.costume_count}</span> costume{char.costume_count !== 1 ? 's' : ''}
            </p>
          </div>
        ))}
        {!isLoading && pendingBuiltins.map((builtin) => (
          <PendingBuiltinCard
            key={`builtin-${builtin.slug}`}
            builtin={builtin}
            onRefresh={onRefresh}
          />
        ))}
      </div>

      {showClimbers && (
        <NewClimbersModal
          onClose={() => setShowClimbers(false)}
          onCreated={onRefresh}
        />
      )}
    </div>
  )
}
