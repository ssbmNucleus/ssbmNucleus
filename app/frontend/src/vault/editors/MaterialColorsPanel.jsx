import { useEffect, useState } from 'react'

function MaterialField({ field, material, controls }) {
  const [value, setValue] = useState(field.value)
  useEffect(() => setValue(field.value), [field.value, material.id])
  const color = field.kind === 'color'
  return <form className="material-color-field" onSubmit={event => { event.preventDefault(); controls.set(material.id, field.key, color ? value : Number(value)) }}>
    <label>{field.label}</label>
    <div>
      {color ? <>
        <input type="color" aria-label={field.label} value={value.slice(0, 7)} onChange={event => setValue(event.target.value + value.slice(7))} />
        <input className="material-hex" aria-label={`${field.label} RGBA`} value={value} pattern="#[0-9a-fA-F]{8}" maxLength={9} onChange={event => setValue(event.target.value)} required />
      </> : <input type="number" aria-label={field.label} value={value} min="0" max={field.key === 'alpha' ? 1 : 128} step={field.key === 'alpha' ? 0.01 : 1} onChange={event => setValue(event.target.value)} required />}
      <button type="submit" disabled={controls.busy || String(value) === String(field.value)}>Apply</button>
      <button type="button" disabled={controls.busy} onClick={() => controls.reset(material.id, field.key)} aria-label={`Reset ${field.label}`}>Reset</button>
    </div>
  </form>
}

export default function MaterialColorsPanel({ controls }) {
  const [selected, setSelected] = useState('')
  const material = controls.materials.find(item => item.id === selected) || controls.materials[0]
  return <div className="material-colors-panel">
    <div className="material-colors-heading"><span>Materials</span><button type="button" onClick={controls.load} disabled={controls.busy}>Refresh</button></div>
    {controls.error && <p role="alert" className="skin-creator-error">{controls.error}</p>}
    {controls.busy && <span role="status">Updating…</span>}
    {material ? <>
      <select aria-label="Material" value={material.id} onChange={event => setSelected(event.target.value)} disabled={controls.busy}>
        {controls.materials.map(item => <option key={item.id} value={item.id}>{item.name}{item.animated ? ' · Animated' : ''}</option>)}
      </select>
      <label className="material-base-preview"><input type="checkbox" checked={controls.baseColors} onChange={event => controls.preview(event.target.checked)} disabled={controls.busy} />Preview base colors</label>
      {material.animated && <p>Animation may override these base colors. Preview base colors temporarily hides color animation; saved animations stay intact.</p>}
      {material.shared > 1 && <p>Shared by {material.shared} meshes.</p>}
      {material.fields.map(field => <MaterialField key={`${material.id}:${field.key}`} field={field} material={material} controls={controls} />)}
      <p>Material and lighting settings determine which colors affect the model.</p>
    </> : !controls.busy && <p>No editable materials loaded.</p>}
  </div>
}
