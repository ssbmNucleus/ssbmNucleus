/**
 * BuildInfoModal - Edit the GameCube disc banner (title / creator / description)
 * and the 96x32 banner image. These are what Dolphin shows in its game list and
 * what appears on the GameCube boot screen. Reads/writes via /api/mex/project/build.
 */
import { useEffect, useState } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { rgbaToDataUrl } from './banner'
import './BuildInfoModal.css'
import { api } from '../shared/transport/api'

// GameCube banner field byte limits (mirror the backend truncation).
const FIELDS = [
  { key: 'shortName', label: 'Short Name', max: 31, hint: 'Title in the game list' },
  { key: 'longName', label: 'Long Name', max: 63, hint: 'Full title' },
  { key: 'shortMaker', label: 'Short Maker', max: 31, hint: 'Creator (short)' },
  { key: 'longMaker', label: 'Long Maker', max: 63, hint: 'Creator (full)' },
]

const EMPTY = { shortName: '', longName: '', shortMaker: '', longMaker: '', description: '' }

export default function BuildInfoModal({ show, onClose }) {
  const [form, setForm] = useState(EMPTY)
  const [previewSrc, setPreviewSrc] = useState(null)
  const [newBannerB64, setNewBannerB64] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!show) return undefined
    let cancelled = false
    setLoading(true)
    setError(null)
    setNewBannerB64(null)
    api.get('/project/build')
      .then((d) => {
        if (cancelled) return
        setForm({
          shortName: d.shortName || '',
          longName: d.longName || '',
          shortMaker: d.shortMaker || '',
          longMaker: d.longMaker || '',
          description: d.description || '',
        })
        setPreviewSrc(rgbaToDataUrl(d.bannerRgbaBase64, d.bannerWidth, d.bannerHeight))
      })
      .catch((e) => { if (!cancelled) setError(e.message || 'Failed to load banner info') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [show])

  if (!show) return null

  const update = (key, value) => setForm((f) => ({ ...f, [key]: value }))

  const handleFile = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = String(reader.result)
      setPreviewSrc(dataUrl)
      setNewBannerB64(dataUrl.split(',')[1] || null)
    }
    reader.readAsDataURL(file)
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const payload = { ...form }
      if (newBannerB64) payload.bannerPngBase64 = newBannerB64
      await api.post('/project/build', payload)
      playSound('start')
      onClose(true)
    } catch (e) {
      setError(e.message || 'Save failed')
      playSound('back')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="build-modal-overlay" onClick={() => { playSound('back'); onClose(false) }}>
      <div className="build-modal" onClick={(e) => e.stopPropagation()}>
        <h2 className="build-modal-title">Disc Banner &amp; Info</h2>
        <p className="build-modal-sub">
          Title, creator, and banner shown in Dolphin&apos;s game list and on the boot screen.
        </p>

        {loading ? (
          <div className="build-modal-loading">Loading…</div>
        ) : (
          <>
            <div className="build-modal-banner">
              <div className="build-banner-frame">
                {previewSrc ? (
                  <img className="build-banner-img" src={previewSrc} alt="Banner preview" />
                ) : (
                  <div className="build-banner-empty">No banner</div>
                )}
              </div>
              <div className="build-banner-actions">
                <input
                  id="banner-file-input"
                  type="file"
                  accept="image/*"
                  onChange={handleFile}
                  style={{ display: 'none' }}
                />
                <button
                  className="action-btn"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); document.getElementById('banner-file-input').click() }}
                >
                  Replace image…
                </button>
                <span className="build-banner-note">96 × 32 · any image, auto-resized</span>
              </div>
            </div>

            <div className="build-modal-fields">
              {FIELDS.map((f) => (
                <label key={f.key} className="build-field">
                  <span className="build-field-label">
                    {f.label}
                    <span className="build-field-count">{(form[f.key] || '').length}/{f.max}</span>
                  </span>
                  <input
                    type="text"
                    maxLength={f.max}
                    value={form[f.key]}
                    placeholder={f.hint}
                    onChange={(e) => update(f.key, e.target.value)}
                  />
                </label>
              ))}
              <label className="build-field build-field--full">
                <span className="build-field-label">
                  Description
                  <span className="build-field-count">{(form.description || '').length}/127</span>
                </span>
                <textarea
                  rows={3}
                  maxLength={127}
                  value={form.description}
                  onChange={(e) => update('description', e.target.value)}
                />
              </label>
            </div>

            {error && <div className="build-modal-error">{error}</div>}

            <div className="build-modal-buttons">
              <button
                className="action-btn export-btn"
                disabled={saving}
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); handleSave() }}
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                className="action-btn"
                disabled={saving}
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('back'); onClose(false) }}
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
