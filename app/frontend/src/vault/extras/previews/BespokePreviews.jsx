import { rgbyToHex } from '../../lib/rgbyColor'
import { nestedTextureHex } from './textureTint'

// Card previews for the extras with bespoke editors: Fox/Falco laser, side-B,
// up-B, shine and laser ring, and the sword trail (Marth, Roy, Link, Young Link).

/**
 * LaserBeamPreview - Reusable laser visualization component
 * Renders layered beam effect matching actual in-game appearance
 */
export function LaserBeamPreview({ modifications, compact = false }) {
  // Get colors from modifications, handling both RGBY and RGB formats
  const getColor = (layerId) => {
    const mod = modifications?.[layerId]
    if (!mod?.color) return null
    // Center layer is RGB format, others are RGBY
    if (layerId === 'center') {
      return `#${mod.color}`
    }
    return rgbyToHex(mod.color)
  }

  const wide = getColor('wide') || '#ff0000'
  const thin = getColor('thin') || '#ff0000'
  const outline = getColor('outline') || '#ff0000'
  const center = getColor('center') || '#ffffff'

  const height = compact ? 40 : 50

  return (
    <div
      className="laser-beam-preview"
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
      {/* Wide glow */}
      <div
        style={{
          position: 'absolute',
          left: '8%',
          right: '8%',
          height: compact ? '24px' : '30px',
          borderRadius: '100px',
          background: `linear-gradient(90deg, transparent 0%, ${wide} 5%, ${wide} 95%, transparent 100%)`,
          boxShadow: `0 0 15px ${wide}50, 0 0 30px ${wide}30`,
          opacity: 0.5
        }}
      />
      {/* Thin layer */}
      <div
        style={{
          position: 'absolute',
          left: '8%',
          right: '8%',
          height: compact ? '14px' : '18px',
          borderRadius: '100px',
          background: `linear-gradient(90deg, transparent 0%, ${thin} 3%, ${thin} 97%, transparent 100%)`,
          boxShadow: `0 0 8px ${thin}70`,
          opacity: 0.7
        }}
      />
      {/* Outline */}
      <div
        style={{
          position: 'absolute',
          left: '8%',
          right: '8%',
          height: compact ? '8px' : '10px',
          borderRadius: '100px',
          background: `linear-gradient(90deg, transparent 0%, ${outline} 2%, ${outline} 98%, transparent 100%)`,
          boxShadow: `0 0 5px ${outline}90`,
          opacity: 0.9
        }}
      />
      {/* Center */}
      <div
        style={{
          position: 'absolute',
          left: '8%',
          right: '8%',
          height: '3px',
          borderRadius: '100px',
          background: `linear-gradient(90deg, transparent 0%, ${center} 2%, ${center} 98%, transparent 100%)`,
          boxShadow: `0 0 3px ${center}`
        }}
      />
    </div>
  )
}

/**
 * SideBPreview - Preview component for side-B afterimage colors
 * Shows the three RGBA colors as a gradient dash effect
 */
export function SideBPreview({ modifications, compact = false }) {
  // Get colors from modifications (RGBA format as hex string)
  const getColor = (layerId) => {
    const mod = modifications?.[layerId]
    if (!mod?.color) return null
    // RGBA format: first 6 chars are RGB
    const hex = mod.color.substring(0, 6)
    return `#${hex}`
  }

  const primary = getColor('primary') || '#0099FF'
  const secondary = getColor('secondary') || '#CCE6FF'
  const tertiary = getColor('tertiary') || '#FFFFFF'

  const height = compact ? 40 : 50

  return (
    <div
      className="sideb-preview"
      style={{
        position: 'relative',
        height: `${height}px`,
        minWidth: '100%',
        background: 'linear-gradient(180deg, #0a0a12 0%, #0d0d18 100%)',
        borderRadius: '4px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        padding: '0 8px'
      }}
    >
      {/* Afterimage trail - multiple fading copies */}
      {[0.15, 0.3, 0.5, 0.7].map((opacity, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: `${10 + i * 18}%`,
            width: compact ? '16px' : '20px',
            height: compact ? '24px' : '30px',
            borderRadius: '4px',
            background: `linear-gradient(135deg, ${primary} 0%, ${secondary} 50%, ${tertiary} 100%)`,
            opacity: opacity,
            boxShadow: `0 0 ${8 + i * 4}px ${primary}40`
          }}
        />
      ))}
      {/* Main character silhouette */}
      <div
        style={{
          position: 'absolute',
          right: '12%',
          width: compact ? '20px' : '24px',
          height: compact ? '28px' : '34px',
          borderRadius: '4px',
          background: `linear-gradient(135deg, ${primary} 0%, ${secondary} 50%, ${tertiary} 100%)`,
          boxShadow: `0 0 12px ${primary}60, 0 0 20px ${secondary}40`
        }}
      />
    </div>
  )
}

/**
 * UpBPreview - Preview component for up-B flame colors
 * Shows tip, body, trail, and rings colors
 */
export function UpBPreview({ modifications, compact = false }) {
  // Get colors from modifications
  const tipColor = modifications?.tip?.color ? rgbyToHex(modifications.tip.color) : '#FF6600'
  const bodyColor = modifications?.body?.color ? `#${modifications.body.color}` : '#FFFFFF'
  const trailColor = modifications?.trail?.color ? `#${modifications.trail.color}` : '#FFFFFF'
  const ringsColor = modifications?.rings?.color ? `#${modifications.rings.color}` : '#FFFF00'
  // Nested sibling texture extra (upb_texture, task #12 migration): the
  // dominant flight-fire texture color, tinting the outer flame glow.
  const fireColor = nestedTextureHex(modifications?.fire, tipColor)

  const height = compact ? 40 : 50

  return (
    <div
      className="upb-preview"
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
      {/* Fire ring */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '50px' : '60px',
          height: compact ? '16px' : '20px',
          bottom: compact ? '8px' : '10px',
          borderRadius: '50%',
          border: `2px solid ${ringsColor}`,
          boxShadow: `0 0 6px ${ringsColor}`,
          opacity: 0.6
        }}
      />
      {/* Body glow */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '24px' : '30px',
          height: compact ? '40px' : '50px',
          bottom: compact ? '5px' : '5px',
          background: `radial-gradient(ellipse at center, ${bodyColor}30 0%, transparent 70%)`,
          filter: `drop-shadow(0 0 8px ${bodyColor}40)`
        }}
      />
      {/* Trail particles */}
      {[0.3, 0.5].map((opacity, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            width: '6px',
            height: '6px',
            bottom: `${compact ? 20 : 25 + i * 10}px`,
            left: `${45 + (i % 2 ? 5 : -5)}%`,
            borderRadius: '50%',
            background: trailColor,
            opacity: opacity,
            boxShadow: `0 0 3px ${trailColor}`
          }}
        />
      ))}
      {/* Flight-fire texture glow (fire, behind the tip flame) */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '26px' : '32px',
          height: compact ? '32px' : '38px',
          bottom: '0',
          borderRadius: '50% 50% 50% 50% / 60% 60% 40% 40%',
          background: `radial-gradient(ellipse at center, ${fireColor}55 0%, transparent 75%)`,
          filter: `drop-shadow(0 0 6px ${fireColor}80)`
        }}
      />
      {/* Main flame */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '18px' : '22px',
          height: compact ? '28px' : '34px',
          bottom: compact ? '2px' : '0',
          borderRadius: '50% 50% 50% 50% / 60% 60% 40% 40%',
          background: `linear-gradient(to top, ${tipColor} 0%, ${tipColor}CC 40%, ${tipColor}66 70%, transparent 100%)`,
          filter: `drop-shadow(0 0 5px ${tipColor})`
        }}
      />
      {/* Inner core */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '8px' : '10px',
          height: compact ? '14px' : '18px',
          bottom: compact ? '4px' : '3px',
          borderRadius: '50% 50% 50% 50% / 60% 60% 40% 40%',
          background: `linear-gradient(to top, #FFFFFF 0%, ${tipColor} 60%, transparent 100%)`
        }}
      />
    </div>
  )
}

export function ShinePreview({ modifications, compact = false }) {
  // Get colors from modifications (new two-color gradient format)
  const primaryColor = modifications?.primary?.color ? rgbyToHex(modifications.primary.color) : '#0066FF'
  const secondaryColor = modifications?.secondary?.color ? rgbyToHex(modifications.secondary.color) : '#8888AA'
  const sparklesColor = modifications?.sparkles?.color ? `#${modifications.sparkles.color}` : '#FFFFFF'

  const size = compact ? 36 : 50

  return (
    <div
      className="shine-preview"
      style={{
        position: 'relative',
        height: `${size}px`,
        minWidth: '100%',
        background: 'linear-gradient(180deg, #0a0a12 0%, #0d0d18 100%)',
        borderRadius: '4px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden'
      }}
    >
      {/* Outer glow using primary */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '45px' : '60px',
          height: compact ? '45px' : '60px',
          background: `radial-gradient(ellipse at center, ${primaryColor}50 0%, transparent 70%)`,
          filter: `drop-shadow(0 0 10px ${primaryColor}60)`
        }}
      />
      {/* Fill glow using secondary */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '35px' : '45px',
          height: compact ? '35px' : '45px',
          background: `radial-gradient(ellipse at center, ${secondaryColor}80 0%, ${secondaryColor}40 40%, transparent 70%)`
        }}
      />
      {/* Hexagon with gradient from secondary (fill) to primary (edge) */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '26px' : '34px',
          height: compact ? '26px' : '34px',
          background: `radial-gradient(circle at center, ${secondaryColor} 30%, ${primaryColor} 100%)`,
          clipPath: 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)',
          opacity: 0.9,
          boxShadow: `0 0 8px ${primaryColor}`
        }}
      />
      {/* Edge highlight */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '28px' : '36px',
          height: compact ? '28px' : '36px',
          border: `2px solid ${primaryColor}`,
          clipPath: 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)',
          opacity: 0.7
        }}
      />
      {/* Sparkle particles around the shield */}
      {[
        { top: '10%', left: '15%' },
        { top: '20%', left: '80%' },
        { top: '70%', left: '85%' },
        { top: '80%', left: '20%' }
      ].map((pos, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            top: pos.top,
            left: pos.left,
            width: '3px',
            height: '3px',
            borderRadius: '50%',
            background: sparklesColor,
            boxShadow: `0 0 4px ${sparklesColor}`
          }}
        />
      ))}
    </div>
  )
}

export function LaserRingPreview({ modifications, compact = false }) {
  // Blaster-flash streak burst (audit 2026-07): color1 = the streak wall
  // around the fighter, color2 = subtle dim-area tint. The beam and the red
  // muzzle ring are separate effects this mod does not touch.
  const color1 = modifications?.color1?.color ? `#${modifications.color1.color}` : '#FF004C'
  const color2 = modifications?.color2?.color ? `#${modifications.color2.color}` : '#B20000'

  const size = compact ? 40 : 50

  return (
    <div
      className="laser-ring-preview"
      style={{
        position: 'relative',
        height: `${size}px`,
        minWidth: '100%',
        background: 'linear-gradient(180deg, #0a0a12 0%, #0d0d18 100%)',
        borderRadius: '4px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden'
      }}
    >
      {/* Dim-area tint - secondary color */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '52px' : '66px',
          height: compact ? '34px' : '44px',
          background: `radial-gradient(ellipse at center, ${color2}38 0%, transparent 70%)`,
          filter: `drop-shadow(0 0 8px ${color2}40)`
        }}
      />
      {/* Streak wall - primary color */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '34px' : '44px',
          height: compact ? '30px' : '40px',
          background: `repeating-linear-gradient(90deg, ${color1} 0px, ${color1} 1.5px, transparent 1.5px, transparent 6px)`,
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
          transform: 'skewX(-6deg)',
          filter: `drop-shadow(0 0 4px ${color1})`,
          opacity: 0.9
        }}
      />
      {/* Hot core streak - primary color */}
      <div
        style={{
          position: 'absolute',
          width: compact ? '26px' : '34px',
          height: '3px',
          borderRadius: '2px',
          background: `linear-gradient(90deg, transparent, ${color1}, white, ${color1}, transparent)`,
          boxShadow: `0 0 6px ${color1}`
        }}
      />
    </div>
  )
}

export function SwordPreview({ modifications, compact = false }) {
  // Two-color ribbon like the real renderer (decomp ft/ftafterimage.c):
  // inner-edge color -> outer-edge color across the band, alpha fading toward
  // the tail. Legacy mods (main/secondary/tertiary) map to the bytes they
  // actually wrote in-game.
  const m = modifications || {}
  const inner = m.inner?.color
    || (m.main?.color && m.secondary?.color
        ? (m.main.color.slice(4, 6) + m.secondary.color.slice(0, 4)) : null)
    || '00FFFF'
  const outer = m.outer?.color || m.tertiary?.color || 'FFFFFF'
  const uid = `sw-${inner}-${outer}${compact ? '-c' : ''}`

  const height = compact ? 40 : 50

  return (
    <div
      className="sword-preview"
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
      <svg width={compact ? 80 : 100} height={compact ? 35 : 45} viewBox="0 0 100 45" style={{ overflow: 'visible' }}>
        <defs>
          <linearGradient id={`${uid}-g`} x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stopColor={`#${inner}`} />
            <stop offset="100%" stopColor={`#${outer}`} />
          </linearGradient>
          <linearGradient id={`${uid}-f`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#fff" stopOpacity="0.05" />
            <stop offset="100%" stopColor="#fff" stopOpacity="1" />
          </linearGradient>
          <mask id={`${uid}-m`}>
            <rect x="-5" y="-15" width="115" height="70" fill={`url(#${uid}-f)`} />
          </mask>
        </defs>
        <path
          d="M 5 40 Q 50 -10 95 40 L 82 40 Q 50 8 18 40 Z"
          fill={`url(#${uid}-g)`}
          mask={`url(#${uid}-m)`}
        />
      </svg>
    </div>
  )
}
