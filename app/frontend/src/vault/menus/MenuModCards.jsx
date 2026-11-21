/**
 * MenuModCards - the card grid every menu kind renders in the vault.
 *
 * Same card shell as the Fighters / Stages grids (framed thumbnail, LED
 * hover border, centered title). Clicking a card (or its big pencil) opens
 * the kind's editor when it has one. Everything that used to hide behind a
 * pencil-then-modal hop sits on the card: inline rename (small pencil by the
 * name), and a hover action row for preview replacement, export, delete,
 * plus any kind-specific action (pause capture). A trailing dashed "+" card
 * creates a mod from scratch for kinds that support it.
 */
import { useEffect, useRef, useState } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'

const PencilIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
)
const ImageIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
    <circle cx="8.5" cy="8.5" r="1.5" />
    <polyline points="21 15 16 10 5 21" />
  </svg>
)
const ExportIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="17 8 12 3 7 8" />
    <line x1="12" y1="3" x2="12" y2="15" />
  </svg>
)
const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
)

function CardName({ mod, onRename }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(mod.name)
  const inputRef = useRef(null)

  useEffect(() => { if (!editing) setValue(mod.name) }, [mod.name, editing])
  useEffect(() => { if (editing) inputRef.current?.select() }, [editing])

  const commit = async () => {
    setEditing(false)
    try { await onRename(mod, value) } catch (err) { alert(`Rename failed: ${err.message}`) }
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        className="mmod-name-input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onClick={(e) => e.stopPropagation()}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit() }
          if (e.key === 'Escape') { setValue(mod.name); setEditing(false) }
        }}
        autoFocus
      />
    )
  }
  return (
    <h3 className="stage-name mmod-name" title={mod.name}>
      <span className="mmod-name-text">{mod.name}</span>
      <button
        className="mmod-rename"
        title="Rename"
        onMouseEnter={playHoverSound}
        onClick={(e) => { e.stopPropagation(); playSound('boop'); setEditing(true) }}
      >
        <PencilIcon />
      </button>
    </h3>
  )
}

export default function MenuModCards({
  kind,
  mods,
  loading,
  expectedCount,   // sidebar count, so the skeleton matches what will appear
  cacheBust = 0,
  onOpen,          // (mod) => void  — card click + big pencil (kinds with an editor)
  onRename,        // (mod, name) => Promise
  onReplaceImage,  // (mod, file) => Promise
  onExport,        // (mod) => void
  onDelete,        // (mod) => Promise
  extraActions,    // (mod) => [{ key, label, icon, title, onClick, disabled }]
  cardExtra,       // (mod) => node (backgrounds' scene toggle)
  createCard,      // { label, title, onClick }
}) {
  const fileInputs = useRef({})
  const thumbClass = `mmod-thumb mmod-thumb--${kind.thumb} mmod-thumb--fit-${kind.imgFit}`

  if (loading) {
    // Reserve exactly the cards that are about to appear (plus the "+" card),
    // so the grid doesn't collapse or grow when the list lands. Unknown
    // count: a single placeholder.
    const n = Math.min(12, (expectedCount ?? 1) + (createCard ? 1 : 0))
    return (
      <div className="mmod-grid">
        {Array.from({ length: Math.max(n, 1) }).map((_, i) => (
          <div key={`mmod-skel-${i}`} className="mmod-card mmod-card--skeleton">
            <div className={`${thumbClass} skeleton`} />
            <div className="skeleton skeleton-text" style={{ width: '55%', height: 12, margin: '0 auto' }} />
          </div>
        ))}
      </div>
    )
  }

  const clickable = Boolean(kind.editor && onOpen)
  const isEmpty = mods.length === 0

  return (
    <>
      {isEmpty && !createCard && <div className="vault-empty">{kind.empty}</div>}
      <div className="mmod-grid">
        {mods.map((mod) => {
          const url = kind.image(mod)
          const src = url ? backendMediaUrl(url, cacheBust || undefined) : null
          const meta = kind.meta?.(mod)
          const extras = extraActions?.(mod) || []
          return (
            <div
              key={mod.id}
              className={`stage-card mmod-card${clickable ? ' mmod-card--clickable' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={clickable ? () => { playSound('boop'); onOpen(mod) } : undefined}
            >
              <div className={thumbClass}>
                {/* Monogram sits underneath; the image overlays it and reveals
                    it again if the preview fails to load. */}
                <span className="mmod-monogram">{(mod.name || '?')[0]}</span>
                {src && (
                  <img
                    src={src}
                    alt={mod.name}
                    draggable={false}
                    onError={(e) => { e.target.style.visibility = 'hidden' }}
                  />
                )}
                {clickable && (
                  <button
                    className="btn-edit"
                    onMouseEnter={playHoverSound}
                    onClick={(e) => { e.stopPropagation(); playSound('boop'); onOpen(mod) }}
                    title={kind.editLabel}
                  >
                    ✎
                  </button>
                )}
              </div>

              <div className="stage-info mmod-info">
                <CardName mod={mod} onRename={onRename} />
                {meta && <p className="stage-variant-count">{meta}</p>}
                {cardExtra && <div className="mmod-card-extra" onClick={(e) => e.stopPropagation()}>{cardExtra(mod)}</div>}
              </div>

              <div className="mmod-card-actions" onClick={(e) => e.stopPropagation()}>
                {extras.map((a) => (
                  <button
                    key={a.key}
                    className="mmod-btn"
                    onMouseEnter={playHoverSound}
                    onClick={() => { if (a.disabled) return; playSound('boop'); a.onClick() }}
                    disabled={a.disabled}
                    title={a.title || a.label}
                  >
                    {a.icon}<span>{a.label}</span>
                  </button>
                ))}
                {onReplaceImage && (
                  <>
                    <input
                      type="file"
                      accept="image/*"
                      style={{ display: 'none' }}
                      ref={(el) => { fileInputs.current[mod.id] = el }}
                      onChange={async (e) => {
                        const file = e.target.files?.[0]
                        e.target.value = ''
                        if (!file) return
                        try { await onReplaceImage(mod, file) } catch (err) { alert(`Image upload failed: ${err.message}`) }
                      }}
                    />
                    <button
                      className="mmod-btn"
                      onMouseEnter={playHoverSound}
                      onClick={() => { playSound('boop'); fileInputs.current[mod.id]?.click() }}
                      title={kind.imageLabel}
                    >
                      <ImageIcon /><span>{kind.imageShort || 'Image'}</span>
                    </button>
                  </>
                )}
                {onExport && (
                  <button
                    className="mmod-btn"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); onExport(mod) }}
                    title="Export as zip"
                  >
                    <ExportIcon /><span>Export</span>
                  </button>
                )}
                {onDelete && (
                  <button
                    className="mmod-btn mmod-btn--danger"
                    onMouseEnter={playHoverSound}
                    onClick={async () => {
                      playSound('boop')
                      try { await onDelete(mod) } catch (err) { alert(`Delete failed: ${err.message}`) }
                    }}
                    title="Delete"
                  >
                    <TrashIcon /><span>Delete</span>
                  </button>
                )}
              </div>
            </div>
          )
        })}

        {createCard && (
          <div
            className="stage-card mmod-card mmod-card--create"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); createCard.onClick() }}
            title={createCard.title}
          >
            <div className={thumbClass}>
              <span className="mmod-monogram mmod-monogram--plus">+</span>
            </div>
            <div className="stage-info mmod-info">
              <h3 className="stage-name">{createCard.label}</h3>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
