import { renderFalconGanonPreview } from './dualColorFalconGanon'
import { renderKirbyClimbersZeldaPreview } from './dualColorKirbyClimbersZelda'
import { renderPokemonSamusLinkPreview } from './dualColorPokemonSamusLink'
import { renderSharedTexturePreview } from './dualColorSharedTextures'
import { renderMarioFamilyPreview } from './dualColorMarioFamily'
import { renderPikachuNessPreview } from './dualColorPikachuNess'

/**
 * DualColorPreview - Preview for 2-color effects (punch, fireball, thunder, shadow ball)
 * Renders based on the extraType to show appropriate visual
 */
export function DualColorPreview({ extraType, modifications, compact = false }) {
  // Get colors - handle both color1/color2 and tip_color1/tip_color2 formats
  const color1 = modifications?.color1?.color || modifications?.tip_color1?.color || 'FFFFFF'
  const color2 = modifications?.color2?.color || modifications?.tip_color2?.color || '0000FF'
  const color1Hex = `#${color1}`
  const color2Hex = `#${color2}`
  // Per-layer getter (mirrors EffectEditorPage's EffectPreview `L`): reads
  // the saved per-layer key, falling back to a summary color. Both Advanced
  // and Simple-mode saves populate these keys, so the card matches the modal.
  const L = (key, fallback) => `#${modifications?.[key]?.color || fallback || 'FFFFFF'}`

  const height = compact ? 40 : 50

  // Per-effect previews live in the dualColor* files, checked in this order;
  // each returns null for ids it does not draw.
  const context = { extraType, modifications, compact, color1, color2, color1Hex, color2Hex, L, height }
  const preview = renderFalconGanonPreview(context)
    || renderKirbyClimbersZeldaPreview(context)
    || renderPokemonSamusLinkPreview(context)
    || renderSharedTexturePreview(context)
    || renderMarioFamilyPreview(context)
    || renderPikachuNessPreview(context)
  if (preview) return preview

  // Default dual-color
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
        <circle cx="35" cy="22" r="14" fill={color1Hex} />
        <circle cx="65" cy="22" r="14" fill={color2Hex} />
      </svg>
    </div>
  )
}
