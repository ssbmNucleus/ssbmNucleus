import { SSS_STATUS_LOCKED, SSS_STATUS_UNLOCKED, stageSlotUpdates } from './sssSlots.js'

const STATUS_OPTIONS = [
  { value: 0, label: 'Hidden' },
  { value: 1, label: 'Locked' },
  { value: 2, label: 'Unlocked' },
  { value: 3, label: 'Random' },
  { value: 4, label: 'Decoration' }
]

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

export default function SssIconProperties({ icons = [], indices = [], stages = [], pages = [], onUpdate }) {
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

  const update = (field, value) => {
    onUpdate(indices, { [field]: value })
  }

  // Single select: full properties
  if (!multi) {
    const isDecoration = icon.status === 4
    const isUnlocked = icon.status === SSS_STATUS_UNLOCKED
    // A Locked slot ("?", what a new page is made of) takes a stage straight
    // from the picker; picking one unlocks it.
    const isEmptySlot = icon.status === SSS_STATUS_LOCKED

    const pickStage = (externalId) => {
      const stage = stages.find(s => s.externalId === externalId)
      if (stage) onUpdate(indices, stageSlotUpdates(stage, pages))
    }

    return (
      <div className="sss-props-panel">
        <h4 style={{ margin: '0 0 0.5rem', color: 'var(--color-text)' }}>
          Icon {indices[0]} {icon.stageName ? `- ${icon.stageName}` : ''}
        </h4>

        <div className="sss-prop-row">
          <label>Status</label>
          <select value={icon.status} onChange={(e) => update('status', parseInt(e.target.value))}>
            {STATUS_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>

        {(isUnlocked || isEmptySlot) && (
          <div className="sss-prop-row">
            <label>Stage</label>
            <select value={isUnlocked ? icon.stageID : ''} onChange={(e) => pickStage(parseInt(e.target.value))}>
              {isEmptySlot && <option value="" disabled>Pick a stage</option>}
              {stages.map(s => (
                <option key={s.externalId} value={s.externalId}>{s.name}</option>
              ))}
            </select>
          </div>
        )}

        {!isDecoration && (
          <div className="sss-prop-row">
            <label>Group</label>
            <select value={icon.group} onChange={(e) => update('group', parseInt(e.target.value))}>
              <option value={0}>0</option>
              <option value={1}>1</option>
              <option value={2}>2</option>
            </select>
          </div>
        )}

        <div className="sss-prop-section">Position</div>
        <NumberField label="X" value={icon.x} onChange={(v) => update('x', v)} />
        <NumberField label="Y" value={icon.y} onChange={(v) => update('y', v)} />
        <NumberField label="Z" value={icon.z} onChange={(v) => update('z', v)} />

        <div className="sss-prop-section">Scale</div>
        <NumberField label="Scale X" value={icon.scaleX} onChange={(v) => update('scaleX', v)} step={0.05} />
        <NumberField label="Scale Y" value={icon.scaleY} onChange={(v) => update('scaleY', v)} step={0.05} />

        {!isDecoration && (
          <>
            <div className="sss-prop-section">Collision</div>
            <NumberField label="Width" value={icon.width} onChange={(v) => update('width', v)} />
            <NumberField label="Height" value={icon.height} onChange={(v) => update('height', v)} />
          </>
        )}

        {isUnlocked && (
          <>
            <div className="sss-prop-section">IDs</div>
            <NumberField label="Preview ID" value={icon.previewID} onChange={(v) => update('previewID', v)} step={1} min={0} max={255} />
            <NumberField label="Random ID" value={icon.randomSelectID} onChange={(v) => update('randomSelectID', v)} step={1} min={0} max={255} />
          </>
        )}
      </div>
    )
  }

  // Multi select: bulk-editable fields only
  const scaleX = getShared(icons, 'scaleX')
  const scaleY = getShared(icons, 'scaleY')
  const width = getShared(icons, 'width')
  const height = getShared(icons, 'height')
  const group = getShared(icons, 'group')
  const status = getShared(icons, 'status')

  return (
    <div className="sss-props-panel">
      <h4 style={{ margin: '0 0 0.5rem', color: 'var(--color-text)' }}>
        {icons.length} icons selected
      </h4>

      <div className="sss-prop-row">
        <label>Status</label>
        <select
          value={status.mixed ? '' : status.value}
          onChange={(e) => update('status', parseInt(e.target.value))}
        >
          {status.mixed && <option value="">mixed</option>}
          {STATUS_OPTIONS.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      <div className="sss-prop-row">
        <label>Group</label>
        <select
          value={group.mixed ? '' : group.value}
          onChange={(e) => update('group', parseInt(e.target.value))}
        >
          {group.mixed && <option value="">mixed</option>}
          <option value={0}>0</option>
          <option value={1}>1</option>
          <option value={2}>2</option>
        </select>
      </div>

      <div className="sss-prop-section">Scale</div>
      <NumberField label="Scale X" {...scaleX} onChange={(v) => update('scaleX', v)} step={0.05} />
      <NumberField label="Scale Y" {...scaleY} onChange={(v) => update('scaleY', v)} step={0.05} />

      <div className="sss-prop-section">Collision</div>
      <NumberField label="Width" {...width} onChange={(v) => update('width', v)} />
      <NumberField label="Height" {...height} onChange={(v) => update('height', v)} />
    </div>
  )
}
