import './HexagonLoader.css'

const HEXAGON_POINTS = '50,2 91.7,26 91.7,74 50,98 8.3,74 8.3,26'
const HEXAGON_CIRCUMFERENCE = 288
const DEFAULT_SEGMENT_LENGTH = HEXAGON_CIRCUMFERENCE * 0.3

const clamp = (value, min, max) => Math.min(Math.max(value, min), max)

export default function HexagonLoader({
  size = 96,
  className = '',
  label = 'Loading',
  decorative = false,
  progress = null,
  centerLabel = null,
  minimumVisibleProgress = 0
}) {
  const classes = ['hexagon-loader', className].filter(Boolean).join(' ')
  const hasProgress = Number.isFinite(progress)
  const safeProgress = hasProgress ? clamp(progress, 0, 100) : null
  const safeMinimumVisibleProgress = hasProgress ? clamp(minimumVisibleProgress, 0, 100) : 0

  let segmentLength = DEFAULT_SEGMENT_LENGTH
  let gapLength = HEXAGON_CIRCUMFERENCE - DEFAULT_SEGMENT_LENGTH
  let animationName

  if (hasProgress) {
    const visibleProgress = safeProgress >= 100
      ? 100
      : Math.max(safeProgress, safeMinimumVisibleProgress)

    if (visibleProgress <= 0) {
      segmentLength = 0
      gapLength = HEXAGON_CIRCUMFERENCE
      animationName = 'none'
    } else if (safeProgress >= 100) {
      segmentLength = HEXAGON_CIRCUMFERENCE
      gapLength = 0
      animationName = 'none'
    } else {
      segmentLength = (HEXAGON_CIRCUMFERENCE * visibleProgress) / 100
      gapLength = HEXAGON_CIRCUMFERENCE - segmentLength
    }
  }

  const accessibilityLabel = decorative
    ? undefined
    : hasProgress
      ? `${label} ${Math.round(safeProgress)}%`
      : label

  const glowStyle = {
    strokeDasharray: `${segmentLength} ${gapLength}`,
    ...(animationName ? { animationName } : {})
  }

  return (
    <div
      className={classes}
      style={{ '--hexagon-loader-size': `${size}px` }}
      role={decorative ? undefined : hasProgress ? 'progressbar' : 'img'}
      aria-label={accessibilityLabel}
      aria-hidden={decorative || undefined}
      aria-valuemin={hasProgress && !decorative ? 0 : undefined}
      aria-valuemax={hasProgress && !decorative ? 100 : undefined}
      aria-valuenow={hasProgress && !decorative ? Math.round(safeProgress) : undefined}
    >
      <svg viewBox="-4 -4 108 108" focusable="false">
        <polygon className="hexagon-loader-track" points={HEXAGON_POINTS} />
        <polygon className="hexagon-loader-glow" points={HEXAGON_POINTS} style={glowStyle} />
      </svg>
      {centerLabel !== null && centerLabel !== undefined && (
        <div className="hexagon-loader-center">{centerLabel}</div>
      )}
    </div>
  )
}
