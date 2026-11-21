import { useEffect, useMemo, useRef, useState } from 'react'
import { playHoverSound, playSound } from '../shared/audio/sounds'
import { buildVaultCatalog, CATEGORIES, CHARACTERS, STAGES, titleCase } from './uploadCatalog'
import { ICONS as EFFECT_ICONS, EffectIcon } from '../vault/extras/ExtrasIcons'
import { ExtraPreview } from '../vault/extras/ExtraPreviews'
import { publishPackage } from './publish'
import UploadPostPreview from './UploadPostPreview'
import './UploadPage.css'

const FILTERS = [
  ['all', 'All'],
  ['costume', 'Costumes'],
  ['stage', 'Stages'],
  ['effect', 'Effects'],
  ['character', 'Characters'],
  ['patch', 'Patches']
]

function Icon({ name }) {
  if (name === 'search') {
    return <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7" /><path d="m16.5 16.5 4 4" /></svg>
  }
  if (name === 'upload') {
    return <svg viewBox="0 0 24 24"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 14v5h14v-5" /></svg>
  }
  if (name === 'plus') {
    return <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
  }
  return <svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6" /></svg>
}

const FILE_TYPE_LABELS = [
  [/\.zip$/i, 'ZIP package'],
  [/\.(png|jpe?g|gif|webp|bmp|tga)$/i, 'Image'],
  [/\.(dat|usd)$/i, 'DAT file'],
  [/\.(hps|ssm|wav|mp3|ogg)$/i, 'Audio'],
  [/\.(gct|ini)$/i, 'Code patch']
]

function fileTypeLabel(filename) {
  const match = FILE_TYPE_LABELS.find(([pattern]) => pattern.test(filename))
  if (match) return match[1]
  const ext = filename.includes('.') ? filename.split('.').pop().toUpperCase() : ''
  return ext ? ext + ' file' : 'File'
}

const normalizeName = value => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '')
const isManualItem = item => String(item.key).startsWith('manual:')
const matchStageName = item =>
  STAGES.find(stage => normalizeName(stage) === normalizeName(item.stage))
  || STAGES.find(stage => normalizeName(stage) === normalizeName(item.parent))
  || 'Other'
const categoryLabel = category =>
  (CATEGORIES.find(([id]) => id === category) || [category, category])[1]

function Thumbnail({ item }) {
  // Effects render the same colored preview the vault's extras page shows,
  // built from the mod's saved colors; the type icon is the fallback.
  if (item.kind === 'effect' && item.extraDef) {
    return (
      <div className="upload-thumb upload-thumb--effect">
        <div className="upload-thumb-extra">
          <ExtraPreview
            extraType={item.extraDef}
            modifications={item.modifications}
            mod={item.raw}
            character={item.character}
            compact
          />
        </div>
        {item.preview && (
          <img
            src={item.preview}
            alt=""
            loading="lazy"
            onError={event => { event.currentTarget.style.display = 'none' }}
          />
        )}
      </div>
    )
  }
  const EffectGlyph = item.kind === 'effect' ? (EFFECT_ICONS[item.effectIcon] || EffectIcon) : null
  return (
    <div className={'upload-thumb upload-thumb--' + item.kind}>
      {EffectGlyph ? <EffectGlyph /> : <span>{(item.name || '?')[0].toUpperCase()}</span>}
      {item.preview && (
        <img
          src={item.preview}
          alt=""
          loading="lazy"
          onError={event => { event.currentTarget.style.display = 'none' }}
        />
      )}
    </div>
  )
}

function SelectedAsset({ item, onRemove }) {
  return (
    <div className="upload-selected-asset">
      <Thumbnail item={item} />
      <div>
        <strong>{item.name}</strong>
        <span>{item.parent || item.type}</span>
      </div>
      {onRemove && (
        <button type="button" onClick={() => onRemove(item)} aria-label={'Remove ' + item.name}>
          &times;
        </button>
      )}
    </div>
  )
}

function SelectField({ id, label, value, onChange, options, format = value => value }) {
  return (
    <div className="upload-field">
      <label htmlFor={id}>{label} <span>*</span></label>
      <select id={id} value={value} onChange={event => onChange(event.target.value)}>
        <option value="">Select {label.toLowerCase()}...</option>
        {options.map(option => <option key={option} value={option}>{format(option)}</option>)}
      </select>
    </div>
  )
}

function Summary({ label, meta }) {
  return (
    <li>
      <Icon name="check" />
      <span>
        <strong>{label}</strong>
        <small>{meta}</small>
      </span>
    </li>
  )
}

export default function UploadPage({ metadata, account }) {
  const vaultItems = useMemo(() => buildVaultCatalog(metadata), [metadata])
  const [manualItems, setManualItems] = useState([])
  const catalog = useMemo(() => [...vaultItems, ...manualItems], [vaultItems, manualItems])
  const [selected, setSelected] = useState(() => new Set())
  const [step, setStep] = useState(1)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [gameplayCharacter, setGameplayCharacter] = useState('')
  const [manualCategory, setManualCategory] = useState('Assets/Other')
  const [manualCharacter, setManualCharacter] = useState('')
  const [manualStage, setManualStage] = useState('')
  const [manualEffectType, setManualEffectType] = useState('')
  const [tags, setTags] = useState([])
  const [tagInput, setTagInput] = useState('')
  const [screenshots, setScreenshots] = useState([])
  const [dragActive, setDragActive] = useState(false)
  // idle | working | done | error
  const [publishState, setPublishState] = useState({ phase: 'idle' })
  const dragDepth = useRef(0)
  const screenshotsRef = useRef(screenshots)
  const manualItemsRef = useRef(manualItems)

  useEffect(() => { screenshotsRef.current = screenshots }, [screenshots])
  useEffect(() => () => screenshotsRef.current.forEach(shot => {
    if (shot.objectUrl) URL.revokeObjectURL(shot.url)
  }), [])
  useEffect(() => { manualItemsRef.current = manualItems }, [manualItems])
  useEffect(() => () => manualItemsRef.current.forEach(item => {
    if (item.objectUrl) URL.revokeObjectURL(item.preview)
  }), [])

  const selectedItems = useMemo(() => catalog.filter(item => selected.has(item.key)), [catalog, selected])
  const effectTypes = useMemo(
    () => [...new Set(vaultItems.filter(item => item.effectType).map(item => item.effectType))].sort(),
    [vaultItems]
  )
  const filteredItems = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return catalog.filter(item => {
      if (filter !== 'all' && item.kind !== filter) return false
      return !needle || [item.name, item.parent, item.filename, item.type].some(value => String(value || '').toLowerCase().includes(needle))
    })
  }, [catalog, filter, query])

  const categoryGroups = useMemo(() => {
    const order = []
    const map = new Map()
    selectedItems.forEach(item => {
      const cat = isManualItem(item) ? manualCategory : (item.category || 'Assets/Other')
      if (!map.has(cat)) { map.set(cat, []); order.push(cat) }
      map.get(cat).push(item)
    })
    return order.map(cat => {
      const items = map.get(cat)
      const characters = new Set()
      const stages = new Set()
      const effectTypes = new Set()
      items.forEach(item => {
        const manual = isManualItem(item)
        if (['Character Costume', 'Effects', 'Gameplay Mod'].includes(cat)) {
          const character = manual ? manualCharacter : item.character
          if (character) characters.add(character)
        }
        if (cat === 'Stage Skin') {
          const stage = manual ? manualStage : matchStageName(item)
          if (stage) stages.add(stage)
        }
        if (cat === 'Effects') {
          const type = manual ? manualEffectType : item.effectType
          if (type) effectTypes.add(titleCase(type))
        }
      })
      if (cat === 'Gameplay Mod' && gameplayCharacter) characters.add(gameplayCharacter)
      const needsGameplayPick = cat === 'Gameplay Mod' && items.some(item => !isManualItem(item) && !item.character)
      const ready = cat === 'Character Costume' || cat === 'Gameplay Mod' ? characters.size > 0
        : cat === 'Stage Skin' ? stages.size > 0
          : cat === 'Effects' ? characters.size > 0 && effectTypes.size > 0
            : true
      return {
        category: cat, items, needsGameplayPick, ready,
        characters: [...characters], stages: [...stages], effectTypes: [...effectTypes]
      }
    })
  }, [selectedItems, manualCategory, manualCharacter, manualStage, manualEffectType, gameplayCharacter])

  const categoryTags = useMemo(() => {
    const tags = []
    const push = value => {
      if (value && !tags.some(tag => tag.toLowerCase() === String(value).toLowerCase())) tags.push(value)
    }
    categoryGroups.forEach(group => {
      push(group.category)
      group.characters.forEach(push)
      group.stages.forEach(push)
      group.effectTypes.forEach(push)
    })
    return tags
  }, [categoryGroups])

  const hasManualItems = selectedItems.some(isManualItem)
  const categoryReady = categoryGroups.length > 0 && categoryGroups.every(group => group.ready)
  const detailsReady = Boolean(title.trim() && description.trim() && screenshots.length && categoryReady)

  const applyDefaults = item => {
    if (item && !title.trim()) setTitle(item.name)
  }

  const toggleItem = item => {
    if (!item) return
    const adding = !selected.has(item.key)
    if (adding && selected.size === 0) applyDefaults(item)
    setSelected(current => {
      const next = new Set(current)
      if (next.has(item.key)) next.delete(item.key)
      else next.add(item.key)
      return next
    })
    playSound(adding ? 'boop' : 'back')
  }

  const addLocalFiles = files => {
    const added = [...files].map(file => {
      const isImage = file.type.startsWith('image/')
      return {
        key: 'manual:' + file.name + ':' + file.size + ':' + file.lastModified,
        kind: 'package', type: fileTypeLabel(file.name),
        name: file.name.replace(/\.[^.]+$/, ''),
        parent: 'From this computer', filename: file.name, file,
        category: 'Assets/Other',
        preview: isImage ? URL.createObjectURL(file) : null, objectUrl: isImage
      }
    })
    if (!added.length) return
    manualItems.filter(item => added.some(next => next.key === item.key)).forEach(item => {
      if (item.objectUrl) URL.revokeObjectURL(item.preview)
    })
    setManualItems(current => [...current.filter(item => !added.some(next => next.key === item.key)), ...added])
    setSelected(current => new Set([...current, ...added.map(item => item.key)]))
    if (selected.size === 0) applyDefaults(added[0])
    playSound('boop')
  }

  const pickLocalFiles = event => {
    addLocalFiles(event.target.files)
    event.target.value = ''
  }

  const hasDraggedFiles = event => [...(event.dataTransfer?.types || [])].includes('Files')

  const onPackageDragEnter = event => {
    if (!hasDraggedFiles(event)) return
    event.preventDefault()
    dragDepth.current += 1
    setDragActive(true)
  }

  const onPackageDragOver = event => {
    if (hasDraggedFiles(event)) event.preventDefault()
  }

  const onPackageDragLeave = event => {
    if (!hasDraggedFiles(event)) return
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setDragActive(false)
  }

  const onPackageDrop = event => {
    if (!hasDraggedFiles(event)) return
    event.preventDefault()
    dragDepth.current = 0
    setDragActive(false)
    addLocalFiles(event.dataTransfer.files)
  }

  const addTag = () => {
    const value = tagInput.trim().replace(/^#/, '')
    if (!value || tags.some(tag => tag.toLowerCase() === value.toLowerCase())) return
    setTags(current => [...current, value])
    setTagInput('')
    playSound('boop')
  }

  const addScreenshots = files => {
    const added = [...files].filter(file => file.type.startsWith('image/')).map(file => ({
      id: 'file:' + file.name + ':' + file.size + ':' + file.lastModified,
      name: file.name, url: URL.createObjectURL(file), objectUrl: true, file
    }))
    setScreenshots(current => [...current, ...added.filter(shot => !current.some(old => old.id === shot.id))])
  }

  const addVaultPreview = item => {
    const id = 'vault:' + item.key
    if (!item.preview || screenshots.some(shot => shot.id === id)) return
    setScreenshots(current => [...current, { id, name: item.name + ' vault preview', url: item.preview, objectUrl: false }])
    playSound('camera')
  }

  const removeScreenshot = id => setScreenshots(current => current.filter(shot => {
    if (shot.id === id && shot.objectUrl) URL.revokeObjectURL(shot.url)
    return shot.id !== id
  }))

  const goToDetails = () => {
    if (!selectedItems.length) return
    applyDefaults(selectedItems[0])
    setStep(2)
    playSound('start')
  }

  const previewPicks = selectedItems.filter(item => item.preview && !screenshots.some(shot => shot.id === 'vault:' + item.key))

  const publishing = publishState.phase === 'working'

  const allTags = useMemo(() => [...categoryTags, ...tags.filter(tag =>
    !categoryTags.some(ct => ct.toLowerCase() === tag.toLowerCase()))],
  [categoryTags, tags])

  // Review step: dry-run the publish so the preview shows the REAL upload
  // plan (exact filenames, website file rows, badge colors) — not a mock-up.
  const [dryRunState, setDryRunState] = useState({ phase: 'idle' })
  useEffect(() => {
    if (step !== 3) return
    let cancelled = false
    setDryRunState({ phase: 'working' })
    publishPackage({
      items: selectedItems,
      screenshots,
      title: title.trim() || 'Untitled',
      description: description.trim() || '-',
      tags: allTags,
      dryRun: true
    }).then(result => {
      if (!cancelled) setDryRunState({ phase: 'done', data: result })
    }).catch(e => {
      if (!cancelled) setDryRunState({ phase: 'error', error: String(e?.message || e) })
    })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step])

  const onPublish = async () => {
    if (!account || !detailsReady || publishing) return
    setPublishState({ phase: 'working' })
    playSound('start')
    try {
      const result = await publishPackage({
        items: selectedItems,
        screenshots,
        title: title.trim(),
        description: description.trim(),
        tags: allTags
      })
      setPublishState({ phase: 'done', result })
      playSound('newSkin')
    } catch (e) {
      setPublishState({ phase: 'error', error: String(e?.message || e) })
      playSound('back')
    }
  }

  const startAnotherUpload = () => {
    screenshots.forEach(shot => { if (shot.objectUrl) URL.revokeObjectURL(shot.url) })
    manualItems.forEach(item => { if (item.objectUrl) URL.revokeObjectURL(item.preview) })
    setSelected(new Set())
    setManualItems([])
    setScreenshots([])
    setTitle('')
    setDescription('')
    setTags([])
    setTagInput('')
    setGameplayCharacter('')
    setManualCategory('Assets/Other')
    setManualCharacter('')
    setManualStage('')
    setManualEffectType('')
    setPublishState({ phase: 'idle' })
    setDryRunState({ phase: 'idle' })
    setQuery('')
    setFilter('all')
    setStep(1)
    playSound('start')
  }

  const steps = [
    [1, 'Select mods', selectedItems.length + ' selected'],
    [2, 'Post details', title ? 'Draft started' : 'Not started'],
    [3, 'Review', detailsReady ? 'Ready' : 'Needs details']
  ]

  return (
    <div className="upload-page-shell">
      <div className="upload-page-inner">
        <header className="upload-header">
          <div>
            <h2>Publish from your vault</h2>
          </div>
          {account ? (
            <div className="upload-account" title="Signed in with your ssbmnucleus.net account">
              <span className="upload-account-avatar">
                <b>{(account.username || '?')[0].toUpperCase()}</b>
                {account.avatarUrl && (
                  <img
                    src={account.avatarUrl}
                    alt=""
                    onError={event => { event.currentTarget.style.display = 'none' }}
                  />
                )}
              </span>
              <strong>{account.username}</strong>
            </div>
          ) : (
            <div className="upload-account upload-account--out" title="Sign in from Settings to publish">
              <span>Not signed in</span>
            </div>
          )}
        </header>

        <nav className="upload-progress" aria-label="Upload progress">
          {steps.map(([number, label, meta]) => {
            const disabled = number === 2 ? !selectedItems.length : number === 3 ? !detailsReady : false
            return (
              <button
                type="button"
                key={number}
                className={(step === number ? 'active ' : '') + (step > number ? 'complete' : '')}
                disabled={disabled}
                onClick={() => setStep(number)}
              >
                <span className="upload-step-number">{step > number ? <Icon name="check" /> : number}</span>
                <span>
                  <strong>{label}</strong>
                  <small>{meta}</small>
                </span>
              </button>
            )
          })}
        </nav>

        {step === 1 && (
          <div className="upload-select-layout">
            <section
              className={'upload-package-panel' + (dragActive ? ' drag-active' : '')}
              onDragEnter={onPackageDragEnter}
              onDragOver={onPackageDragOver}
              onDragLeave={onPackageDragLeave}
              onDrop={onPackageDrop}
            >
              <div className="upload-section-heading">
                <div>
                  <h3>Upload package</h3>
                  <p>Drop files anywhere on this panel, or pick mods from your vault.</p>
                </div>
                <label className="upload-add-file" onMouseEnter={playHoverSound}>
                  <Icon name="upload" /> Add files
                  <input type="file" multiple onChange={pickLocalFiles} />
                </label>
              </div>
              {selectedItems.length ? (
                <div className="upload-package-grid">
                  {selectedItems.map(item => (
                    <div className="upload-package-card" key={item.key}>
                      <Thumbnail item={item} />
                      <span className="upload-card-copy">
                        <strong>{item.name}</strong>
                        <small>{item.parent || item.type}</small>
                      </span>
                      <span className="upload-kind-badge">
                        {item.type}
                        {item.slot && (
                          <span className="upload-slot-chip" title={item.slot.name + ' slot'}>
                            <span className="upload-color-dot" style={{ background: item.slot.hex }} />
                            {item.slot.name}
                          </span>
                        )}
                      </span>
                      <button type="button" onClick={() => toggleItem(item)} aria-label={'Remove ' + item.name}>&times;</button>
                    </div>
                  ))}
                  <label className="upload-package-add-tile" onMouseEnter={playHoverSound}>
                    <b>+</b>
                    <span>Add more files</span>
                    <input type="file" multiple onChange={pickLocalFiles} />
                  </label>
                </div>
              ) : (
                <label className="upload-dropzone">
                  <Icon name="upload" />
                  <strong>Drag files here</strong>
                  <span>Drop mod ZIPs, textures, or any other files — or pick finished mods from your vault.</span>
                  <input type="file" multiple onChange={pickLocalFiles} />
                </label>
              )}
              <footer>
                <button type="button" className="upload-primary" disabled={!selectedItems.length} onClick={goToDetails}>
                  Continue to details <span>&rarr;</span>
                </button>
              </footer>
            </section>

            <aside className="upload-vault-picker">
              <div className="upload-picker-heading">
                <h3>Your vault</h3>
                <strong>{filteredItems.length}</strong>
              </div>
              <div className="upload-picker-toolbar">
                <label className="upload-search">
                  <Icon name="search" />
                  <input
                    value={query}
                    onChange={event => setQuery(event.target.value)}
                    placeholder="Search your vault..."
                  />
                  {query && <button type="button" onClick={() => setQuery('')}>&times;</button>}
                </label>
              </div>
              <div className="upload-filter-row">
                {FILTERS.map(([id, label]) => (
                  <button type="button" key={id} className={filter === id ? 'active' : ''} onClick={() => setFilter(id)}>
                    {label}
                  </button>
                ))}
              </div>
              {filteredItems.length ? (
                <div className="upload-picker-list">
                  {filteredItems.map(item => {
                    const isSelected = selected.has(item.key)
                    return (
                      <button
                        type="button"
                        key={item.key}
                        className={'upload-picker-row' + (isSelected ? ' selected' : '')}
                        onClick={() => toggleItem(item)}
                        onMouseEnter={playHoverSound}
                        aria-pressed={isSelected}
                      >
                        <Thumbnail item={item} />
                        <span className="upload-picker-copy">
                          <strong>{item.name}</strong>
                          <small>
                            {[item.parent, item.type].filter(Boolean).join(' · ')}
                            {item.slot && (
                              <span className="upload-slot-chip" title={item.slot.name + ' slot'}>
                                <span className="upload-color-dot" style={{ background: item.slot.hex }} />
                                {item.slot.name}
                              </span>
                            )}
                          </small>
                        </span>
                        <span className="upload-picker-check"><Icon name={isSelected ? 'check' : 'plus'} /></span>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="upload-empty">
                  <Icon name="search" />
                  <strong>No vault mods found</strong>
                  <span>Try a broader search.</span>
                </div>
              )}
            </aside>
          </div>
        )}

        {step === 2 && (
          <div className="upload-details-layout">
            <div className="upload-form-column">
              <section className="upload-form-section">
                <div className="upload-section-heading">
                  <div>
                    <h3>Screenshots</h3>
                    <p>Show the mod in-game. At least one image is required on the website.</p>
                  </div>
                </div>
                {screenshots.length > 0 && (
                  <div className="upload-screenshot-grid">
                    {screenshots.map((shot, index) => (
                      <div className="upload-screenshot" key={shot.id}>
                        <img src={shot.url} alt={'Screenshot ' + (index + 1)} />
                        <span>{index === 0 ? 'Cover' : index + 1}</span>
                        <button type="button" onClick={() => removeScreenshot(shot.id)}>&times;</button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="upload-screenshot-actions">
                  <label className="upload-secondary">
                    <Icon name="upload" /> Add images
                    <input type="file" accept="image/*" multiple onChange={event => addScreenshots(event.target.files)} />
                  </label>
                  {previewPicks.length > 0 && (
                    <div className="upload-preview-picks">
                      <span>Use a vault preview:</span>
                      {previewPicks.slice(0, 5).map(item => (
                        <button type="button" key={item.key} onClick={() => addVaultPreview(item)} title={'Use ' + item.name}>
                          <Thumbnail item={item} />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </section>

              <section className="upload-form-section">
                <div className="upload-section-heading">
                  <div>
                    <h3>Post details</h3>
                  </div>
                </div>
                <div className="upload-field">
                  <label htmlFor="upload-title">Title <span>*</span></label>
                  <input
                    id="upload-title"
                    value={title}
                    maxLength={100}
                    onChange={event => setTitle(event.target.value)}
                    placeholder="e.g. Fox - Green Chrome"
                  />
                  <small>{title.length}/100</small>
                </div>
                <div className="upload-field">
                  <label htmlFor="upload-description">Description <span>*</span><em>Markdown supported</em></label>
                  <textarea
                    id="upload-description"
                    rows={8}
                    value={description}
                    onChange={event => setDescription(event.target.value)}
                    placeholder={'Describe your mod, credits, installation notes, and compatibility.\n\n## Credits'}
                  />
                </div>
                <div className="upload-field">
                  <label>Categories <em>From your selection</em></label>
                  <div className="upload-category-groups">
                    {categoryGroups.map(group => {
                      const details = [...group.characters, ...group.stages, ...group.effectTypes]
                      return (
                        <div className={'upload-category-group' + (group.ready ? '' : ' needs-input')} key={group.category}>
                          <div className="upload-category-group-head">
                            <strong>{categoryLabel(group.category)}</strong>
                            <span>{group.items.length} item{group.items.length === 1 ? '' : 's'}</span>
                          </div>
                          {details.length > 0 && (
                            <div className="upload-tags upload-tags--system">
                              {details.map(tag => <span key={tag}>{tag}</span>)}
                            </div>
                          )}
                          {group.needsGameplayPick && (
                            <SelectField id="upload-gameplay" label="Character" value={gameplayCharacter} onChange={setGameplayCharacter} options={CHARACTERS} />
                          )}
                        </div>
                      )
                    })}
                  </div>
                  <p>Detected from your selection. These route the post to the correct pages on the website.</p>
                </div>
                {hasManualItems && (
                  <div className="upload-field-grid">
                    <div className="upload-field">
                      <label htmlFor="upload-manual-category">Added files category <span>*</span></label>
                      <select id="upload-manual-category" value={manualCategory} onChange={event => setManualCategory(event.target.value)}>
                        {CATEGORIES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                      </select>
                    </div>
                    {['Character Costume', 'Gameplay Mod'].includes(manualCategory) && (
                      <SelectField id="upload-manual-character" label="Character" value={manualCharacter} onChange={setManualCharacter} options={CHARACTERS} />
                    )}
                    {manualCategory === 'Stage Skin' && (
                      <SelectField id="upload-manual-stage" label="Stage" value={manualStage} onChange={setManualStage} options={STAGES} />
                    )}
                  </div>
                )}
                {hasManualItems && manualCategory === 'Effects' && (
                  <div className="upload-field-grid">
                    <SelectField id="upload-manual-effect-char" label="Character" value={manualCharacter} onChange={setManualCharacter} options={CHARACTERS} />
                    <SelectField id="upload-manual-effect-type" label="Effect type" value={manualEffectType} onChange={setManualEffectType} options={effectTypes} format={titleCase} />
                  </div>
                )}
                <div className="upload-field">
                  <label htmlFor="upload-tags">Search tags <em>Optional</em></label>
                  {tags.length > 0 && (
                    <div className="upload-tags">
                      {tags.map(tag => (
                        <span key={tag}>
                          {tag}
                          <button type="button" onClick={() => setTags(current => current.filter(value => value !== tag))}>&times;</button>
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="upload-tag-input">
                    <input
                      id="upload-tags"
                      value={tagInput}
                      onChange={event => setTagInput(event.target.value)}
                      onKeyDown={event => {
                        if (event.key === 'Enter' || event.key === ',') {
                          event.preventDefault()
                          addTag()
                        }
                      }}
                      placeholder="Type a tag and press Enter"
                    />
                    <button type="button" onClick={addTag} disabled={!tagInput.trim()}>Add</button>
                  </div>
                </div>
              </section>

              <div className="upload-form-actions">
                <button type="button" className="upload-quiet" onClick={() => setStep(1)}>&larr; Back to vault</button>
                <button type="button" className="upload-primary" disabled={!detailsReady} onClick={() => { setStep(3); playSound('start') }}>
                  Review upload &rarr;
                </button>
              </div>
            </div>

            <aside className="upload-package-summary">
              <h3>{selectedItems.length} mod{selectedItems.length === 1 ? '' : 's'} selected</h3>
              <div className="upload-selected-list">
                {selectedItems.map(item => <SelectedAsset key={item.key} item={item} />)}
              </div>
              <button type="button" onClick={() => setStep(1)}>Edit selection</button>
            </aside>
          </div>
        )}

        {step === 3 && (
          <div className="upload-review-layout">
            <section className="upload-review-card upload-review-card--postpreview">
              {dryRunState.phase === 'working' && (
                <div className="upload-preview-loading">Building an exact post preview…</div>
              )}
              {dryRunState.phase === 'error' && (
                <div className="upload-publish-error" role="alert">
                  Could not build the post preview: {dryRunState.error}
                </div>
              )}
              {dryRunState.phase === 'done' && (
                <UploadPostPreview
                  account={account}
                  title={title}
                  description={description}
                  categoryTags={categoryTags}
                  userTags={tags}
                  screenshots={screenshots}
                  dryRun={dryRunState.data}
                  items={selectedItems}
                />
              )}
            </section>
            <aside className="upload-review-sidebar">
              <h3>Upload summary</h3>
              <ul>
                <Summary label={selectedItems.length + ' vault mod' + (selectedItems.length === 1 ? '' : 's')} meta="Package sources linked" />
                <Summary label={screenshots.length + ' screenshot' + (screenshots.length === 1 ? '' : 's')} meta="First image will be the cover" />
                <Summary label={categoryTags.length + ' routing tags'} meta="Website category format" />
              </ul>
              {publishState.phase === 'done' ? (
                <div className="upload-auth-callout upload-auth-callout--ready">
                  <span className="upload-account-dot" />
                  <div>
                    <strong>Published!</strong>
                    <p>
                      Your post is in the approval queue. Track it at{' '}
                      <a href={publishState.result.url} target="_blank" rel="noreferrer">
                        ssbmnucleus.net/post/{publishState.result.postId}
                      </a>.
                    </p>
                  </div>
                </div>
              ) : account ? (
                <div className="upload-auth-callout upload-auth-callout--ready">
                  <span className="upload-account-dot" />
                  <div>
                    <strong>Signed in as {account.username}</strong>
                    <p>Publishing sends this package to the ssbmnucleus.net approval queue under your account.</p>
                  </div>
                </div>
              ) : (
                <div className="upload-auth-callout">
                  <span className="upload-account-dot" />
                  <div>
                    <strong>Account required to publish</strong>
                    <p>Sign in from Settings to connect this package to the website approval queue.</p>
                  </div>
                </div>
              )}
              {publishState.phase === 'error' && (
                <div className="upload-publish-error" role="alert">{publishState.error}</div>
              )}
              {publishState.phase === 'done' ? (
                <button type="button" className="upload-primary" onClick={startAnotherUpload}>
                  <Icon name="plus" /> Upload another mod
                </button>
              ) : (
                <button
                  type="button"
                  className="upload-primary"
                  disabled={!account || !detailsReady || publishing}
                  onClick={onPublish}
                >
                  <Icon name="upload" /> {publishing ? 'Publishing…' : account ? 'Publish' : 'Sign in to publish'}
                </button>
              )}
              {publishState.phase !== 'done' && (
                <button type="button" className="upload-quiet" disabled={publishing} onClick={() => setStep(2)}>&larr; Edit post details</button>
              )}
            </aside>
          </div>
        )}
      </div>
    </div>
  )
}
