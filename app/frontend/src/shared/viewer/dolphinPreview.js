// Own one media lease. Late getUserMedia results are stopped after cancellation.
export function startDolphinPreview({ bridge, mediaDevices, video, onState, expectedSessionId,
  startupMs = 120000, mediaMs = 10000, heartbeatMs = 1000 }) {
  let stopped = false, disposed = false, presentationRequested = false, stream = null, leaseId = null, timer = null, deadlineTimer = null
  let mutedSince = null
  // Where the game sits inside the captured frame (title bar and borders are
  // part of a window capture); null when unknown. Presentation only.
  let client = null
  const sameClient = (a, b) => JSON.stringify(a) === JSON.stringify(b)
  const stopTracks = value => value?.getTracks().forEach(track => track.stop())
  const cleanup = () => {
    stopped = true
    clearTimeout(timer); clearTimeout(deadlineTimer)
    stopTracks(stream); video.srcObject = null
  }
  const separate = async (explicit = false) => {
    // Capture the old identity before awaiting; cleanup never touches a new run.
    const oldLease = leaseId
    try {
      if ((explicit && (!expectedSessionId || oldLease)) || (oldLease && presentationRequested))
        await bridge.dolphinCaptureSeparate(oldLease || undefined)
    } catch { /* backend may have exited */ }
    finally {
      if (oldLease) await bridge.dolphinCaptureRelease(oldLease).catch(() => {})
      if (leaseId === oldLease) leaseId = null
    }
  }
  const fail = async message => {
    if (stopped) return
    cleanup()
    await separate()
    if (!disposed) onState({ status: 'separate', message })
  }
  const heartbeat = async () => {
    if (stopped) return
    try {
      presentationRequested = true
      const checked = await bridge.dolphinCaptureCheck(leaseId)
      if (!checked?.active)
        throw new Error('The Dolphin preview session ended.')
      if (stopped) return
      // Dolphin can resize or recreate its window; keep the crop in step.
      if (checked.client && !sameClient(checked.client, client)) {
        client = checked.client
        if (!disposed) onState({ status: 'live', message: '', client })
      }
      // Chromium suppresses duplicate frames for unchanged/paused windows.
      // Missing new pixels cannot distinguish a paused game from a dead feed.
      const tracks = stream.getVideoTracks()
      if (tracks.some(track => track.readyState === 'ended')) throw new Error('The live preview ended.')
      if (tracks.some(track => track.muted)) {
        mutedSince ??= Date.now()
        if (Date.now() - mutedSince > 10000) throw new Error('The live preview source is unavailable.')
      } else mutedSince = null
      timer = setTimeout(heartbeat, heartbeatMs)
    } catch (error) { fail(error.message) }
  }
  const prepare = async () => {
    try {
      const target = await bridge.dolphinCapturePrepare(expectedSessionId)
      if (stopped) {
        if (target?.leaseId) bridge.dolphinCaptureRelease(target.leaseId).catch(() => {})
        return
      }
      if (target?.supported === false) return fail('The game plays in a separate Dolphin window on this platform.')
      if (!target?.found) { timer = setTimeout(prepare, 400); return }
      if (expectedSessionId && target.sessionId !== expectedSessionId) {
        if (target.leaseId) await bridge.dolphinCaptureRelease(target.leaseId).catch(() => {})
        return fail('This game session ended. Its preview will not attach to another session.')
      }
      leaseId = target.leaseId
      client = target.client || null
      clearTimeout(deadlineTimer)
      deadlineTimer = setTimeout(() => fail('The live preview could not start. Use the Dolphin window.'), mediaMs)
      const acquired = await mediaDevices.getUserMedia({ audio: false, video: { mandatory: {
        chromeMediaSource: 'desktop', chromeMediaSourceId: target.sourceId,
        maxWidth: 1920, maxHeight: 1080, maxFrameRate: 60
      } } })
      if (stopped) { stopTracks(acquired); return }
      stream = acquired
      stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => fail('The live preview ended.')))
      video.srcObject = stream
      await video.play()
      if (stopped) return
      const firstFrame = () => {
        if (stopped) return
        if (video.readyState < 2 || !video.videoWidth) { timer = setTimeout(firstFrame, 50); return }
        clearTimeout(deadlineTimer)
        onState({ status: 'live', message: '', client })
        heartbeat() // Native windows are untouched until this first decoded frame.
      }
      firstFrame()
    } catch (error) { fail(error.message || 'The live preview could not start.') }
  }
  deadlineTimer = setTimeout(() => fail('Dolphin is taking too long to open. Use its separate window.'), startupMs)
  onState({ status: 'starting', message: 'The game appears here once Dolphin boots…' })
  prepare()
  return {
    stop() { disposed = true; if (!stopped) { cleanup(); separate() } },
    async popout() { cleanup(); await separate(true); if (!disposed) onState({ status: 'separate', message: 'The game is playing in a separate Dolphin window.' }) }
  }
}
