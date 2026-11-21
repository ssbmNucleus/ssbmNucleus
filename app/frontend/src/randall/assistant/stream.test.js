import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readAssistantStream } from './stream.js'

test('SSE handles bytewise UTF-8, CRLF, heartbeats and final unterminated event', async () => {
  const bytes = new TextEncoder().encode(': ping\r\n\r\ndata: {"type":"delta","content":"Marth ✧"}\r\n\r\ndata: {"type":"done"}')
  const response = new Response(new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
    controller.close()
  } }))
  const events = []
  await readAssistantStream(response, event => events.push(event))
  assert.deepEqual(events, [{ type: 'delta', content: 'Marth ✧' }, { type: 'done' }])
})

test('A truncated stream is not reported as complete', async () => {
  await assert.rejects(readAssistantStream(new Response('data: {"type":"delta","content":"partial"}\n\n'), () => {}), /before the turn finished/)
})
