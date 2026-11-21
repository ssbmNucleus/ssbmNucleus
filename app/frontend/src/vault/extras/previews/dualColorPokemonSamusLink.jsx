/**
 * Dual-color card previews, part of DualColorPreview's dispatch:
 * Thunder, fireball, Mewtwo up-smash and Shadow Ball, Samus screw attack/missile/charge shot, Link spin trail.
 * Returns the preview for a matching extraType id, else null.
 */
export function renderPokemonSamusLinkPreview({ extraType, compact, color1, color2, color1Hex, color2Hex, L, height }) {
  // Thunder effect - lightning bolt
  if (extraType?.id === 'thunder' || extraType?.id === 'pk_thunder') {
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
          <path d="M42 3 L28 18 L38 18 L24 42 L56 22 L44 22 L58 3 Z"
            fill={color2Hex} opacity="0.4" transform="scale(1.1) translate(-4, -2)" />
          <path d="M42 3 L28 18 L38 18 L24 42 L56 22 L44 22 L58 3 Z"
            fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Fireball effect
  if (extraType?.id === 'fireball') {
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
          <circle cx="40" cy="22" r="18" fill={color2Hex} opacity="0.4" />
          <circle cx="40" cy="22" r="12" fill={color1Hex} opacity="0.7" />
          <circle cx="40" cy="22" r="6" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Up-smash swirl (Mewtwo Galaxy Force) - spiral arcs
  if (extraType?.id === 'upsmash') {
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
          <circle cx="40" cy="22" r="16" fill={color2Hex} opacity="0.5" />
          <path d="M40 22 m-14 0 a14 14 0 1 1 14 14" fill="none"
            stroke={color1Hex} strokeWidth="3" strokeLinecap="round" opacity="0.9" />
          <path d="M40 22 m-8 0 a8 8 0 1 0 8 -8" fill="none"
            stroke={color1Hex} strokeWidth="2.5" strokeLinecap="round" />
          <circle cx="40" cy="22" r="3" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Screw Attack (Samus up-B) - electric arcs wrapping the body
  if (extraType?.id === 'screw_attack') {
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
          {(() => {
            const core = L('arc_c1', color1)
            const halo = L('arc_c2', color2)
            return (<>
              <circle cx="40" cy="22" r="18" fill={halo} opacity="0.3" />
              <ellipse cx="40" cy="22" rx="16" ry="9" fill="none" stroke={core} strokeWidth="1.5" opacity="0.85" transform="rotate(-20 40 22)" />
              <ellipse cx="40" cy="22" rx="10" ry="6" fill="none" stroke={core} strokeWidth="1.5" opacity="0.7" transform="rotate(20 40 22)" />
              {[[34, 19], [46, 20], [40, 25], [44, 16]].map(([x, y], i) => (
                <circle key={i} cx={x} cy={y} r={3 - (i % 2)} fill={core} opacity="0.85" />
              ))}
              <circle cx="40" cy="22" r="8" fill={core} opacity="0.5" />
              <circle cx="40" cy="22" r="3.5" fill="#FFFFFF" opacity="0.6" />
            </>)
          })()}
        </svg>
      </div>
    )
  }

  // Spin Attack Trail (Link/Young Link up-B) - swirling blade/disc trail
  if (extraType?.id === 'spin_attack_trail') {
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
          <ellipse cx="40" cy="22" rx="19" ry="16" fill={color2Hex} opacity="0.3" />
          <path d="M40 22 m0 -15 a15 15 0 1 1 -10.6 4.4" fill="none"
            stroke={color1Hex} strokeWidth="2.5" strokeLinecap="round" opacity="0.9" />
          <path d="M40 22 m0 -9 a9 9 0 1 0 6.4 2.6" fill="none"
            stroke={color1Hex} strokeWidth="2" strokeLinecap="round" opacity="0.7" />
          <circle cx="40" cy="22" r="4" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Missile (Samus side-B) - contrail smoke with back-blast puff
  if (extraType?.id === 'missile') {
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
          {(() => {
            const bb1 = L('backblast_c1', color1)
            const bb2 = L('backblast_c2', color2)
            const ct1 = L('contrail_c1', color1)
            const ct2 = L('contrail_c2', color2)
            return (<>
              <circle cx="16" cy="22" r="10" fill={bb2} opacity="0.45" />
              <circle cx="16" cy="22" r="5.5" fill={bb1} opacity="0.8" />
              <circle cx="48" cy="22" r="12" fill={ct2} opacity="0.4" />
              <circle cx="46" cy="22" r="8" fill={ct1} opacity="0.75" />
              <ellipse cx="78" cy="22" rx="7" ry="3.5" fill="#FF66CC" />
              <rect x="69" y="20.5" width="7" height="3" rx="1" fill="#DADADA" />
            </>)
          })()}
        </svg>
      </div>
    )
  }

  // Charge Shot (Samus neutral-B) - radiating spark needles
  if (extraType?.id === 'charge_shot') {
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
          {(() => {
            const needle = L('needles_c1', color1)
            const ring = L('needles_c2', color2)
            return (<>
              <circle cx="40" cy="22" r="18" fill="#3A66CC" opacity="0.28" />
              {[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map((deg) => (
                <rect key={deg} x="39.4" y="5" width="1.2" height="13" rx="0.6"
                  fill={needle} opacity="0.9"
                  transform={`rotate(${deg} 40 22)`} />
              ))}
              <circle cx="40" cy="22" r="5" fill="none" stroke={ring} strokeWidth="2" />
              <circle cx="40" cy="22" r="2.2" fill="#FFFFFF" opacity="0.85" />
            </>)
          })()}
        </svg>
      </div>
    )
  }

  // Shadow Ball effect
  if (extraType?.id === 'shadow_ball') {
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
          <circle cx="40" cy="22" r="18" fill={color2Hex} opacity="0.3" />
          <circle cx="40" cy="22" r="13" fill={color1Hex} opacity="0.5" />
          <circle cx="40" cy="22" r="7" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  return null
}
