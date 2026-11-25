// An AI's problem report (MCP report_problem): what the window shows and how Send goes.
//
// The user's own AI wrote it; the backend assembled it on this computer and sent nothing
// (randall/reports/problem_report.py). Only this window can read the waiting reports and send or
// discard one (shared/routes/mcp.py, the window-only key: shared/transport/api.js WINDOW_ONLY).
//
// Send, as "Report this chat" sends (chatReport.js):
//   1. POST /api/mcp/window/problem-reports/<id>/review {include, app_version}
//        -> the report frozen with the ticked attachments: {submission_id, approval_hash}. Sends nothing.
//   2. POST /chat-reports/submit {submission_id, approval_hash, consent: true}
//        -> the chat report's own submit sends exactly that frozen ZIP.
// Discard: POST /api/mcp/window/problem-reports/<id>/discard. Nothing is sent.

import { errorView } from '../chat/chatReport.js'

export const REPORTS_URL = '/api/mcp/window/problem-reports'
export const REPORT_EVENT = 'mcp_problem_report'
export const PROBLEM_CONSENT = 'Send gives this report and the ticked attachments to the Nucleus developer, to help '
  + 'fix the problem. It is not public. Nothing has been sent yet.'

/** The optional attachments ticked at first: {name: true|false}, as the backend suggests. */
export function initialChoice(report) {
  const choice = {}
  for (const part of report?.attachments || []) {
    if (part.optional && !part.too_large) choice[part.name] = part.include === true
  }
  return choice
}

/** The optional attachments to send, in the report's order. */
export function includedNames(report, choice) {
  return (report?.attachments || [])
    .filter(part => part.optional && !part.too_large && choice?.[part.name] === true)
    .map(part => part.name)
}

/** What Send sends: the parts that always go plus the ticked ones. */
export function sendSummary(report, choice) {
  const ticked = new Set(includedNames(report, choice))
  const going = (report?.attachments || []).filter(part => !part.optional || ticked.has(part.name))
  return { count: going.length, bytes: going.reduce((sum, part) => sum + (Number(part.bytes) || 0), 0) }
}

/** "Your AI (claude-opus-5-5, effort high)": who wrote it, as it said. */
export function whoWrote(report) {
  const by = report?.reported_by || {}
  const said = [by.model, by.effort ? `effort ${by.effort}` : null].filter(Boolean)
  return said.length ? `Your AI (${said.join(', ')})` : 'Your AI'
}

export async function listReports(api) {
  const data = await api.get(REPORTS_URL)
  return Array.isArray(data?.pending) ? data.pending : []
}

export async function sendProblemReport(api, report, choice, appVersion) {
  const frozen = await api.post(`${REPORTS_URL}/${encodeURIComponent(report.id)}/review`, {
    include: includedNames(report, choice),
    ...(appVersion ? { app_version: appVersion } : {}),
  })
  const sent = await api.post('/chat-reports/submit', {
    submission_id: frozen.submission_id,
    approval_hash: frozen.approval_hash,
    consent: true,
  })
  return { state: 'sent', id: sent.id || null, confirmed: sent.confirmed !== false }
}

export async function discardProblemReport(api, report) {
  return api.post(`${REPORTS_URL}/${encodeURIComponent(report.id)}/discard`, {})
}

const ENDED = {
  report_sent: 'This report was already sent.',
  report_discarded: 'This report was discarded.',
  report_expired: 'This report expired; nothing was sent.',
  unknown_report: 'This report is gone; nothing was sent.',
  unknown_attachment: 'The report changed. Close this and look again.',
}

/** What the window shows for a thrown api error: the update gate or a sentence (chatReport.js errorView). */
export function problemErrorView(err) {
  const code = err?.data?.error
  if (ENDED[code]) return { kind: 'error', text: ENDED[code] }
  return errorView(err)
}
