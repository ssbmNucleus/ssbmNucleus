// Transport-level failures have no paint-pair sessionId. Handle them before
// filtering pair replies, without treating a failed load as a new animation.
export function handleViewerControlMessage(message, { onError, onAnimationFrame }) {
  if (message.type === 'commandError' || message.type === 'error' ||
      (message.type === 'animLoaded' && (message.success === false || message.error))) {
    onError(message.error || message.message || (message.type === 'animLoaded'
      ? 'Could not load the animation. The current animation is unchanged.'
      : `Viewer command failed${message.command ? `: ${message.command}` : ''}.`))
    return true
  }
  if (message.type === 'animFrame') {
    const update = {}
    if (Number.isFinite(message.frame) && message.frame >= 0) update.frame = message.frame
    if (Number.isFinite(message.frameCount) && message.frameCount >= 0) update.frameCount = message.frameCount
    if (typeof message.playing === 'boolean') update.playing = message.playing
    if (Number.isFinite(message.speed)) update.speed = message.speed
    onAnimationFrame?.(update)
    return true
  }
  return false
}
