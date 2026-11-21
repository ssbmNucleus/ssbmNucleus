/**
 * SSS (Stage Select Screen) slot helpers for the SSS layout editor.
 *
 * A new page starts as the vanilla grid of Locked slots (the "?" icon, as
 * MexManager makes one). A slot holds a stage once it is Unlocked with that
 * stage's external id; m-ex compiles whatever status and stage each icon has,
 * so filling a slot is only these per-icon fields.
 */

export const SSS_STATUS_LOCKED = 1
export const SSS_STATUS_UNLOCKED = 2

/**
 * The fields a slot takes when it is given `stage` (an entry of the layout's
 * `stages` list). The stage's icon elsewhere in the layout, when it has one,
 * lends its picture, preview id and random-select id, so a stage placed on a
 * second page matches its first-page icon; without one the slot keeps its own
 * ids and has no picture until the layout is saved and reloaded.
 */
export function stageSlotUpdates(stage, pages = []) {
  const twin = pages
    .flatMap(page => page?.icons || [])
    .find(icon => icon.status === SSS_STATUS_UNLOCKED && icon.stageID === stage.externalId)
  const updates = {
    status: SSS_STATUS_UNLOCKED,
    stageID: stage.externalId,
    stageName: stage.name,
    iconPath: twin?.iconPath || null,
  }
  if (twin) {
    updates.previewID = twin.previewID
    updates.randomSelectID = twin.randomSelectID
  }
  return updates
}
