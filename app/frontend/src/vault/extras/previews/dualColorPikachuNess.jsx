/**
 * Dual-color card previews, part of DualColorPreview's dispatch:
 * Pikachu thunder jolt and forward smash, Ness PSI Magnet, PK Thunder, PK Fire.
 * Returns the preview for a matching extraType id, else null.
 */
export function renderPikachuNessPreview({ extraType, compact, color1Hex, color2Hex, height }) {
  // Pikachu Thunder Jolt (Aerial) - radiating starburst with lens-flare rings
  if (extraType?.id === 'pikachu_thunder_jolt_air') {
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
        <svg width={compact ? 60 : 80} height={compact ? 36 : 45} viewBox="0 0 80 45">
          <circle cx="40" cy="22" r="18" fill={color2Hex} opacity="0.35" />
          {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => (
            <rect key={deg} x="38.5" y="4" width="3" height="16" rx="1.5"
              fill={color1Hex} opacity="0.8"
              transform={`rotate(${deg} 40 22)`} />
          ))}
          <circle cx="40" cy="22" r="6" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Pikachu Thunder Jolt (Ground Bolt) - traveling jagged bolt with a spawn head
  if (extraType?.id === 'pikachu_thunder_jolt_ground') {
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
        <svg width={compact ? 80 : 100} height={compact ? 36 : 45} viewBox="0 0 100 45">
          <circle cx="14" cy="22" r="8" fill={color1Hex} opacity="0.9" />
          <path d="M22 22 L45 16 L38 22 L62 14 L54 22 L84 18"
            fill="none" stroke={color2Hex} strokeWidth="4" strokeLinecap="round" opacity="0.5" />
          <path d="M22 22 L45 16 L38 22 L62 14 L54 22 L84 18"
            fill="none" stroke={color1Hex} strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
    )
  }

  // Pikachu Forward Smash Arc - electric arc wrapping the fist with a ball core
  if (extraType?.id === 'pikachu_fsmash') {
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
        <svg width={compact ? 60 : 80} height={compact ? 36 : 45} viewBox="0 0 80 45">
          <ellipse cx="46" cy="22" rx="24" ry="15" fill="none" stroke={color1Hex} strokeWidth="3" opacity="0.5" />
          <path d="M24 10 Q42 6 34 22 Q48 30 38 35" fill="none"
            stroke={color2Hex} strokeWidth="2.5" strokeLinecap="round" opacity="0.85" />
          <circle cx="46" cy="22" r="7" fill={color1Hex} />
          <circle cx="46" cy="22" r="3.5" fill={color2Hex} opacity="0.8" />
        </svg>
      </div>
    )
  }

  // Ness PSI Magnet - swirling absorb aura orbiting the body
  if (extraType?.id === 'ness_psi_magnet') {
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
        <svg width={compact ? 60 : 80} height={compact ? 36 : 45} viewBox="0 0 80 45">
          <ellipse cx="40" cy="22" rx="24" ry="17" fill="none" stroke={color2Hex} strokeWidth="4" opacity="0.4" />
          <path d="M40 6 Q62 12 40 22 Q20 30 40 40" fill="none"
            stroke={color2Hex} strokeWidth="2.5" strokeLinecap="round" opacity="0.85" />
          <circle cx="40" cy="22" r="7" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Ness PK Thunder - lightning ball at the tip of a jagged tail
  if (extraType?.id === 'ness_pk_thunder') {
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
        <svg width={compact ? 60 : 80} height={compact ? 36 : 45} viewBox="0 0 80 45">
          <path d="M10 34 L28 22 L22 22 L42 8 L33 19 L41 19 L20 35"
            fill="none" stroke={color1Hex} strokeWidth="2.5" strokeLinecap="round" opacity="0.9" />
          <circle cx="60" cy="14" r="10" fill={color2Hex} opacity="0.35" />
          <circle cx="60" cy="14" r="6" fill={color2Hex} />
        </svg>
      </div>
    )
  }

  // Ness PK Fire - burn pillar: fixed-orange fire body (texture, not
  // recolored) with a bright ring core (color1) banding its base and a
  // glow (color2) around the ring + aura
  if (extraType?.id === 'ness_pk_fire') {
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
        <svg width={compact ? 60 : 80} height={compact ? 36 : 45} viewBox="0 0 80 45">
          <path d="M40 4 C32 14 29 21 31 28 C33 34 36 38 40 38 C44 38 47 34 49 28 C51 21 48 14 40 4 Z"
            fill="#FF9900" opacity="0.55" />
          <ellipse cx="40" cy="27" rx="15" ry="7" fill={color2Hex} opacity="0.35" />
          <ellipse cx="40" cy="30" rx="17" ry="4" fill="none" stroke={color2Hex} strokeWidth="3" opacity="0.7" />
          <ellipse cx="40" cy="30" rx="17" ry="4" fill="none" stroke={color1Hex} strokeWidth="1.5" opacity="0.95" />
        </svg>
      </div>
    )
  }

  return null
}
