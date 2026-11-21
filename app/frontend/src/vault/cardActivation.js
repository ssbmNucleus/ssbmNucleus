// Keep a card's edit action separate from its drag/reorder gesture.
export function createCardActivation(justDraggedRef) {
  let pointer = null
  return {
    onPointerDown(event) {
      if (event.button === 0) pointer = { x: event.clientX, y: event.clientY, moved: false }
    },
    onPointerMove(event) {
      if (pointer && Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > 5) {
        pointer.moved = true
      }
    },
    onPointerCancel() { pointer = { moved: true } },
    onDragStart() { pointer = { moved: true } },
    onClick(event, activate) {
      const dragged = pointer?.moved || justDraggedRef?.current
      pointer = null
      if (!dragged && (event.button == null || event.button === 0)) activate()
    },
    onKeyDown(event, activate) {
      if (event.target !== event.currentTarget || event.repeat) return
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        activate()
      }
    },
  }
}
