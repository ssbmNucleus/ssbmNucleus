/**
 * Dual-color card previews, part of DualColorPreview's dispatch:
 * Luigi, Bowser, Mario and Dr. Mario: fireballs, cyclone, impact spark, fire breath, cape, tornado.
 * Returns the preview for a matching extraType id, else null.
 */
export function renderMarioFamilyPreview({ extraType, compact, color1Hex, color2Hex, height }) {
  // Luigi Fireball - PlLg article body/aura core (single-color)
  if (extraType?.id === 'luigi_fireball') {
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
          <circle cx="40" cy="22" r="16" fill={color1Hex} opacity="0.35" />
          <circle cx="40" cy="22" r="11" fill={color1Hex} opacity="0.75" />
          <circle cx="40" cy="22" r="6" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Luigi Fireball Smoke & Hand Ring - hand-spawn smoke puff + oval portal ring
  if (extraType?.id === 'luigi_fireball_smoke' || extraType?.id === 'kirby_copy_luigi') {
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
          <ellipse cx="24" cy="22" rx="10" ry="15" fill="none" stroke={color1Hex} strokeWidth="2.5" opacity="0.9" />
          <circle cx="58" cy="16" r="8" fill={color2Hex} opacity="0.5" />
          <circle cx="70" cy="22" r="6" fill={color1Hex} opacity="0.6" />
          <circle cx="64" cy="30" r="5" fill={color2Hex} opacity="0.45" />
        </svg>
      </div>
    )
  }

  // Luigi Cyclone - spinning tornado swirl with a ground finish ring
  if (extraType?.id === 'luigi_cyclone') {
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
          <path d="M40 4 Q60 8 40 14 Q23 18 40 22 Q58 26 40 30 Q25 34 40 38"
            fill="none" stroke={color1Hex} strokeWidth="3" strokeLinecap="round" opacity="0.85" />
          <ellipse cx="40" cy="40" rx="17" ry="4" fill="none" stroke={color2Hex} strokeWidth="2" opacity="0.7" />
        </svg>
      </div>
    )
  }

  // Luigi Impact Spark - on-hit melee contact flash inner burst
  if (extraType?.id === 'luigi_hitspark') {
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
          <circle cx="40" cy="22" r="14" fill={color2Hex} opacity="0.35" />
          {[0, 60, 120, 180, 240, 300].map((deg) => (
            <path key={deg} d="M40 22 L40 8 L43 14 L40 5"
              fill="none" stroke={color1Hex} strokeWidth="2" strokeLinecap="round"
              transform={`rotate(${deg} 40 22)`} opacity="0.9" />
          ))}
          <circle cx="40" cy="22" r="5.5" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Bowser Fire Breath - streaming flame cone with trailing puffs
  if (extraType?.id === 'bowser_fire_breath' || extraType?.id === 'kirby_copy_bowser') {
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
          <circle cx="80" cy="22" r="8" fill={color2Hex} opacity="0.5" />
          <circle cx="66" cy="19" r="6.5" fill={color2Hex} opacity="0.45" />
          <path d="M15 22 Q45 12 74 18 Q84 20 90 22 Q84 24 74 26 Q45 32 15 22 Z"
            fill={color1Hex} opacity="0.8" />
          <ellipse cx="27" cy="22" rx="11" ry="5.5" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Mario Fireball - orb with smoke puffs, trail, and hand ring
  if (extraType?.id === 'mario_fireball' || extraType?.id === 'kirby_copy_mario') {
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
          <ellipse cx="16" cy="22" rx="8" ry="11" fill="none" stroke={color1Hex} strokeWidth="2" opacity="0.8" />
          <circle cx="38" cy="19" r="6" fill={color2Hex} opacity="0.45" />
          <circle cx="55" cy="25" r="7" fill={color1Hex} opacity="0.55" />
          <circle cx="72" cy="19" r="5" fill={color2Hex} opacity="0.4" />
          <circle cx="84" cy="22" r="8" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Mario Fireball Aura - glow halo around the fireball orb + body material
  if (extraType?.id === 'mario_fireball_aura') {
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
          <circle cx="40" cy="22" r="11" fill={color1Hex} opacity="0.6" />
          <circle cx="40" cy="22" r="5" fill="#FFFFFF" opacity="0.8" />
        </svg>
      </div>
    )
  }

  // Cape Sparkles - swing sparkle stars (subtle, multi-hue in vanilla)
  if (extraType?.id === 'cape_sparkles') {
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
          {[[20, 15], [40, 30], [62, 12], [80, 27]].map(([x, y], i) => (
            <path key={i} d={`M${x} ${y - 5} L${x + 1.5} ${y - 1.5} L${x + 5} ${y} L${x + 1.5} ${y + 1.5} L${x} ${y + 5} L${x - 1.5} ${y + 1.5} L${x - 5} ${y} L${x - 1.5} ${y - 1.5} Z`}
              fill={i % 2 === 0 ? color1Hex : color2Hex} opacity="0.8" />
          ))}
        </svg>
      </div>
    )
  }

  // Mario / Doc Cape Cloth - flowing cape fabric swatch
  if (extraType?.id === 'mario_cape' || extraType?.id === 'doc_cape') {
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
          <path d="M20 8 Q60 5 64 22 Q60 40 20 37 Q34 22 20 8 Z" fill={color1Hex} opacity="0.85" />
          <path d="M27 14 Q54 12 57 22 Q54 33 27 31 Q35 22 27 14 Z" fill={color2Hex} opacity="0.5" />
        </svg>
      </div>
    )
  }

  // Mario Tornado - spinning vortex with ground haze
  if (extraType?.id === 'mario_tornado') {
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
          <path d="M40 4 Q60 8 40 14 Q23 18 40 22 Q58 26 40 30 Q25 34 40 38"
            fill="none" stroke={color1Hex} strokeWidth="3" strokeLinecap="round" opacity="0.85" />
          <ellipse cx="40" cy="40" rx="20" ry="4" fill="none" stroke={color2Hex} strokeWidth="2" opacity="0.6" />
        </svg>
      </div>
    )
  }

  return null
}
