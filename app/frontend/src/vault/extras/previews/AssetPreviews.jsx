import { API_URL } from '../../../shared/config/config.js'

// Card previews for mods that carry a file instead of colors: 3D models,
// decoded shield textures and image effects.

/**
 * ModelPreview - Preview for model-type extras (gun, etc.)
 * Shows a placeholder with 3D icon since we can't render actual models
 */
export function ModelPreview({ extraType, mod, compact = false }) {
  const height = compact ? 40 : 50

  return (
    <div
      className="model-preview"
      style={{
        position: 'relative',
        height: `${height}px`,
        minWidth: '100%',
        background: 'linear-gradient(180deg, #0a0a12 0%, #0d0d18 100%)',
        borderRadius: '4px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden'
      }}
    >
      {/* 3D cube icon */}
      <svg
        width={compact ? 24 : 32}
        height={compact ? 24 : 32}
        viewBox="0 0 24 24"
        fill="none"
        stroke="#4a9eff"
        strokeWidth="1.5"
      >
        <path d="M12 2L2 7l10 5 10-5-10-5z" />
        <path d="M2 17l10 5 10-5" />
        <path d="M2 12l10 5 10-5" />
      </svg>
      {mod?.name && (
        <span style={{
          position: 'absolute',
          bottom: '4px',
          fontSize: '9px',
          color: '#666',
          maxWidth: '90%',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}>
          3D Model
        </span>
      )}
    </div>
  )
}

/**
 * ShieldTexturePreview - Preview for texture_region extras (common_shield).
 * Shows the mod's decoded texture image when it has one (screenshot rendered
 * at import time), else an honest SVG of the vanilla-style bubble. The
 * per-port tint is engine-side and NOT part of the mod, so the preview stays
 * neutral gray -- drawing it tinted would promise a recolor we can't ship.
 */
export function ShieldTexturePreview({ extraType, mod, character, compact = false }) {
  const height = compact ? 40 : 50
  const owner = extraType?.owner || character
  const shot = mod?.screenshot && API_URL
    ? `${API_URL.replace('/api/mex', '')}/storage/${owner}/${mod.screenshot}`
    : null

  return (
    <div style={{
      position: 'relative',
      height: `${height}px`,
      minWidth: '100%',
      background: 'linear-gradient(180deg, #0a0a12 0%, #0d0d18 100%)',
      borderRadius: '4px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      overflow: 'hidden'
    }}>
      {shot ? (
        <img
          src={shot}
          alt={mod?.name || 'shield texture'}
          style={{ height: '100%', imageRendering: 'pixelated' }}
          onError={(e) => { e.target.style.display = 'none' }}
        />
      ) : (
        <svg width={height - 8} height={height - 8} viewBox="0 0 48 48">
          <defs>
            <radialGradient id="shieldBubble" cx="42%" cy="30%" r="65%">
              <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
              <stop offset="45%" stopColor="#c8c8c8" stopOpacity="0.55" />
              <stop offset="100%" stopColor="#7a7a7a" stopOpacity="0.35" />
            </radialGradient>
          </defs>
          <circle cx="24" cy="24" r="21" fill="url(#shieldBubble)" stroke="#9a9a9a" strokeWidth="1.5" />
          <ellipse cx="29" cy="14" rx="6" ry="3.5" fill="#ffffff" opacity="0.85" />
        </svg>
      )}
    </div>
  )
}

/**
 * ImageEffectPreview - Preview for image_model mods (Fox/Falco image shines).
 * The mod IS a picture, so the card shows it (decoded at import time into
 * `screenshot`) rather than any color swatch. No screenshot means the import
 * could not decode one, and an honest label beats a fake gradient.
 */
export function ImageEffectPreview({ extraType, mod, character, compact = false }) {
  const height = compact ? 40 : 50
  const owner = extraType?.owner || character
  const shot = mod?.screenshot && API_URL
    ? `${API_URL.replace('/api/mex', '')}/storage/${owner}/${mod.screenshot}`
    : null

  return (
    <div style={{
      position: 'relative',
      height: `${height}px`,
      minWidth: '100%',
      background: 'linear-gradient(180deg, #0a0a12 0%, #0d0d18 100%)',
      borderRadius: '4px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      overflow: 'hidden'
    }}>
      {shot ? (
        <img
          src={shot}
          alt={mod?.name || 'image effect'}
          style={{ height: '100%', objectFit: 'contain', imageRendering: 'pixelated' }}
          onError={(e) => { e.target.style.display = 'none' }}
        />
      ) : (
        <span style={{ fontSize: '10px', color: '#777', letterSpacing: '0.06em' }}>
          IMAGE EFFECT
        </span>
      )}
    </div>
  )
}
