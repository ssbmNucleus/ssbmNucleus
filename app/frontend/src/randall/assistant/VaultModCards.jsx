import { useContext, useState } from 'react'
import { EditorContext } from '../../shared/lib/EditorContext'
import { backendMediaUrl } from '../../shared/config/config'
import { SafetyLabel } from './TaskCards'

const keyOf = item => `${item.character}:${item.id}`

function VaultItem({ item, selected, onOpen }) {
  const editor = useContext(EditorContext)
  const [failed, setFailed] = useState(false)
  const variant = item.variant || item.color
  const label = [item.name, variant !== item.name ? variant : null].filter(Boolean).join(' · ')
  return <article className={`assistant-vault-card ${selected ? 'is-selected' : ''}`}>
    <button className="assistant-vault-open" disabled={item.unavailable} onClick={() => onOpen(item.character, item.id)} aria-label={`Open ${label} in vault`}>
      {item.image && !failed ? <img src={backendMediaUrl(item.image)} alt="" onError={() => setFailed(true)} loading="lazy" />
        : <span className="assistant-vault-no-image">No portrait</span>}
      <span><strong>{item.name}</strong><small>{item.character}{variant && variant !== item.name ? ` · ${variant}` : ''}</small>
        {/* One badge said "Slippi safe" whether the app had checked the costume
            or somebody had typed the label in by hand. Those are different
            claims and they now read differently. */}
        <SafetyLabel item={item} compact />
        {item.unavailable && <small>No longer in vault</small>}</span>
    </button>
    {editor?.openEditor && <button type="button" className="assistant-vault-edit" disabled={item.unavailable}
      aria-label={`Edit ${label} in Texture Lab`} onClick={() => editor.openEditor(item)}>Edit</button>}
  </article>
}

export default function VaultModCards({ items, selection, onOpen }) {
  return <div className="assistant-vault-cards">{items.map(item => <VaultItem key={`${keyOf(item)}:${item.image || ''}`}
    item={item} selected={selection.some(s => keyOf(s) === keyOf(item))} onOpen={onOpen} />)}</div>
}
