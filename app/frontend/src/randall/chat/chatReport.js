// "Report this chat" -- the request/response logic, kept out of the modal so it
// can be tested without a DOM.
//
// Flow (backend: randall/routes/chat_reports.py):
//   1. review  -> the backend freezes the exact bundle and describes it. Sends nothing.
//   2. send    -> review AGAIN with the final note/contact, check the conversation
//                 and files parts are byte-identical to what the preview showed,
//                 then submit that frozen snapshot with consent: true.
// If the conversation changed between preview and send (a turn finished, a
// message arrived), nothing is sent and the new preview is shown instead.
//
// Files: a mods conversation can carry the files the user attached and the
// preview pictures Randall made. They go only with `include_files: true` (the
// modal's toggle, on by default); the backend puts the choice in the approval
// hash. Model-import notes (scrubbed text) go either way.

export const CONSENT_LINE = 'This sends this conversation to the developer to help fix Randall. It is not public.'
export const FILES_LABEL = 'Include the files I attached'
export const FILES_HINT = 'Sends the files you gave Randall in this chat and the preview pictures it made, so the '
  + 'developer can try exactly what you did. Game files from your ISO and your vault are never sent.'

// Entitlement fields a report may carry: ai-entitlement's current ones (shared/account/entitlement.js). The budget
// fields are USD; the report is the developer's, so it keeps them. The key (`api_key`) is never among them. The
// backend's allowlist is the same (randall/reports/chat_report.py, BUDGET_FIELDS).
const BUDGET_FIELDS = ['active', 'linked', 'paused', 'patron_status', 'period_budget', 'remaining', 'usage',
  'resets_at']

export function budgetFromEntitlement(entitlement, usage) {
  const out = { source: entitlement?.active ? 'patreon' : 'none' }
  for (const field of BUDGET_FIELDS) {
    const value = entitlement?.[field]
    if (value === null || value === undefined) continue
    if (['number', 'boolean'].includes(typeof value) || (typeof value === 'string' && value.length <= 64)) {
      out[field] = value
    }
  }
  if (usage && Number.isFinite(Number(usage.cap))) {
    out.spent = Number(usage.spent) || 0
    out.cap = Number(usage.cap)
  }
  return out
}

export function reviewBody({ surface, conversationId, note = '', contact = '', appVersion, budget, includeFiles = false,
  baseSubmission }) {
  return {
    surface,
    conversation_id: String(conversationId),
    note: note.trim(),
    contact: contact.trim(),
    include_files: includeFiles === true,
    ...(baseSubmission ? { base_submission: String(baseSubmission) } : {}),
    ...(appVersion ? { app_version: appVersion } : {}),
    ...(budget ? { budget } : {}),
  }
}

export async function reviewReport(api, request) {
  return api.post('/chat-reports/review', reviewBody(request))
}

/**
 * Re-freeze with the final note/contact and send it -- unless the conversation
 * or its files changed since `preview` was shown. The re-freeze names the
 * previewed freeze (`base_submission`), so the backend copies ITS files part
 * byte for byte instead of reading the files again. Returns one of:
 *   {state: 'sent', id, confirmed}
 *   {state: 'changed', review}      nothing sent; show the new preview and
 *                                    wait for the user to press Send again
 * Throws the api error for everything else (see errorView).
 */
export async function sendReport(api, request, preview) {
  let fresh
  try {
    fresh = await reviewReport(api, { ...request, baseSubmission: preview?.submission_id })
  } catch (err) {
    // The previewed freeze can no longer be reused (expired, or its bytes
    // changed): never send a rebuilt one unseen -- show a new preview instead.
    if (err?.data?.error !== 'review_again') throw err
    return { state: 'changed', review: await reviewReport(api, request) }
  }
  if (preview && (fresh.conversation_sha256 !== preview.conversation_sha256
    || fresh.files_sha256 !== preview.files_sha256)) {
    return { state: 'changed', review: fresh }
  }
  const sent = await api.post('/chat-reports/submit', {
    submission_id: fresh.submission_id,
    approval_hash: fresh.approval_hash,
    consent: true,
  })
  return { state: 'sent', id: sent.id, confirmed: sent.confirmed !== false, review: fresh }
}

const REVIEW_ERRORS = {
  app_version_unknown: 'This build does not report a version, so reports can only be sent from the installed app.',
  unknown_conversation: 'This conversation is not saved yet. Send a message first, then report it.',
  unknown_surface: 'This chat cannot be reported.',
  consent_invalid: 'The report changed after you reviewed it. Close this and try again.',
  bundle_changed: 'The prepared report changed on disk. Close this and try again.',
  already_sending: 'This report is already being sent.',
  retries_exhausted: 'This report could not be sent after several tries. Close this and try again later.',
  files_unavailable: 'Your attached files could not be gathered. Untick "Include the files I attached" to send the conversation on its own.',
  files_changing: 'One of your files is still changing. Wait a moment, then try again.',
}

/** What the modal shows for a thrown api error: an update gate or a message. */
export function errorView(err) {
  const status = err?.status
  const data = err?.data || {}
  if (status === 426 || data.error === 'update_required') {
    return { kind: 'gate', latest: data.latest || null, url: data.url || null }
  }
  if (status === 429 || data.error === 'rate_limited') {
    return { kind: 'error', text: 'Too many reports right now. Please try again in a minute.' }
  }
  if (status === 0) {
    return { kind: 'error', text: 'No connection. Check your internet and try again.' }
  }
  if (REVIEW_ERRORS[data.error]) return { kind: 'error', text: REVIEW_ERRORS[data.error] }
  if (status === 502) {
    return { kind: 'error', text: 'Could not reach the report server. Nothing was lost; try again.' }
  }
  return { kind: 'error', text: data.error || err?.message || 'Sending failed' }
}
