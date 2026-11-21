/**
 * ImportFab - THE import affordance for the whole vault.
 *
 * A floating bottom-right button that is always visible across every storage
 * view, plus a window-wide drag-and-drop overlay. Both feed the unified
 * /import/file pipeline, which auto-detects costumes, stages, custom
 * characters/stages (incl. classic stage.yml packages), bundles, xdelta
 * patches, menu mods (compiled files or loose pictures), and effect files —
 * so this one button replaces the per-view import buttons that used to be
 * scattered around the app.
 */
import { useEffect, useRef, useState } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { DOWN, next } from './importDrag'
import './ImportFab.css'

const ACCEPT = '.zip,.7z,.rar,.dat,.usd,.xdelta,.ssbm,.iso,.gcm,.png,.jpg,.jpeg,.webp'

export default function ImportFab({ importing, importMessage, onImportFiles }) {
  const [dragActive, setDragActive] = useState(false)
  const dragDepth = useRef(DOWN)
  const fab = useRef(null)

  useEffect(() => {
    // Only react to OS file drags. Two guards: (1) an explicit flag set by
    // internal card drags (reorder / costume-to-skin) — Electron sometimes
    // reports 'Files' in dataTransfer.types even for in-app element drags, so
    // the type check alone isn't enough; (2) the dataTransfer 'Files' type.
    const hasFiles = (e) => {
      if (document.documentElement.dataset.nucInternalDrag === '1') return false
      return Array.from(e.dataTransfer?.types || []).includes('Files')
    }

    // The vault stays mounted while the AI page or another tab covers it
    // (display: none further up), and then this button has no box.
    const onScreen = () => Boolean(fab.current?.getClientRects().length)

    // When the screen is up (importDrag.js). Heard on the way down, before any
    // handler below: a chat takes its own drops and stops them there, and the
    // screen has to come down all the same.
    const track = (e) => {
      const files = hasFiles(e)
      if (files && e.type === 'dragenter') e.preventDefault()
      dragDepth.current = next(dragDepth.current, { type: e.type, files, onScreen: onScreen() })
      setDragActive(dragDepth.current > DOWN)
    }
    const onDragOver = (e) => {
      if (!hasFiles(e)) return
      e.preventDefault()
    }
    // The import itself stays on the way up: a drop a chat took is not ours.
    const onDrop = (e) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      const files = Array.from(e.dataTransfer.files || [])
      if (files.length) {
        playSound('start')
        onImportFiles(files)
      }
    }

    const ENDS = ['dragenter', 'dragleave', 'drop', 'dragend']
    ENDS.forEach(type => window.addEventListener(type, track, true))
    window.addEventListener('dragover', onDragOver)
    window.addEventListener('drop', onDrop)
    return () => {
      ENDS.forEach(type => window.removeEventListener(type, track, true))
      window.removeEventListener('dragover', onDragOver)
      window.removeEventListener('drop', onDrop)
    }
  }, [onImportFiles])

  const isError = importMessage &&
    (importMessage.includes('✗') || importMessage.includes('failed') || importMessage.includes('Error'))

  return (
    <>
      {dragActive && (
        <div className="import-drop-overlay">
          <div className="import-drop-card">
            <div className="import-drop-title">Drop to import</div>
            <div className="import-drop-subtitle">
              skins · stages · custom characters · patches · bundles · menu mods · effects · pictures · ISOs to scan
            </div>
          </div>
        </div>
      )}

      <div className="import-fab-container" ref={fab}>
        {importMessage && (
          <div className={`import-fab-toast ${isError ? 'error' : 'success'}`}>
            {importMessage}
          </div>
        )}
        <label
          className={`import-fab ${importing ? 'busy' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={() => { if (!importing) playSound('start') }}
          title="Import anything — skins, stages, custom characters, patches, bundles, menu mods, effect files, pictures (doors, pause screens, glyph packs), or ISOs to scan. Or just drop files anywhere."
        >
          <span className="import-fab-icon">{importing ? '⋯' : '+'}</span>
          <span className="import-fab-label">{importing ? 'Importing' : 'Import'}</span>
          <input
            type="file"
            accept={ACCEPT}
            onChange={(e) => {
              const files = Array.from(e.target.files || [])
              e.target.value = null
              if (files.length) onImportFiles(files)
            }}
            disabled={importing}
            multiple
            style={{ display: 'none' }}
          />
        </label>
      </div>
    </>
  )
}
