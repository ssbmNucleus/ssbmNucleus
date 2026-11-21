/** Load only this editor's controls; missing legacy values always use defaults. */
export function readEditorColors(mod, defaults) {
  return Object.fromEntries(Object.entries(defaults).map(([key, fallback]) =>
    [key, mod?.modifications?.[key]?.color || fallback]))
}

/** Preserve imported layers the editor does not expose, replacing every visible control. */
export function serializeEditorColors(colors, previous = {}) {
  return { ...previous, ...Object.fromEntries(Object.entries(colors).map(
    ([key, color]) => [key, { color }])) }
}

export function displayColor(hex, fallback = '#FF6600') {
  const value = String(hex || '').replace(/^#/, '')
  return /^[0-9a-f]{6}$/i.test(value) ? `#${value.toUpperCase()}` : fallback
}

/** An RGB picker changes color while retaining the recipe's opacity. */
export function rgbWithAlpha(hex, currentRgba = 'FFFFFFFF') {
  const rgb = displayColor(hex).slice(1)
  const alpha = /^[0-9a-f]{8}$/i.test(currentRgba) ? currentRgba.slice(6) : 'FF'
  return `${rgb}${alpha}`.toUpperCase()
}

/** Ignore completed texture requests after close, selection changes, or user edits. */
export function loadCurrentTextureColor(promise, { onValue, onError, onSettled, isCurrent = () => true }) {
  let active = true
  const current = () => active && isCurrent()
  Promise.resolve(promise)
    .then(value => { if (current()) onValue(value) })
    .catch(error => { if (current()) onError?.(error) })
    .finally(() => { if (current()) onSettled?.() })
  return () => { active = false }
}
