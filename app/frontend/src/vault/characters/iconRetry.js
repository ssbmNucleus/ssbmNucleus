/**
 * iconRetry.js - which of the vault grid's character icons (the vanilla CSS icons, /vanilla/<name>/css_icon.png)
 * failed to load, and their retry when the vault is read again. Before first-run setup there are no vanilla icons,
 * so each card shows its letter; the grid used to hide a failed <img> for good, and after setup the letters stayed
 * until the grid remounted. Now a vault read (setup finished, an import saved: App.jsx fetchMetadata) tries each
 * failed icon once more, with a query its cached failure cannot answer. An icon that loaded is never asked again.
 *
 * State: { attempts: { name: n }, broken: { name: true } }, never changed in place.
 */
export const EMPTY = Object.freeze({ attempts: Object.freeze({}), broken: Object.freeze({}) })

/** The icon of `name` did not load: its card shows the letter until the next retry. */
export function iconFailed(state, name) {
  if (state.broken[name]) return state
  return { ...state, broken: { ...state.broken, [name]: true } }
}

/** The vault was read again: every failed icon gets one more try. The same state when none failed. */
export function retryIcons(state) {
  const names = Object.keys(state.broken)
  if (names.length === 0) return state
  const attempts = { ...state.attempts }
  for (const name of names) attempts[name] = (attempts[name] || 0) + 1
  return { attempts, broken: {} }
}

/** The src of `name`'s icon (`url`), or null while it is shown as its letter. A retried icon carries its try. */
export function iconSrc(state, name, url) {
  if (state.broken[name]) return null
  const attempt = state.attempts[name] || 0
  return attempt ? `${url}${url.includes('?') ? '&' : '?'}retry=${attempt}` : url
}
