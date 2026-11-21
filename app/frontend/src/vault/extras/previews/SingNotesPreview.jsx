/**
 * SingNotesPreview - Jigglypuff up-B Sing, three independently-colored
 * musical notes (red/blue/green, each its own core+glow pair -- NOT a
 * shared color1/color2, so this reads all 6 modification keys directly).
 */
export function SingNotesPreview({ modifications, compact = false }) {
  const get = (key, fallback) => `#${modifications?.[key]?.color || fallback}`
  const redCore = get('note_red_core', 'FFFFFF')
  const redGlow = get('note_red_glow', 'FF0000')
  const blueCore = get('note_blue_core', 'FFFFFF')
  const blueGlow = get('note_blue_glow', '0000FF')
  const greenCore = get('note_green_core', 'FFFFFF')
  const greenGlow = get('note_green_glow', '00FF00')

  const height = compact ? 40 : 50

  const Note = ({ cx, cy, core, glow }) => (
    <g transform={`translate(${cx} ${cy})`}>
      <circle r="10" fill={glow} opacity="0.35" />
      <ellipse cx="-2" cy="5" rx="5" ry="3.8" fill={core} transform="rotate(-15 -2 5)" />
      <rect x="2.5" y="-8" width="1.8" height="14" fill={core} />
      <path d="M4.3 -8 Q11 -6.5 9 -1 Q7.5 -5 4.3 -4 Z" fill={core} />
    </g>
  )

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
        <Note cx={25} cy={16} core={blueCore} glow={blueGlow} />
        <Note cx={75} cy={17} core={greenCore} glow={greenGlow} />
        <Note cx={50} cy={33} core={redCore} glow={redGlow} />
      </svg>
    </div>
  )
}
