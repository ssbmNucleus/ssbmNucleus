// The small set of generic cards every Randall activity is drawn with
// (ASTRA-UI-REVIEW, "I would use six generic cards"). They are selected by task
// state and evidence purpose, never by tool name: adapters in taskEnvelope.js
// turn a tool result into these props, so no renderer here branches on
// `model_fit` or `download_website_mod`.
//
// The rules they all share:
//   * running shows the current activity and Stop; a number only when measured.
//   * awaiting a decision or an approval is not a working animation.
//   * a terminal card shows the real outcome. Partial, blocked, denied and
//     cancelled look different from success -- no "Done!" that a limitation
//     underneath then takes back.
//   * the honest sentence, what was preserved, and one thing to do next.
import { ACHIEVED_LABELS, CHECK_STATUS_LABELS, checkLabel, elapsedText, moneyText, settledLines } from './activity'
import { OUTCOME_WORDS, errorText, recoveryText } from './taskEnvelope'
import { useDevDetails } from './devDetails'

const cx = (...names) => names.filter(Boolean).join(' ')

/** The three-part sentence every failed, declined, expired or stopped state gets. */
export function FailureNotice({ tool, lines }) {
  const parts = lines || settledLines(tool)
  if (!parts) return null
  return <div className="assistant-settled" role={tool?.status === 'error' ? 'alert' : 'status'}>
    <p className="assistant-settled-what">{parts.sentence}</p>
    <p className="assistant-settled-kept">{parts.preserved}</p>
    {parts.alternative && <p className="assistant-settled-next">{parts.alternative}</p>}
  </div>
}

/** Running work: the stage, how long it has taken, what stops it. Its AI cost only with developer details on:
    users never see dollars. */
export function ProgressCard({ title, progress, onStop, stopping, compact }) {
  const devDetails = useDevDetails()
  if (!progress) return null
  const { stage, elapsedSeconds, estimateSeconds, costUsd, costPending, waitingReason } = progress
  const waiting = Boolean(waitingReason)
  const facts = [
    Number.isFinite(elapsedSeconds) ? `${elapsedText(elapsedSeconds)} so far` : null,
    Number.isFinite(estimateSeconds) ? `about ${elapsedText(estimateSeconds)} expected` : null,
    Number.isFinite(progress.completed) && Number.isFinite(progress.total)
      ? `${progress.completed} of ${progress.total}${progress.unit ? ` ${progress.unit}` : ''}` : null,
  ].filter(Boolean)
  const cost = devDetails ? moneyText(costUsd) : null
  return <aside className={cx('assistant-task-card', 'assistant-task-progress', compact && 'is-compact')}>
    <div role="status" aria-live="polite">
      <strong>{stage || title || 'Working'}</strong>
      {waiting ? <p className="assistant-task-waiting">{waitingReason}</p>
        : <span className="assistant-work-pulse" aria-hidden="true"><i /></span>}
      {facts.length > 0 && <p className="assistant-task-facts">{facts.join(' · ')}</p>}
      {cost && <p className="assistant-task-cost">AI cost so far: {cost}
        {costPending ? ' reported · final charge pending' : ''}</p>}
      <p className="assistant-task-bound">Randall stops on his own if this runs too long or reaches its usage
        limit.</p>
    </div>
    {onStop && <button type="button" className="assistant-secondary" disabled={stopping}
      onClick={onStop}>{stopping ? 'Stopping…' : 'Stop'}</button>}
  </aside>
}

function CheckRows({ checks = [] }) {
  if (!checks.length) return null
  return <ul className="assistant-check-list">{checks.map((check, index) => <li key={check.check_id || index}
    className={`is-${check.status}`}>
    <span>{check.label || checkLabel(check)}</span>
    <strong>{CHECK_STATUS_LABELS[check.status] || check.status}</strong>
    {check.reason && <small>{check.reason}</small>}
  </li>)}</ul>
}

/** What the user got, what is missing, and what they can do about it. */
export function ResultCard({ title, outcome, summary, headline, scope, facts = [], achieved,
  checks = [], limitations = [], receipts = [], error, actions = [], note, children }) {
  const blocking = checks.filter(check => check.required !== false && ['fail', 'unknown'].includes(check.status))
  // The card's TONE follows the effective outcome, not the claimed one: a
  // success carrying a required check that failed or could not be measured is
  // not a success, and it must not be drawn as one (ASTRA-REVIEW-BB 15).
  const effective = outcome === 'success' && (blocking.length || limitations.length) ? 'partial' : outcome
  const clear = effective === 'success'
  // A check that failed, or a required one that could not be measured. An optional check the work never
  // runs (a delivery's "tested in a match") stays in "What was checked"; as the headline it read as a problem.
  const worst = checks.find(check => check.status === 'fail') || blocking.find(check => check.status === 'unknown')
  const gained = achieved ? Object.entries(achieved).filter(([, value]) => value) : []
  const missing = achieved ? Object.entries(achieved).filter(([, value]) => !value) : []
  return <section className={cx('assistant-task-card', 'assistant-task-result', `is-${effective || 'unknown'}`,
    clear ? 'is-clear' : 'is-qualified')} aria-label={title || 'Result'}>
    <header><strong>{title}</strong><span className="assistant-outcome">{OUTCOME_WORDS[effective] || ''}</span></header>
    {summary && <p className="assistant-task-summary">{summary}</p>}
    {headline && <p className="assistant-task-headline" role="alert">{headline}</p>}
    {scope && <p className="assistant-task-scope">{scope}</p>}
    {/* The consequential one, immediately -- never only inside a disclosure. */}
    {worst && <p className="assistant-task-worst" role={worst.status === 'fail' ? 'alert' : 'status'}>
      {(worst.label || checkLabel(worst))}: {CHECK_STATUS_LABELS[worst.status]}
      {worst.reason ? ` — ${worst.reason}` : ''}</p>}
    {limitations.length > 0 && <p className="assistant-task-limit">{limitations[0]}</p>}
    {gained.length > 0 && <ul className="assistant-achieved">
      {gained.map(([key]) => <li key={key} className="is-yes">{ACHIEVED_LABELS[key]?.yes || key}</li>)}
      {missing.filter(([key]) => ACHIEVED_LABELS[key]).slice(0, 2).map(([key]) =>
        <li key={key} className="is-no">{ACHIEVED_LABELS[key].no}</li>)}
    </ul>}
    {facts.filter(Boolean).length > 0 && <p className="assistant-task-facts">{facts.filter(Boolean).join(' · ')}</p>}
    {children}
    {error && <FailureNotice lines={{ sentence: errorText(error) || 'This did not work.',
      preserved: 'Everything finished before this is kept.',
      alternative: recoveryText(error) || 'Tell Randall what to try instead.' }} />}
    {actions.length > 0 && <div className="assistant-task-actions">{actions.map(action => <button key={action.id}
      type="button" className={action.primary ? 'assistant-approve' : 'assistant-secondary'}
      disabled={action.disabled} title={action.disabledReason || undefined}
      onClick={action.onSelect}>{action.label}</button>)}</div>}
    {(checks.length > 1 || limitations.length > 1 || receipts.length > 0 || note) && <details className="assistant-task-detail">
      <summary>What was checked</summary>
      <CheckRows checks={checks} />
      {limitations.length > 1 && <ul>{limitations.slice(1).map((line, index) => <li key={index}>{line}</li>)}</ul>}
      {receipts.map((receipt, index) => <p key={index}>{receipt.say || receipt.description || ''}</p>)}
      {note && <p>{note}</p>}
    </details>}
  </section>
}

/** A bounded choice, in ordinary language. Never a working animation. */
export function DecisionCard({ request, evidence, onRespond, busy }) {
  if (!request) return null
  const options = (request.options || request.allowed_responses || []).map(option =>
    typeof option === 'string' ? { id: option, label: option } : option)
  return <section className="assistant-task-card assistant-task-decision" aria-label="Randall needs a decision">
    <header><strong>{request.title || 'Which would you like?'}</strong></header>
    {request.prompt && <p>{request.prompt}</p>}
    {evidence}
    <div className="assistant-task-actions">{options.map(option => <button key={option.id} type="button"
      className="assistant-secondary" disabled={busy || option.disabled} title={option.disabledReason || undefined}
      onClick={() => onRespond?.(request.id, option.id)}>{option.label}
      {option.description && <small>{option.description}</small>}</button>)}</div>
  </section>
}

/** A capability Randall does not have, what it cost this request, what instead. */
export function WishCard({ wish }) {
  if (!wish) return null
  const recorded = { queued: 'Saved on this computer', submitted: 'Sent to the Nucleus team',
    declined: 'Not sent', duplicate: 'Already reported' }[wish.record_status]
  return <section className="assistant-task-card assistant-task-wish" aria-label="Something Nucleus cannot do yet">
    <header><strong>Nucleus cannot do this part yet</strong></header>
    <p>{wish.capability}</p>
    {wish.blocked_operation && <p className="assistant-task-limit">That is what stopped: {wish.blocked_operation}.</p>}
    {wish.available_alternative && <p className="assistant-settled-next">{wish.available_alternative}</p>}
    {recorded && <p className="assistant-muted">{recorded}</p>}
  </section>
}

// --- compatibility, kept in separate sentences --------------------------------
// A costume that passed the app's costume check has said nothing about a stage
// or about the rest of a build, and a flag somebody typed in by hand has not
// been checked at all. One undifferentiated "Slippi safe" badge erased both.
//
// The rule this follows (ASTRA-REVIEW-BB finding 13): only an EXPLICIT PASSING
// VERDICT with provenance may read as a check that passed. The vault writes
// `slippi_safe: False` when no validator ran at all
// (vault/importing/unified/characters.py: `slippi_validation['slippi_safe']
// if slippi_validation else False`), so a bare false is not a failed check --
// calling it one invents evidence in the other direction.
//
// Provenance fields, as the vault records them:
//   slippi_manual_override  True when a person set the label by hand
//   slippi_tested           the import-time validator ran
//   slippi_test_date        when that label was written
//   dat_hash                the bytes it was written about
// `slippi_evidence` / `slippi_verdict` are read too, for when B1 carries real
// provenance through `_item` (they are absent today).
export const SAFETY_TEXT = {
  costume_check_passed: { label: 'Costume check passed',
    detail: 'The app\u2019s costume check passed on these exact files. It says nothing about your stages or '
      + 'the rest of your build, and it is not a test of your online setup.' },
  costume_check_failed: { label: 'Costume check failed',
    detail: 'The app\u2019s costume check found a problem with this costume; it can desync online play. '
      + 'It says nothing about your stages or the rest of your build.' },
  manual_safe: { label: 'Manually marked safe',
    detail: 'Someone set this label by hand. It has not had the app\u2019s costume check, and it says nothing '
      + 'about your stages or the rest of your build.' },
  manual_unsafe: { label: 'Manually marked unsafe',
    detail: 'Someone set this label by hand. It has not had the app\u2019s costume check, and it says nothing '
      + 'about your stages or the rest of your build.' },
  not_marked_safe: { label: 'Not marked safe',
    detail: 'Either the check found a problem or it never ran \u2014 the vault does not record which. '
      + 'Treat it as unchecked for online play. It says nothing about your stages or the rest of your build.' },
  unchecked: { label: 'Not checked',
    detail: 'Nothing has checked this costume for online play. It says nothing about your stages or your build.' },
}

export function safetyKind(item = {}) {
  if (!item || typeof item !== 'object') return 'unchecked'
  if (item.slippi_manual_override === true) {
    return item.slippi_safe === false ? 'manual_unsafe' : 'manual_safe'
  }
  // An explicit verdict from a check, when one is carried.
  const verdict = item.slippi_verdict || item.slippi_evidence || item.slippi_source
  if (verdict === 'manual' || verdict === 'manual_flag') {
    return item.slippi_safe === false ? 'manual_unsafe' : 'manual_safe'
  }
  if (verdict === 'costume_check_failed' || verdict === 'failed') return 'costume_check_failed'
  const checked = item.slippi_tested === true || verdict === 'costume_check' || verdict === 'validator'
  if (checked && item.slippi_safe === true) return 'costume_check_passed'
  if (checked && item.slippi_safe === false) return 'not_marked_safe'
  if (item.slippi_safe === true) return 'recorded_safe'
  if (item.slippi_safe === false) return 'not_marked_safe'
  return 'unchecked'
}

/** The provenance sentence: what was tested, and when. Never invented. */
export function safetyProvenance(item = {}) {
  const parts = []
  const when = item.slippi_test_date
  if (when) parts.push(`recorded ${String(when).slice(0, 10)}`)
  if (item.dat_hash) parts.push(`on file ${String(item.dat_hash).slice(0, 8)}`)
  return parts.join(' \u00b7 ')
}

export function SafetyLabel({ item, compact }) {
  const kind = safetyKind(item)
  const text = SAFETY_TEXT[kind] || { label: 'Marked safe for online play',
    detail: 'The vault has this marked safe, but not how that was decided \u2014 a costume check and a '
      + 'hand-typed label look the same here. It says nothing about your stages or your build.' }
  const provenance = safetyProvenance(item)
  return <span className={cx('assistant-safety', `is-${kind}`)} title={`${text.detail}${provenance ? ` (${provenance})` : ''}`}>
    {text.label}
    {provenance && <small className="assistant-safety-provenance">{provenance}</small>}
    {!compact && <small>{text.detail}</small>}
  </span>
}
