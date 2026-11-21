// The cloud's failures in the words a user should read. The backend passes the
// vault's verdicts through as they came ("vault-public: HTTP 403 {...}",
// "vault-sync: unreachable (...)", wire codes like not_configured), which is
// right for logs and wrong for a person. Every Cloud surface (the Cloud card,
// a running sync's error, the share button) goes through here.

/** What kind of failure this is; decides which button goes next to it. */
export function cloudErrorKind(message, status) {
  const m = String(message || '')
  if (!m && !status) return null
  // api.js: the request never reached Nucleus's own backend
  if (status === 0 || m === 'Backend unreachable') return 'local'
  if (/not_configured/.test(m)) return 'not_linked'
  if (/membership_required/.test(m)) return 'not_member'
  if (/pledge_required/.test(m) || status === 402) return 'pledge_required'
  if (/invalid_token|invalid token|unauthori[sz]ed|HTTP 401/i.test(m) || status === 401) return 'relink'
  // the app-token branch says "inactive" only for a banned Patreon identity
  if (/^inactive$|"inactive"/.test(m)) return 'blocked'
  if (/quota exceeded|HTTP 429/i.test(m) || status === 429) return 'quota'
  if (/unreachable|Failed to fetch|NetworkError|timed out|getaddrinfo|ECONNREFUSED/i.test(m)) return 'offline'
  if (/already running/i.test(m) || (status === 409 && /sync/i.test(m))) return 'busy'
  if (/HTTP 403/.test(m)) return 'refused'
  if (/HTTP 5\d\d/.test(m)) return 'server'
  return 'other'
}

const SENTENCES = {
  not_linked: 'Link a Patreon account first. The free tier is enough to share replays.',
  not_member: "Your Patreon is linked, but it isn't a member of sc00p's Patreon yet. Following isn't enough: join on the free tier, then try again.",
  pledge_required: 'Your whole library on your phone is part of the $5 tier. Sharing single replays stays free.',
  relink: 'Your Patreon link has expired. Link Patreon again to carry on.',
  blocked: "This Patreon account can't use the cloud. Contact sc00p if that seems wrong.",
  quota: 'Upload limit reached for now. Syncing carries on by itself in about ten minutes.',
  offline: "Can't reach the cloud. Check your internet connection and try again.",
  busy: 'A sync is already running.',
  local: "Nucleus's background service isn't answering. Restart Nucleus if this keeps happening.",
  refused: 'The cloud refused that request. Link Patreon again, then try once more.',
  server: 'The cloud had a problem on its end. Try again in a minute.',
}

// A message that still looks like plumbing (an HTTP status, JSON, a function
// name and a colon) is not shown as it is.
const RAW = /HTTP \d{3}|returned \d{3}|[{}]|^[\w-]+: |Traceback|Errno/

/** One plain sentence for a cloud failure. */
export function friendlyCloudError(message, status) {
  const kind = cloudErrorKind(message, status)
  if (!kind) return ''
  if (SENTENCES[kind]) return SENTENCES[kind]
  const m = String(message || '').trim()
  return m && !RAW.test(m) ? m : 'Something went wrong talking to the cloud. Try again in a minute.'
}
