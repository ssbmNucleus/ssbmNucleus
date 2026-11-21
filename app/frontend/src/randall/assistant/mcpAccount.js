/**
 * Hand the backend this window's Patreon app token, so the user's own AI (MCP) spends the same Randall usage as
 * this chat (backend randall/mcp/credits.py, docs/dev/APP_MCP.md). The backend keeps it in memory only and checks
 * the entitlement itself before each AI call, as this chat does before each turn; it never gets the provider key.
 *
 * App.jsx runs this at launch and on every entitlement change: a link sends the new token, a sign-out (including
 * the automatic one on invalid_token) sends null. Quitting ends the backend, and the token with it.
 */
export function createMcpAccountMirror({ getToken, post }) {
  return async function mirror() {
    try {
      await post({ token: getToken() || null })
    } catch { /* backend down or restarting: the next launch or entitlement change sends it again */ }
  }
}

/** Fired on window when the Slippi Dolphin folder in Settings (localStorage slippi_dolphin_path) changes. */
export const SLIPPI_PATH_EVENT = 'nucleus:slippi-dolphin-path'   // fired by name in SlippiPathSection and FirstRunSetup

/**
 * Hand the backend the Slippi Dolphin folder set in Settings, so test_in_game over MCP uses it without the user's AI
 * asking for it (backend randall/mcp/window.py). The chat sends it with every request; an MCP client has no window.
 * App.jsx runs this at launch and on SLIPPI_PATH_EVENT (Settings and first-run setup fire it).
 */
export function createMcpWindowMirror({ getDolphinPath, post }) {
  return async function mirror() {
    try {
      await post({ slippi_dolphin_path: getDolphinPath() || null })
    } catch { /* backend down or restarting: the next launch or change sends it again */ }
  }
}

/**
 * Show the user's own AI's questions for the person at this window (backend randall/mcp/window.py), such as
 * connecting a creation toolkit folder, whose Python Nucleus then runs. The AI client's own prompt is not enough
 * for those: the backend waits for the answer given here, which only this window can send (its own key).
 *
 * `list` reads the open questions, `ask(item)` shows one and resolves true (allowed) or false, `answer(id, allowed)`
 * sends it, and `subscribe(refresh)` calls refresh when the backend says the list changed (and on reconnect).
 * Each question is shown once. Returns the unsubscribe.
 */
export function createMcpConfirmWatcher({ list, ask, answer, subscribe }) {
  const shown = new Set()
  async function refresh() {
    let pending
    try {
      pending = (await list())?.pending
    } catch { return }       // backend restarting: the reconnect refreshes again
    for (const item of Array.isArray(pending) ? pending : []) {
      if (!item?.id || shown.has(item.id)) continue
      shown.add(item.id)
      let allowed = false
      try { allowed = (await ask(item)) === true } catch { allowed = false }
      try { await answer(item.id, allowed) } catch { /* withdrawn meanwhile: the AI was told nobody answered */ }
    }
  }
  const stop = subscribe(refresh)
  refresh()
  return stop
}
