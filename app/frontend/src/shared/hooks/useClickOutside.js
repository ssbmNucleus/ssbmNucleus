import { useEffect, useRef } from 'react'

/**
 * Dismiss a popover when a pointer goes down outside of it.
 *
 * Listens only while `active`, on bubble-phase `document` `pointerdown`, and
 * ignores events whose target is inside `ref` — the exact shape of the
 * hand-rolled effects this replaced.
 */
export function useClickOutside(ref, active, onOutside) {
  const onOutsideRef = useRef(onOutside)
  onOutsideRef.current = onOutside

  useEffect(() => {
    if (!active) return
    const handlePointerDown = (event) => {
      if (ref.current?.contains(event.target)) return
      onOutsideRef.current()
    }
    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [active])
}
