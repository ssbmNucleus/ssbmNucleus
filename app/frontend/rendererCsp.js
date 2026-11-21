// The renderer's Content-Security-Policy (security review 11-19, H1).
//
// The packaged app loads frontend/dist/index.html over file://, with the
// preload's IPC bridge in reach of any script that runs there. This policy
// lets only the built bundle run code: no inline or remote scripts, no eval,
// no plugins, frames, <base> or form posts. What the app legitimately reaches
// stays open:
//   - the local backend (REST, Socket.IO, /storage images and audio) on
//     127.0.0.1 / localhost at whatever port it picked;
//   - HTTPS / WSS: Supabase (account, cloud, realtime), the website and its
//     media CDN, Patreon, start.gg and the other remote images;
//   - Google Fonts (index.html's stylesheet and its font files);
//   - blob: and data: for previews, downloads, textures and workers
//     (Watch Lite's deriver is a module worker from the bundle).
// React inline styles need style-src 'unsafe-inline'.
//
// It is added to the BUILT index.html only (`apply: 'build'`): the Vite dev
// server injects an inline React-refresh preamble that script-src 'self' would
// block. Note a <meta> CSP cannot carry frame-ancestors, report-uri or sandbox.
const LOCAL = 'http://127.0.0.1:* http://localhost:*'
const LOCAL_WS = 'ws://127.0.0.1:* ws://localhost:*'

export const RENDERER_CSP_DIRECTIVES = {
  'default-src': "'self'",
  'script-src': "'self'",
  'worker-src': "'self' blob:",
  'style-src': "'self' 'unsafe-inline' https://fonts.googleapis.com",
  'font-src': "'self' data: https://fonts.gstatic.com",
  'img-src': `'self' data: blob: ${LOCAL} https:`,
  'media-src': `'self' data: blob: ${LOCAL} https:`,
  'connect-src': `'self' data: blob: ${LOCAL} ${LOCAL_WS} https: wss:`,
  'object-src': "'none'",
  'base-uri': "'self'",
  'form-action': "'none'",
  'frame-src': "'none'",
}

export const RENDERER_CSP = Object.entries(RENDERER_CSP_DIRECTIVES)
  .map(([name, value]) => `${name} ${value}`)
  .join('; ')

/** Vite plugin: the CSP <meta> as the first element of the built <head>. */
export function rendererCsp() {
  return {
    name: 'nucleus-renderer-csp',
    apply: 'build',
    transformIndexHtml() {
      return [{
        tag: 'meta',
        attrs: { 'http-equiv': 'Content-Security-Policy', content: RENDERER_CSP },
        injectTo: 'head-prepend',
      }]
    },
  }
}
