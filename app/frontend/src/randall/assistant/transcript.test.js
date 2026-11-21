import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyPendingInput, applyTurnProgress, mergeTranscript, orderedMessageParts, showWorkingBubble, showLongRunningNotice } from './transcript.js'

test('text and tools retain arrival order across rounds, emoji, approval and reload', () => {
  const first = 'Let me check ☁️ and 🐸.'
  const next = '\n\nI can create the project.'
  const message = { content: first + next, status: 'running', tools: [
    { id: 'search', content_offset: first.length, name: 'search_vault', status: 'done' },
    { id: 'create', content_offset: first.length + next.length, name: 'create_project', approval: { status: 'pending' } },
  ] }
  const parts = orderedMessageParts(message)
  assert.deepEqual(parts.map(p => p.text || p.tools?.[0].id || ''), [first, 'search', next, 'create', ''])
  assert.deepEqual(orderedMessageParts(JSON.parse(JSON.stringify(message))), parts)
  assert.equal(showWorkingBubble(message), false)
  const working = { ...message, tools: message.tools.slice(0, 1) }
  assert.equal(showWorkingBubble(working), false, 'Dots stay hidden after the reply starts')
  assert.equal(showWorkingBubble({ ...working, status: 'done' }), false)
})

test('dots track whether the model is working, not just the opening silence', () => {
  const waiting = { status: 'running', content: '', tools: [] }
  assert.equal(showWorkingBubble(waiting), true)
  // Prose arriving speaks for itself.
  assert.equal(showWorkingBubble({ ...waiting, content: 'Hello' }), false)
  // A finished turn, a failure, or a question aimed at the USER are not work.
  assert.equal(showWorkingBubble({ ...waiting, tools: [{ approval: { status: 'pending' } }] }), false)
  assert.equal(showWorkingBubble({ ...waiting, error: 'Connection lost' }), false)
  assert.equal(showWorkingBubble({ ...waiting, status: 'done' }), false)
})

test('dots return in the gap after a tool finishes', () => {
  // The regression this replaces: any completed tool silenced the dots for the
  // rest of the turn, so a chain of reads looked stalled between every call.
  const afterRead = { status: 'running', content: '', tools: [
    { id: 'a', name: 'skin_lab', status: 'done', result: { reading: true, files: [{ name: 'Skin texture 0.png' }] } },
  ] }
  assert.equal(showWorkingBubble(afterRead), true)
  // Still true for a tool nobody allowlisted, which used to go silent too.
  assert.equal(showWorkingBubble({ ...afterRead, tools: [{ name: 'open_vanilla_file', status: 'done', result: { files: [] } }] }), true)
  // But not once the reply resumes streaming after that tool.
  assert.equal(showWorkingBubble({ ...afterRead, content: 'Here is what I found', tools: [
    { ...afterRead.tools[0], content_offset: 0 }] }), false)
})

test('only adjacent tools with no intervening text can be grouped', () => {
  const parts = orderedMessageParts({ content: 'AB', tools: [
    { id: 'a', content_offset: 1 }, { id: 'b', content_offset: 1 }, { id: 'c', content_offset: 2 },
  ] })
  assert.deepEqual(parts.filter(p => p.kind === 'tools').map(p => p.tools.map(t => t.id)), [['a', 'b'], ['c']])
  const legacy = orderedMessageParts({ content: 'Explanation', tools: [{ id: 'old' }] })
  assert.equal(legacy[0].text, 'Explanation')
  assert.equal(legacy[1].tools[0].id, 'old')
})

test('download polling cannot duplicate or overwrite in-flight reply tokens', () => {
  const reply = { id: 'reply', content: 'First ', run_kind: 'reply' }
  const receipt = { id: 'download', content: '', tools: [{ id: 'receipt' }] }
  const incoming = [{ ...reply, content: 'First last.' }, receipt]
  const merged = mergeTranscript([reply], incoming, 'reply')
  assert.equal(merged[0], reply)
  assert.equal(merged[1], receipt)
  assert.equal(merged[0].content + 'last.', 'First last.')
  assert.deepEqual(mergeTranscript(merged, incoming, null), incoming)
})

test('a receipt arriving before SSE started preserves the optimistic reply', () => {
  const reply = { id: 'optimistic', content: '', run_kind: 'reply' }
  const incoming = [{ id: 'server', content: 'First ', run_kind: 'reply' }, { id: 'download', run_kind: 'download' }]
  const merged = mergeTranscript([reply], incoming, 'optimistic')
  assert.equal(merged.length, 2)
  assert.equal(merged[0], reply)
  assert.equal(merged[1].id, 'download')
})

test('a poll ahead of queued SSE delivery never substitutes multiple replies', () => {
  const first = { id: 'first', run_kind: 'reply', content: 'streamed' }
  const second = { id: 'second', run_kind: 'reply', content: 'future' }
  const user = { id: 'queued', role: 'user', content: 'Next' }
  const merged = mergeTranscript([first], [{ ...first, content: 'completed' }, user, second], 'first')
  assert.equal(merged[0], first)
  assert.equal(merged[2], second)
  const event = { user, message: { ...second, content: '' } }
  const applied = applyPendingInput(merged, event)
  assert.equal(applied.length, 3)
  assert.equal(applied[2].content, '')
  assert.deepEqual(applyPendingInput(applied, event), applied)
})

test('a stale poll cannot remove a newly delivered queued turn', () => {
  const old = { id: 'old', role: 'assistant' }
  const user = { id: 'queued', role: 'user', content: 'Next' }
  const current = { id: 'a'.repeat(32), run_kind: 'reply', content: 'In flight' }
  assert.deepEqual(mergeTranscript([old, user, current], [old], current.id), [old, user, current])
})

test('send all inserts each accepted user once and a single continuation', () => {
  const users = ['first', 'second'].map(id => ({ id, role: 'user', content: id }))
  const event = { users, message: { id: 'reply', role: 'assistant', content: '' } }
  const applied = applyPendingInput([users[0]], event)
  assert.deepEqual(applied, [...users, event.message])
})

test('long-task notice is informational, time-based even during a slow first request', () => {
  const message = { id: 'reply', role: 'assistant', status: 'running', started_at: 1000, model_rounds: 1 }
  assert.equal(showLongRunningNotice(message, 1_119_000), false)
  assert.equal(showLongRunningNotice(message, 1_120_000), true)
  assert.equal(showLongRunningNotice({ ...message, model_rounds: 12 }, 1_000_000), true)
  assert.equal(showLongRunningNotice({ ...message, model_rounds: 100 }, 1_000_000), true)
  assert.equal(showLongRunningNotice({ ...message, started_at: undefined }, 9_000_000), false)
  assert.equal(showLongRunningNotice({ ...message, status: 'done' }, 9_000_000), false)
  assert.equal(showLongRunningNotice({ ...message, status: 'cancelled' }, 9_000_000), false)
  assert.equal(showLongRunningNotice({ ...message, run_kind: 'download' }, 9_000_000), false)
  assert.equal(showLongRunningNotice({ ...message, error: 'Provider unavailable' }, 9_000_000), false)
  assert.equal(showLongRunningNotice({ ...message, tools: [{ approval: { status: 'pending' } }] }, 9_000_000), false)
  assert.equal(showLongRunningNotice(null), false)
})

test('progress updates preserve streamed content and address the exact running turn', () => {
  const message = { id: 'reply', role: 'assistant', status: 'running', content: 'So far ', tools: [{ id: 'tool' }] }
  const event = { type: 'turn_progress', message_id: 'reply', started_at: 1000, model_rounds: 25 }
  const result = applyTurnProgress(message, event)
  assert.equal(result.content, message.content)
  assert.equal(result.tools, message.tools)
  assert.equal(result.model_rounds, 25)
  assert.equal(result.started_at, 1000)
  assert.equal(message.model_rounds, undefined)
  assert.equal(applyTurnProgress(message, { ...event, message_id: 'old' }), message)
  const completed = { ...message, status: 'done' }
  assert.equal(applyTurnProgress(completed, event), completed)
})

test('saved progress restores the notice after reopening without duplicating SSE tokens', () => {
  const saved = { id: 'reply', role: 'assistant', run_kind: 'reply', status: 'running', started_at: 1000,
    model_rounds: 25, content: 'A saved answer' }
  const reopened = mergeTranscript([], [saved], null)
  assert.equal(showLongRunningNotice(reopened[0], 1_001_000), true)
  const streaming = { ...saved, content: 'A saved ' }
  const polled = mergeTranscript([streaming], [{ ...saved, content: 'A saved answer ahead of SSE' }], saved.id)
  assert.equal(polled[0].content, 'A saved ')
  assert.equal(showLongRunningNotice(polled[0], 1_001_000), true)
})
