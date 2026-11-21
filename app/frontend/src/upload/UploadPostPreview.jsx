import { useMemo, useState } from 'react'
import { BACKEND_URL } from '../shared/config/config'
import './UploadPostPreview.css'

// ssbmnucleus.net PostPage.getColorForBadge — keep in sync with the site.
function getColorForBadge(colorName) {
  const colorMap = {
    'Default': '#e5e7eb', 'Red': '#dc2626', 'Blue': '#2563eb', 'Green': '#16a34a',
    'Yellow': '#eab308', 'Black': '#1f2937', 'White': '#f3f4f6', 'Pink': '#ec4899',
    'Orange': '#ea580c', 'Lavender': '#a855f7', 'Aqua/Light Blue': '#06b6d4', 'Grey': '#6b7280'
  }
  return colorMap[colorName] || '#1a2d4d'
}

// Very light markdown approximation for the description (the site renders
// real markdown; headings/bold/lists cover what mod posts actually use).
function renderDescription(text) {
  return String(text || '').split(/\n/).map((line, i) => {
    const h = /^(#{1,3})\s+(.*)$/.exec(line)
    if (h) {
      const Tag = `h${Math.min(4, h[1].length + 1)}`
      return <Tag key={i}>{h[2]}</Tag>
    }
    if (/^\s*[-*]\s+/.test(line)) {
      return <li key={i}>{line.replace(/^\s*[-*]\s+/, '')}</li>
    }
    if (!line.trim()) return <br key={i} />
    const parts = line.split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
      /^\*\*[^*]+\*\*$/.test(part) ? <strong key={j}>{part.slice(2, -2)}</strong> : part)
    return <p key={i}>{parts}</p>
  })
}

/**
 * Post-page-accurate preview for the Upload flow's Review step. Rendered
 * from the backend's dry-run (the REAL upload plan and website file rows),
 * so what you see is what the post page will show.
 */
export default function UploadPostPreview({ account, title, description, categoryTags, userTags, screenshots, dryRun, items }) {
  const [selectedShot, setSelectedShot] = useState(0)

  const itemByKey = useMemo(() => {
    const map = new Map()
    items.forEach(item => map.set(item.key, item))
    return map
  }, [items])

  const characterRows = (dryRun?.fileRows || []).filter(row => row.file_type === 'character_dat')
  const stageRows = (dryRun?.fileRows || []).filter(row => row.file_type === 'stage_dat')
  const planFiles = dryRun?.plan || []
  const shot = screenshots[selectedShot] || screenshots[0]

  const stockUrlFor = key => {
    const parts = String(key || '').split(':')
    if (parts[0] !== 'costume' || parts.length < 3) return null
    return `${BACKEND_URL}/storage/${encodeURIComponent(parts[1])}/${encodeURIComponent(parts[2])}_stc.png`
  }

  return (
    <div className="upload-postpreview">
      <div className="upload-postpreview-chrome">ssbmnucleus.net/post/… — preview</div>
      <div className="pp-layout">
        <div className="pp-info">
          <h1 className="pp-title">{title}</h1>
          <div className="pp-meta">
            <span className="pp-author">
              <span className="pp-avatar">
                {(account?.username || '?')[0].toUpperCase()}
                {account?.avatarUrl && <img src={account.avatarUrl} alt="" />}
              </span>
              By&nbsp;<span className="pp-author-link">{account?.username || 'you'}</span>
            </span>
            <span>{new Date().toLocaleDateString()}</span>
            <span>💾 0 downloads</span>
            <span className="pp-like">♡ 0</span>
          </div>

          <div className="pp-description">{renderDescription(description)}</div>

          {categoryTags.length > 0 && (
            <section className="pp-section">
              <h3>Category</h3>
              <div className="pp-tags">
                {categoryTags.map(tag => <span key={tag} className="pp-tag pp-tag--category">{tag}</span>)}
              </div>
            </section>
          )}
          {userTags.length > 0 && (
            <section className="pp-section">
              <h3>Tags</h3>
              <div className="pp-tags">
                {userTags.map(tag => <span key={tag} className="pp-tag">{tag}</span>)}
              </div>
            </section>
          )}

          {planFiles.length > 0 && (
            <section className="pp-section">
              <h3>Files Included</h3>
              <div className="pp-files">
                {planFiles.map(file => (
                  <div key={file.relPath} className="pp-file-row">{file.relPath}</div>
                ))}
              </div>
            </section>
          )}

          <div className="pp-download">
            <span className="pp-download-button">⬇ Download</span>
          </div>

          {(characterRows.length > 0 || stageRows.length > 0) && (
            <section className="pp-section">
              <h3>Mods Included</h3>
              <div className="pp-mods-grid">
                {characterRows.map(row => {
                  const item = itemByKey.get(row.item_key)
                  return (
                    <div key={row.filename} className="pp-mod-card">
                      {item?.preview && (
                        <div className="pp-mod-csp"><img src={item.preview} alt="" /></div>
                      )}
                      <div className="pp-mod-name">
                        {row.character}
                        {row.color && (
                          <span className="pp-badge-color" style={{ backgroundColor: getColorForBadge(row.color) }}>
                            {row.color}
                          </span>
                        )}
                      </div>
                      <div className="pp-mod-actions">
                        {stockUrlFor(row.item_key) && (
                          <img className="pp-mod-stock" src={stockUrlFor(row.item_key)} alt=""
                            onError={event => { event.currentTarget.style.display = 'none' }} />
                        )}
                        <span className="pp-badge-nucleus">Add to Nucleus</span>
                      </div>
                    </div>
                  )
                })}
                {stageRows.map(row => {
                  const item = itemByKey.get(row.item_key)
                  return (
                    <div key={row.filename} className="pp-mod-card">
                      {item?.preview && (
                        <div className="pp-mod-shot"><img src={item.preview} alt="" /></div>
                      )}
                      <div className="pp-mod-name">{item?.name || row.filename}</div>
                      <div className="pp-mod-actions">
                        <span className="pp-badge-nucleus">Add to Nucleus</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>
          )}
        </div>

        <div className="pp-shots">
          {shot ? (
            <>
              <div className="pp-shot-main"><img src={shot.url} alt="Screenshot" /></div>
              {screenshots.length > 1 && (
                <div className="pp-shot-thumbs">
                  {screenshots.map((s, i) => (
                    <button
                      type="button"
                      key={s.id || i}
                      className={i === selectedShot ? 'active' : ''}
                      onClick={() => setSelectedShot(i)}
                    >
                      <img src={s.url} alt="" />
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="pp-shot-empty">No screenshots</div>
          )}
        </div>
      </div>
    </div>
  )
}
