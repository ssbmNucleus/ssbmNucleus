/**
 * CssLloadBadges - the small "L" badge on every L-load base icon in the CSS
 * layout editor (tap L on the select screen to scroll through its group).
 *
 * SssCanvas has no per-icon decorations, so this is an overlay laid on top of
 * the canvas with the canvas's own game->screen math (transformRect). It
 * ignores the pointer, so selection and drags go straight to the canvas.
 */

// Shared with the icon list so both badges look the same
export const L_BADGE_STYLE = {
  display: 'inline-block',
  padding: '0 3px',
  fontFamily: 'var(--font-display)',
  fontSize: '9px',
  fontWeight: 700,
  lineHeight: '12px',
  color: 'var(--color-cyan)',
  background: 'rgba(0, 0, 0, 0.6)',
  borderRadius: '3px'
}

export default function CssLloadBadges({ icons, baseIds, zoom, offset, iconBaseWidth, iconBaseHeight }) {
  if (baseIds.size === 0) return null
  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden' }}>
      {icons.map((icon, idx) => {
        if (icon.status === 0 || !baseIds.has(icon.fighter)) return null
        // Top-right corner of the drawn icon, relative to the canvas center
        const right = icon.x * zoom + offset.x + iconBaseWidth * icon.scaleX * zoom
        const top = offset.y - icon.y * zoom - iconBaseHeight * icon.scaleY * zoom
        return (
          <span key={idx} style={{
            ...L_BADGE_STYLE,
            position: 'absolute',
            left: `calc(50% + ${right}px)`,
            top: `calc(50% + ${top}px)`,
            transform: 'translate(calc(-100% - 2px), 2px)'
          }}>L</span>
        )
      })}
    </div>
  )
}
