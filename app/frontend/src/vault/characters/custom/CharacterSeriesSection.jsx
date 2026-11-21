import { useState, useEffect, useRef } from 'react'
import { playSound, playHoverSound } from '../../../shared/audio/sounds'
import { appPrompt } from '../../../shared/ui/appDialogs'
import { API_URL, backendMediaUrl } from '../../../shared/config/config.js'
import { api } from '../../../shared/transport/api'

/**
 * The franchise line under the character name: emblem + series name, a rename
 * button for a character-owned ("custom") series, and the ✎ that opens the
 * picker below. `seriesIconBust` is owned by the page because the picker card
 * cache-busts the same uploaded icon.
 */
export function CharacterFranchiseLine({
  slug,
  detail,
  backendBase,
  seriesIconBust,
  showPicker,
  onTogglePicker,
  onRefresh,
}) {
  const customSeriesActive = detail?.custom_series?.active

  const handleRenameCustomSeries = async () => {
    const current = detail?.custom_series?.name || ''
    const name = await appPrompt('Franchise name (used to share the series between characters):', {
      title: 'Rename Franchise',
      defaultValue: current,
      confirmText: 'Save',
    })
    if (!name || name.trim() === current) return
    try {
      await api.post(`/custom-characters/${slug}/set-series-custom`, { name: name.trim() })
      playSound('boop')
      await onRefresh()
    } catch (err) {
      alert(err.message || 'Rename failed')
    }
  }

  if (detail?.series_id == null) return null

  return (
    <div className="custom-char-franchise">
      {customSeriesActive ? (
        <>
          {detail.custom_series.icon_url && (
            <img
              src={backendMediaUrl(`${detail.custom_series.icon_url}?v=${seriesIconBust}`)}
              alt=""
              className="series-emblem"
            />
          )}
          <span>{detail.custom_series.name || `Custom series ${detail.custom_series.source_id ?? ''}`}</span>
          <button
            className="series-change-btn"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); handleRenameCustomSeries() }}
            title="Rename custom franchise"
          >
            ✏ name
          </button>
        </>
      ) : (
        <>
          {detail.series_icon_url && (
            <img
              src={backendMediaUrl(detail.series_icon_url)}
              alt=""
              className="series-emblem"
            />
          )}
          <span>{detail.series_name || `Series ${detail.series_id} (custom, not extracted)`}</span>
        </>
      )}
      <button
        className="series-change-btn"
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('boop'); onTogglePicker(!showPicker) }}
        title="Change franchise"
      >
        ✎
      </button>
    </div>
  )
}

/**
 * The franchise picker card: every extracted vanilla series, this character's
 * own custom series, and an upload slot for a hand-made emblem. Always mounted
 * (it loads the series list once) but only visible while `show` is set.
 */
export default function SeriesPicker({
  show,
  slug,
  detail,
  backendBase,
  seriesIconBust,
  onClose,
  onIconBust,
  onRefresh,
}) {
  const [seriesList, setSeriesList] = useState([])
  const seriesFileRef = useRef(null)

  useEffect(() => {
    api.get(`/custom-characters/series-list`)
      .then(data => setSeriesList(data.series || []))
      .catch(err => console.error('Failed to fetch series list:', err))
  }, [API_URL])

  const handleSetSeries = async (seriesId) => {
    try {
      await api.post(`/custom-characters/${slug}/set-series`, { seriesId })
      playSound('boop')
      onClose()
      await onRefresh()
    } catch (err) {
      alert(err.message || 'Failed to set franchise')
    }
  }

  const handleActivateCustomSeries = async () => {
    try {
      await api.post(`/custom-characters/${slug}/set-series-custom`, {})
      playSound('boop')
      onClose()
      await onRefresh()
    } catch (err) {
      alert(err.message || 'Failed to activate custom franchise')
    }
  }

  const handleUploadSeriesIcon = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    try {
      await api.post(`/custom-characters/${slug}/replace-series-icon`, formData)
      playSound('newSkin')
      onClose()
      onIconBust(Date.now())
      await onRefresh()
    } catch (err) {
      alert(err.message || 'Icon upload failed')
    }
  }

  if (!show) return null

  const customSeriesActive = detail?.custom_series?.active

  return (
    <div className="series-picker">
      {detail?.custom_series && (
        <button
          className={`series-pick series-pick--custom ${customSeriesActive ? 'active' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={handleActivateCustomSeries}
          title="Use this character's own franchise (added to your project on install)"
        >
          {detail.custom_series.icon_url ? (
            <img src={backendMediaUrl(`${detail.custom_series.icon_url}?v=${seriesIconBust}`)} alt="" />
          ) : (
            <span className="series-pick-noicon">★</span>
          )}
          <span className="series-pick-name">{detail.custom_series.name || 'Custom'}</span>
        </button>
      )}
      {seriesList.map((s) => (
        <button
          key={s.id}
          className={`series-pick ${!customSeriesActive && s.id === detail?.series_id ? 'active' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={() => handleSetSeries(s.id)}
          title={s.name}
        >
          {s.icon_url ? (
            <img src={backendMediaUrl(s.icon_url)} alt={s.name} />
          ) : (
            <span className="series-pick-noicon">?</span>
          )}
          <span className="series-pick-name">{s.name}</span>
        </button>
      ))}
      <button
        className="series-pick series-pick--upload"
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('boop'); seriesFileRef.current?.click() }}
        title="Upload your own franchise icon (PNG, shown at 80x64)"
      >
        <span className="series-pick-noicon">⬆</span>
        <span className="series-pick-name">Upload PNG…</span>
      </button>
      <input
        ref={seriesFileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={handleUploadSeriesIcon}
        style={{ display: 'none' }}
      />
    </div>
  )
}
