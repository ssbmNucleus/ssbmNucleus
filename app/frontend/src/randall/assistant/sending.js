// Whether the panel can send a message now (AssistantPanel's `send`), as a pure function.

/**
 * What a send does now: 'send' (the turn starts), 'queue' (a message typed while Randall works goes to the queue),
 * or null (nothing happens: no text, an upload or a change to the queue in progress, the chat loading, no access, or
 * a queued message while Randall's reply is still open).
 *
 * `busy`: a turn is on (busyRef); `replying`: its reply stream is open (replyRunId or a controller); `queued`: the
 * queued input being sent (a queued one may start while the panel is still busy with the turn it waited on).
 */
export function sendGate({ text, uploading = false, loadingChat = false, ready = true, changingInput = false,
  busy = false, replying = false, queued = null }) {
  if (!String(text ?? '').trim() || uploading || loadingChat || !ready || changingInput) return null
  if (busy && (replying || !queued)) return queued ? null : 'queue'
  return 'send'
}

/** A failed send restores its text only if the user has not typed a new draft. */
export function restoreFailedDraft(current, sent) {
  return current.trim() ? current : sent
}
