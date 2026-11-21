import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import '../lib/NoticeModal.css'

// Shown once, before the first share link this install ever mints. Sharing is
// free and ungated; this is consent, not a gate. It says the three things that
// are true and not obvious from a button labelled "share": the replay leaves
// the machine, the link needs no account, and it does not expire.

export const SHARE_NOTICE_ACK_KEY = 'nucleus.share.noticeAck'

export function shareNoticeAcknowledged() {
  try {
    return localStorage.getItem(SHARE_NOTICE_ACK_KEY) === '1'
  } catch {
    // Private-mode / storage-disabled: ask every time rather than assume
    // consent that was never given.
    return false
  }
}

export function acknowledgeShareNotice() {
  try {
    localStorage.setItem(SHARE_NOTICE_ACK_KEY, '1')
  } catch { /* the share still proceeds; we just ask again next time */ }
}

export default function ShareNoticeModal({ onConfirm, onCancel }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  // Portalled to <body>: this mounts inside combo/replay ROWS, whose entrance
  // animations (transform) would otherwise hijack position:fixed and pin the
  // "fullscreen" backdrop to the row.
  return createPortal(
    <div className="share-notice-backdrop" onClick={() => { playSound('boop'); onCancel() }}>
      <div className="share-notice" onClick={(e) => e.stopPropagation()}>
        <button className="share-notice-close" aria-label="Cancel"
                onClick={() => { playSound('boop'); onCancel() }}>✕</button>
        <h2 className="share-notice-title">Before you share</h2>
        <ul className="share-notice-body">
          <li>This replay — and a small thumbnail of it — gets uploaded to ssbmnucleus.net.</li>
          <li>Anyone with the link can watch it. No account needed.</li>
          <li>The link is permanent.</li>
        </ul>
        <div className="share-notice-actions">
          <button
            type="button" className="share-notice-btn"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); onCancel() }}
          >
            Cancel
          </button>
          <button
            type="button" className="share-notice-btn share-notice-btn--go"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); onConfirm() }}
          >
            Create link
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
