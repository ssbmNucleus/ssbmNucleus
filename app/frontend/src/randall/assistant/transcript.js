// Poll download receipts while SSE owns the in-flight reply. A server snapshot
// can include tokens that SSE has not delivered yet; replacing that reply would
// append those tokens twice when the stream catches up.
export function mergeTranscript(previous, incoming, streamingId) {
  const streaming = streamingId && previous.find(message => message.id === streamingId)
  if (!streaming) return incoming
  let found = false
  const exact = incoming.some(message => message.id === streamingId)
  if (!exact && /^[a-f0-9]{32}$/.test(streamingId)) {
    // An older poll can arrive after SSE has already started the next turn.
    // Keep its user/assistant pair; only merge independent download receipts.
    const downloads = incoming.filter(message => message.run_kind === 'download')
    return [...previous.map(message => downloads.find(row => row.id === message.id) || message),
      ...downloads.filter(message => !previous.some(row => row.id === message.id))]
  }
  const merged = incoming.map(message => {
    if (message.id === streamingId || (!exact && !found && message.run_kind === 'reply' &&
        !previous.some(old => old.id === message.id))) {
      found = true
      return streaming
    }
    return message
  })
  return found ? merged : [...merged, streaming]
}

export function applyPendingInput(messages, event) {
  const replaced = messages.map(message => message.id === event.message.id ? event.message : message)
  for (const user of event.users || [event.user]) {
    if (!replaced.some(message => message.id === user.id)) replaced.push(user)
  }
  if (!replaced.some(message => message.id === event.message.id)) replaced.push(event.message)
  return replaced
}

export function applyTurnProgress(message, event) {
  // SSE progress updates metadata only; never replace streamed prose or receipts.
  if (message.id !== event.message_id || message.status !== 'running') return message
  return { ...message, started_at: event.started_at, model_rounds: event.model_rounds }
}

export function showLongRunningNotice(message, now = Date.now()) {
  if (!message || message.role !== 'assistant' || message.run_kind === 'download'
      || message.status !== 'running' || message.error) return false
  if (message.tools?.some(tool => tool.approval?.status === 'pending')) return false
  const elapsed = Number.isFinite(message.started_at) ? now - message.started_at * 1000 : 0
  // Informational thresholds only. Neither value pauses or limits the worker.
  return elapsed >= 120_000 || message.model_rounds >= 12
}

export function orderedMessageParts(message) {
  const content = message.content || ''
  const parts = []
  let cursor = 0
  for (const tool of message.tools || []) {
    // Legacy turns did not record interleaving. Put their explanation before
    // their tools; never guess a boundary from model prose.
    const offset = Math.max(cursor, Math.min(content.length,
      Number.isInteger(tool.content_offset) ? tool.content_offset : content.length))
    if (offset > cursor) parts.push({ kind: 'text', key: `text-${cursor}`, text: content.slice(cursor, offset), complete: true })
    const previous = parts.at(-1)
    if (previous?.kind === 'tools' && offset === cursor) previous.tools.push(tool)
    else parts.push({ kind: 'tools', key: tool.id, tools: [tool] })
    cursor = offset
  }
  parts.push({ kind: 'text', key: `text-${cursor}`, text: content.slice(cursor), complete: false })
  return parts
}

export function showWorkingBubble(message) {
  // The turn is waiting on the model: before the first token, and again in every
  // gap after a tool finishes. This used to go quiet for the rest of the turn as
  // soon as ANY tool produced a result, so a long chain of reads looked stalled.
  // A hardcoded allowlist of tools with their own live row had the same effect
  // for anything missing from it; the row's single dot and these three share a
  // cadence and are meant to coexist, so no list is needed.
  if (message.status !== 'running' || message.error) return false
  // A pending approval waits on the USER, not the model. Nothing is working.
  if (message.tools?.some(tool => tool.approval?.status === 'pending')) return false
  const last = orderedMessageParts(message).at(-1)
  return !(last?.kind === 'text' && last.text.trim())
}
