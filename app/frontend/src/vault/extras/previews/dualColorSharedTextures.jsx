/**
 * Dual-color card previews, part of DualColorPreview's dispatch:
 * Texture recolors and shared common effects (charge ball, coins, common fire/flash/electric, sparks, Fox charge flames).
 * Returns the preview for a matching extraType id, else null.
 */
export function renderSharedTexturePreview({ extraType, compact, color1, color2, color1Hex, color2Hex, L, height }) {
  // Charge Ball (Samus neutral-B fired projectile) - texture_recolor,
  // single-color: the whole texture (glow + ring + core) recolors together
  if (extraType?.id === 'charge_ball') {
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
          <circle cx="40" cy="22" r="16" fill={color1Hex} opacity="0.3" />
          <circle cx="40" cy="22" r="11" fill={color1Hex} opacity="0.7" />
          <circle cx="40" cy="22" r="5" fill="#FFFFFF" opacity="0.9" />
        </svg>
      </div>
    )
  }

  // Mario/Doc Coins (EfMrData shared texture_recolor) - up-B coin sprite,
  // single-color: recolors the whole coin texture's palette (Mario + Dr.
  // Mario both draw from the same EfMrData tex-bank group)
  if (extraType?.id === 'mario_coins') {
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
          <ellipse cx="40" cy="22" rx="10" ry="15" fill={color1Hex} opacity="0.9" />
          <ellipse cx="40" cy="22" rx="5.5" ry="15" fill={color1Hex} opacity="0.55" />
          <ellipse cx="40" cy="22" rx="10" ry="15" fill="none" stroke={color1Hex} strokeWidth="1.2" opacity="0.7" />
        </svg>
      </div>
    )
  }

  // Common Fire (EfCoData shared texture_recolor) - orange flame puff,
  // single-color: recolors the whole shared CI8 fire-cloud texture (Din's
  // Fire, Bowser Bomb, Charizard breath, Roy's fire all draw from it)
  if (extraType?.id === 'common_fire') {
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
          <path d="M40 8 C32 16 28 22 30 28 C31 33 35 37 40 37 C45 37 49 33 50 28 C52 22 48 16 40 8 Z"
            fill={color1Hex} opacity="0.85" />
          <path d="M40 18 C36 22 34 26 35 30 C36 33 38 35 40 35 C42 35 44 33 45 30 C46 26 44 22 40 18 Z"
            fill={color1Hex} opacity="0.5" />
        </svg>
      </div>
    )
  }

  // Charge flames: broad puffs and thin wisps, each with two blended colors.
  // Schematic only; rings and charge lines belong to the existing Up-B extra.
  if (extraType?.id === 'charge_flames') {
    const puffs = 'M43 28 C33 21 40 10 49 13 C47 3 64 3 66 13 C78 7 86 23 76 29 C85 40 69 49 62 39 C54 49 37 39 43 28Z'
    const wisps = 'M29 48 C17 36 36 32 28 21 C46 32 23 38 35 48Z M89 42 C77 30 98 25 88 13 C109 25 85 32 96 43Z'
    return <div style={{ height: `${height}px`, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0d0d18', borderRadius: '4px' }}>
      <svg width={compact ? 80 : 100} height={compact ? 40 : 50} viewBox="0 0 120 60" aria-label="Charge flames schematic">
        <path d={puffs} fill={L('flame_c1', 'FEF3A0')} />
        <path d={puffs} fill={L('flame_c2', 'FC885A')} opacity=".5" />
        <path d={wisps} fill={L('wisp_c1', 'FEF6B9')} />
        <path d={wisps} fill={L('wisp_c2', 'FD9A73')} opacity=".5" />
        <ellipse cx="60" cy="55" rx="21" ry="2" fill="#536171" />
      </svg>
    </div>
  }

  // Flight Fire Texture (legacy id upb_charge_fire): EfFx texture group 3,
  // used by the flight puff scripts 5/9. The Up-B trail controls also tint
  // these puffs. This schematic shows their texture color, not charge flames.
  if (extraType?.id === 'upb_charge_fire') {
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
          <circle cx="40" cy="24" r="9" fill={color1Hex} opacity="0.85" />
          <circle cx="30" cy="20" r="6" fill={color1Hex} opacity="0.7" />
          <circle cx="50" cy="21" r="6" fill={color1Hex} opacity="0.7" />
          <circle cx="35" cy="30" r="5" fill={color1Hex} opacity="0.6" />
          <circle cx="47" cy="30" r="5" fill={color1Hex} opacity="0.6" />
          <circle cx="40" cy="24" r="4" fill="#FFFFFF" opacity="0.55" />
        </svg>
      </div>
    )
  }

  // Bowser Fire Breath Texture (EfKpData texture_recolor) - the 9-frame CI8
  // flame-body billboard, single-color: most visible as the fire lingering
  // where the breath lands. Ground-flame patch to read as "landed fire" vs
  // bowser_fire_breath's horizontal cone.
  if (extraType?.id === 'breath_texture') {
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
          <line x1="12" y1="38" x2="68" y2="38" stroke={color1Hex} strokeWidth="2" opacity="0.35" />
          <path d="M28 38 C24 30 27 24 30 19 C31 25 33 27 34 24 C37 28 36 34 33 38 Z"
            fill={color1Hex} opacity="0.85" />
          <path d="M44 38 C39 28 43 20 47 13 C48 21 51 24 52 20 C56 26 54 34 50 38 Z"
            fill={color1Hex} opacity="0.9" />
          <path d="M58 38 C56 33 57 29 59 26 C60 30 62 31 62 29 C64 32 63 36 61 38 Z"
            fill={color1Hex} opacity="0.7" />
        </svg>
      </div>
    )
  }

  // Common Flash (EfCoData shared texture_recolor) - purple electric
  // star-burst, single-color: recolors the whole shared CI8 flash texture
  // (Vanish, Transform, Pikachu/Pichu thunder + Quick Attack burst)
  if (extraType?.id === 'common_flash') {
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
          {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => (
            <rect key={deg} x="39" y="4" width="2" height="18" rx="1"
              fill={color1Hex} opacity="0.8"
              transform={`rotate(${deg} 40 22)`} />
          ))}
          <circle cx="40" cy="22" r="6" fill={color1Hex} opacity="0.9" />
          <circle cx="40" cy="22" r="3" fill="#FFFFFF" opacity="0.9" />
        </svg>
      </div>
    )
  }

  // Common Electric (EfCoData cast-wide on-hit spark pool) - radial burst +
  // jagged arc, the hitlag electric spark that flashes on EVERY character
  // when they take a hit (research/docs-research/effect-maps/efcodata.md §6b)
  if (extraType?.id === 'common_electric') {
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
          <circle cx="40" cy="22" r="14" fill={color2Hex} opacity="0.3" />
          {[0, 60, 120, 180, 240, 300].map((deg) => (
            <rect key={deg} x="39" y="8" width="2" height="14" rx="1"
              fill={color1Hex} opacity="0.85"
              transform={`rotate(${deg} 40 22)`} />
          ))}
          <path d="M37 12 L43 20 L38 20 L44 32 L34 22 L39 22 Z" fill={color1Hex} />
        </svg>
      </div>
    )
  }

  // Thunder Jolt Cheek Spark (EfCoData s95) - small caster-side sparkle
  // cluster, subtle by design (honest about not being the marquee jolt bolt)
  if (extraType?.id === 'thunder_jolt_spark') {
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
          <circle cx="40" cy="22" r="9" fill={color2Hex} opacity="0.25" />
          {[{ x: 30, y: 14 }, { x: 50, y: 15 }, { x: 38, y: 30 }, { x: 46, y: 28 }].map((p, i) => (
            <path key={i} d={`M${p.x} ${p.y - 3} L${p.x + 1} ${p.y} L${p.x} ${p.y + 3} L${p.x - 1} ${p.y} Z`}
              fill={color1Hex} opacity="0.9" />
          ))}
          <circle cx="40" cy="22" r="3.5" fill={color1Hex} opacity="0.6" />
        </svg>
      </div>
    )
  }

  // Rapid Jab Finisher Spark (EfCoData s11/s15/s91) - the connect flash of a
  // rapid jab's finishing hit: leading diamond (s11/c1) inside an electric
  // burst body + cyan flash halo (s15/s91/c2). Per-layer bound via L(...).
  if (extraType?.id === 'jab_finisher_spark') {
    const lead = L('finisher_lead_c1', color1)
    const burst = L('finisher_burst_a_c2', color2)
    const flash = L('finisher_flash_c2', color2)
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
          <circle cx="40" cy="22" r="16" fill={flash} opacity="0.28" />
          {[20, 70, 130, 200, 250, 310].map((deg) => (
            <rect key={deg} x="39" y="6" width="1.8" height="16" rx="0.9"
              fill={burst} opacity="0.8"
              transform={`rotate(${deg} 40 22)`} />
          ))}
          <path d="M40 10 L48 22 L40 34 L32 22 Z" fill={lead} />
          <path d="M40 15 L45 22 L40 29 L35 22 Z" fill={flash} opacity="0.55" />
        </svg>
      </div>
    )
  }

  return null
}
