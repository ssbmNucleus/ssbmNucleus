import { useCallback, useEffect, useState } from 'react'
import WatchLiteClip from './WatchLiteClip'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import './WatchLiteModal.css'

// Full-size Watch Lite popup. Accepts a single clip (gameId/start/end) or a
// `clips` playlist [{gameId, start, end, title, subtitle}] with prev/next.
export default function WatchLiteModal({ clips, startIndex = 0, gameId, start, end, clipRef, title, subtitle, onClose }) {
  const list = (clips && clips.length) ? clips : [{ gameId, start, end, clipRef, title, subtitle }]
  const [idx, setIdx] = useState(Math.max(0, Math.min(startIndex, list.length - 1)))
  const cur = list[idx] || list[0]
  const many = list.length > 1
  const go = useCallback((d) => setIdx((i) => Math.max(0, Math.min(list.length - 1, i + d))), [list.length])
  const close = useCallback(() => { playSound('boop'); onClose() }, [onClose])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') close()
      else if (many && e.key === ']') go(1)
      else if (many && e.key === '[') go(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close, go, many])

  return (
    <div className="wl-backdrop" onClick={close}>
      <div className={`wl-modal${many ? ' wl-modal--list' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="wl-head">
          <div className="wl-title">{cur.title || title || 'Watch Lite'}
            {(cur.subtitle || subtitle) && <span className="wl-sub">{cur.subtitle || subtitle}</span>}
          </div>
          {many && <span className="wl-count">{idx + 1} / {list.length}</span>}
          <button className="wl-close" onClick={close} aria-label="Close">✕</button>
        </div>
        <div className="wl-modal-body">
          <WatchLiteClip key={idx} gameId={cur.gameId} start={cur.start} end={cur.end}
                         clipRef={cur.clipRef} title={cur.title} showPanel />
        </div>
        {many && (
          <div className="wl-controls">
            <div className="wl-nav">
              <button onMouseEnter={playHoverSound} onClick={() => go(-1)} disabled={idx === 0}>‹ Prev</button>
              <span className="wl-navpos">{idx + 1} / {list.length}</span>
              <button onMouseEnter={playHoverSound} onClick={() => go(1)} disabled={idx === list.length - 1}>Next ›</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
