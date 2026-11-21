/**
 * "Report this chat" -- send one Randall conversation privately to the developer.
 *
 * Same look as BugReportModal. On open the backend freezes the report and says
 * exactly what is in it (the "What gets sent" list and the readable transcript);
 * nothing leaves the machine until Send is clicked. When the conversation has
 * files (a model import), one toggle -- on by default -- decides whether the
 * files the user attached go too; flipping it freezes a new preview. See
 * chatReport.js for the send flow and docs/RANDALL.md (Report this chat) for what is
 * collected.
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../../shared/transport/api'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { CONSENT_LINE, FILES_HINT, FILES_LABEL, errorView, reviewReport, sendReport } from './chatReport'
import '../../shared/ui/CreditsModalChrome.css'
import './ChatReportModal.css'

const FlagIcon = () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
  <path d="M5 21V4" /><path d="M5 4h11l-2 4 2 4H5" />
</svg>

/** The quiet header control. Hidden until there is a saved conversation. */
export function ReportChatButton({ conversationId, messageCount, busy, onClick }) {
  if (!conversationId || !messageCount) return null
  return <button type="button" className="chat-report-button" onClick={onClick} disabled={busy}
    onMouseEnter={playHoverSound}
    aria-label="Report this chat"
    title={busy ? 'Report this chat (available when Randall finishes)' : 'Report this chat'}>
    <FlagIcon />
  </button>
}

export function ReportPreview({ review }) {
  if (!review) return <p className="chat-report-muted" role="status">Preparing the preview…</p>
  return <details className="chat-report-preview">
    <summary>What gets sent</summary>
    <ul>{review.includes.map(line => <li key={line}>{line}</li>)}</ul>
    <p className="chat-report-muted">Not included:</p>
    <ul className="chat-report-excluded">{review.not_included.map(line => <li key={line}>{line}</li>)}</ul>
    <p className="chat-report-muted">Files: {review.manifest.members.map(m => `${m.name} (${formatBytes(m.bytes)})`).join(', ')}</p>
    <details className="chat-report-transcript">
      <summary>Show the conversation as the developer will read it</summary>
      <pre>{review.transcript}</pre>
    </details>
  </details>
}

/**
 * "Include the files I attached (N MB)". Shown only when the conversation has
 * files to offer; `bytes` is what goes when it is on.
 */
export function FilesToggle({ offered, bytes, checked, disabled, onChange }) {
  if (!offered) return null
  return <div className="chat-report-files">
    <label className="chat-report-files-toggle">
      <input type="checkbox" checked={checked} disabled={disabled}
        onChange={event => onChange?.(event.target.checked)} />
      <span>{FILES_LABEL}{bytes ? ` (${formatBytes(bytes)})` : ''}</span>
    </label>
    <p className="chat-report-muted">{FILES_HINT}</p>
  </div>
}

export function formatBytes(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * Everything the modal renders, as a pure function of its state, so tests can
 * render each state without a DOM.
 */
export function ChatReportView({ phase, review, note, contact, error, gate, result, changed,
  includeFiles = true, filesOffered = 0, filesBytes = 0, onIncludeFiles, onNote, onContact, onSend, onClose }) {
  const sending = phase === 'sending'
  return <div className="credits-modal chat-report-modal" role="dialog" aria-modal="true"
    aria-labelledby="chat-report-title" onClick={event => event.stopPropagation()}>
    <h2 id="chat-report-title" className="credits-modal-title">Report this chat</h2>
    {gate ? <div className="chat-report-gate">
      <p className="credits-modal-sub">A newer version{gate.latest ? ` (v${gate.latest})` : ''} is available.
        Update Nucleus first, then report the chat again if the problem is still there.</p>
      <p className="chat-report-muted">Settings → Updates installs the new version.</p>
    </div> : result ? <div className="chat-report-done">
      <p className="credits-modal-sub">Sent. Thank you — this goes straight to the developer.</p>
      {result.id && <p className="chat-report-id">Reference: {String(result.id).slice(0, 8)}</p>}
    </div> : <>
      <p className="credits-modal-sub chat-report-consent">{CONSENT_LINE}</p>
      <label className="chat-report-label" htmlFor="chat-report-note">What went wrong? (optional)</label>
      <textarea id="chat-report-note" className="chat-report-note" rows={4} maxLength={4000}
        value={note} disabled={sending} onChange={event => onNote?.(event.target.value)}
        placeholder="e.g. It said the costume was installed, but the game still shows the old one." />
      <input className="chat-report-contact" type="text" maxLength={200} value={contact} disabled={sending}
        aria-label="Contact (optional)" onChange={event => onContact?.(event.target.value)}
        placeholder="How can we reach you? Discord or email (optional)" />
      <FilesToggle offered={filesOffered} bytes={filesBytes} checked={includeFiles}
        disabled={sending || phase === 'loading'} onChange={onIncludeFiles} />
      {changed && <p className="chat-report-notice" role="status">This chat or its files changed since the preview.
        Nothing was sent. Check what gets sent, then press Send again.</p>}
      <ReportPreview review={review} />
      {error && <p className="update-status-error chat-report-error" role="alert">{error}</p>}
    </>}
    <div className="credits-modal-buttons chat-report-buttons">
      {!result && !gate && <button type="button" className="restore-button chat-report-send"
        disabled={sending || phase === 'loading' || !review} onMouseEnter={playHoverSound} onClick={onSend}>
        {sending ? 'Sending…' : 'Send'}</button>}
      <button type="button" className="credits-close-button" disabled={sending} onMouseEnter={playHoverSound}
        onClick={onClose}>{result || gate ? 'Close' : 'Cancel'}</button>
    </div>
  </div>
}

/**
 * props: show, onClose, surface ('mods' | 'tracker'), conversationId, budget
 */
export default function ChatReportModal({ show, onClose, surface, conversationId, budget }) {
  const [phase, setPhase] = useState('loading')   // loading | ready | sending | done
  const [review, setReview] = useState(null)
  const [note, setNote] = useState('')
  const [contact, setContact] = useState('')
  const [error, setError] = useState(null)
  const [gate, setGate] = useState(null)
  const [result, setResult] = useState(null)
  const [changed, setChanged] = useState(false)
  const [appVersion, setAppVersion] = useState(undefined)
  const [includeFiles, setIncludeFiles] = useState(true)
  // What the toggle offers, kept from the last preview that had it on, so the
  // size still shows after it is switched off.
  const [filesOffered, setFilesOffered] = useState(0)
  const [filesBytes, setFilesBytes] = useState(0)
  // Only the newest preview request may land; a toggle flip or close drops older ones.
  const ticket = useRef(0)

  async function preview(include, version) {
    const mine = ++ticket.current
    setPhase('loading'); setReview(null); setError(null); setChanged(false)
    try {
      const data = await reviewReport(api, { surface, conversationId, appVersion: version, budget, includeFiles: include })
      if (mine !== ticket.current) return
      setReview(data); setPhase('ready')
      setFilesOffered(data.files?.offer_count || 0)
      if (include) setFilesBytes(data.files?.send_bytes || 0)
    } catch (err) {
      if (mine !== ticket.current) return
      const view = errorView(err)
      if (view.kind === 'gate') setGate(view); else setError(view.text)
      setPhase('ready')
    }
  }

  // Fresh state and a fresh preview each time it opens for a conversation.
  useEffect(() => {
    if (!show) return undefined
    let live = true
    setPhase('loading'); setReview(null); setNote(''); setContact(''); setError(null)
    setGate(null); setResult(null); setChanged(false)
    setIncludeFiles(true); setFilesOffered(0); setFilesBytes(0)
    ;(async () => {
      const version = await Promise.resolve(window.electron?.getAppVersion?.()).catch(() => null)
      if (!live) return
      setAppVersion(version || undefined)
      await preview(true, version || undefined)
    })()
    return () => { live = false; ticket.current += 1 }
  }, [show, surface, conversationId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!show) return undefined
    const onKey = event => { if (event.key === 'Escape' && phase !== 'sending') close() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  if (!show) return null

  function close() {
    if (phase === 'sending') return
    playSound('back')
    onClose()
  }

  const toggleFiles = include => {
    if (phase === 'sending') return
    setIncludeFiles(include)
    preview(include, appVersion)
  }

  const send = async () => {
    if (phase === 'sending' || !review) return
    setPhase('sending'); setError(null)
    try {
      const outcome = await sendReport(api, { surface, conversationId, note, contact, appVersion, budget, includeFiles }, review)
      if (outcome.state === 'changed') {
        setReview(outcome.review); setChanged(true); setPhase('ready')
        return
      }
      playSound('start')
      setResult(outcome); setPhase('done')
    } catch (err) {
      const view = errorView(err)
      if (view.kind === 'gate') setGate(view); else setError(view.text)
      setPhase('ready')
    }
  }

  return <div className="credits-overlay" onClick={close}>
    <ChatReportView phase={phase} review={review} note={note} contact={contact} error={error} gate={gate}
      result={result} changed={changed} includeFiles={includeFiles} filesOffered={filesOffered} filesBytes={filesBytes}
      onIncludeFiles={toggleFiles} onNote={setNote} onContact={setContact} onSend={send} onClose={close} />
  </div>
}
