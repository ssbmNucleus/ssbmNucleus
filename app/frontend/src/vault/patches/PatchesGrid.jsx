/**
 * PatchesGrid - the vault's "Patches" view, as a Steam-style cover-art library.
 *
 * Bundles and patches are rendered as portrait cover cards: a cover image is
 * shown letterboxed over a blurred backdrop (so any aspect ratio looks good),
 * and cards with no cover get a gradient monogram placeholder. Each card carries
 * a primary Play action, a hover-reveal edit button, and (patches) a secondary
 * "build & download ISO" action.
 */

import { useState } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { BACKEND_URL } from '../../shared/config/config'

function CoverCard({
  kind, // 'bundle' | 'patch'
  name,
  meta,
  imageUrl,
  playing,
  playPercent,
  onPlay,
  onEdit,
  secondaryLabel,
  secondaryTitle,
  onSecondary,
}) {
  const [imgError, setImgError] = useState(false)
  const showImg = imageUrl && !imgError
  const initial = (name?.trim()?.[0] || '?').toUpperCase()

  return (
    <div
      className={`cover-card ${kind} ${playing ? 'is-playing' : ''}`}
      onMouseEnter={playHoverSound}
    >
      <div className="cover-art">
        {showImg ? (
          <>
            <div className="cover-art-blur" style={{ backgroundImage: `url("${imageUrl}")` }} />
            <img className="cover-img" src={imageUrl} alt={name} draggable={false} onError={() => setImgError(true)} />
          </>
        ) : (
          <div className="cover-placeholder">
            <span className="cover-monogram">{initial}</span>
          </div>
        )}
      </div>

      {onEdit && (
        <button
          className="btn-edit"
          onMouseEnter={playHoverSound}
          onClick={(e) => { e.stopPropagation(); playSound('boop'); onEdit() }}
          title="Edit"
        >
          ✎
        </button>
      )}

      <div className="cover-scrim" />

      <div className="cover-body">
        <h4 className="cover-title" title={name}>{name}</h4>
        {meta && <p className="cover-meta">{meta}</p>}
        <div className="cover-actions">
          <button
            className="cover-play"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('start'); onPlay() }}
            disabled={playing}
            title="Build (if needed) and launch in Slippi"
          >
            {playing ? `${playPercent}%` : '▶ Play'}
          </button>
          {onSecondary && (
            <button
              className="cover-secondary"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('start'); onSecondary() }}
              title={secondaryTitle}
            >
              {secondaryLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function PatchesGrid({
  xdeltaPatches,
  bundles = [],
  onEditPatch,
  onBuildIso,
  onShowCreateModal,
  onEditBundle,
  onPlayBundle,
  onPlayPatch,
  playingId = null,
  playPercent = 0,
}) {
  const fmtMb = (mb, bytes) => {
    const v = typeof mb === 'number' ? mb : (bytes ? bytes / (1024 * 1024) : 0)
    return `${v.toFixed(1)} MB`
  }

  return (
    <div className="patches-section">
      {bundles.length > 0 && (
        <>
          <h3 className="vault-section-title">Bundles</h3>
          <div className="cover-grid">
            {bundles.map((bundle) => (
              <CoverCard
                key={bundle.id}
                kind="bundle"
                name={bundle.name}
                meta={`${fmtMb(bundle.size_mb, bundle.size)}${bundle.texture_count > 0 ? ` · ${bundle.texture_count} HD` : ''}`}
                imageUrl={bundle.imageUrl ? `${BACKEND_URL}${bundle.imageUrl}` : null}
                playing={playingId === bundle.id}
                playPercent={playPercent}
                onPlay={() => onPlayBundle?.(bundle)}
                onEdit={() => onEditBundle(bundle)}
              />
            ))}
          </div>
        </>
      )}

      <h3 className="vault-section-title">Patches</h3>
      <div className="cover-grid">
        {xdeltaPatches.map((patch) => (
          <CoverCard
            key={patch.id}
            kind="patch"
            name={patch.name}
            meta={patch.size ? fmtMb(null, patch.size) : null}
            imageUrl={patch.imageUrl ? `${BACKEND_URL}${patch.imageUrl}` : null}
            playing={playingId === patch.id}
            playPercent={playPercent}
            onPlay={() => onPlayPatch?.(patch)}
            onEdit={() => onEditPatch(patch)}
            secondaryLabel="Export ISO"
            secondaryTitle="Build & download the ISO file"
            onSecondary={() => onBuildIso(patch)}
          />
        ))}

        {/* Create-new-patch tile */}
        <button
          className="cover-card cover-create"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); onShowCreateModal() }}
        >
          <span className="cover-create-plus">+</span>
          <span className="cover-create-label">New Patch</span>
          <span className="cover-create-sub">From a modded ISO</span>
        </button>
      </div>
    </div>
  )
}
