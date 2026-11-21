// A new chat's starting-point pick (the costume a recolor starts from, the fighter
// a model import goes on, the stage a stage recolor starts from) and what it adds
// to the message context. Pure: no React, no fetch. The pick objects are
// vault/picker/CostumePicker's and StagePicker's.
//
// What the backend receives (assistant_bp CONTEXT_FIELDS):
//   costume picker, a vault costume -> selection += {id, character, name}
//     the exact item a Vault selection sends; the recolor acquisition stage
//     reads it as the (character, skin_id) pair it may open (workflows._source_facts)
//   costume picker, a stock slot    -> selection += {character, vanilla: true, color, name}
//     no `id`, so it is never mistaken for a vault pair; workflows.picked_costume
//     opens it with open_vanilla_file(character, color)
//   fighter picker                  -> fighter: 'Fox' (a model-import fighter;
//     assistant_bp drops a name it does not know). The "AI Choice" pick ({auto: true},
//     no character) sends no `fighter` at all: Randall picks, as with no pick.
//   stage picker, a vault variant   -> selection = [{kind: 'stage', stage: 'GrNBa', id, name}]
//   stage picker, the stock stage   -> selection = [{kind: 'stage', stage: 'GrNBa', vanilla: true, name}]
//     checked by assistant_bp._stage_item; stage_start.picked_stage opens it with
//     stage_lab_open(stage_code, variant_id?). `name` is the label ("Battlefield · Night Sky").
// All go with the FIRST message only, like `task`: they are how the chat starts.
// The backend reads the fighter back from the chat's user messages
// (studio_import.chosen_fighter), so a model attached later still goes on it.

// Extensioned so node's test runner loads this module.
import { pickLabel } from '../../vault/picker/costumePicks.js'
import { stagePickLabel } from '../../vault/picker/stagePicks.js'

const PICKERS = ['costume', 'fighter', 'stage']

/** The picker the task names in `status.tasks` ('costume' | 'fighter' | 'stage'), or null. */
export function pickerFor(tasks, taskId) {
  const picker = taskId ? (tasks || []).find((task) => task?.id === taskId)?.picker : null
  return PICKERS.includes(picker) ? picker : null
}

/** What the panel calls a pick: "Fox · Blue Hoodie", "Marth", "Battlefield · Night Sky". */
export function pickText(pick) {
  return pick?.kind === 'stage' ? stagePickLabel(pick) : pickLabel(pick)
}

/** The selected-app item a costume or stage pick sends, or null. */
export function selectionItem(pick) {
  if (pick?.kind === 'vault' && pick.id && pick.character) {
    return { id: pick.id, character: pick.character, name: pick.name }
  }
  if (pick?.kind === 'stock' && pick.code && pick.character) {
    return { character: pick.character, vanilla: true, color: pick.color, name: `${pick.name} (stock)` }
  }
  if (pick?.kind === 'stage' && pick.stage) {
    if (pick.vanilla) return { kind: 'stage', stage: pick.stage, vanilla: true, name: stagePickLabel(pick) }
    if (pick.id) return { kind: 'stage', stage: pick.stage, id: pick.id, name: stagePickLabel(pick) }
  }
  return null
}

/**
 * The context of an outgoing message. `context` is the app's (page, character,
 * stage), `selection` the skins picked in this chat, `files` the attachments.
 * `locked`: the chat already has messages, so the task and the starting pick are
 * not sent again. `picker`/`pick`: the empty chat's starting point; a costume or
 * stage pick replaces any attached skins as `selection` (see below).
 */
export function outgoingContext({ context = {}, selection = [], files = [], task = null, locked = false,
  editor = null, picker = null, pick = null } = {}) {
  const sent = { ...context, selection, files, ...(task && !locked ? { task } : {}), ...(editor ? { editor } : {}) }
  if (locked) return sent
  if (picker === 'costume' || picker === 'stage') {
    const item = selectionItem(pick)
    // The pick IS the selection: the backend opens a costume or a stage directly
    // only when `selection` has exactly one entry, so skins attached to the
    // composer are not sent alongside it on this first message (the panel's "N
    // skins attached" chip still shows them; it has no way to say they were set
    // aside). A pick of the other kind (a costume under the stage picker) sends nothing.
    if (item && (item.kind === 'stage') === (picker === 'stage')) sent.selection = [item]
  }
  if (picker === 'fighter' && pick?.kind === 'fighter' && pick.character && !pick.auto) sent.fighter = pick.character
  return sent
}

/** The composer placeholder once something is picked, else null (the task's own placeholder stays). */
export function pickPlaceholder(picker, pick) {
  if (picker === 'costume' && (pick?.kind === 'vault' || pick?.kind === 'stock')) return `What look do you want for ${pickLabel(pick)}?`
  if (picker === 'fighter' && pick?.auto) return 'Attach a model. Randall picks the fighter.'
  if (picker === 'fighter' && pick?.kind === 'fighter') return `Attach the model for ${pick.character} and send it.`
  if (picker === 'stage' && pick?.kind === 'stage') return `What colors do you want for ${stagePickLabel(pick)}?`
  return null
}

/** The short notes a sent user message shows for what its context carried. */
export function contextNotes(context) {
  const notes = []
  const selection = Array.isArray(context?.selection) ? context.selection : []
  if (selection.length === 1 && selection[0]?.kind === 'stage' && selection[0]?.name) {
    notes.push(selection[0].name)
  } else if (selection.length === 1 && selection[0]?.character && selection[0]?.name) {
    notes.push(`${selection[0].character} · ${selection[0].name}`)
  } else if (selection.length) {
    notes.push(`${selection.length} attached skin${selection.length === 1 ? '' : 's'}`)
  }
  if (typeof context?.fighter === 'string' && context.fighter) notes.push(`For ${context.fighter}`)
  return notes
}
