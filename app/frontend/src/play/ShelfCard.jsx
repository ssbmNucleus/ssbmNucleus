/**
 * ShelfCard - one game on the shelf: its picture (coverKind: the built-in Nucleus Unlocked game's is drawn
 * from the app's own logo and the game's name, Vanilla's is the user's disc banner, an added game's is its
 * cover), its name and one line (cardLine), what state it is in (playCards.js), and its Play
 * button, with the quieter menu and "where to play" beside it. With no game client installed the
 * built-in cards' button installs it (Install, then Installing 42%, then Play), and a newer client
 * shows as a quiet line under them (clientUpdate) that never stops Play. Names and descriptions
 * are rendered as text.
 */
import { useLayoutEffect, useRef, useState } from 'react'
import { backendMediaUrl } from '../shared/config/config'
import { playHoverSound } from '../shared/audio/sounds'
import { bannerFit, cardLine, cardState, clientUpdate, coverKind, engineNote, percent } from './playCards'

/** The Nucleus Unlocked game's picture: the app's logo and the game's name in the header wordmark's style, banner-shaped like Vanilla's. */
function NucleusArt() {
  return (
    <span className="play-art-nucleus" aria-hidden="true">
      <img className="play-art-nucleus-logo" src="./nucleuslogo.svg" alt="" />
      <span className="play-art-nucleus-word">
        <span className="play-art-nucleus-name">Nucleus</span> Unlocked
      </span>
    </span>
  )
}

/**
 * Vanilla's picture: the disc's whole 96x32 banner, framed as the Projects page frames it, at the
 * largest whole-pixel size that fits the picture area (bannerFit), so it stays sharp and uncropped.
 * Sized again when the area changes or the display's scaling does.
 */
function BannerArt({ src, onError }) {
  const area = useRef(null)
  const [fit, setFit] = useState(null)
  useLayoutEffect(() => {
    const box = area.current?.parentElement
    if (!box) return undefined
    let media = null
    const measure = () => {
      const dpr = window.devicePixelRatio || 1
      setFit(bannerFit({ width: box.clientWidth, height: box.clientHeight, dpr }))
      media?.removeEventListener('change', measure)
      media = window.matchMedia?.(`(resolution: ${dpr}dppx)`) || null
      media?.addEventListener('change', measure)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(box)
    return () => { observer.disconnect(); media?.removeEventListener('change', measure) }
  }, [])
  return (
    <span ref={area} className="play-banner-frame" style={fit ? undefined : { visibility: 'hidden' }}>
      <img src={src} alt="" onError={onError}
        style={fit ? { width: `${fit.width}px`, height: `${fit.height}px` } : undefined} />
    </span>
  )
}

function Cover({ entry, coverVersion, badge }) {
  const kind = coverKind(entry)
  const src = kind === 'banner' || kind === 'picture'
    ? backendMediaUrl(`/api/play/shelf/${encodeURIComponent(entry.id)}/cover`, coverVersion)
    : null
  const [failed, setFailed] = useState(null)
  const shown = src && failed === src ? 'plain' : kind
  return (
    <div className={`play-cover play-cover--${shown}`}>
      {shown === 'nucleus' && <NucleusArt />}
      {shown === 'banner' && <BannerArt src={src} onError={() => setFailed(src)} />}
      {shown === 'picture' && <img src={src} alt="" onError={() => setFailed(src)} />}
      {shown === 'plain' && <span className="play-cover-title" aria-hidden="true">{entry.name}</span>}
      {badge && <span className="play-cover-badge">{badge}</span>}
    </div>
  )
}

/** The quiet line about a newer client on a built-in card: never in the way of Play. */
function UpdateLine({ update, onUpdate, onCancel }) {
  if (update.busy) {
    return (
      <p className="play-card-update play-card-update--busy">
        {update.label}{update.detail ? ` (${update.detail})` : ''}{' '}
        <button type="button" className="play-link" onClick={onCancel}>Cancel</button>
      </p>
    )
  }
  return (
    <p className="play-card-update">
      A newer Nucleus Unlocked is ready.{' '}
      <button type="button" className="play-link" onMouseEnter={playHoverSound} onClick={onUpdate}>{update.label}</button>
    </p>
  )
}

export default function ShelfCard({
  entry, env, active, last, requestError, onPlay, onInstall, onUpdate, onCancelInstall, children, coverVersion,
}) {
  const [target, setTarget] = useState(null)
  const card = cardState({ entry, env, active, last, target })
  const update = clientUpdate({ entry, env })
  const reason = requestError || card.reason
  const state = requestError ? 'error' : card.state
  const engine = engineNote(entry)
  const line = cardLine(entry, card.target)
  const busy = state === 'launching' || state === 'running'
  const installing = card.state === 'installing'
  const installs = card.action === 'install'

  return (
    <article className={`play-card play-card--${state}`} data-entry={entry.id}>
      <Cover entry={entry} coverVersion={coverVersion}
        badge={busy ? (state === 'running' ? 'Playing' : 'Starting') : installing ? 'Installing' : null} />
      <div className="play-card-body">
        <h3 className="play-card-name" title={entry.name}>{entry.name}</h3>
        {line && <p className="play-card-description">{line}</p>}
        {engine && <p className="play-card-engine">{engine}</p>}
        {reason && <p className={`play-card-reason play-card-reason--${state}`} role={state === 'error' || state === 'crashed' || state === 'install-failed' ? 'alert' : undefined}>{reason}</p>}
        {installing && (
          <>
            <div className="play-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={percent(card.progress)} aria-label="Installing Nucleus Unlocked">
              <div className="play-progress-fill" style={{ width: `${percent(card.progress)}%` }} />
            </div>
            {onCancelInstall && (
              <p className="play-card-update">
                <button type="button" className="play-link" onClick={onCancelInstall}>Cancel</button>
              </p>
            )}
          </>
        )}
        {update && <UpdateLine update={update} onUpdate={onUpdate} onCancel={onCancelInstall} />}
      </div>
      <div className="play-card-actions">
        {children?.({ target: card.target, setTarget })}
        <button
          type="button"
          className="btn-primary play-button"
          disabled={installs ? !onInstall : !card.canPlay || busy}
          onMouseEnter={playHoverSound}
          onClick={() => (installs ? onInstall() : onPlay(entry, card.target))}
        >
          {card.label}
        </button>
      </div>
    </article>
  )
}
