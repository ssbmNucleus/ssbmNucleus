/**
 * What Escape does in the Pose Manager (PoseManagerModal.jsx) and its Generate CSPs dialog
 * (PoseSkinSelectorModal.jsx), as in the vault's edit modal (vault/editModalKeys.js): it closes the innermost layer.
 *
 * 0.9.0 hand-check: nothing listened for Escape in either, and both stayed on screen over the Install tab (they are
 * portaled into .app-content). Now Escape closes Generate CSPs (not while it is rendering), then the model menu, then
 * steps from Create Pose back to the pose list, then closes the Pose Manager. A text field keeps Escape in Create Pose,
 * so a stray key while naming the pose does not throw the pose away, and a modal hidden behind another tab
 * (VaultActiveContext) never answers it.
 */

const NOT_TEXT = new Set(['button', 'checkbox', 'color', 'file', 'image', 'radio', 'range', 'reset', 'submit'])

/** Whether a key event's target is a field the user types into (the pose name, an animation search). */
export function isTextEntry(target) {
  if (!target) return false
  if (target.isContentEditable) return true
  const tag = String(target.tagName || '').toUpperCase()
  if (tag === 'TEXTAREA') return true
  return tag === 'INPUT' && !NOT_TEXT.has(String(target.type || 'text').toLowerCase())
}

/**
 * Escape pressed with the Pose Manager open -> 'menu' (close the model menu), 'library' (Create Pose back to the
 * pose list), 'close' (the Pose Manager), or null (another key, already handled, the Generate CSPs dialog on top
 * answers it, the modal is hidden, or a text field in Create Pose keeps it).
 */
export function poseManagerEscape({ key, defaultPrevented = false, hidden = false, skinSelectorOpen = false,
  modelMenuOpen = false, creating = false, typing = false }) {
  if (key !== 'Escape' || defaultPrevented || hidden || skinSelectorOpen) return null
  if (modelMenuOpen) return 'menu'
  if (creating) return typing ? null : 'library'
  return 'close'
}

/** Escape pressed with Generate CSPs open -> 'close', or null (another key, handled, hidden, or still rendering). */
export function skinSelectorEscape({ key, defaultPrevented = false, hidden = false, generating = false }) {
  if (key !== 'Escape' || defaultPrevented || hidden || generating) return null
  return 'close'
}
