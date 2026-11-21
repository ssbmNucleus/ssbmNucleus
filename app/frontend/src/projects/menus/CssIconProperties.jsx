function NumberField({ label, value, mixed, onChange, step = 0.1, min, max }) {
  return (
    <div className="sss-prop-row">
      <label>{label}</label>
      <input
        type="number"
        value={mixed ? '' : (value ?? 0)}
        placeholder={mixed ? 'mixed' : undefined}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
      />
    </div>
  )
}

function getShared(icons, field) {
  if (icons.length === 0) return { value: undefined, mixed: false }
  const first = icons[0][field]
  const allSame = icons.every(i => i[field] === first)
  return { value: first, mixed: !allSame }
}

export default function CssIconProperties({
  icons = [], indices = [], fighters = [], onUpdate,
  lload
}) {
  if (icons.length === 0) {
    return (
      <div className="sss-props-panel">
        <p style={{ color: 'var(--color-text-muted)', textAlign: 'center', padding: '1rem' }}>
          Select an icon to edit properties
        </p>
      </div>
    )
  }

  const multi = icons.length > 1
  const icon = icons[0]

  const update = (field, value) => onUpdate(indices, { [field]: value })

  // Single select: full properties
  if (!multi) {
    // L alternates have no icon of their own, so they can't be picked here
    const altIds = new Set(lload?.altExternalIds || [])
    return (
      <div className="sss-props-panel">
        <h4 style={{ margin: '0 0 0.5rem', color: 'var(--color-text)' }}>
          Icon {indices[0]} {icon.fighterName ? `- ${icon.fighterName}` : ''}
        </h4>

        <div className="sss-prop-row">
          <label>Fighter</label>
          <select value={icon.fighter} onChange={(e) => update('fighter', parseInt(e.target.value))}>
            {fighters.filter(f => !altIds.has(f.externalId) || f.externalId === icon.fighter).map(f => (
              <option key={f.externalId} value={f.externalId}>{f.name}</option>
            ))}
          </select>
        </div>

        <NumberField label="SFX ID" value={icon.sfxID} onChange={(v) => update('sfxID', v)} step={1} min={0} />

        <div className="sss-prop-section">Position</div>
        <NumberField label="X" value={icon.x} onChange={(v) => update('x', v)} />
        <NumberField label="Y" value={icon.y} onChange={(v) => update('y', v)} />
        <NumberField label="Z" value={icon.z} onChange={(v) => update('z', v)} />

        <div className="sss-prop-section">Scale</div>
        <NumberField label="Scale X" value={icon.scaleX} onChange={(v) => update('scaleX', v)} step={0.05} />
        <NumberField label="Scale Y" value={icon.scaleY} onChange={(v) => update('scaleY', v)} step={0.05} />

        <div className="sss-prop-section">Collision</div>
        <NumberField label="Size X" value={icon.collisionSizeX} onChange={(v) => update('collisionSizeX', v)} />
        <NumberField label="Size Y" value={icon.collisionSizeY} onChange={(v) => update('collisionSizeY', v)} />
        <NumberField label="Offset X" value={icon.collisionOffsetX} onChange={(v) => update('collisionOffsetX', v)} />
        <NumberField label="Offset Y" value={icon.collisionOffsetY} onChange={(v) => update('collisionOffsetY', v)} />
      </div>
    )
  }

  // Multi select: bulk fields
  const scaleX = getShared(icons, 'scaleX')
  const scaleY = getShared(icons, 'scaleY')
  const colSX = getShared(icons, 'collisionSizeX')
  const colSY = getShared(icons, 'collisionSizeY')
  const colOX = getShared(icons, 'collisionOffsetX')
  const colOY = getShared(icons, 'collisionOffsetY')

  return (
    <div className="sss-props-panel">
      <h4 style={{ margin: '0 0 0.5rem', color: 'var(--color-text)' }}>
        {icons.length} icons selected
      </h4>

      <div className="sss-prop-section">Scale</div>
      <NumberField label="Scale X" {...scaleX} onChange={(v) => update('scaleX', v)} step={0.05} />
      <NumberField label="Scale Y" {...scaleY} onChange={(v) => update('scaleY', v)} step={0.05} />

      <div className="sss-prop-section">Collision</div>
      <NumberField label="Size X" {...colSX} onChange={(v) => update('collisionSizeX', v)} />
      <NumberField label="Size Y" {...colSY} onChange={(v) => update('collisionSizeY', v)} />
      <NumberField label="Offset X" {...colOX} onChange={(v) => update('collisionOffsetX', v)} />
      <NumberField label="Offset Y" {...colOY} onChange={(v) => update('collisionOffsetY', v)} />
    </div>
  )
}
