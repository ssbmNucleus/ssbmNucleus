import { useState, useRef, useLayoutEffect } from 'react'

/**
 * PropsPopup - the right-click properties popup in the CSS/SSS layout
 * editors. Anchors at the click point but clamps itself to the viewport so
 * it never hangs off the bottom/edges of the screen.
 */
export default function PropsPopup({ x, y, onClose, children }) {
  const ref = useRef(null)
  const [pos, setPos] = useState({ left: x, top: y, ready: false })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const margin = 8
    const r = el.getBoundingClientRect()
    let left = x
    let top = y

    if (r.right > window.innerWidth - margin) left -= r.right - (window.innerWidth - margin)
    if (r.left < margin) left += margin - r.left
    if (r.bottom > window.innerHeight - margin) top -= r.bottom - (window.innerHeight - margin)
    if (r.top < margin) top += margin - r.top

    setPos({ left, top, ready: true })
  }, [x, y])

  return (
    <div className="sss-props-popup-overlay" onClick={onClose}>
      <div
        ref={ref}
        className="sss-props-popup"
        style={{ left: pos.left, top: pos.top, visibility: pos.ready ? 'visible' : 'hidden' }}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  )
}
