/**
 * importDrag - when the vault's "Drop to import" screen is up.
 *
 * It is up while a file dragged in from outside the app is over a vault that
 * is on screen, and it comes down when that drag ends, whoever took the drop.
 * The vault stays mounted behind the AI page and the other tabs, and a chat
 * takes its own drops and stops them there, so "the vault is mounted" and
 * "the vault heard the drop" cannot stand in for those two facts.
 */
export const DOWN = 0

// `depth` counts the elements the drag is inside: dragenter and dragleave come
// one per element, so crossing onto a child must not lower the screen.
export function next(depth, event) {
  if (event.type === 'dragenter') return event.files && event.onScreen ? depth + 1 : depth
  if (event.type === 'dragleave') return Math.max(DOWN, depth - 1)
  return DOWN // drop or dragend: the drag is over
}
