/**
 * The area-selection box drawn over the paint canvas.
 *
 * The overlay lives INSIDE the canvas's zoom transform so the rect tracks its
 * texture pixels exactly (useCanvasScale pins and transforms it). That is also
 * what used to make it look wrong: a 1px dashed border was scaled with the
 * canvas, so painting at 16x drew 16px-thick dashes.
 *
 * Everything that should look constant is therefore sized in TEXTURE units as
 * `screen px / zoom`, which cancels the transform out. Note that SVG's
 * `vector-effect="non-scaling-stroke"` does NOT help here and was measured
 * doing nothing: it only compensates for transforms inside the SVG's own
 * coordinate system, not for a CSS transform on an ancestor element (Chrome
 * draws both a marked and an unmarked 1px stroke at 16 CSS px under scale(16)).
 */
import { selectionHandles } from './canvasUtils'

const HANDLE_SCREEN_PX = 7
const DASH_SCREEN_PX = 4

export default function SelectionOverlay({ selection, width, height, zoom }) {
  if (!selection || !width || !height) return null
  const { x, y, w, h } = selection
  const unit = 1 / Math.max(zoom || 1, 0.01)   // one screen pixel, in texture units
  const handle = HANDLE_SCREEN_PX * unit
  const dash = DASH_SCREEN_PX * unit
  const ants = {
    strokeWidth: unit,
    strokeDasharray: `${dash} ${dash}`,
    // the keyframe marches to this, so a full cycle is one dash pair
    '--ants-march': -2 * dash
  }

  return (
    <div className="paint-selection" aria-hidden="true">
      <svg className="paint-selection-svg" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <rect className="paint-selection-fill" x={x} y={y} width={w} height={h} />
        {/* dark strand offset half a dash under the bright one, so the ants stay
            readable whatever colour the texture is */}
        <rect className="paint-selection-ants paint-selection-ants--shadow" x={x} y={y} width={w} height={h}
          style={{ ...ants, strokeDashoffset: dash }} />
        <rect className="paint-selection-ants" x={x} y={y} width={w} height={h} style={ants} />
        {selectionHandles(selection).map(point => (
          <rect key={point.zone} className="paint-selection-handle"
            x={point.x - handle / 2} y={point.y - handle / 2} width={handle} height={handle}
            style={{ strokeWidth: unit }} />
        ))}
      </svg>
    </div>
  )
}
