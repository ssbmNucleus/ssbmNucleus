/**
 * CodesPasteModal - the "carelessly paste anything" import flow for gecko codes.
 *
 * Textarea -> POST /codes/vault/parse (smart parser: raw hex, INI blocks,
 * Dolphin ini, loose forum pastes) -> editable preview cards -> save the
 * checked, valid ones to the vault. Invalid codes render greyed with their
 * compile error and cannot be selected.
 */
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'
import '../../shared/ui/EditModal.css'
import './GeckoCodes.css'
import './CodesPasteModal.css'

export default function CodesPasteModal({ show, onClose, onSaved }) {
  const [text, setText] = useState('')
  const [parsing, setParsing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState(null)   // {codes:[{...,checked}], warnings}
  const [summary, setSummary] = useState('')

  if (!show) return null

  const reset = () => {
    setText(''); setPreview(null); setSummary(''); setParsing(false); setSaving(false)
  }

  const handleClose = () => { playSound('back'); reset(); onClose?.() }

  const handleParse = async () => {
    setParsing(true)
    setSummary('')
    try {
      const data = await api.post('/codes/vault/parse', { text })
      setPreview({
        codes: (data.codes || []).map((c) => ({ ...c, checked: c.valid })),
        warnings: data.warnings || [],
      })
    } catch (err) {
      setSummary(`Parse failed: ${err.message}`)
    } finally {
      setParsing(false)
    }
  }

  const handleSave = async () => {
    const chosen = preview.codes.filter((c) => c.checked && c.valid)
    if (chosen.length === 0) return
    setSaving(true)
    try {
      const data = await api.post('/codes/vault/save', { codes: chosen })
      playSound('newSkin')
      const skippedNote = data.skipped?.length
        ? ` — ${data.skipped.length} skipped (${data.skipped.map((s) => s.reason)[0]})`
        : ''
      setSummary(`Added ${data.added.length} code${data.added.length === 1 ? '' : 's'}${skippedNote}`)
      await onSaved?.()
      if (!data.skipped?.length) {
        reset()
        onClose?.()
      }
    } catch (err) {
      setSummary(`Save failed: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  const updateCode = (idx, patch) => {
    setPreview((p) => ({
      ...p,
      codes: p.codes.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    }))
  }

  const checkedCount = preview ? preview.codes.filter((c) => c.checked && c.valid).length : 0

  const modal = (
    <div className="edit-modal-fullscreen-overlay" onClick={handleClose}>
      <div className="edit-modal-fullscreen codes-paste-modal" onClick={(e) => e.stopPropagation()}>
        <div className="edit-modal-header">
          <h2>Paste Codes</h2>
        </div>

        {!preview ? (
          <>
            <div className="codes-paste-hint">
              Paste anything: raw hex lines, a <code>$Name [Creator]</code> INI
              block (one or many codes), a Dolphin ini section, or a loose
              copy-paste from a forum thread. It gets figured out.
            </div>
            <textarea
              className="codes-paste-textarea"
              spellCheck={false}
              autoFocus
              placeholder={'Widescreen 16:9 [dan]\n04452C68 C0A00000\n...'}
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={parsing}
            />
            <div className="edit-modal-actions">
              <button
                className="edit-modal-action-btn edit-modal-action-btn--save"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); handleParse() }}
                disabled={parsing || !text.trim()}
              >
                {parsing ? 'Parsing...' : 'Preview'}
              </button>
              <button
                className="edit-modal-action-btn edit-modal-action-btn--cancel"
                onClick={handleClose}
                disabled={parsing}
              >
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="codes-preview-list">
              {preview.warnings.map((w, i) => (
                <div key={`w${i}`} className="codes-warning-text">⚠ {w}</div>
              ))}
              {preview.codes.length === 0 && (
                <div className="codes-empty">Nothing parseable found — go back and check the paste.</div>
              )}
              {preview.codes.map((c, idx) => (
                <div key={idx} className={`codes-preview-card ${c.valid ? '' : 'invalid'}`}>
                  <div className="codes-preview-card-head">
                    <input
                      type="checkbox"
                      checked={c.checked && c.valid}
                      disabled={!c.valid}
                      onChange={(e) => updateCode(idx, { checked: e.target.checked })}
                    />
                    <input
                      className="codes-preview-name"
                      type="text"
                      value={c.name}
                      onChange={(e) => updateCode(idx, { name: e.target.value })}
                      placeholder="Code name"
                      disabled={!c.valid}
                    />
                    <input
                      className="codes-preview-creator"
                      type="text"
                      value={c.creator || ''}
                      onChange={(e) => updateCode(idx, { creator: e.target.value })}
                      placeholder="Creator"
                      disabled={!c.valid}
                    />
                    <input
                      className="codes-preview-category"
                      type="text"
                      value={c.category || ''}
                      onChange={(e) => updateCode(idx, { category: e.target.value })}
                      placeholder="Category"
                      disabled={!c.valid}
                    />
                  </div>
                  {!c.valid && <div className="codes-error-text">{c.error}</div>}
                  {c.warnings?.map((w, i) => (
                    <div key={i} className="codes-warning-text">⚠ {w}</div>
                  ))}
                  <pre className="codes-preview-hex">{c.source}</pre>
                </div>
              ))}
            </div>
            {summary && <div className="codes-summary-text">{summary}</div>}
            <div className="edit-modal-actions">
              <button
                className="edit-modal-action-btn edit-modal-action-btn--save"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); handleSave() }}
                disabled={saving || checkedCount === 0}
              >
                {saving ? 'Saving...' : `Add ${checkedCount} to Vault`}
              </button>
              <button
                className="edit-modal-action-btn edit-modal-action-btn--cancel"
                onClick={() => { playSound('back'); setPreview(null); setSummary('') }}
                disabled={saving}
              >
                Back
              </button>
              <button
                className="edit-modal-action-btn edit-modal-action-btn--cancel"
                onClick={handleClose}
                disabled={saving}
              >
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
