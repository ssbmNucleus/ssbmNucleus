/**
 * Dual-color card previews, part of DualColorPreview's dispatch:
 * Kirby Stone, Ice Climbers ice shot, Zelda Farore's Wind and transform flash.
 * Returns the preview for a matching extraType id, else null.
 */
export function renderKirbyClimbersZeldaPreview({ extraType, compact, color1Hex, color2Hex, height }) {
  // Kirby Stone - down-B transform burst: radial dust/debris cloud (color1)
  // in a swirling ring (color2, s9 teal env tint). Mirrors mex/charactermode/
  // ExtraPreviews.jsx.
  if (extraType?.id === 'kirby_stone') {
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
          <ellipse cx="50" cy="22" rx="32" ry="16" fill="none" stroke={color2Hex}
            strokeWidth="3" opacity="0.55" />
          {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => (
            <rect key={deg} x="48.75" y="4" width="2.5" height="14" rx="1.2"
              fill={color1Hex} opacity="0.6" transform={`rotate(${deg} 50 22)`} />
          ))}
          <circle cx="50" cy="22" r="11" fill={color1Hex} opacity="0.9" />
          <circle cx="50" cy="22" r="4.5" fill="#FFFFFF" opacity="0.65" />
        </svg>
      </div>
    )
  }

  // Ice Shot - forward-firing icy swirl with a sparkle burst at the block
  if (extraType?.id === 'ice_shot' || extraType?.id === 'kirby_copy_iceclimbers') {
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
          <path d="M16 22 Q34 8 50 22 Q66 36 84 22"
            fill="none" stroke={color2Hex} strokeWidth="4" strokeLinecap="round" opacity="0.6" />
          <circle cx="21" cy="22" r="8" fill={color1Hex} opacity="0.85" />
          <circle cx="21" cy="22" r="3.2" fill="#FFFFFF" opacity="0.8" />
          {[0, 72, 144, 216, 288].map((deg) => (
            <rect key={deg} x="78" y="16" width="2.5" height="13" rx="1.2"
              fill={color1Hex} opacity="0.75"
              transform={`rotate(${deg} 80 22)`} />
          ))}
          <circle cx="80" cy="22" r="5" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Farore's Wind - teleport burst core flash (color1) inside a glowing ring (color2)
  if (extraType?.id === 'zelda_farore') {
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
          <circle cx="40" cy="22" r="18" fill="none" stroke={color2Hex} strokeWidth="4" opacity="0.4" />
          {[0, 60, 120, 180, 240, 300].map((deg) => (
            <rect key={deg} x="38.5" y="3" width="3" height="14" rx="1.5"
              fill={color1Hex} opacity="0.55"
              transform={`rotate(${deg} 40 22)`} />
          ))}
          <circle cx="40" cy="22" r="10" fill={color1Hex} />
          <circle cx="40" cy="22" r="4" fill="#FFFFFF" opacity="0.6" />
        </svg>
      </div>
    )
  }

  // Transform Flash (Zelda<->Sheik) - chest-flash core orb (color1) with an
  // environmental ring (color2)
  if (extraType?.id === 'zelda_transform') {
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
          <ellipse cx="40" cy="22" rx="20" ry="15" fill="none" stroke={color2Hex} strokeWidth="3.5" opacity="0.4" />
          <circle cx="40" cy="22" r="11" fill={color1Hex} opacity="0.85" />
          <circle cx="40" cy="22" r="5" fill="#FFFFFF" opacity="0.6" />
        </svg>
      </div>
    )
  }

  return null
}
