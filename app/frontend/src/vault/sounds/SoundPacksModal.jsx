import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { CloseIcon } from '../../shared/ui/Icons'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import SoundBankModal from './SoundBankModal'
import { API_URL } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'
import './SoundPacksModal.css'

/**
 * Sound packs for a vanilla character: any number of alternate voice/SFX
 * packs in the vault. "New" creates a pack on the spot (auto-named) and opens
 * it in the SoundBankModal browser; the name is edited inline on its row.
 * In installMode (Install tab) packs are installed into the open project as an
 * explicit action -- nothing applies automatically.
 *
 * Zelda and Sheik share one bank, so they share one pack list.
 */

/** Pack name as an inline field: Enter / blur commit, Escape reverts. */
function PackName({ name, onRename, disabled }) {
  const [value, setValue] = useState(name)
  const [editing, setEditing] = useState(false)
  const revertingRef = useRef(false)
  const inputRef = useRef(null)
  useEffect(() => { if (!editing) setValue(name) }, [name, editing])

  const commit = async () => {
    setEditing(false)
    if (revertingRef.current) { revertingRef.current = false; setValue(name); return }
    const next = value.trim()
    if (!next || next === name) { setValue(name); return }
    const ok = await onRename(next)
    if (!ok) setValue(name)
  }

  if (!editing) {
    return (
      <button
        type="button"
        className="sp-pack-name"
        title="Click to rename"
        onClick={() => { if (!disabled) { setEditing(true); setTimeout(() => inputRef.current?.select(), 0) } }}
        disabled={disabled}
      >
        {name}
      </button>
    )
  }
  return (
    <input
      ref={inputRef}
      className="sp-pack-name sp-pack-name--input"
      value={value}
      autoFocus
      spellCheck={false}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { e.preventDefault(); inputRef.current?.blur() }
        if (e.key === 'Escape') { e.preventDefault(); revertingRef.current = true; inputRef.current?.blur() }
      }}
    />
  )
}

function nextPackName(packs) {
  const taken = new Set(packs.map((p) => p.name))
  for (let n = 1; ; n++) {
    const candidate = `Sound Pack ${n}`
    if (!taken.has(candidate)) return candidate
  }
}

export default function SoundPacksModal({ show, character, displayName, onClose, installMode = false }) {
  const [packs, setPacks] = useState([])
  const [installed, setInstalled] = useState(null)
  const [projectOpen, setProjectOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)
  const [editingPack, setEditingPack] = useState(null)
  const messageTimerRef = useRef(null)

  const base = `${API_URL}/storage/characters/${encodeURIComponent(character)}/sound-packs`

  const fetchPacks = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get(base)
      setPacks(data.packs)
      setInstalled(data.installed)
      setProjectOpen(data.project_open)
    } catch (err) {
      setError(err.message || 'Failed to load sound packs')
    } finally {
      setLoading(false)
    }
  }, [base])

  useEffect(() => {
    if (show) {
      fetchPacks()
    } else {
      setConfirmDeleteId(null)
      setEditingPack(null)
      setMessage('')
    }
  }, [show, fetchPacks])

  useEffect(() => () => clearTimeout(messageTimerRef.current), [])

  const flashMessage = (text) => {
    setMessage(text)
    clearTimeout(messageTimerRef.current)
    messageTimerRef.current = setTimeout(() => setMessage(''), 3000)
  }

  // New pack: created on the spot with the next free name, straight into the editor
  const handleCreate = async () => {
    setBusy(true)
    try {
      const data = await api.post(`${base}/create`, { name: nextPackName(packs) })
      playSound('newSkin')
      await fetchPacks()
      setEditingPack({ id: data.id, name: data.name })
    } catch (err) {
      playSound('error')
      flashMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  const handleRename = async (pack, name) => {
    try {
      const data = await api.post(`${base}/${pack.id}/rename`, { name })
      setPacks((prev) => prev.map((p) => (p.id === pack.id ? { ...p, name: data.name } : p)))
      playSound('boop')
      return true
    } catch (err) {
      playSound('error')
      flashMessage(err.message)
      return false
    }
  }

  const handleDelete = async (pack) => {
    playSound('back')
    setBusy(true)
    try {
      await api.post(`${base}/${pack.id}/delete`)
      await fetchPacks()
    } catch (err) {
      playSound('error')
      flashMessage(err.message)
    } finally {
      setConfirmDeleteId(null)
      setBusy(false)
    }
  }

  const handleInstall = async (pack) => {
    playSound('start')
    setBusy(true)
    try {
      const data = await api.post(`${base}/${pack.id}/install`)
      playSound('newSkin')
      setInstalled(data.installed)
    } catch (err) {
      playSound('error')
      flashMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  const handleUninstall = async () => {
    playSound('back')
    setBusy(true)
    try {
      await api.post(`${base}/uninstall`)
      setInstalled(null)
    } catch (err) {
      playSound('error')
      flashMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!show) return null

  const canInstall = installMode && projectOpen
  const close = () => { playSound('back'); onClose() }

  const modal = (
    <div className="sp-overlay" onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="sp-modal">
        <div className="sp-header">
          <h2>Sound Packs</h2>
          <span className="sp-header-char">{displayName || character}</span>
          <button className="sp-close-btn" onClick={close} title="Close"><CloseIcon /></button>
        </div>

        {message && <div className="sp-message">{message}</div>}

        <div className="sp-list">
          {loading ? (
            <div className="sp-empty">Loading…</div>
          ) : error ? (
            <div className="sp-empty sp-error">{error}</div>
          ) : (
            <>
              {canInstall && (
                <div className={`sp-row sp-row--original${installed == null ? ' sp-row--installed' : ''}`}>
                  <span className="sp-pack-name sp-pack-name--static">Original Sounds</span>
                  <span className="sp-actions">
                    {installed == null ? (
                      <span className="sp-installed-badge">In project</span>
                    ) : (
                      <button className="sp-action-btn sp-install-btn" onMouseEnter={playHoverSound}
                        onClick={handleUninstall} disabled={busy}>Restore</button>
                    )}
                  </span>
                </div>
              )}

              {packs.map((pack) => (
                <div key={pack.id}
                  className={`sp-row${canInstall && installed === pack.id ? ' sp-row--installed' : ''}`}>
                  <PackName name={pack.name} disabled={busy} onRename={(name) => handleRename(pack, name)} />
                  <span className="sp-pack-meta">
                    {pack.modified_count ? `${pack.modified_count} replaced` : 'untouched'}
                  </span>
                  <span className="sp-actions">
                    {canInstall && (installed === pack.id ? (
                      <span className="sp-installed-badge">In project</span>
                    ) : (
                      <button className="sp-action-btn sp-install-btn" onMouseEnter={playHoverSound}
                        onClick={() => handleInstall(pack)} disabled={busy}>Install</button>
                    ))}
                    <button className="sp-action-btn" onMouseEnter={playHoverSound}
                      onClick={() => { playSound('boop'); setEditingPack(pack) }} disabled={busy}>
                      Edit
                    </button>
                    {confirmDeleteId === pack.id ? (
                      <button className="sp-action-btn sp-delete-btn sp-delete-confirm" onMouseEnter={playHoverSound}
                        onClick={() => handleDelete(pack)} disabled={busy}
                        onBlur={() => setConfirmDeleteId(null)}>
                        Delete?
                      </button>
                    ) : (
                      <button className="sp-action-btn sp-delete-btn" onMouseEnter={playHoverSound}
                        onClick={() => { playSound('boop'); setConfirmDeleteId(pack.id) }} disabled={busy}
                        title="Delete this pack">
                        ✕
                      </button>
                    )}
                  </span>
                </div>
              ))}

              {packs.length === 0 && !canInstall && (
                <div className="sp-empty">No sound packs yet.</div>
              )}
            </>
          )}
        </div>

        <div className="sp-footer">
          <button className="sp-new-pack-btn" onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); handleCreate() }} disabled={busy || loading}>
            {busy ? 'Working…' : '+ New Sound Pack'}
          </button>
        </div>
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return (
    <>
      {portalTarget ? createPortal(modal, portalTarget) : modal}
      <SoundBankModal
        show={editingPack !== null}
        displayName={editingPack?.name || ''}
        endpoint={`storage/characters/${encodeURIComponent(character)}/sound-packs/${editingPack?.id}/audio`}
        onClose={() => { setEditingPack(null); fetchPacks() }}
      />
    </>
  )
}
