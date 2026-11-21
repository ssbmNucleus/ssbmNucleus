// A window capture is the whole window: Dolphin's title bar and borders come
// with the game. Given where the client area sits inside the captured frame
// (dolphinPreview's `client`), place the video so a stage of `aspect` shows
// only the game: the largest centred `aspect` rectangle of the client area
// (Dolphin letterboxes its 4:3 picture inside a window of another shape).
// Returns the video's style as percentages of the stage, or null when the
// geometry is unknown (the caller then shows the whole frame, contained).
const pct = value => `${Math.round(value * 10000) / 100}%`

export function captureCrop(client, aspect = 4 / 3) {
  if (!client || !(aspect > 0)) return null
  const { x, y, width, height, frameWidth, frameHeight } = client
  const values = [x, y, width, height, frameWidth, frameHeight]
  if (!values.every(Number.isFinite) || width <= 0 || height <= 0 || x < 0 || y < 0
      || x + width > frameWidth || y + height > frameHeight) return null
  const regionWidth = Math.min(width, height * aspect)
  const regionHeight = regionWidth / aspect
  const left = x + (width - regionWidth) / 2
  const top = y + (height - regionHeight) / 2
  return {
    position: 'absolute', maxWidth: 'none', objectFit: 'fill',
    width: pct(frameWidth / regionWidth), height: pct(frameHeight / regionHeight),
    left: pct(-left / regionWidth), top: pct(-top / regionHeight),
  }
}
