/**
 * api.js — the ONE way the frontend talks to the Flask backend.
 *
 *   import { api, ApiError } from './api'
 *   const data = await api.get('/storage/costumes', { query: { character } })
 *   await api.post('/storage/costumes/retest-slippi', { character, skinId })
 *
 * Path resolution:
 *   '/storage/...'            -> `${API_URL}/storage/...`   (API_URL = BACKEND_URL + '/api/mex')
 *   '/api/nucleome/...'       -> `${BACKEND_URL}/api/nucleome/...`  (any absolute '/api/...' path,
 *                                 so '/api/mex/storage/...' is equivalent to '/storage/...')
 *   'http(s)://...'           -> used verbatim
 *
 * Contract: a resolved promise means the call WORKED. Every failure is a thrown
 * `ApiError` — network failure (status 0), non-2xx HTTP, or the backend's own
 * `{ success: false, error }` envelope (status stays 200 in that case). Check
 * `err.status` when a specific code matters (e.g. 404 = feature gated off).
 *
 * JSON bodies are encoded automatically; pass a FormData to upload files.
 * Non-JSON 2xx responses (images, blobs) resolve to `null` — fetch those with
 * `api.url(path)` + your own `fetch`, or use `api.blob(path)`.
 */
import { BACKEND_TOKEN, BACKEND_URL, API_URL, UI_APPROVAL_KEY } from '../config/config.js'
import { getProjectGeneration } from './projectGeneration.js'
import { explainAppControl } from '../lib/appControl.js'

export class ApiError extends Error {
  constructor(message, { status = 0, data = null, url = '' } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
    this.url = url
  }
}

/**
 * Resolve a short API path to a full backend URL.
 *
 * Only '/api/...' is treated as absolute (against BACKEND_URL) — it covers
 * both '/api/mex/...' and '/api/nucleome/...'. Everything else is relative
 * to API_URL, so '/storage/costumes' means the JSON route
 * `/api/mex/storage/costumes`, NOT the static file server at
 * `${BACKEND_URL}/storage/...`. Static assets (images, vanilla DATs) are never
 * fetched through this client; build those URLs from BACKEND_URL directly.
 */
export function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path
  if (path.startsWith('/api/')) return BACKEND_URL + path
  return API_URL + (path.startsWith('/') ? path : `/${path}`)
}

function withQuery(url, query) {
  if (!query) return url
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue
    qs.set(k, String(v))
  }
  const s = qs.toString()
  return s ? `${url}${url.includes('?') ? '&' : '?'}${s}` : url
}

function isBackendUrl(url) {
  try {
    return new URL(url).origin === new URL(BACKEND_URL).origin
  } catch {
    return false
  }
}

export function authenticatedFetch(url, init = {}) {
  if (!isBackendUrl(url)) return fetch(url, init)
  const headers = new Headers(init.headers || {})
  if (BACKEND_TOKEN) headers.set('X-Nucleus-Token', BACKEND_TOKEN)
  // The open project this window is showing (projectGeneration.js).
  const generation = getProjectGeneration()
  if (generation !== null && !headers.has('X-Nucleus-Project')) headers.set('X-Nucleus-Project', String(generation))
  // The endpoints that record a person's decision made in this window (the
  // build-change approval card, the MCP's questions for the window), so they
  // know it came from here, not from anything holding the shared backend token.
  if (UI_APPROVAL_KEY && (String(url).includes('/builds/changes/')
      || String(url).includes('/api/mcp/window/confirmations'))) {
    headers.set('X-Nucleus-UI-Key', UI_APPROVAL_KEY)
  }
  return fetch(url, { ...init, headers })
}

async function request(path, { method = 'GET', body, headers, signal, query } = {}) {
  const url = withQuery(apiUrl(path), query)
  const init = { method, headers: { ...(headers || {}) }, signal }
  if (body !== undefined && body !== null) {
    if (body instanceof FormData || typeof body === 'string') {
      // FormData sets its own multipart boundary; a string is assumed to be
      // already-encoded (callers migrating from raw fetch pass JSON.stringify'd
      // bodies with their own Content-Type header).
      init.body = body
    } else {
      init.headers['Content-Type'] = 'application/json'
      init.body = JSON.stringify(body)
    }
  }

  let res
  try {
    res = await authenticatedFetch(url, init)
  } catch (err) {
    if (err?.name === 'AbortError') throw err
    throw new ApiError('Backend unreachable', { status: 0, url })
  }

  let data = null
  const type = res.headers.get('content-type') || ''
  if (type.includes('application/json')) {
    try { data = await res.json() } catch { data = null }
  } else if (!res.ok) {
    try { data = { error: (await res.text()).slice(0, 500) } } catch { /* empty body */ }
  }

  if (!res.ok || (data && data.success === false)) {
    // A 2xx {success:false} envelope with no error text gets an EMPTY message
    // so call sites' own fallbacks (`err.message || 'Save failed'`) still win,
    // exactly as `data.error || 'Save failed'` did before the migration.
    // A tool Windows refused to load (Smart App Control) is explained, not dumped.
    const message = explainAppControl(data?.error || data?.message || (res.ok ? '' : `HTTP ${res.status}`))
    throw new ApiError(message, { status: res.status, data, url })
  }
  return data
}

export const api = {
  request,
  url: apiUrl,
  get: (path, opts) => request(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body }),
  put: (path, body, opts) => request(path, { ...opts, method: 'PUT', body }),
  patch: (path, body, opts) => request(path, { ...opts, method: 'PATCH', body }),
  delete: (path, body, opts) => request(path, { ...opts, method: 'DELETE', body }),
  /** Fetch a binary response (image, zip) as a Blob; throws ApiError on non-2xx. */
  async blob(path, opts = {}) {
    const url = withQuery(apiUrl(path), opts.query)
    const res = await authenticatedFetch(url, { signal: opts.signal })
    if (!res.ok) throw new ApiError(`HTTP ${res.status}`, { status: res.status, url })
    return res.blob()
  },
}

export default api
