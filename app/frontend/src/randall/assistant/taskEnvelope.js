// Reading the Session-1 task envelope (backend/randall/assistant/tasks/contracts.py)
// the way the cards need it, and adapting the tool results that do not carry
// one yet into the same shape.
//
// Two rules come straight from the contract and are enforced here so no card
// has to re-derive them:
//
//   * execution state is not outcome. `completed` is not `success`; a turn that
//     finished by explaining that it was blocked is `blocked`.
//   * a required check that FAILED or is UNKNOWN is not a pass, and an envelope
//     carrying one cannot be rendered as an unqualified success.
//
// Everything here is pure: no React, no fetch, so it is testable on its own.

// Extensioned so this module also loads directly under node's ESM resolver,
// which the card tests use.
import { CHECK_LABELS } from './activity.js'

export const OUTCOME_WORDS = {
  success: 'Done', partial: 'Partly done', blocked: 'Stopped short',
  denied: 'You said no', failed: 'Did not work', cancelled: 'Stopped',
}

// Only `success` may read as a plain success. Everything else keeps its own
// visible tone so "Done!" can never be followed by a limitation that reverses it.
export const GOOD_OUTCOMES = new Set(['success'])

const BLOCKING = new Set(['fail', 'unknown'])

export const blocksRelease = check => check?.required !== false && BLOCKING.has(check?.status)

/** The envelope this tool carries, or null.
 *
 * Three shapes reach here and all three are the same object:
 *   * the tool RESULT is the envelope -- `deliver_to_game` returns
 *     `TaskResult.to_dict()` straight out of `delivery/deliver.py`;
 *   * the engine hangs the current envelope on the message as `task`
 *     (`engine._task_card`, on every tool_start/tool_result);
 *   * a nested `task`/`envelope`/`task_result` key.
 * The first was the one being missed, which is how a partial delivery rendered
 * as "Put into the game you play - Done" (ASTRA-REVIEW-BB finding 10).
 */
export function envelopeOf(tool) {
  const result = tool?.result || {}
  for (const raw of [result.task_result, result.envelope, result.task, result, tool?.task]) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue
    const looksLikeEnvelope = raw.contracts_version !== undefined
      || (raw.achieved && typeof raw.achieved === 'object')
      || (raw.state !== undefined && raw.outcome !== undefined)
    if (looksLikeEnvelope) return normalizeEnvelope(raw)
  }
  return null
}

/**
 * The envelope a call's card is drawn from, or null when the call has no result of its own yet: still running,
 * waiting on the user's yes (its approval card must show), or carrying only the chat's own task record while that is
 * still running with no outcome (it says nothing about this call: drawn as a result, it hid a delivery's real error).
 */
export function settledEnvelope(tool) {
  if (!tool || tool.status === 'running' || tool.approval?.status === 'pending') return null
  const envelope = envelopeOf(tool)
  return envelope && (envelope.outcome || envelope.state !== 'running') ? envelope : null
}

// Backend errors are structured (`{code, message, retryable, ...}`) as often as
// they are strings, and a card that assumes a string throws while rendering.
export function errorText(error) {
  if (!error) return ''
  if (typeof error === 'string') return error.trim()
  if (typeof error !== 'object') return String(error)
  const said = error.message || error.detail || error.error || error.reason || error.code
  return typeof said === 'string' ? said.trim() : ''
}

export function recoveryText(error) {
  if (!error || typeof error !== 'object') return ''
  const actions = error.recovery_actions || error.recoveryActions
  if (Array.isArray(actions) && actions.length) {
    const first = actions[0]
    return typeof first === 'string' ? first : (first?.label || first?.say || '')
  }
  return typeof error.recovery === 'string' ? error.recovery : ''
}

export function normalizeEnvelope(raw) {
  const checks = Array.isArray(raw.checks) ? raw.checks : []
  return {
    taskRef: { taskId: raw.task_id || null, revision: raw.revision || 1 },
    workflow: raw.workflow || '',
    state: raw.state || null,
    outcome: raw.outcome || null,
    achieved: raw.achieved && typeof raw.achieved === 'object' ? raw.achieved : null,
    facts: raw.facts && typeof raw.facts === 'object' ? raw.facts : {},
    checks,
    blocking: checks.filter(blocksRelease),
    limitations: Array.isArray(raw.limitations) ? raw.limitations : [],
    artifacts: Array.isArray(raw.artifacts) ? raw.artifacts : [],
    receipts: Array.isArray(raw.receipts) ? raw.receipts : [],
    next: raw.next && typeof raw.next === 'object' ? raw.next : null,
    error: raw.error || null,
    wishIds: Array.isArray(raw.wish_ids) ? raw.wish_ids : [],
  }
}

/** True when this envelope may be drawn as a plain success. */
export function isClearSuccess(envelope) {
  if (!envelope || !GOOD_OUTCOMES.has(envelope.outcome)) return false
  return envelope.blocking.length === 0
}

// --- progress, without asking a model where the task is ----------------------
// The engine already streams `started_at` and `model_rounds` on a running
// reply, and the coordinator emits stages. Nothing here invents a percentage:
// an estimate is shown only where the backend supplied one.

export function taskProgress(message, now = Date.now()) {
  if (!message) return null
  const tools = message.tools || []
  const running = [...tools].reverse().find(tool => tool.status === 'running')
  const envelope = [...tools].reverse().map(envelopeOf).find(Boolean) || null
  const started = Number.isFinite(message.started_at) ? message.started_at * 1000 : null
  const facts = envelope?.facts || {}
  const stage = running?.result?.progress_label || facts.stage_label || facts.stage || null
  return {
    tool: running || null,
    envelope,
    stage,
    state: envelope?.state || (message.status === 'running' ? 'running' : null),
    waitingReason: facts.waiting_reason || null,
    elapsedSeconds: started ? Math.max(0, (now - started) / 1000) : null,
    // Backend-supplied only. `estimate_seconds` does not exist yet anywhere in
    // the backend; when it does, this shows it and says it is an estimate.
    estimateSeconds: firstFinite(message.estimate_seconds, facts.estimate_seconds),
    rounds: Number.isFinite(message.model_rounds) ? message.model_rounds : null,
    roundLimit: firstFinite(message.round_limit, message.max_rounds, facts.round_limit),
    costUsd: firstFinite(message.cost_usd),
    // `committed_usd` counts money reserved for a charge the provider never
    // reported back, so a total below it is a subtotal, not a final bill.
    costPending: firstFinite(message.committed_usd) > firstFinite(message.cost_usd) + 1e-6,
  }
}

function firstFinite(...values) {
  for (const value of values) if (Number.isFinite(Number(value)) && value !== null && value !== '') return Number(value)
  return null
}

// --- adapters: results that predate the envelope ------------------------------
// Each one returns the ResultCard's props, or null when that tool result is not
// a finished outcome. They never claim a postcondition the result cannot prove:
// a costume in the vault is `exported`, never `installed`.

const achieved = extra => ({ prepared: false, exported: false, installed: false, previewed: false, ...extra })

// A release-gate check ID, said in words. `CHECK_LABELS` is the same map the
// check rows use, so a headline and a row never name one check two ways.
export function checkName(checkId) {
  return CHECK_LABELS[checkId] || String(checkId || '').replace(/_/g, ' ')
}

// A produced file, named for a person. Candidate IDs are 32 hex characters and
// are identity for us and noise for the reader.
export function artifactLabel(artifact) {
  if (!artifact) return ''
  const explicit = artifact.label || artifact.display_name
  if (explicit) return explicit
  const name = String(artifact.name || artifact.path || '').split(/[\\/]/).pop()
  return name.replace(/[0-9a-f]{8,}/gi, '').replace(/[_-]{2,}/g, '-').replace(/^[-_ ]+|[-_ ]+(?=\.)/g, '')
    || 'a file'
}

/** An automated in-game verification (delivery/game_tests.py `verify`). */
export function verificationResult(result) {
  const record = result?.game_verification
  if (!record) return null
  const outcome = record.outcome === 'verified' ? 'success'
    : record.outcome === 'failed' ? 'failed' : 'blocked'
  const checks = [...(record.checks || []),
    ...(record.appearance_checks || []).map(row => ({
      check_id: `frame:${row.move}`, status: row.status, reason: row.reason,
      label: `${row.move}, frame ${row.frame}`,
    }))]
  return {
    title: 'Automatic checks in the game',
    outcome,
    summary: record.outcome === 'verified'
      ? `${record.character} played through the recorded checks in the game.`
      : record.outcome === 'failed'
        ? `${record.character} did not pass the checks in the game.`
        : `Randall could not finish checking ${record.character} in the game, so nothing here is a pass.`,
    // Checked in a throwaway test build, never in the user's own game.
    scope: `Costume checks only, on slot ${record.costume_slot} of a test copy of the game. `
      + 'This does not check your stages or the rest of your build.',
    facts: [`${record.frames_captured} of ${record.frames_requested} moments captured`,
      record.timing?.seconds ? `${Math.round(record.timing.seconds)} seconds in the game` : null],
    checks,
    limitations: record.limitations || [],
    achieved: achieved({ prepared: true, previewed: record.frames_captured > 0 }),
    reasons: record.reasons || [],
  }
}

/** Costumes added to a build (delivery/projects.py install). */
export function projectInstallResult(result) {
  if (!result || result.project_action !== 'installed') return null
  const count = result.installed_count || (result.installed_items || []).length
  const name = result.project?.name || 'your build'
  // The backend reports `failed_count` and drops `failed` entirely on a partial
  // install, so counting an absent array turned a partial into a success.
  const failed = Number(result.failed_count ?? (result.failed || []).length) || 0
  return {
    title: 'Costumes added to a build',
    outcome: failed ? 'partial' : 'success',
    // "Installed" in the envelope means the playable build changed AND was
    // verified. Adding costumes to a project is neither.
    summary: `Added ${count} costume${count === 1 ? '' : 's'} to ${name}.`,
    scope: 'These are the ingredients for that build. Your playable game does not change until the build is made.',
    facts: [failed ? `${failed} could not be added` : null],
    limitations: failed ? [`${failed} of the costumes you asked for are not in that build.`] : [],
    achieved: achieved({ prepared: true }),
    nextStepLabel: 'Build the playable game',
  }
}


// What `deliver.py` puts in `facts`: the four questions the change card has to
// answer, already written as sentences by the code that did the work. The card
// RELAYS them; it does not compose its own version of what happened.
//   summary                  one sentence for the whole result
//   what_changed / where     the change and the place it landed
//   limitation_that_matters  the one qualification that survives it
//   how_to_undo              what reverses it, or that nothing does
//
// `receipts` is a list of receipt ID strings, not objects.
export function deliveryResult(envelope) {
  if (!envelope) return null
  const facts = envelope.facts || {}
  const outcome = envelope.outcome
  const installed = Boolean(envelope.achieved?.installed)
  const fallback = outcome === 'denied' ? 'You said no, so nothing was changed.'
    : outcome === 'cancelled' ? 'You stopped this before it finished.'
      : outcome === 'failed' ? 'This did not reach the game you play.'
        : installed ? 'This is in the game you play.'
          : 'This did not reach the game you play yet.'
  const limitations = [facts.limitation_that_matters, ...(envelope.limitations || [])]
    .filter(Boolean).filter((line, index, all) => all.indexOf(line) === index)
  const receiptId = (envelope.receipts || []).map(entry =>
    typeof entry === 'string' ? entry : entry?.receipt_id).filter(Boolean)[0] || null
  return {
    title: 'Your game',
    outcome: outcome || null,
    state: envelope.state,
    summary: facts.summary || fallback,
    scope: [facts.what_changed, facts.where ? `Where: ${facts.where}` : ''].filter(Boolean).join(' '),
    achieved: envelope.achieved,
    checks: envelope.checks,
    limitations,
    receipts: envelope.receipts,
    error: envelope.error,
    next: envelope.next,
    // Only an undo that the producer says exists. "There is nothing to undo"
    // is an answer, not a missing control.
    undoSay: /nothing to undo/i.test(facts.how_to_undo || '') ? '' : (facts.how_to_undo || ''),
    undoable: Boolean(receiptId) && !/nothing to undo/i.test(facts.how_to_undo || ''),
    receiptId,
  }
}

// `next.allowed_responses` from deliver.py are objects like
// `{action: 'open_build_screen', where: '...'}`, with no id or label of their
// own. DecisionCard needs both, and inventing a sentence for an action we do
// not recognise would be worse than showing the action's own words.
const ACTION_LABELS = {
  install_project_mods: 'Add it to a build instead',
  open_build_screen: 'Open the build screen',
  deliver_to_game: 'Put it in the game I play',
  undo_delivery: 'Take it back out',
  designate_destination: 'Choose which game copy is mine',
  choose_game_file: 'Choose my game file',
  check_slippi_selection: 'Check it now',
  i_selected_this_file: 'I selected it',
  choose_emulator: 'Choose an emulator',
  test_in_game: 'Play it now',
  open_game: 'Open the game',
  inspect_project: 'Look at the build',
  name_the_costume: 'Name the costume',
  save_copy: 'Save the built copy',
}

// Two answers may be the same action with different arguments ("make it my
// Slippi game" / "make it my offline game" are both deliver_to_game), so an id
// is made unique by position. `say` is what pressing it sends to Randall: the
// producer's own label when it gave one (the user's words for that answer),
// else the old "Yes: <action>." line.
export function decisionOptions(next) {
  const seen = new Set()
  return (next?.allowed_responses || []).map((entry, index) => {
    if (typeof entry === 'string') return { id: entry, label: entry, say: `Yes: ${entry.replace(/_/g, ' ')}.` }
    const action = entry?.action || entry?.id || `option_${index}`
    const id = seen.has(action) ? `${action}_${index}` : action
    seen.add(action)
    const label = entry?.label || ACTION_LABELS[action] || String(action).replace(/_/g, ' ')
    return { id, label,
      say: entry?.label ? `${entry.label}.` : `Yes: ${String(action).replace(/_/g, ' ')}.`,
      description: entry?.where || entry?.description || '' }
  })
}
