import { nestedTextureHex } from './textureTint'

/**
 * Dual-color card previews, part of DualColorPreview's dispatch:
 * Captain Falcon and Ganondorf: punch, kick, Raptor Boost, Wizard's Foot, Gerudo Dragon.
 * Returns the preview for a matching extraType id, else null.
 */
export function renderFalconGanonPreview({ extraType, modifications, compact, color1, color2, color1Hex, color2Hex, L, height }) {
  // Punch effect - explosion/flame burst. falcon_punch ALSO carries the
  // nested punch_texture sibling extra (task #12 migration) -- its
  // dominant fire-bird texture color tints an outer glow behind the burst.
  // warlock_punch (Ganon) has no texture sibling, so fireHex falls back to
  // color2 there (no visual change for that extra).
  if (extraType?.id === 'falcon_punch' || extraType?.id === 'warlock_punch' || extraType?.id === 'kirby_copy_ganon') {
    const fireHex = extraType?.id === 'falcon_punch'
      ? nestedTextureHex(modifications?.fire, color2Hex)
      : color2Hex
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
            const flareBig = L('flare_big_c1', color1)
            const flareSmall = L('flare_small_c1', color1)
            const flareLines = L('flare_lines_c2', 'FFFFFF')
            const smoke = L('smoke', color2)
            return (<>
              <circle cx="15" cy="26" r="8" fill={smoke} opacity="0.4" />
              <circle cx="27" cy="20" r="6" fill={smoke} opacity="0.35" />
              <ellipse cx="44" cy="22" rx="38" ry="15" fill={fireHex} opacity="0.35" />
              <ellipse cx="42" cy="22" rx="25" ry="11" fill={fireHex} opacity="0.7" />
              <ellipse cx="40" cy="22" rx="13" ry="7" fill={fireHex} />
              {[0, 30, 60, 90, 120, 150].map((deg) => (
                <rect key={deg} x="73" y="20" width="1.6" height="20" rx="0.8"
                  fill={flareLines} opacity="0.6" transform={`rotate(${deg} 74 22)`} />
              ))}
              <circle cx="74" cy="22" r="9" fill={flareBig} opacity="0.5" />
              <circle cx="74" cy="22" r="4.5" fill={flareSmall} />
              <circle cx="74" cy="22" r="2" fill="#FFFFFF" opacity="0.8" />
            </>)
          })()}
        </svg>
      </div>
    )
  }

  // Falcon Kick - fire streak with glow at the foot
  if (extraType?.id === 'falcon_kick') {
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
            const core = color1Hex, halo = color2Hex
            const front = L('front_c1', color1)
            const trail1 = L('trail_c1', color1)
            const trail2 = L('trail_c2', color2)
            const dot1 = L('dots_c1', color1)
            const dot2 = L('dots_c2', color2)
            return (<>
              <circle cx="25" cy="22" r="9" fill={trail1} opacity="0.55" />
              <circle cx="13" cy="23" r="8" fill={trail2} opacity="0.5" />
              <circle cx="35" cy="21" r="7" fill={trail1} opacity="0.45" />
              {[[20, 12], [33, 30], [27, 18], [42, 14]].map(([x, y], i) => (
                <rect key={i} x={x} y={y} width="3" height="3" rx="0.8"
                  fill={i % 2 ? dot2 : dot1} opacity="0.9" />
              ))}
              <circle cx="72" cy="22" r="16" fill={halo} opacity="0.4" />
              {[-13, -4, 6, 15].map((dy, i) => (
                <path key={i} d={`M58 ${22 + dy} L80 ${22 + dy * 0.5}`}
                  stroke={front} strokeWidth="2.6" strokeLinecap="round" opacity="0.8" />
              ))}
              <circle cx="72" cy="22" r="8" fill={core} />
              <circle cx="72" cy="22" r="3" fill="#FFFFFF" opacity="0.55" />
            </>)
          })()}
        </svg>
      </div>
    )
  }

  // Raptor Boost - fist flare burst
  if (extraType?.id === 'raptor_boost') {
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
            const smoke1 = L('hit_smoke_c1', color1)
            const smoke2 = L('hit_smoke_c2', color2)
            const hdot1 = L('hit_dots_c1', color1)
            const hdot2 = L('hit_dots_c2', color2)
            const mat = L('hit_mat_c1', color1)
            return (<>
              {/* fist flare (whiff) */}
              <circle cx="20" cy="22" r="13" fill={color2Hex} opacity="0.4" />
              <circle cx="20" cy="22" r="6.5" fill={color1Hex} />
              <circle cx="20" cy="22" r="3" fill="#FFFFFF" opacity="0.7" />
              {/* on-hit burst */}
              <circle cx="60" cy="22" r="15" fill={mat} opacity="0.3" />
              <circle cx="54" cy="19" r="7" fill={smoke1} opacity="0.55" />
              <circle cx="63" cy="24" r="6.5" fill={smoke2} opacity="0.5" />
              <path d="M60 30 C57 24 58 20 60 15 C62 20 63 24 60 30 Z" fill="#FF8000" opacity="0.5" />
              {[[52, 15], [66, 16], [56, 30], [64, 31]].map(([x, y], i) => (
                <rect key={i} x={x} y={y} width="2.6" height="2.6" rx="0.8"
                  fill={i % 2 ? hdot2 : hdot1} opacity="0.9" />
              ))}
            </>)
          })()}
        </svg>
      </div>
    )
  }

  // Wizard's Foot - dark low foot-fire streak trailing behind the dash
  if (extraType?.id === 'wizards_foot') {
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
          <path d="M8 34 Q42 30 76 34 L82 36 L76 38 Q42 41 8 38 Z"
            fill={color2Hex} opacity="0.5" />
          <circle cx="18" cy="35" r="5" fill={color2Hex} opacity="0.45" />
          <circle cx="33" cy="34" r="6" fill={color1Hex} opacity="0.5" />
          <path d="M38 35 Q58 30 78 33 L82 35 L78 37 Q58 36 38 37 Z"
            fill={color1Hex} opacity="0.85" />
          <ellipse cx="78" cy="35" rx="7" ry="3.5" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Gerudo Dragon - flame aura engulfing the grabbed victim on connect
  // (scripts 12/14/15/16).
  if (extraType?.id === 'gerudo_dragon') {
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
          <ellipse cx="50" cy="22" rx="34" ry="18" fill={color2Hex} opacity="0.3" />
          {[-18, -6, 6, 18].map((dy, i) => (
            <path key={i} d={`M34 ${22 + dy * 0.6} Q50 ${13 + dy} 66 ${22 + dy * 0.6}`}
              fill="none" stroke={color1Hex} strokeWidth="4" strokeLinecap="round" opacity="0.55" />
          ))}
          <circle cx="50" cy="22" r="12" fill={color1Hex} opacity="0.85" />
          <circle cx="50" cy="22" r="5" fill="#FFFFFF" opacity="0.6" />
        </svg>
      </div>
    )
  }

  return null
}
