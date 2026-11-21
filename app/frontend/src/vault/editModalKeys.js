/**
 * What Escape does in the vault's edit modal (EditModal.jsx), as the other modals do it: it closes the modal.
 *
 * 0.9.0 smoke test: Escape in the name field only reverted the name, so with the name unchanged it did nothing, and
 * nothing else listened for it. Now the name field keeps Escape only while it holds an unsaved name (it reverts that
 * first); otherwise Escape closes the open pose list or Slippi menu inside the modal, then the modal. A dialog or
 * viewer over the modal (`covered`) answers Escape itself, and a modal hidden behind another tab never does.
 */

/** Whether Escape in the name field reverts an unsaved name (and so stops there) rather than closing the modal. */
export function titleEscapeReverts(value, committedName) {
  return String(value ?? '').trim() !== String(committedName ?? '')
}

/**
 * Escape pressed with the modal open -> 'close' (the modal), 'poses' or 'safety' (the open list inside it), or null
 * (not for the modal: another key, already handled by the name field, covered by a dialog, or the modal hidden).
 */
export function editModalEscape({ key, defaultPrevented = false, covered = false, hidden = false,
  posesOpen = false, safetyOpen = false }) {
  if (key !== 'Escape' || defaultPrevented || covered || hidden) return null
  if (posesOpen) return 'poses'
  if (safetyOpen) return 'safety'
  return 'close'
}
