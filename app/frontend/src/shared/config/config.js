// Dev override: open http://localhost:3000/?backendPort=NNNNN to point a
// browser preview at a test backend instead of the app's port-5000 instance.
const port = window.electron?.backendPort
  || new URLSearchParams(window.location.search).get('backendPort')
  || 5000;
export const BACKEND_TOKEN = window.electron?.backendToken
  || new URLSearchParams(window.location.search).get('backendToken')
  || '';
// Only the app window has this: Electron passes it on the renderer's command
// line, the backend reads it from its own environment, and it is never printed
// or served. The build-change approval endpoint requires it, because the
// backend token is shared with every tool that can read the startup log.
export const UI_APPROVAL_KEY = window.electron?.uiApprovalKey || '';
export const BACKEND_URL = `http://127.0.0.1:${port}`;
export const API_URL = `${BACKEND_URL}/api/mex`;

export function backendMediaUrl(pathOrUrl, cacheBust) {
  const url = new URL(pathOrUrl, `${BACKEND_URL}/`)
  if (cacheBust !== undefined) url.searchParams.set('v', cacheBust)
  if (BACKEND_TOKEN && url.origin === new URL(BACKEND_URL).origin && url.pathname.startsWith('/api/')) {
    url.searchParams.set('_nucleus_token', BACKEND_TOKEN)
  }
  return url.toString()
}
