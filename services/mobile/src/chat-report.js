// "Report this chat" on the phone. Pure module (no imports) so node:test can
// load it directly: build the report from one Randall thread, scrub it, zip it,
// and send it through the same bug-report worker the desktop uses, with
// kind "chat" and platform "mobile" (see services/cloudflare/bugreport-worker).
//
// Rules mirrored from the desktop (backend/randall/reports/chat_report.py):
//   * nothing is sent without the Send tap; the preview is built from the same
//     bytes that are sent, and a thread that changed since the preview is not
//     sent (the caller re-previews instead);
//   * secrets never leave: OpenRouter / sk- keys, bearer tokens, JWTs and any
//     secret the caller names (the device token) are masked everywhere;
//   * long tool results are cut with a visible "…[truncated N chars]" marker;
//   * a failed upload retries into the SAME remote report (its id is kept in
//     storage before the upload), so a lost reply never files twice.

export const REPORT_URL = 'https://ssbmnucleus.net/bugreport'
export const CONSENT_LINE = 'This sends this conversation to the developer to help fix Randall. It is not public.'
export const CONTENT_MAX = 20000
export const ARGS_MAX = 4000
export const RESULT_MAX = 6000
export const BUDGET = 4 * 1024 * 1024     // uncompressed; a phone thread is tiny next to this
const FLOOR = 256
const PENDING_KEY = 'nucleus.randall.report.pending'

// ── scrubbing ───────────────────────────────────────────────────────────────

const TOKEN_RES = [
  [/(sk-or-v\d+-)[A-Za-z0-9]{16,}/g, '$1***'],
  [/(sk-(?:ant-|proj-)?)[A-Za-z0-9_-]{20,}/g, '$1***'],
  [/(Bearer\s+)[A-Za-z0-9._+/=-]{8,}/g, '$1***'],
  [/(eyJ[A-Za-z0-9_-]{8,}\.)[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, '$1***'],
  [/(token=)[^&\s"']+/gi, '$1***'],
  [/("(?:access_token|refresh_token|api_key|apikey|token)"\s*:\s*")[^"]+/gi, '$1***'],
]
const SECRET_KEYS = new Set(['api_key', 'apikey', 'token', 'access_token', 'refresh_token',
  'authorization', 'password', 'secret', 'device_token'])

export function scrubText(text, secrets = []) {
  if (typeof text !== 'string' || !text) return text
  let out = text
  for (const secret of secrets) {
    if (secret && secret.length >= 8) out = out.split(secret).join('***')
  }
  for (const [re, rep] of TOKEN_RES) out = out.replace(re, rep)
  return out
}

export function scrub(value, secrets = [], key = null) {
  if (key && SECRET_KEYS.has(String(key).toLowerCase()) && value) return '***'
  if (typeof value === 'string') return scrubText(value, secrets)
  if (Array.isArray(value)) return value.map((v) => scrub(v, secrets))
  if (value && typeof value === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(value)) out[k] = scrub(v, secrets, k)
    return out
  }
  return value
}

// Tool arguments/results are JSON strings: scrub the structure they encode so
// credential KEYS are masked too, and do it before any clip (a cut can split a
// secret the text patterns would otherwise catch, or hide the key entirely).
export function scrubJsonText(text, secrets = []) {
  if (typeof text !== 'string' || !/^\s*[[{]/.test(text)) return scrubText(text, secrets)
  let parsed
  try { parsed = JSON.parse(text) } catch { return scrubText(text, secrets) }
  return parsed && typeof parsed === 'object' ? JSON.stringify(scrub(parsed, secrets)) : scrubText(text, secrets)
}

export function clip(text, limit) {
  const s = typeof text === 'string' ? text : JSON.stringify(text ?? null)
  return s.length <= limit ? s : `${s.slice(0, limit)}…[truncated ${s.length - limit} chars]`
}

// ── the report ──────────────────────────────────────────────────────────────

const iso = (ms) => (Number.isFinite(ms) && ms > 0 ? new Date(ms).toISOString() : null)

function conversationOf(thread, caps, secrets = []) {
  const cut = (text, limit) => clip(scrubJsonText(text, secrets), limit)
  const api = (thread.api || []).map((m, index) => {
    const row = { index, role: m.role }
    if (m.role === 'tool') {
      row.name = m.name || null
      row.tool_call_id = m.tool_call_id || null
      row.result = cut(m.content || '', caps.result)
      try {
        const parsed = JSON.parse(m.content || 'null')
        if (parsed && parsed.error) row.error = cut(String(parsed.error), 500)
      } catch { /* not JSON: kept as text */ }
      return row
    }
    row.content = cut(m.content || '', caps.content)
    if (m.tool_calls?.length) {
      row.tool_calls = m.tool_calls.map((tc) => ({
        id: tc.id || null,
        name: tc.function?.name || null,
        arguments: cut(tc.function?.arguments || '', caps.args),
      }))
    }
    return row
  })
  const display = (thread.display || []).map((m, index) => ({
    index,
    role: m.role,
    at: iso(m.at),
    content: m.role === 'upsell' ? '(AI tier upsell card)' : cut(m.content || '', caps.content),
    ...(m.meta ? { turn: m.meta } : {}),
    ...(m.chips?.length ? { references: m.chips.length } : {}),
  }))
  const toolCalls = api.reduce((n, m) => n + (m.tool_calls?.length || 0), 0)
  const errors = [
    ...display.filter((m) => m.role === 'error').map((m) => ({ where: 'turn', index: m.index, error: m.content })),
    ...api.filter((m) => m.error).map((m) => ({ where: `tool:${m.name}`, index: m.index, error: m.error })),
  ]
  return {
    display, api, errors,
    counts: {
      messages: display.length,
      user: display.filter((m) => m.role === 'user').length,
      assistant: display.filter((m) => m.role !== 'user').length,
      tool_calls: toolCalls,
    },
  }
}

export function transcriptMarkdown(conversation, note) {
  const lines = ['# Randall chat report (mobile)', '',
    `- Thread: \`${conversation.conversation_id}\` ${conversation.title || ''}`.trimEnd(),
    `- App: ${conversation.app.version} · ${conversation.app.user_agent || ''}`.trimEnd(),
    `- Messages: ${conversation.counts.messages}, tool calls: ${conversation.counts.tool_calls}, errors: ${conversation.errors.length}`]
  if (note) lines.push('', '## What went wrong', '', note)
  lines.push('', '## Transcript', '')
  for (const m of conversation.display) {
    const who = m.role === 'user' ? 'You' : m.role === 'error' ? 'Error' : 'Randall'
    const extra = m.turn ? ` (${[m.turn.model, m.turn.rounds != null ? `${m.turn.rounds} rounds` : null]
      .filter(Boolean).join(', ')})` : ''
    lines.push(`### ${m.index}. ${who}${m.at ? ` · ${m.at}` : ''}${extra}`, '', m.content || '', '')
    for (const t of m.turn?.tools || []) lines.push(`- tool \`${t}\``)
    if (m.turn?.tools?.length) lines.push('')
  }
  lines.push('## Tool calls (model-facing history)', '')
  for (const m of conversation.api) {
    for (const tc of m.tool_calls || []) lines.push(`- \`${tc.name}\` args: \`${clip(tc.arguments, 300)}\``)
    if (m.role === 'tool' && m.error) lines.push(`  - error from \`${m.name}\`: ${m.error}`)
  }
  return `${lines.join('\n').trimEnd()}\n`
}

/**
 * Build the scrubbed, size-capped report for one thread.
 *   thread: {id, title, api, display, updated}
 *   info:   {appVersion, model, usage: {weekly_allowance, remaining}, userAgent}
 * Returns {files: [{name, text}], meta, counts, truncated, conversationText}.
 */
export function buildMobileReport({ thread, note = '', contact = '', info = {}, secrets = [], now = Date.now() }) {
  let caps = { content: CONTENT_MAX, args: ARGS_MAX, result: RESULT_MAX }
  const cleanNote = scrubText(String(note).trim().slice(0, 4000), secrets)
  const cleanContact = scrubText(String(contact).trim().slice(0, 200), secrets)
  const usage = info.usage || null
  let conversation, conversationText, transcript
  for (;;) {
    conversation = scrub({
      report_version: 1, kind: 'chat', surface: 'mobile',
      conversation_id: String(thread.id || 'unsaved'), title: thread.title || null,
      updated_at: iso(thread.updated),
      app: { version: info.appVersion || '0.0.0', platform: 'mobile', user_agent: info.userAgent || null },
      randall: { model_key: info.model || null, transport: 'randall-chat edge function' },
      budget: usage ? {
        source: 'nucleus_ai_tier',
        weekly_allowance: Number.isFinite(usage.weekly_allowance) ? usage.weekly_allowance : null,
        remaining: Number.isFinite(usage.remaining) ? usage.remaining : null,
      } : null,
      ...conversationOf(thread, caps, secrets),
      caps: { ...caps },
    }, secrets)
    conversationText = JSON.stringify(conversation, null, 2)
    transcript = scrubText(transcriptMarkdown(conversation, cleanNote), secrets)
    if (conversationText.length + transcript.length <= BUDGET
        || Object.values(caps).every((v) => v <= FLOOR)) break
    caps = Object.fromEntries(Object.entries(caps).map(([k, v]) => [k, Math.max(FLOOR, v >> 1)]))
  }
  const truncated = conversationText.includes('…[truncated ')
  const report = {
    kind: 'chat', report_version: 1, surface: 'mobile',
    conversation_id: conversation.conversation_id,
    submitted_at: new Date(now).toISOString(),
    note: cleanNote, contact: cleanContact,
    app: conversation.app, budget: conversation.budget,
    counts: conversation.counts, truncated,
  }
  const files = [
    { name: 'report.json', text: JSON.stringify(report, null, 2) },
    { name: 'conversation.json', text: conversationText },
    { name: 'transcript.md', text: transcript },
  ]
  const meta = {
    kind: 'chat',
    app_version: /^\d+\.\d+\.\d+$/.test(conversation.app.version) ? conversation.app.version : '0.0.0',
    platform: 'mobile',
    description: cleanNote || 'Randall chat report (no note)',
    contact: cleanContact,
    truncated,
    chat: {
      surface: 'mobile',
      message_count: conversation.counts.messages,
      tool_calls: conversation.counts.tool_calls,
      errors: conversation.errors.length,
      conversation_id: conversation.conversation_id.slice(0, 64),
      model: (info.model || '').slice(0, 80),
    },
  }
  return { files, meta, counts: conversation.counts, truncated, conversationText, transcript }
}

/** Plain-language lines for the "What gets sent" preview. */
export function describeReport(built) {
  const c = built.counts
  const lines = [`This conversation: ${c.user} of your messages and ${c.assistant} of Randall's replies, with timestamps.`]
  if (c.tool_calls) lines.push(`${c.tool_calls} tool call(s) Randall made on this phone, with their inputs and results (long results are shortened).`)
  lines.push('Which model you picked, and how many rounds each answer took.')
  lines.push('App version and your browser name.')
  lines.push('Your AI allowance status, if it was loaded (not a key).')
  lines.push('Your note and contact, if you add them.')
  if (built.truncated) lines.push('Some long parts were shortened to keep the report small.')
  return lines
}

export const NOT_INCLUDED = [
  'Your device pairing token and any keys (removed if they appear).',
  'Your replay library, other chats and app data.',
]

// ── zip (stored, no compression: the worker only needs a valid archive) ─────

const CRC_TABLE = (() => {
  const t = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    t[n] = c >>> 0
  }
  return t
})()

export function crc32(bytes) {
  let c = 0xffffffff
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

export function zipStore(files) {
  const enc = new TextEncoder()
  const entries = files.map((f) => {
    const name = enc.encode(f.name)
    const data = f.bytes || enc.encode(f.text)
    return { name, data, crc: crc32(data) }
  })
  const size = entries.reduce((n, e) => n + 30 + e.name.length + e.data.length + 46 + e.name.length, 22)
  const out = new Uint8Array(size)
  const view = new DataView(out.buffer)
  let p = 0
  const central = []
  // DOS date 2020-01-01 00:00 so the same inputs give the same bytes.
  const DOS_DATE = ((2020 - 1980) << 9) | (1 << 5) | 1
  for (const e of entries) {
    central.push({ ...e, offset: p })
    view.setUint32(p, 0x04034b50, true); view.setUint16(p + 4, 20, true); view.setUint16(p + 6, 0x0800, true)
    view.setUint16(p + 8, 0, true); view.setUint16(p + 10, 0, true); view.setUint16(p + 12, DOS_DATE, true)
    view.setUint32(p + 14, e.crc, true); view.setUint32(p + 18, e.data.length, true)
    view.setUint32(p + 22, e.data.length, true); view.setUint16(p + 26, e.name.length, true)
    view.setUint16(p + 28, 0, true)
    out.set(e.name, p + 30); out.set(e.data, p + 30 + e.name.length)
    p += 30 + e.name.length + e.data.length
  }
  const cdStart = p
  for (const e of central) {
    view.setUint32(p, 0x02014b50, true); view.setUint16(p + 4, 20, true); view.setUint16(p + 6, 20, true)
    view.setUint16(p + 8, 0x0800, true); view.setUint16(p + 10, 0, true); view.setUint16(p + 12, 0, true)
    view.setUint16(p + 14, DOS_DATE, true); view.setUint32(p + 16, e.crc, true)
    view.setUint32(p + 20, e.data.length, true); view.setUint32(p + 24, e.data.length, true)
    view.setUint16(p + 28, e.name.length, true); view.setUint16(p + 30, 0, true); view.setUint16(p + 32, 0, true)
    view.setUint16(p + 34, 0, true); view.setUint16(p + 36, 0, true); view.setUint32(p + 38, 0, true)
    view.setUint32(p + 42, e.offset, true)
    out.set(e.name, p + 46)
    p += 46 + e.name.length
  }
  view.setUint32(p, 0x06054b50, true); view.setUint16(p + 4, 0, true); view.setUint16(p + 6, 0, true)
  view.setUint16(p + 8, central.length, true); view.setUint16(p + 10, central.length, true)
  view.setUint32(p + 12, p - cdStart, true); view.setUint32(p + 16, cdStart, true); view.setUint16(p + 20, 0, true)
  return out
}

// ── sending ─────────────────────────────────────────────────────────────────

function readPending(storage) {
  try { return JSON.parse(storage?.getItem(PENDING_KEY) || 'null') } catch { return null }
}
function writePending(storage, value) {
  try {
    if (value) storage?.setItem(PENDING_KEY, JSON.stringify(value))
    else storage?.removeItem(PENDING_KEY)
  } catch { /* private mode: retries then just file anew */ }
}

/**
 * Two-stage send of an already-built zip. Returns {state: 'sent', id, confirmed}
 * or throws an Error with `.status` and `.data` (426 carries latest/url).
 */
export async function sendMobileReport({ zip, meta, fetchImpl = fetch, url = REPORT_URL, storage = null }) {
  const bundleKey = `${crc32(zip).toString(16)}:${zip.length}`
  let pending = readPending(storage)
  if (!pending || pending.bundle !== bundleKey) pending = { bundle: bundleKey, id: null }
  const fail = async (r, stage) => {
    const data = await r.json().catch(() => ({}))
    const err = new Error(data.error || `${stage} failed (HTTP ${r.status})`)
    err.status = r.status
    err.data = data
    return err
  }
  if (!pending.id) {
    const created = await fetchImpl(url, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ...meta, zip_size: zip.length }),
    })
    if (!created.ok) throw await fail(created, 'create')
    const body = await created.json()
    if (!body.id) throw Object.assign(new Error('report server returned no id'), { status: 502, data: {} })
    pending = { ...pending, id: body.id }
    writePending(storage, pending)            // before the upload: a lost reply retries into THIS report
  }
  const put = await fetchImpl(`${url}/${pending.id}/zip`, {
    method: 'PUT', headers: { 'content-type': 'application/zip' }, body: zip,
  })
  if (put.ok) {
    writePending(storage, null)
    const body = await put.json().catch(() => ({}))
    return { state: 'sent', id: pending.id, confirmed: true, notified: !!body.notified }
  }
  // A re-upload of a report the worker already stored answers 200 from its
  // receipt, so 404 is never proof of delivery: the slot expired (maybe on an
  // earlier try whose 410 was lost) or never existed. The next try files anew.
  if (put.status === 404 || put.status === 410) writePending(storage, null)
  throw await fail(put, 'upload')
}

/** What the sheet shows for a thrown send error. */
export function errorText(err) {
  if (err?.status === 426) return 'Update the app first, then report again.'
  if (err?.status === 429) return 'Too many reports right now. Please try again in a minute.'
  if (!err?.status) return 'No connection. Check your internet and try again.'
  return `Sending failed (${err.data?.error || err.message}). Try again.`
}
