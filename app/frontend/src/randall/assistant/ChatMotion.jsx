import { useEffect, useLayoutEffect, useRef, useState } from 'react'

export { TypingBubble } from '../chat/ChatUI'

// Ease bursty network chunks into the existing markdown without replaying history.
export function SmoothText({ text, active, children, onReveal }) {
  const [shown, setShown] = useState(active ? '' : text)
  const displayed = useRef(shown), animate = useRef(active)
  useEffect(() => {
    if (active) animate.current = true
    if (!animate.current || !text.startsWith(displayed.current) || matchMedia('(prefers-reduced-motion: reduce)').matches) {
      displayed.current = text; setShown(text); return
    }
    let frame, last = performance.now(), credit = 0
    const tick = now => {
      const remaining = text.length - displayed.current.length
      credit += Math.min(now - last, 50) / 1000 * Math.max(90, remaining / .18)
      last = now
      const amount = Math.min(remaining, Math.floor(credit))
      if (amount > 0) {
        let end = displayed.current.length + amount
        // Keep emoji/code points intact while revealing a chunk.
        if (end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1])) end++
        displayed.current = text.slice(0, end); setShown(displayed.current); credit -= amount
      }
      if (displayed.current.length < text.length) frame = requestAnimationFrame(tick)
      else if (!active) animate.current = false
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [text, active])
  useLayoutEffect(() => { onReveal?.() }, [shown])
  return children(shown)
}
