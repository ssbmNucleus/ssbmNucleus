// An AI's problem report in the window: what the person sees before anything is sent, and how Send and
// Discard reach the backend. The report fixture is the shape GET /api/mcp/window/problem-reports answers
// (randall/reports/problem_report.py, tests/backend/test_mcp_problem_reports.py).
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as problemReportModule from './problemReport.js'

const {
  PROBLEM_CONSENT, REPORTS_URL, discardProblemReport, includedNames, initialChoice, listReports, problemErrorView,
  sendProblemReport, sendSummary, whoWrote,
} = problemReportModule

const realRequire = createRequire(import.meta.url)
const source = readFileSync(new URL('./McpProblemReports.jsx', import.meta.url), 'utf8')
const compiled = transformSync(source, { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
const formatBytes = n => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB`
  : `${(n / (1024 * 1024)).toFixed(1)} MB`)
new Function('require', 'module', 'exports', compiled)(name => {
  if (name === '../../shared/transport/api') return { api: {} }
  if (name === '../../shared/transport/socket') return { subscribe: () => () => {} }
  if (name === '../../shared/audio/sounds') return { playSound: () => {}, playHoverSound: () => {} }
  if (name === '../chat/ChatReportModal') return { formatBytes }
  if (name.endsWith('.css')) return {}
  if (name === './problemReport') return problemReportModule
  return realRequire(name)
}, module, module.exports)
const { ProblemReportView } = module.exports
const render = props => renderToStaticMarkup(React.createElement(ProblemReportView, props))

const REPORT = {
  id: 'a'.repeat(32), title: 'Import of Clank failed', created_at: 1,
  markdown: '# It failed\nThe model at ~/Documents/models/Clank.glb did not load. <b>not html</b>',
  reported_by: { model: 'claude-opus-5-5', effort: 'high' }, refs: { job_id: 'job1' },
  attachments: [
    { name: 'report.md', label: "Your AI's report", kind: 'markdown', bytes: 120, optional: false, include: true, too_large: false },
    { name: 'metadata.json', label: 'Versions, timings and error output', kind: 'metadata', bytes: 900, optional: false, include: true, too_large: false },
    { name: 'import/job.log', label: "The import's log", kind: 'record', bytes: 2048, optional: true, include: true, too_large: false },
    { name: 'source/Clank.glb', label: 'The model file it was made from', kind: 'source', bytes: 3 * 1024 * 1024, optional: true, include: false, too_large: false },
    { name: 'source/Huge.zip', label: 'The model file it was made from', kind: 'source', bytes: 90 * 1024 * 1024, optional: true, include: false, too_large: true },
  ],
}

function fakeApi({ review = { submission_id: 's1', approval_hash: 'h1' }, submit = { state: 'sent', id: 'abcdef0123456789' }, fail } = {}) {
  const calls = []
  return {
    calls,
    get: async path => { calls.push(['GET', path]); return { pending: [REPORT] } },
    post: async (path, body) => {
      calls.push(['POST', path, body])
      if (fail && path.includes(fail.on)) throw fail.error
      return path.endsWith('/review') ? review : path.endsWith('/discard') ? { ok: true } : submit
    },
  }
}

test('the card shows who wrote it, the markdown as text, each part with its size, Send and Discard', () => {
  const html = render({ report: REPORT, choice: initialChoice(REPORT) })
  assert.match(html, /Your AI \(claude-opus-5-5, effort high\) wrote a problem report/)
  assert.match(html, /Import of Clank failed/)
  assert.match(html, /&lt;b&gt;not html&lt;\/b&gt;/)                          // shown as text, never as HTML
  assert.ok(html.includes(PROBLEM_CONSENT))
  assert.match(html, /report\.md<\/code><\/span><span class="problem-report-part-size">120 B · always sent/)
  assert.match(html, /import\/job\.log<\/code><\/span><\/label><span class="problem-report-part-size">2\.0 KB/)
  assert.match(html, /<input type="checkbox" checked=""\/><span class="problem-report-part-name">The import&#x27;s log/)
  assert.match(html, /<input type="checkbox"\/><span class="problem-report-part-name">The model file it was made from <code>source\/Clank\.glb/)
  assert.match(html, /disabled=""\/><span class="problem-report-part-name">The model file it was made from <code>source\/Huge\.zip/)
  assert.match(html, /90\.0 MB · too large to send/)
  assert.match(html, /Sends 3 parts, 3\.0 KB/)
  assert.match(html, />Send</)
  assert.match(html, />Discard</)
  assert.doesNotMatch(html, /style=/)
})

test('busy, sent and gate states', () => {
  const sending = render({ report: REPORT, phase: 'sending' })
  assert.match(sending, /<button[^>]*disabled=""[^>]*>Sending…<\/button>/)
  assert.match(sending, /<button[^>]*disabled=""[^>]*>Discard<\/button>/)
  const done = render({ report: REPORT, result: { id: 'abcdef0123456789' } })
  assert.match(done, /Reference: abcdef01/)
  assert.doesNotMatch(done, />Send</)
  assert.match(done, />Close</)
  const gate = render({ report: REPORT, gate: { latest: '0.9.4' } })
  assert.match(gate, /newer version \(v0\.9\.4\)/)
  assert.match(render({ report: REPORT, waiting: 3 }), /2 more waiting after this one/)
})

test('the ticked parts: the backend suggestion first, never one too large', () => {
  const choice = initialChoice(REPORT)
  assert.deepEqual(choice, { 'import/job.log': true, 'source/Clank.glb': false })
  assert.deepEqual(includedNames(REPORT, { ...choice, 'source/Clank.glb': true, 'source/Huge.zip': true }),
    ['import/job.log', 'source/Clank.glb'])
  assert.deepEqual(sendSummary(REPORT, { 'import/job.log': false }), { count: 2, bytes: 1020 })
  assert.equal(whoWrote({ reported_by: {} }), 'Your AI')
})

test('Send freezes the ticked parts, then sends them through the chat report submit with consent', async () => {
  const api = fakeApi()
  const outcome = await sendProblemReport(api, REPORT, { 'import/job.log': true, 'source/Clank.glb': true }, '0.10.0')
  assert.deepEqual(api.calls, [
    ['POST', `${REPORTS_URL}/${'a'.repeat(32)}/review`, { include: ['import/job.log', 'source/Clank.glb'], app_version: '0.10.0' }],
    ['POST', '/chat-reports/submit', { submission_id: 's1', approval_hash: 'h1', consent: true }],
  ])
  assert.deepEqual(outcome, { state: 'sent', id: 'abcdef0123456789', confirmed: true })
})

test('a refused freeze sends nothing; Discard and the list use the window routes', async () => {
  const error = Object.assign(new Error('x'), { status: 409, data: { error: 'report_discarded' } })
  const api = fakeApi({ fail: { on: '/review', error } })
  await assert.rejects(sendProblemReport(api, REPORT, {}, undefined))
  assert.equal(api.calls.length, 1)                                // the submit was never reached
  assert.deepEqual(api.calls[0][2], { include: [] })
  assert.deepEqual(problemErrorView(error), { kind: 'error', text: 'This report was discarded.' })
  assert.deepEqual(problemErrorView({ status: 426, data: { error: 'update_required', latest: '0.9.4' } }),
    { kind: 'gate', latest: '0.9.4', url: null })
  const other = fakeApi()
  await discardProblemReport(other, REPORT)
  assert.deepEqual(await listReports(other), [REPORT])
  assert.deepEqual(other.calls, [['POST', `${REPORTS_URL}/${'a'.repeat(32)}/discard`, {}], ['GET', REPORTS_URL]])
})
