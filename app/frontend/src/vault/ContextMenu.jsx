/**
 * ContextMenu - Right-click context menu for costumes and stage variants
 *
 * Provides "Move to Top" and "Move to Bottom" actions
 */
export default function ContextMenu({ contextMenu, onMoveToTop, onMoveToBottom }) {
  if (!contextMenu) return null

  const handleClick = (e) => {
    e.stopPropagation()
  }

  return (
    <div
      className="context-menu"
      style={{ top: contextMenu.y, left: contextMenu.x }}
      onClick={handleClick}
    >
      <button onClick={onMoveToTop}>Move to Top</button>
      <button onClick={onMoveToBottom}>Move to Bottom</button>
    </div>
  )
}
