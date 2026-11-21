// Declared task modes for a Randall chat (git history before 2026-10-03: randall-task-modes-contract.md).
// A chat may carry one launchable recipe family, picked before the first
// message; the backend's `status.tasks` is the only list of them, so nothing
// here hardcodes ids, labels or placeholders. Pure: no React, no fetch.

// Extensioned so this module also loads under node's ESM resolver for its tests.
import { envelopeOf } from './taskEnvelope.js'

// The receipt that means the task is finished, per family. `model_import` is
// left out on purpose: the studio owns its own completion card. A recolor also
// finishes on delivery, so following "Put it in my game" keeps the row. A stage
// recolor finishes when the Stage Lab saves a new vault variant (`stage_lab`
// action=save; every other stage_lab call is a step, see `savedStage`); it has
// no same-chat follow-up (a stage cannot be delivered into the game).
// A retexture is saved by code when its turn ends (backend randall/recolor/autosave.py): that save is the
// same receipt (`save_mod_copy`; `stage_lab` with action=save), its result marked `autosave: 'saved'` or
// `'updated'`, so it finishes the task and leads to "Put it in my game" exactly as an asked-for save does.
// An auto-save that failed is an error receipt: nothing is terminal then.
// A chat stored under a retired task id ("find_mod", "menu_background", removed
// 2026-10-03) has no entry here and no label in status.tasks: it reads as a
// plain chat (no badge, no pill, no "Start another").
export const TERMINAL_TOOLS = {
  recolor_part: ['save_mod_copy', 'deliver_to_game'],
  recolor_stage: ['stage_lab'],
}

// The next step in the SAME chat once a task's receipt lands. A saved recolor
// is not in the game yet, so delivery is offered before "Start another"
// rather than nudging people into a new chat.
const FOLLOW_UPS = {
  recolor_part: { label: 'Put it in my game', draft: 'Put it in my game', after: ['save_mod_copy'] },
}

const validTask = task => task && typeof task === 'object' && typeof task.id === 'string' && task.id
  && typeof task.label === 'string' && task.label

/** The launchable tasks from `status.tasks`, dropping malformed rows; [] when missing.
 *  This includes a starting point that is not built yet (`available: false`): the
 *  empty state shows it, disabled. */
export function launchableTasks(status) {
  return Array.isArray(status?.tasks) ? status.tasks.filter(validTask) : []
}

/** True for a task a chat can be started as: every row but one the backend marks
 *  `available: false` (a row from a backend that predates the flag counts). */
export const isStartable = task => Boolean(task) && task.available !== false

/** The tasks a chat can be started as: the pill's menu, the sidebar rows, "Start another". */
export function startableTasks(tasks) {
  return (tasks || []).filter(isStartable)
}

/** The chat's declared task id, or null: the chat row's `task`, else the FIRST
 *  user message's `context.task` (a chat stored before the column existed).
 *  Only the first message can declare, as in the backend's `recipes.chat_task`:
 *  a task on a later message never counts. */
export function taskOf(chat, messages = []) {
  if (typeof chat?.task === 'string' && chat.task) return chat.task
  const task = (messages || []).find(message => message?.role === 'user')?.context?.task
  return typeof task === 'string' && task ? task : null
}

// A delivery counts only when the costume is in the copy the user plays. One
// that stopped to ask (which game copy, the online-risk question: state
// `waiting_decision`, nothing achieved), was blocked, or only reached the
// project files put nothing in the game.
const delivered = tool => envelopeOf(tool)?.achieved?.installed === true
// Only the Stage Lab's save adds a vault variant (its result names it: `variantId`).
const savedStage = tool => tool.arguments?.action === 'save' || Boolean(tool.result?.variantId)

/** The LAST tool receipt in this message that finishes `taskId`, or null.
 *  Read from the end because the latest step is where the task stands: under
 *  a reply that saved and then delivered, the delivery is the receipt. A
 *  delivery attempt after the save that did not deliver means the task is
 *  waiting on that step (its decision card), so nothing is terminal yet. A
 *  Stage Lab call that is not a save (closing the session after it) is a step,
 *  never the end. */
export function terminalReceipt(taskId, message) {
  const names = TERMINAL_TOOLS[taskId]
  if (!names || !message) return null
  for (const tool of [...(message.tools || [])].reverse()) {
    if (!names.includes(tool?.name)) continue
    if (tool.name === 'deliver_to_game') return tool.status === 'done' && delivered(tool) ? tool : null
    if (tool.name === 'stage_lab' && !savedStage(tool)) continue
    if (tool.status === 'done') return tool
  }
  return null
}

/** Whether to offer "Start another" under the last message: a task chat whose
 *  final assistant reply has finished and holds the task's terminal receipt. */
export function showStartAnother(taskId, messages, busy) {
  if (!taskId || busy) return false
  const last = (messages || []).at(-1)
  if (!last || last.role !== 'assistant' || last.status === 'running') return false
  return Boolean(terminalReceipt(taskId, last))
}

/** `{label, draft}` for the same-chat follow-up chip after `taskId` finishes, or
 *  null. Given the finishing `receipt`, only the step it leads to is offered:
 *  no "Put it in my game" under the delivery itself. */
export function followUpFor(taskId, receipt = null) {
  const follow = FOLLOW_UPS[taskId]
  if (!follow || (receipt && !follow.after.includes(receipt.name))) return null
  return { label: follow.label, draft: follow.draft }
}

/** `{family}` when the engine flagged this reply as asking for another task. */
export function mismatchOf(message) {
  const family = message?.role === 'assistant' ? message.routing?.task_mismatch : null
  return typeof family === 'string' && family ? { family } : null
}

/** The text of the user message that came before `index`, for a mismatch draft. */
export function previousUserText(messages, index) {
  return (messages || []).slice(0, index).findLast(message => message?.role === 'user')?.content || ''
}

/** The composer placeholder for `taskId`, else `fallback`. */
export function placeholderFor(tasks, taskId, fallback) {
  return (taskId && (tasks || []).find(task => task.id === taskId)?.placeholder) || fallback
}

/** The label for `taskId`, or null when this build does not offer that task. */
export function labelFor(tasks, taskId) {
  return (taskId && (tasks || []).find(task => task.id === taskId)?.label) || null
}
