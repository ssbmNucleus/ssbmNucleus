import { useState } from 'react'
import { textureKey } from './paintProtocol'
import { sectionTextures } from './textureSections'

// List positions select UI rows; stable member IDs own edits.
// `textureModels` ({ memberId or '': rows }, see textureSections) splits each
// group into Model / Low-poly model / Animated; when it is missing or does not
// line up with the viewer's list, the group stays one list.
export default function TextureStrip({ modelTextures, selectedTextureIndex,
  onSelectTexture, editedTextures, textureModels = null, disabled = false }) {
  const [query, setQuery] = useState('')
  const paired = modelTextures.some(texture => texture.memberId)
  const groups = paired ? [{ id: 'popo', label: 'Popo' }, { id: 'nana', label: 'Nana' }]
    : [{ id: undefined, label: 'Textures' }]
  const wanted = query.toLowerCase().trim()
  const matches = ({ texture: tex }) => `${tex.name || ""} ${tex.index} ${tex.width}x${tex.height}`.toLowerCase().includes(wanted)

  const item = (group, { texture: tex, position: idx, model }) => {
    const key = textureKey(tex)
    const edited = editedTextures[key]
    const src = edited || (tex.thumbnail ? `data:image/png;base64,${tex.thumbnail}` : null)
    const note = model === 'both' ? ' · also low-poly' : model === 'low' ? ' · low-poly' : ''
    return (
      <button type="button" key={key}
        className={`skin-creator-texture-item ${selectedTextureIndex === idx ? 'selected' : ''} ${edited ? 'edited' : ''}`}
        aria-label={`${group.label} ${tex.name || `texture ${tex.index}`}${note}`}
        title={`${tex.name || `Texture ${tex.index}`} · ${tex.width} × ${tex.height}${note}${edited ? " · Edited" : ""}`}
        aria-pressed={selectedTextureIndex === idx}
        onClick={() => onSelectTexture(idx)} disabled={disabled}>
        <div className="texture-thumbnail">
          {src && <img src={src} alt={tex.name || `Texture ${tex.index}`}
            style={{ aspectRatio: `${tex.width} / ${tex.height}` }} />}
        </div>
        <div className="texture-info">
          <span className="texture-name">{tex.name || `Texture ${tex.index}`}{edited && ' *'}</span>
          <span className="texture-size">{tex.width}x{tex.height}</span>
          {model === 'both' && <span className="texture-also">also low-poly</span>}
        </div>
      </button>
    )
  }

  return (
    <div className="skin-creator-texture-strip" inert={disabled}>
      <div className="skin-creator-panel-header"><span>Textures <span className="texture-count">{modelTextures.length}</span></span>
        <input className="texture-search" type="search" aria-label="Filter textures" placeholder="Find a texture…" value={query} onChange={event => setQuery(event.target.value)} />
      </div>
      <div className={`skin-creator-texture-groups${paired ? ' paired' : ''}`}>
        {groups.map(group => {
          const entries = modelTextures.map((texture, position) => ({ texture, position }))
            .filter(({ texture }) => texture.memberId === group.id)
          const sections = sectionTextures(entries, textureModels?.[group.id ?? ''])
          return (
            <section key={group.id || 'single'} className="skin-creator-texture-group" aria-label={`${group.label} textures`}>
              {paired && <h3>{group.label}</h3>}
              {sections ? (
                <div className="skin-creator-texture-sections">
                  {sections.map(section => {
                    const shown = section.entries.filter(matches)
                    if (!shown.length) return null
                    return (
                      <section key={section.id} className={`skin-creator-texture-section texture-section-${section.id}`}
                        aria-label={`${paired ? `${group.label} ` : ''}${section.label} textures`}>
                        <h4 className="texture-section-header">{section.label} <span className="texture-count">{shown.length}</span></h4>
                        <div className="skin-creator-texture-list">{shown.map(entry => item(group, entry))}</div>
                      </section>
                    )
                  })}
                </div>
              ) : (
                <div className="skin-creator-texture-list">
                  {!modelTextures.length && <div className="texture-loading">Loading textures...</div>}
                  {entries.filter(matches).map(entry => item(group, entry))}
                </div>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}
