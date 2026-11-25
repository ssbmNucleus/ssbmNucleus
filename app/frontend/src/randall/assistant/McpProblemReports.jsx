/**
 * The problem reports the user's own AI wrote over MCP (report_problem), waiting for the person here.
 *
 * Nothing was sent when the AI made one. This shows the oldest waiting report in the "Report this
 * chat" card: who wrote it, its title and markdown, every attachment with its size and a checkbox
 * for each optional one, and Send and Discard. Send freezes the ticked parts and sends them through
 * the chat report's own submit; Discard deletes the report. See problemReport.js for the flow and
 * docs/dev/APP_MCP.md (Problem reports) for what is collected.
 */
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../shared/transport/api'
import { subscribe as subscribeSocket } from '../../shared/transport/socket'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { formatBytes } from '../chat/ChatReportModal'
import {
  PROBLEM_CONSENT, REPORT_EVENT, discardProblemReport, initialChoice, listReports, problemErrorView,
  sendProblemReport, sendSummary, whoWrote,
} from './problemReport'
import '../../shared/ui/CreditsModalChrome.css'
import '../chat/ChatReportModal.css'
import './McpProblemReports.css'

/** One attachment row: a checkbox when it is optional, "always sent" when it is not. */
export function AttachmentRow({ part, checked, disabled, onToggle }) {
  const size = formatBytes(Number(part.bytes) || 0)
  if (!part.optional) {
    return <li className="problem-report-part">
      <span className="problem-report-part-name">{part.label} <code>{part.name}</code></span>
      <span className="problem-report-part-size">{size} · always sent</span>
    </li>
  }
  return <li className="problem-report-part">
    <label className="chat-report-files-toggle">
      <input type="checkbox" checked={!part.too_large && checked} disabled={disabled || part.too_large}
        onChange={event => onToggle?.(part.name, event.target.checked)} />
      <span className="problem-report-part-name">{part.label} <code>{part.name}</code></span>
    </label>
    <span className="problem-report-part-size">{size}{part.too_large ? ' · too large to send' : ''}</span>
  </li>
}

/** Everything the card renders, as a pure function of its state (tests render it without a DOM). */
export function ProblemReportView({ report, choice = {}, phase = 'ready', error = null, gate = null, result = null,
  waiting = 1, onToggle, onSend, onDiscard, onClose }) {
  const busy = phase === 'sending' || phase === 'discarding'
  const summary = sendSummary(report, choice)
  return <div className="credits-modal chat-report-modal problem-report-modal" role="dialog" aria-modal="true"
    aria-labelledby="problem-report-title" onClick={event => event.stopPropagation()}>
    <h2 id="problem-report-title" className="credits-modal-title">Report a problem</h2>
    {gate ? <div className="chat-report-gate">
      <p className="credits-modal-sub">A newer version{gate.latest ? ` (v${gate.latest})` : ''} is available.
        Update Nucleus first; the report keeps waiting here.</p>
      <p className="chat-report-muted">Settings → Updates installs the new version.</p>
    </div> : result ? <div className="chat-report-done">
      <p className="credits-modal-sub">Sent. Thank you — this goes straight to the developer.</p>
      {result.id && <p className="chat-report-id">Reference: {String(result.id).slice(0, 8)}</p>}
    </div> : <>
      <p className="credits-modal-sub">{whoWrote(report)} wrote a problem report for the Nucleus developer and
        asks you to send it. Read it, choose what goes with it, then Send or Discard.</p>
      <p className="problem-report-heading">{report.title}</p>
      <pre className="problem-report-markdown" aria-label="The report">{report.markdown}</pre>
      <ul className="problem-report-parts">
        {(report.attachments || []).map(part => <AttachmentRow key={part.name} part={part}
          checked={choice[part.name] === true} disabled={busy} onToggle={onToggle} />)}
      </ul>
      <p className="chat-report-muted">Sends {summary.count} part{summary.count === 1 ? '' : 's'},
        {' '}{formatBytes(summary.bytes)}. Your user name is masked in paths; passwords and keys are removed.</p>
      <p className="chat-report-muted chat-report-consent">{PROBLEM_CONSENT}</p>
      {waiting > 1 && <p className="chat-report-muted">{waiting - 1} more waiting after this one.</p>}
      {error && <p className="update-status-error chat-report-error" role="alert">{error}</p>}
    </>}
    <div className="credits-modal-buttons chat-report-buttons">
      {!result && !gate && <>
        <button type="button" className="restore-button chat-report-send" disabled={busy}
          onMouseEnter={playHoverSound} onClick={onSend}>{phase === 'sending' ? 'Sending…' : 'Send'}</button>
        <button type="button" className="credits-close-button" disabled={busy} onMouseEnter={playHoverSound}
          onClick={onDiscard}>{phase === 'discarding' ? 'Discarding…' : 'Discard'}</button>
      </>}
      {(result || gate) && <button type="button" className="credits-close-button" onMouseEnter={playHoverSound}
        onClick={onClose}>Close</button>}
    </div>
  </div>
}

export default function McpProblemReports() {
  const [reports, setReports] = useState([])
  const [shown, setShown] = useState(null)          // the report on screen, kept while its outcome shows
  const [choice, setChoice] = useState({})
  const [phase, setPhase] = useState('ready')       // ready | sending | discarding | done
  const [error, setError] = useState(null)
  const [gate, setGate] = useState(null)
  const [result, setResult] = useState(null)

  const refresh = useCallback(() => {
    listReports(api).then(setReports).catch(() => {})     // backend restarting: the reconnect reads it again
  }, [])

  useEffect(() => {
    refresh()
    return subscribeSocket({ [REPORT_EVENT]: refresh, connect: refresh })
  }, [refresh])

  useEffect(() => {
    if (shown || !reports.length) return
    setShown(reports[0]); setChoice(initialChoice(reports[0]))
    setPhase('ready'); setError(null); setGate(null); setResult(null)
  }, [reports, shown])

  if (!shown) return null

  const toggle = (name, on) => setChoice(current => ({ ...current, [name]: on }))

  const send = async () => {
    if (phase !== 'ready') return
    setPhase('sending'); setError(null)
    try {
      const version = await Promise.resolve(window.electron?.getAppVersion?.()).catch(() => null)
      const outcome = await sendProblemReport(api, shown, choice, version || undefined)
      playSound('start')
      setResult(outcome); setPhase('done')
    } catch (err) {
      const view = problemErrorView(err)
      if (view.kind === 'gate') setGate(view); else setError(view.text)
      setPhase('ready')
    }
    refresh()
  }

  const discard = async () => {
    if (phase !== 'ready') return
    setPhase('discarding'); setError(null)
    try {
      await discardProblemReport(api, shown)
      playSound('back')
      setShown(null)
    } catch (err) {
      setError(problemErrorView(err).text)
    }
    setPhase('ready')
    refresh()
  }

  const close = () => {
    playSound('back')
    setShown(null)
    refresh()
  }

  const waiting = Math.max(1, reports.filter(r => r.id !== shown.id).length + 1)
  return <div className="credits-overlay">
    <ProblemReportView report={shown} choice={choice} phase={phase} error={error} gate={gate} result={result}
      waiting={waiting} onToggle={toggle} onSend={send} onDiscard={discard} onClose={close} />
  </div>
}
