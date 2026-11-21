// "Report this chat": what the person sees before anything is sent, and how the
// send flow treats the backend's answers. The review fixture below is the shape
// randall/routes/chat_reports.py returns (see tests/backend/test_chat_reports.py).
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as chatReportModule from './chatReport.js'
const { CONSENT_LINE, FILES_HINT, FILES_LABEL, budgetFromEntitlement, errorView, reviewBody, sendReport } = chatReportModule

const realRequire = createRequire(import.meta.url)
const source = readFileSync(new URL('./ChatReportModal.jsx', import.meta.url), 'utf8')
const compiled = transformSync(source, { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
new Function('require', 'module', 'exports', compiled)(name => {
  if (name === '../../shared/transport/api') return { api: {} }
  if (name === '../../shared/audio/sounds') return { playSound: () => {}, playHoverSound: () => {} }
  if (name.endsWith('.css')) return {}
  if (name === './chatReport') return chatReportModule
  return realRequire(name)
}, module, module.exports)
const { ChatReportView, FilesToggle, ReportChatButton, ReportPreview } = module.exports
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props))

const REVIEW = {
  submission_id: 's1', approval_hash: 'h1', conversation_sha256: 'c1',
  includes: ['This conversation: 3 of your messages and 3 of Randall\'s replies, with timestamps.',
    '2 tool call(s) Randall made, with their inputs and results (long results are shortened).'],
  not_included: ['Your API key, passwords and sign-in tokens (they are removed if they appear).'],
  manifest: { members: [{ name: 'report.json', bytes: 300 }, { name: 'conversation.json', bytes: 5300 },
    { name: 'transcript.md', bytes: 2100 }] },
  transcript: '# Randall chat report (mods)\n### 0. You\nRecolor my Fox',
}

test('the form states the consent line and its two optional fields', () => {
  const html = render(ChatReportView, { phase: 'ready', review: REVIEW, note: '', contact: '' })
  assert.ok(html.includes(CONSENT_LINE))
  assert.match(html, /What went wrong\? \(optional\)/)
  assert.match(html, /Discord or email \(optional\)/)
  assert.match(html, />Send</)
  assert.match(html, />Cancel</)
})

test('"What gets sent" lists exactly what the backend froze, plus the transcript', () => {
  const html = render(ReportPreview, { review: REVIEW })
  assert.match(html, /<summary>What gets sent<\/summary>/)
  for (const line of [...REVIEW.includes, ...REVIEW.not_included]) {
    assert.ok(html.includes(line.replace(/'/g, '&#x27;')), line)
  }
  assert.match(html, /conversation\.json \(5\.2 KB\)/)
  assert.match(html, /Recolor my Fox/)
})

test('Send is disabled until the preview exists, and while sending', () => {
  const loading = render(ChatReportView, { phase: 'loading', review: null, note: '', contact: '' })
  assert.match(loading, /<button[^>]*disabled=""[^>]*>Send<\/button>/)
  assert.match(loading, /Preparing the preview/)
  const sending = render(ChatReportView, { phase: 'sending', review: REVIEW, note: 'x', contact: '' })
  assert.match(sending, /Sending…/)
  assert.match(sending, /<button[^>]*disabled=""[^>]*>Cancel<\/button>/)
})

test('the outdated-version gate replaces the form', () => {
  const html = render(ChatReportView, { phase: 'ready', review: REVIEW, gate: { latest: '0.9.4' }, note: '', contact: '' })
  assert.match(html, /newer version \(v0\.9\.4\) is available/)
  assert.doesNotMatch(html, />Send</)
  assert.match(html, />Close</)
})

test('errors and the done state are shown plainly', () => {
  const failed = render(ChatReportView, { phase: 'ready', review: REVIEW, note: '', contact: '', error: 'No connection.' })
  assert.match(failed, /role="alert"[^>]*>No connection\./)
  const done = render(ChatReportView, { phase: 'done', review: REVIEW, result: { id: 'abcdef0123456789' }, note: '', contact: '' })
  assert.match(done, /Reference: abcdef01/)
  assert.doesNotMatch(done, />Send</)
})

test('the flag only appears for a saved conversation with messages', () => {
  assert.equal(render(ReportChatButton, { conversationId: null, messageCount: 3 }), '')
  assert.equal(render(ReportChatButton, { conversationId: 'c1', messageCount: 0 }), '')
  const html = render(ReportChatButton, { conversationId: 'c1', messageCount: 3, busy: true })
  assert.match(html, /aria-label="Report this chat"/)
  assert.match(html, /disabled=""/)
})

// --- send flow ---------------------------------------------------------------

function fakeApi(replies) {
  const calls = []
  return {
    calls,
    post: async (path, body) => {
      calls.push({ path, body })
      const next = replies.shift()
      if (next instanceof Error) throw next
      return next
    },
  }
}

const apiError = (status, data) => Object.assign(new Error(data?.error || 'x'), { status, data })

test('send re-freezes with the note, then submits that snapshot with consent: true', async () => {
  const api = fakeApi([{ ...REVIEW, submission_id: 's2', approval_hash: 'h2' }, { success: true, id: 'r1', confirmed: true }])
  const out = await sendReport(api, { surface: 'mods', conversationId: 'c1', note: ' it broke ', contact: '', appVersion: '0.9.1' }, REVIEW)
  assert.equal(out.state, 'sent')
  assert.equal(api.calls[0].path, '/chat-reports/review')
  assert.equal(api.calls[0].body.note, 'it broke')
  assert.deepEqual(api.calls[1], { path: '/chat-reports/submit', body: { submission_id: 's2', approval_hash: 'h2', consent: true } })
})

test('a conversation that changed since the preview is not sent', async () => {
  const api = fakeApi([{ ...REVIEW, conversation_sha256: 'c2' }])
  const out = await sendReport(api, { surface: 'mods', conversationId: 'c1' }, REVIEW)
  assert.equal(out.state, 'changed')
  assert.equal(api.calls.length, 1)            // no submit
})

test('the 426 version gate and other failures map to what the modal shows', async () => {
  const api = fakeApi([REVIEW, apiError(426, { error: 'update_required', latest: '0.9.4', url: 'https://x' })])
  await assert.rejects(sendReport(api, { surface: 'mods', conversationId: 'c1' }, REVIEW), err => {
    assert.deepEqual(errorView(err), { kind: 'gate', latest: '0.9.4', url: 'https://x' })
    return true
  })
  assert.match(errorView(apiError(429, { error: 'rate_limited' })).text, /Too many reports/)
  assert.match(errorView(apiError(0, null)).text, /No connection/)
  assert.match(errorView(apiError(400, { error: 'app_version_unknown' })).text, /installed app/)
  assert.match(errorView(apiError(502, { error: 'Could not reach the report server' })).text, /report server/)
})

test('the budget block never carries the API key', () => {
  const budget = budgetFromEntitlement({ active: true, api_key: 'sk-or-v1-secret', patreon_name: 'Real Name',
    period_budget: 5, remaining: 2.5, usage: 2.5, resets_at: '2026-11-01T00:00:00Z' }, { spent: 0.1, cap: 2 })
  assert.deepEqual(budget, { source: 'patreon', active: true, period_budget: 5, remaining: 2.5, usage: 2.5,
    resets_at: '2026-11-01T00:00:00Z', spent: 0.1, cap: 2 })
  const body = reviewBody({ surface: 'tracker', conversationId: 7, budget })
  assert.equal(body.conversation_id, '7')
  assert.doesNotMatch(JSON.stringify(body), /sk-or|Real Name/)
})

// --- the files toggle ----------------------------------------------------------

test('a conversation with files offers one toggle, on by default, with its size', () => {
  const html = render(ChatReportView, { phase: 'ready', review: REVIEW, note: '', contact: '',
    filesOffered: 3, filesBytes: 1.5 * 1024 * 1024 })
  assert.match(html, /<input type="checkbox" checked=""\/>/)
  assert.ok(html.includes(`${FILES_LABEL} (1.5 MB)`))
  assert.equal(FILES_LABEL, 'Include the files I attached')
  assert.ok(html.includes(FILES_HINT.replace(/'/g, '&#x27;')))
  const off = render(FilesToggle, { offered: 3, bytes: 1024, checked: false })
  assert.doesNotMatch(off, /checked=""/)
  assert.ok(off.includes(`${FILES_LABEL} (1.0 KB)`))
})

test('no toggle when the conversation has no files (tracker, plain chats)', () => {
  const html = render(ChatReportView, { phase: 'ready', review: REVIEW, note: '', contact: '' })
  assert.doesNotMatch(html, /type="checkbox"/)
  assert.doesNotMatch(html, new RegExp(FILES_LABEL))
})

test('the toggle is locked while a preview is being frozen or the report is sending', () => {
  for (const phase of ['loading', 'sending']) {
    const html = render(ChatReportView, { phase, review: phase === 'loading' ? null : REVIEW, note: '', contact: '',
      filesOffered: 1, filesBytes: 10 })
    assert.match(html, /<input type="checkbox"[^>]*disabled=""/, phase)
  }
})

test('the review asks for the files only with a real true, and send carries the choice', async () => {
  assert.equal(reviewBody({ surface: 'mods', conversationId: 'c1' }).include_files, false)
  assert.equal(reviewBody({ surface: 'mods', conversationId: 'c1', includeFiles: 'yes' }).include_files, false)
  assert.equal(reviewBody({ surface: 'mods', conversationId: 'c1', includeFiles: true }).include_files, true)
  const preview = { ...REVIEW, files_sha256: 'f1' }
  const api = fakeApi([{ ...preview, submission_id: 's2', approval_hash: 'h2' }, { success: true, id: 'r1' }])
  const out = await sendReport(api, { surface: 'mods', conversationId: 'c1', includeFiles: false }, preview)
  assert.equal(out.state, 'sent')
  assert.equal(api.calls[0].body.include_files, false)
})

test('files that changed since the preview are not sent', async () => {
  const preview = { ...REVIEW, files_sha256: 'f1' }
  const api = fakeApi([{ ...preview, files_sha256: 'f2' }])
  const out = await sendReport(api, { surface: 'mods', conversationId: 'c1', includeFiles: true }, preview)
  assert.equal(out.state, 'changed')
  assert.equal(api.calls.length, 1)            // no submit
})

// --- Send transmits what was previewed -------------------------------------------

test('send names the previewed freeze, so its files are reused byte for byte', async () => {
  const api = fakeApi([{ ...REVIEW, submission_id: 's2', approval_hash: 'h2' }, { success: true, id: 'r1' }])
  await sendReport(api, { surface: 'mods', conversationId: 'c1', includeFiles: true }, REVIEW)
  assert.equal(api.calls[0].body.base_submission, 's1')
  assert.equal(api.calls[1].path, '/chat-reports/submit')
})

test('a previewed freeze that cannot be reused is never replaced by an unseen rebuild', async () => {
  const fresh = { ...REVIEW, submission_id: 's3', files_sha256: 'f9' }
  const api = fakeApi([apiError(409, { error: 'review_again' }), fresh])
  const out = await sendReport(api, { surface: 'mods', conversationId: 'c1', includeFiles: true }, REVIEW)
  assert.deepEqual(out, { state: 'changed', review: fresh })
  assert.equal(api.calls.length, 2)                    // a new preview, no submit
  assert.equal(api.calls[1].path, '/chat-reports/review')
  assert.equal(api.calls[1].body.base_submission, undefined)
  const html = render(ChatReportView, { phase: 'ready', review: fresh, note: '', contact: '', changed: true })
  assert.match(html, /Nothing was sent\. Check what gets sent, then press Send again\./)
})
