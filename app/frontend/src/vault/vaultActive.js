import { createContext } from 'react'

/**
 * Whether the vault is the page on screen (App.jsx: the Vault tab, and not under the full AI page). The vault's
 * panels stay mounted while another tab shows, but its edit modal is portaled out of them into .app-content, so it
 * reads this to hide itself (EditModal.jsx). 0.9.0 smoke test: the modal stayed on top of the AI page.
 *
 * The Pose Manager and its Generate CSPs dialog read it too (vault/characters/poses). The Install tab borrows the
 * Pose Manager for "apply a pose to all", so App.jsx provides it around that tab as well, true while the Install tab
 * is on screen. 0.9.0 hand-check: both stayed over the Install tab.
 */
export const VaultActiveContext = createContext(true)
