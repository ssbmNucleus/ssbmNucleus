import { useState, useCallback, useEffect, useRef } from 'react'

const STORAGE_KEY = 'skinCreatorPanelSizes'
const DEFAULT_SIZES = { rightPanelWidth: 310, textureStripHeight: 220, colorToolsWidth: 340 }
const LIMITS = { rightPanelWidth: [220, 700], textureStripHeight: [140, 600], colorToolsWidth: [240, 700] }
const clamp = (key, value) => Math.max(LIMITS[key][0], Math.min(LIMITS[key][1], Number.isFinite(value) ? value : DEFAULT_SIZES[key]))

export function usePanelResize() {
  const cleanup = useRef(() => {})
  const [sizes, setSizes] = useState(() => {
    let saved = {}
    try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {} } catch {}
    return Object.fromEntries(Object.keys(DEFAULT_SIZES).map(key => [key, clamp(key, saved[key])]))
  })
  useEffect(() => { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(sizes)) } catch {} }, [sizes])
  useEffect(() => () => cleanup.current(), [])
  const resetSizes = useCallback(() => setSizes(DEFAULT_SIZES), [])
  const separatorProps = (key, label) => {
    const vertical = key === 'rightPanelWidth' || key === 'colorToolsWidth'
    const update = value => setSizes(previous => ({ ...previous, [key]: clamp(key, value) }))
    return {
      role: 'separator', tabIndex: 0, 'aria-label': label,
      'aria-orientation': vertical ? 'vertical' : 'horizontal',
      'aria-valuemin': LIMITS[key][0], 'aria-valuemax': LIMITS[key][1], 'aria-valuenow': sizes[key],
      title: `${label} · drag or use arrow keys; double-click to reset`,
      onDoubleClick: () => update(DEFAULT_SIZES[key]),
      onKeyDown: event => {
        const direction = { ArrowLeft: 1, ArrowRight: -1, ArrowUp: 1, ArrowDown: -1 }[event.key]
        if (event.key === 'Home') { event.preventDefault(); update(DEFAULT_SIZES[key]) }
        else if (direction) { event.preventDefault(); update(sizes[key] + direction * (event.shiftKey ? 40 : 16)) }
      },
      onPointerDown: event => {
        if (event.button !== 0) return
        event.preventDefault(); cleanup.current()
        event.currentTarget.focus()
        const start = vertical ? event.clientX : event.clientY
        const initial = sizes[key]
        const rect = event.currentTarget.closest(vertical ? '.skin-creator-main, .skin-creator-bottom' : '.skin-creator-body').getBoundingClientRect()
        const cursor = document.body.style.cursor, select = document.body.style.userSelect
        const move = e => {
          const value = initial + start - (vertical ? e.clientX : e.clientY)
          update(Math.min(value, vertical ? rect.width - 240 : rect.height - 200))
        }
        const end = () => {
          window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end)
          window.removeEventListener('pointercancel', end); window.removeEventListener('blur', end)
          document.body.style.cursor = cursor; document.body.style.userSelect = select
          cleanup.current = () => {}
        }
        cleanup.current = end
        document.body.style.cursor = vertical ? 'ew-resize' : 'ns-resize'; document.body.style.userSelect = 'none'
        window.addEventListener('pointermove', move); window.addEventListener('pointerup', end)
        window.addEventListener('pointercancel', end); window.addEventListener('blur', end)
      },
    }
  }
  return { sizes, separatorProps, resetSizes }
}
