/**
 * CodesManagerModal - THE home of gecko codes (the vault has no Codes section;
 * this modal is the single surface). Opened from the "Codes" button in the
 * MexPanel header.
 *
 * Left, "In this build": the project's codes.ini. Checkbox = enabled, ✕ =
 * remove. Default codes (the Slippi SSS fix) start enabled and have no ✕, but
 * can be unticked; the off state persists per project, and only then does
 * the Slippi Dolphin warning show. Codes that aren't in the vault survive
 * Apply untouched unless removed. Under it, one collapsed line for the codes
 * Slippi Dolphin injects at launch (not part of the exported ISO).
 *
 * Right, "Add codes": a search box, then the library in collapsible category
 * groups. The codes Nucleus makes itself (GET /codes/nucleus; today Now
 * Playing, which new projects start with) are listed first in their own
 * category like any other code, so an existing build can add them; one that
 * would conflict with the build says why instead of offering Add. "Paste
 * codes" adds new codes to the vault (the smart-paste flow); ✕ deletes a code
 * you added from the vault.
 *
 * Apply sends the FULL desired list to POST /codes/project/sync, which
 * rewrites codes.ini and recompiles codes.gct via `mexcli sync-codes`.
 * DiscUsageIndicator conventions: plain fetch, local busy state, no stores.
 */
import { useEffect, useState, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import CodesPasteModal from './CodesPasteModal'
import { api } from '../../shared/transport/api'
import '../../shared/ui/EditModal.css'
import './GeckoCodes.css'
import './CodesManager.css'

const headerOf = (c) => {
  const name = c.iniName || c.name
  return (c.creator ? `${name} [${c.creator}]` : name).toLowerCase()
}

// The name a vault entry uses inside a project codes.ini (mirrors the
// backend's _ini_name: builtin library codes keep their category prefix).
const iniNameOf = (v) => (v.builtin && v.category ? `${v.category} | ${v.name}` : v.name)

// What a row shows: the codes.ini name without its "CATEGORY | " prefix.
const displayName = (name) => (name || '').replace(/^[A-Z0-9 ]+ \| /, '')

const CATEGORY_LABELS = { QOL: 'Quality of life', CUSTOM: 'Your codes' }
const categoryLabel = (cat) => CATEGORY_LABELS[cat] || cat.charAt(0) + cat.slice(1).toLowerCase()

// header -> enabled, for counting what Apply will change
const snapshot = (codes) => new Map(codes.filter((c) => !c.removed).map((c) => [headerOf(c), c.enabled]))

export default function CodesManagerModal({ show, onClose }) {
  const [buildCodes, setBuildCodes] = useState([])   // {..., removed: bool}
  const [vaultCodes, setVaultCodes] = useState([])
  const [dolphinCodes, setDolphinCodes] = useState(null)  // {available, codes} | null
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)
  const [message, setMessage] = useState('')
  const [dirty, setDirty] = useState(false)
  const [showPaste, setShowPaste] = useState(false)
  const [nucleusCodes, setNucleusCodes] = useState([])
  const [query, setQuery] = useState('')
  const [showDolphin, setShowDolphin] = useState(false)
  const [loaded, setLoaded] = useState(() => new Map())   // snapshot() at load
  // category name -> open? Seeded on load: custom/user categories start open,
  // all-builtin ones (the m-ex library wall) start collapsed.
  const [openCats, setOpenCats] = useState({})

  const refreshVault = useCallback(async () => {
    try {
      const vault = await api.get('/codes/vault/list')
      setVaultCodes(vault.codes || [])
      return vault
    } catch (err) {
      // a backend error envelope leaves the list untouched (old `if (vault.success)`);
      // only transport failures propagate
      if (err.data) return err.data
      throw err
    }
  }, [])

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setMessage('')
    setDirty(false)
    try {
      const slippiPath = localStorage.getItem('slippi_dolphin_path') || ''
      const [proj, vault, dolphinRes, nucleusRes] = await Promise.all([
        // a project-codes failure is reported but must not block the vault/dolphin lists
        api.get('/codes/project').catch((err) => ({ error: err.message || 'Failed to read project codes' })),
        refreshVault(),
        api.get('/codes/dolphin', { query: { slippiPath } }).catch(() => null),
        api.get('/codes/nucleus').catch(() => null),
      ])
      if (proj.error) setMessage(proj.error)  // keep the current buildCodes, as before
      else {
        const codes = (proj.codes || []).map((c) => ({ ...c, removed: false }))
        setBuildCodes(codes)
        setLoaded(snapshot(codes))
      }
      setNucleusCodes(nucleusRes?.codes || [])
      if (proj.duplicatesCollapsed > 0) setDirty(true)  // first Apply heals dupes
      setDolphinCodes(dolphinRes?.success ? dolphinRes : null)
      setOpenCats((prev) => {
        const next = { ...prev }
        for (const v of vault.codes || []) {
          const cat = v.category || 'CUSTOM'
          if (!(cat in next)) next[cat] = !v.builtin
          else if (!v.builtin) next[cat] = next[cat] || true
        }
        return next
      })
    } catch (err) {
      setMessage(`Load error: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [refreshVault])

  useEffect(() => { if (show) fetchAll() }, [show, fetchAll])

  if (!show) return null

  const inBuildHeaders = new Set(buildCodes.filter((c) => !c.removed).map(headerOf))

  const updateBuildCode = (idx, patch) => {
    setDirty(true)
    setBuildCodes((codes) => codes.map((c, i) => (i === idx ? { ...c, ...patch } : c)))
  }

  const stagedFromVault = (v) => ({
    name: iniNameOf(v),
    creator: v.creator,
    description: v.description,
    source: v.source,
    enabled: true,
    default: false,
    inVault: true,
    vaultId: v.id,
    removed: false,
  })

  const addFromVault = (v) => {
    playSound('boop')
    setDirty(true)
    setBuildCodes((codes) => [...codes, stagedFromVault(v)])
  }

  const deleteFromVault = async (v) => {
    if (!window.confirm(`Delete "${v.name}" from the code vault?`)) return
    playSound('back')
    try {
      await api.post(`/codes/vault/delete/${v.id}`)
      await refreshVault()
    } catch (err) {
      setMessage(`Delete failed: ${err.message}`)
    }
  }

  // Stage every builtin library code not already in the build. Stock
  // MexManager seeds all of these (enabled) into every new workspace;
  // Nucleus-created projects never got them, so this is the one-click
  // catch-up to the stock m-ex experience. Nothing applies until Apply.
  const addMexDefaults = () => {
    playSound('boop')
    setDirty(true)
    setBuildCodes((codes) => {
      const present = new Set(codes.filter((c) => !c.removed).map(headerOf))
      const missing = vaultCodes.filter((v) => v.builtin && !present.has(headerOf(stagedFromVault(v))))
      return [...codes, ...missing.map(stagedFromVault)]
    })
  }

  const handleApply = async () => {
    setApplying(true)
    setMessage('')
    try {
      const desired = buildCodes
        .filter((c) => !c.removed)
        .map((c) => ({
          name: c.name,
          creator: c.creator,
          description: c.description,
          source: c.source,
          enabled: c.enabled,
        }))
      const data = await api.post('/codes/project/sync', { codes: desired })
      playSound('newSkin')
      setMessage(`Applied — ${data.enabled} of ${data.applied} codes enabled. Export the ISO to play with them.`)
      await fetchAll()
    } catch (err) {
      const failed = err.data?.codes
      const detail = failed?.length ? ` (${failed[0].name}: ${failed[0].error})` : ''
      setMessage(`Apply failed: ${err.message}${detail}`)
    } finally {
      setApplying(false)
    }
  }

  const handleClose = () => { playSound('back'); onClose?.() }

  const q = query.trim().toLowerCase()
  const matches = (...texts) => !q || texts.some((t) => (t || '').toLowerCase().includes(q))

  // Nucleus's own codes as library entries: "QOL | Now Playing (...)" becomes
  // name + category, so iniNameOf() gives back the exact codes.ini header.
  const nucleusEntries = nucleusCodes.map((n) => {
    const [category, ...rest] = n.iniName.split(' | ')
    return { ...n, name: rest.length ? rest.join(' | ') : n.iniName, category: rest.length ? category : 'CUSTOM', builtin: true }
  })
  const vaultAvailable = [...nucleusEntries, ...vaultCodes].filter(
    (v) => !inBuildHeaders.has((v.creator ? `${iniNameOf(v)} [${v.creator}]` : iniNameOf(v)).toLowerCase())
      && matches(v.name, v.description, v.creator, v.category)
  )
  const vaultGrouped = {}
  for (const v of vaultAvailable) {
    (vaultGrouped[v.category || 'CUSTOM'] = vaultGrouped[v.category || 'CUSTOM'] || []).push(v)
  }
  const toggleCat = (cat) => {
    playSound('boop')
    setOpenCats((o) => ({ ...o, [cat]: !o[cat] }))
  }

  const missingDefaults = vaultCodes.filter(
    (v) => v.builtin && !inBuildHeaders.has(headerOf(stagedFromVault(v)))
  ).length

  const live = buildCodes.filter((c) => !c.removed)
  const onCount = live.filter((c) => c.enabled).length
  const now = snapshot(buildCodes)
  let changes = 0
  for (const [h, on] of now) if (!loaded.has(h) || loaded.get(h) !== on) changes++
  for (const h of loaded.keys()) if (!now.has(h)) changes++
  const sssOff = live.some((c) => c.default && !c.enabled)
  const dolphinList = dolphinCodes?.available ? dolphinCodes.codes : []

  const modal = (
    <div className="edit-modal-fullscreen-overlay" onClick={handleClose}>
      <div className="edit-modal-fullscreen codes-mgr-modal" onClick={(e) => e.stopPropagation()}>
        <div className="edit-modal-header codes-mgr-header">
          <h2>Codes</h2>
          <p className="codes-mgr-sub">Gecko codes are built into this project's ISO when you export it.</p>
        </div>

        {loading ? (
          <div className="codes-empty">Loading codes...</div>
        ) : (
          <div className="codes-mgr-body">
            <section className="codes-mgr-col">
              <div className="codes-mgr-col-head">
                <h3>In this build</h3>
                <span className="codes-mgr-col-count">{onCount} on</span>
              </div>
              {live.length === 0 && <div className="codes-empty">No codes in this build yet.</div>}
              <div className="codes-mgr-list">
                {buildCodes.map((c, idx) => c.removed ? null : (
                  <div key={idx} className={`codes-mgr-row ${c.enabled ? '' : 'is-off'}`}>
                    <label
                      className="codes-mgr-toggle"
                      title={c.enabled ? 'On: built into the ISO' : 'Off: kept in the list, left out of the ISO'}
                    >
                      <input
                        type="checkbox"
                        checked={c.enabled}
                        disabled={applying}
                        onChange={(e) => updateBuildCode(idx, { enabled: e.target.checked })}
                      />
                      <span className="codes-mgr-row-text">
                        <span className="codes-row-name">{displayName(c.name)}</span>
                        <span className="codes-row-meta">
                          {c.default ? 'Needed for Slippi Dolphin' : c.creator}
                        </span>
                      </span>
                    </label>
                    {!c.default && (
                      <button
                        className="codes-mgr-remove"
                        title="Remove from this build"
                        disabled={applying}
                        onClick={() => { playSound('back'); updateBuildCode(idx, { removed: true }) }}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                ))}
              </div>
              {sssOff && (
                <div className="codes-mgr-warning">
                  With Skip Slippi SSS off, this ISO crashes at the stage select on Slippi
                  Dolphin. Only turn it off for a Slippi Nintendont (console) build that
                  crashes there.
                </div>
              )}

              <div className="codes-mgr-dolphin">
                <button
                  className="codes-mgr-dolphin-toggle"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); setShowDolphin((o) => !o) }}
                >
                  <span className="codes-category-chevron">{showDolphin ? '▾' : '▸'}</span>
                  {dolphinList.length
                    ? `Slippi Dolphin adds ${dolphinList.length} more when it launches`
                    : 'Slippi Dolphin adds its own codes when it launches'}
                </button>
                {showDolphin && (
                  <div className="codes-mgr-dolphin-body">
                    {dolphinList.length > 0 && (
                      <ul>{dolphinList.map((c, i) => <li key={i}>{c.name}</li>)}</ul>
                    )}
                    <p>
                      They run on top of the exported ISO (UCF, netplay fixes) and aren't part
                      of it, so there is nothing to change here.
                    </p>
                  </div>
                )}
              </div>
            </section>

            <section className="codes-mgr-col">
              <div className="codes-mgr-col-head">
                <h3>Add codes</h3>
                <span className="codes-mgr-head-actions">
                  <button
                    className="codes-mgr-link"
                    onMouseEnter={playHoverSound}
                    disabled={applying}
                    title="Paste codes from anywhere (raw hex, an INI block, a forum copy-paste) and keep them in your vault."
                    onClick={() => { playSound('start'); setShowPaste(true) }}
                  >
                    Paste codes
                  </button>
                  {missingDefaults > 0 && (
                    <button
                      className="codes-mgr-link"
                      onMouseEnter={playHoverSound}
                      disabled={applying}
                      title="Add every code stock MexManager turns on by default (Skip Memcard Prompt, Unlock Everything, Neutral Spawn, …). Review, then Apply."
                      onClick={addMexDefaults}
                    >
                      Add all m-ex defaults ({missingDefaults})
                    </button>
                  )}
                </span>
              </div>
              <input
                className="codes-mgr-search"
                type="search"
                placeholder="Search codes"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />

              {vaultAvailable.length === 0 && (
                <div className="codes-empty">
                  {q
                    ? 'No codes match.'
                    : vaultCodes.length === 0
                      ? 'No codes in the vault yet. Use "Paste codes" to add some.'
                      : 'Everything in the vault is already in this build.'}
                </div>
              )}
              {Object.keys(vaultGrouped).sort((a, b) => categoryLabel(a).localeCompare(categoryLabel(b))).map((cat) => {
                const open = q ? true : openCats[cat]
                return (
                  <div key={cat} className="codes-mgr-group">
                    <button
                      className="codes-mgr-group-head"
                      onMouseEnter={playHoverSound}
                      onClick={() => toggleCat(cat)}
                    >
                      <span className="codes-category-chevron">{open ? '▾' : '▸'}</span>
                      {categoryLabel(cat)}
                      <span className="codes-category-count">{vaultGrouped[cat].length}</span>
                    </button>
                    {open && (
                      <div className="codes-mgr-list">
                        {vaultGrouped[cat].map((v) => (
                          <div key={v.id} className="codes-mgr-row codes-mgr-row--lib">
                            <div className="codes-mgr-row-text">
                              <span className="codes-row-name">{v.name}</span>
                              {(v.conflict || v.description || v.creator) && (
                                <span className="codes-row-meta">
                                  {v.conflict || (v.description ? v.description.split('\n')[0] : v.creator)}
                                </span>
                              )}
                            </div>
                            {!v.builtin && (
                              <button
                                className="codes-mgr-remove"
                                title="Delete from your vault"
                                disabled={applying}
                                onClick={() => deleteFromVault(v)}
                              >
                                ✕
                              </button>
                            )}
                            <button
                              className="codes-mgr-add"
                              onMouseEnter={playHoverSound}
                              disabled={applying || Boolean(v.conflict)}
                              onClick={() => addFromVault(v)}
                            >
                              Add
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </section>
          </div>
        )}

        {message && <div className="codes-summary-text">{message}</div>}

        <div className="edit-modal-actions">
          <button
            className="edit-modal-action-btn edit-modal-action-btn--save"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); handleApply() }}
            disabled={loading || applying || !dirty}
          >
            {applying ? 'Applying...' : changes ? `Apply ${changes} change${changes === 1 ? '' : 's'}` : 'Apply'}
          </button>
          <button
            className="edit-modal-action-btn edit-modal-action-btn--cancel"
            onClick={handleClose}
            disabled={applying}
          >
            Close
          </button>
        </div>
      </div>

      <CodesPasteModal
        show={showPaste}
        onClose={() => setShowPaste(false)}
        onSaved={refreshVault}
      />
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
