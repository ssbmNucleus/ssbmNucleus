/**
 * MeleeUnlockedSection - the two folders the Melee Unlocked export needs
 * (projects/export/MeleeUnlockedCard.jsx, backend projects/install/melee_unlocked.py):
 *
 *   - the fighter plugin kit (headers, lists and build tools; Melee Unlocked's
 *     tools/mexft/mexft_kit.py makes it)
 *   - the bin folder of a MinGW-w64 GCC, which compiles the fighters' C
 *
 * Both are checked by the backend before they are kept, and persisted to localStorage.
 */
import { useState, useEffect } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { api } from '../shared/transport/api'
import { KIT_PATH_KEY, GCC_BIN_KEY } from '../projects/export/meleeUnlocked.js'

const FOLDERS = [
  { key: KIT_PATH_KEY, field: 'kit', body: 'kitPath', label: 'Fighter plugin kit',
    empty: 'No kit folder set', hint: 'The folder with flags.json, abi.txt and tools/mexft_build.py' },
  { key: GCC_BIN_KEY, field: 'compiler', body: 'gccBin', label: 'MinGW-w64 GCC',
    empty: 'No compiler folder set', hint: 'The bin folder that holds gcc.exe' },
]

export default function MeleeUnlockedSection() {
  const [paths, setPaths] = useState(() => Object.fromEntries(FOLDERS.map(f => [f.key, localStorage.getItem(f.key) || ''])))
  const [state, setState] = useState({})   // field -> { valid, abi, error }
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState({ text: '', type: '' })

  const verify = async (next) => {
    setBusy(true)
    try {
      const data = await api.post('/melee-unlocked/verify', Object.fromEntries(FOLDERS.map(f => [f.body, next[f.key]])))
      setState(data)
      return data
    } catch (err) {
      setMessage({ text: `Verification failed: ${err.message}`, type: 'error' })
      return null
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (FOLDERS.some(f => paths[f.key])) verify(paths)
    // once, for the saved paths
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const browse = async (folder) => {
    if (!window.electron) {
      setMessage({ text: 'Electron API not available', type: 'error' })
      return
    }
    const selected = await window.electron.selectDirectory()
    if (!selected) return
    const next = { ...paths, [folder.key]: selected }
    const data = await verify(next)
    if (data?.[folder.field]?.valid) {
      localStorage.setItem(folder.key, selected)
      setPaths(next)
      setMessage({ text: `${folder.label} set`, type: 'success' })
      setTimeout(() => setMessage({ text: '', type: '' }), 3000)
    } else if (data) {
      // an invalid folder is not kept: show why, and go back to what was saved
      setMessage({ text: data[folder.field]?.error || 'That folder cannot be used.', type: 'error' })
      verify(paths)
    }
  }

  const clear = (folder) => {
    localStorage.removeItem(folder.key)
    const next = { ...paths, [folder.key]: '' }
    setPaths(next)
    setState(s => ({ ...s, [folder.field]: { valid: false } }))
    setMessage({ text: `${folder.label} cleared`, type: 'success' })
    setTimeout(() => setMessage({ text: '', type: '' }), 3000)
  }

  return (
    <section className="settings-section">
      <h3>Melee Unlocked</h3>
      <p className="section-description">
        Build fighter plugins for Melee Unlocked's Source Port from the Export screen. A custom
        fighter gets one when its C source is in the Vault.
      </p>

      {FOLDERS.map(folder => {
        const path = paths[folder.key]
        const info = state[folder.field]
        const valid = path ? info?.valid : null
        return (
          <div key={folder.key}>
            <p className="section-description">
              {folder.label}
              <br />
              <span className="path-hint">{folder.hint}</span>
            </p>
            <div className="iso-path-container">
              {path ? (
                <div className={`iso-path-display ${valid === true ? 'verified' : valid === false ? 'invalid' : ''}`}>
                  <span className="iso-status-icon">{busy ? '...' : valid === true ? '✓' : valid === false ? '✕' : '?'}</span>
                  <span className="iso-path-text" title={path}>{path}</span>
                  <button
                    className="iso-clear-button"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); clear(folder) }}
                    title={`Clear ${folder.label}`}
                  >
                    ×
                  </button>
                </div>
              ) : (
                <div className="iso-path-empty">{folder.empty}</div>
              )}
              <button
                className="iso-browse-button"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); browse(folder) }}
                disabled={busy}
              >
                {busy ? 'Verifying...' : path ? 'Change' : 'Browse'}
              </button>
            </div>
            {folder.field === 'kit' && valid && info?.abi && (
              <div className="derived-paths">
                <div className="derived-path">
                  <span className="derived-label">Layout id:</span>
                  <span className="derived-value">{info.abi}</span>
                </div>
              </div>
            )}
          </div>
        )
      })}

      {message.text && <div className={`message ${message.type}`}>{message.text}</div>}
    </section>
  )
}
