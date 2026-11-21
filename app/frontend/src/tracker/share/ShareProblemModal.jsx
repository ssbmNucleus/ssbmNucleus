import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { buildPatreonAuthorizeUrl, openExternal, PATREON_CAMPAIGN_URL } from '../../shared/account/entitlement'
import { cloudErrorKind, friendlyCloudError } from '../cloud/cloudErrors'
import '../lib/NoticeModal.css'

// Why a share link could not be made, and the button that fixes it. This used
// to be a red ✕ with the reason in a 1.8-second tooltip, sometimes as raw JSON
// from the vault; the two commonest reasons (no Patreon linked, a Patreon that
// follows but never joined) are one click from fixed, so the fix sits here.

const openCloudSettings = () =>
  window.dispatchEvent(new CustomEvent('nucleus:open-settings', { detail: { section: 'cloud' } }))

export function shareProblem(message, status, what = 'game') {
  const kind = cloudErrorKind(message, status) || 'other'
  const text = friendlyCloudError(message, status) || `Couldn't make a link for this ${what}. Try again.`
  if (kind === 'not_linked') {
    return {
      kind,
      title: 'Link Patreon to share',
      body: ['Sharing a replay is free.', 'Link a Patreon account (a free one is enough) and this ' + what + ' gets a permanent link.'],
      primary: { label: 'Link Patreon', run: () => openExternal(buildPatreonAuthorizeUrl()) },
      secondary: { label: 'What the cloud includes', run: openCloudSettings },
    }
  }
  if (kind === 'not_member') {
    return {
      kind,
      title: 'Join for free to share',
      body: [
        "Your Patreon is linked, but it isn't a member of sc00p's Patreon yet. Following isn't enough.",
        'Choose Join on the free tier, then link Patreon again so Nucleus sees it.',
      ],
      primary: { label: 'Join free on Patreon', run: () => openExternal(PATREON_CAMPAIGN_URL) },
      secondary: { label: 'Joined already? Link Patreon again', run: () => openExternal(buildPatreonAuthorizeUrl()) },
    }
  }
  if (kind === 'relink' || kind === 'refused') {
    return {
      kind,
      title: 'Link Patreon again',
      body: [text],
      primary: { label: 'Link Patreon', run: () => openExternal(buildPatreonAuthorizeUrl()) },
    }
  }
  return {
    kind,
    title: `Couldn't share this ${what}`,
    body: [text],
    retry: ['offline', 'server', 'quota', 'other'].includes(kind),
  }
}

export default function ShareProblemModal({ problem, onClose, onRetry }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const act = (run) => () => { playSound('boop'); run(); onClose() }

  // Portalled to <body> for the same reason as ShareNoticeModal: the button
  // lives inside animated rows whose transform would capture position:fixed.
  return createPortal(
    <div className="share-notice-backdrop" onClick={() => { playSound('boop'); onClose() }}>
      <div className="share-notice" role="alertdialog" aria-labelledby="share-problem-title"
           onClick={(e) => e.stopPropagation()}>
        <button className="share-notice-close" aria-label="Close"
                onClick={() => { playSound('boop'); onClose() }}>✕</button>
        <h2 className="share-notice-title" id="share-problem-title">{problem.title}</h2>
        <div className="share-notice-body share-problem-body">
          {problem.body.map((line) => <p key={line}>{line}</p>)}
        </div>
        {problem.secondary && (
          <button type="button" className="share-problem-link" onMouseEnter={playHoverSound}
                  onClick={act(problem.secondary.run)}>
            {problem.secondary.label}
          </button>
        )}
        <div className="share-notice-actions">
          <button type="button" className="share-notice-btn" onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); onClose() }}>
            Close
          </button>
          {problem.retry && onRetry && (
            <button type="button" className="share-notice-btn share-notice-btn--go" onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); onRetry() }}>
              Try again
            </button>
          )}
          {problem.primary && (
            <button type="button" className="share-notice-btn share-problem-patreon" onMouseEnter={playHoverSound}
                    onClick={act(problem.primary.run)}>
              {problem.primary.label}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
