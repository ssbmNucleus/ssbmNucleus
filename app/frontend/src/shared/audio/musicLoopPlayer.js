/** Web Audio transport with independent playback and loop-start positions. */
export function createMusicLoopPlayer(context, buffer, { loopStart = 0, volume = 1 } = {}) {
  const gain = context.createGain()
  gain.gain.value = volume
  gain.connect(context.destination)
  let source = null
  let offset = 0
  let startedAt = 0
  let generation = 0
  let disposed = false
  let wantsPlayback = false
  const clamp = value => Math.max(0, Math.min(buffer.duration - 0.001, value))

  function position() {
    const elapsed = offset + (source ? Math.max(0, context.currentTime - startedAt) : 0)
    return elapsed < buffer.duration ? elapsed
      : loopStart + (elapsed - buffer.duration) % (buffer.duration - loopStart)
  }

  function pause() {
    offset = position()
    generation++
    source?.stop()
    source?.disconnect()
    source = null
    wantsPlayback = false
  }

  async function play(from = position()) {
    pause()
    offset = clamp(from)
    wantsPlayback = true
    const request = generation
    try {
      await context.resume()
    } catch (error) {
      if (request === generation) wantsPlayback = false
      throw error
    }
    if (disposed || request !== generation) return
    const node = context.createBufferSource()
    node.buffer = buffer
    node.loop = true
    node.loopStart = loopStart
    node.loopEnd = buffer.duration
    node.connect(gain)
    node.start(0, offset)
    startedAt = context.currentTime
    source = node
  }

  return {
    get playing() { return source !== null },
    position, play, pause,
    async seek(value) {
      const resume = wantsPlayback
      pause()
      offset = clamp(value)
      if (resume) await play(offset)
    },
    setLoopStart(value) {
      // Preserve the current listening position when changing the repeat point.
      offset = position()
      startedAt = context.currentTime
      loopStart = clamp(value)
      if (source) source.loopStart = loopStart
    },
    setVolume(value) { gain.gain.value = Math.max(0, Math.min(1, value)) },
    dispose() {
      pause()
      disposed = true
      gain.disconnect()
    },
  }
}
