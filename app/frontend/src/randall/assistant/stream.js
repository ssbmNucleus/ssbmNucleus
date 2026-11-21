// SSE framing is independent of network chunk boundaries (including UTF-8).
export async function readAssistantStream(response, onEvent) {
  if (!response.body) throw new Error('Streaming is unavailable in this browser.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = '', completed = false
  const dispatch = (block) => {
    const data = block.split('\n').filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart()).join('\n')
    if (!data) return
    const event = JSON.parse(data)
    if (event.type === 'done') completed = true
    onEvent(event)
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      buffer = buffer.replace(/\r\n/g, '\n')
      let end
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        dispatch(buffer.slice(0, end))
        buffer = buffer.slice(end + 2)
      }
      if (done) break
    }
    if (buffer.trim()) dispatch(buffer)
    if (!completed) throw new Error('The connection ended before the turn finished.')
  } finally {
    reader.releaseLock()
  }
}
