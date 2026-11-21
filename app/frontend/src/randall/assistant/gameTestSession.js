// Observe a server-started session. Opening history never launches Dolphin.
export function observeGameTest({ read, stop, onState, setTimer = setTimeout, clearTimer = clearTimeout }) {
  let disposed = false, timer = null, version = 0, sequence = -1, stopping = false
  let controller = null, stopSending = false
  const emit = value => { if (!disposed) onState(value) }
  async function refresh() {
    const revision = ++version
    controller?.abort()
    const request = new AbortController(); controller = request
    const deadline = setTimer(() => request.abort(), 10000)
    try {
      const value = await read(request.signal)
      if (disposed || revision !== version) return
      const nextSequence = value.lastEvent?.payload?.sequence ?? value.status?.sequence ?? -1
      if (nextSequence < sequence && value.running) {
        timer = setTimer(refresh, 1000)
        return
      }
      sequence = Math.max(sequence, nextSequence)
      stopping = stopSending || !!value.stopRequested
      emit({ snapshot: value, error: null, stopping })
      if (!value.running) return
    } catch (error) {
      if (disposed || revision !== version) return
      emit({ error: 'Connection interrupted. Reconnecting; Stop is still available.' })
    } finally { clearTimer(deadline) }
    if (!disposed && revision === version) timer = setTimer(refresh, 1000)
  }
  refresh()
  return {
    async stop() {
      if (disposed || stopping) return
      stopSending = true; stopping = true; emit({ stopping: true, stopError: null })
      const request = new AbortController()
      const deadline = setTimer(() => request.abort(), 10000)
      try {
        await stop(request.signal)
        stopSending = false
        if (!disposed) { clearTimer(timer); await refresh() }
      } catch (error) {
        stopping = false
        emit({ stopping: false, stopError: `Could not stop the session: ${error.message}. Retry Stop.` })
      } finally { stopSending = false; clearTimer(deadline) }
    },
    dispose() { disposed = true; version++; clearTimer(timer); controller?.abort() },
  }
}
