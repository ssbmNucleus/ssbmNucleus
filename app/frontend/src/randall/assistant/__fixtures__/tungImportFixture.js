// Test data only (no app code imports this): the Tung Tung Tung Sahur import from the launch-video run (the v4
// importer's, so an older chat's reply: its flow, stages, choices and picture sheet are what v4 sent), as its chat
// record stored it (tungImport.fixture.json: the user's message with tung_tung_sahur.glb attached, Randall's reply
// and its import_model call, paths shortened). The user's file is "tung_tung_sahur.glb"; Randall saved the costume
// as "Tung Tung Tung Sahur" (the name in the user's message). The reply started 2.9 s before the import call did.
import { readFileSync } from 'node:fs'

const FIXTURE = JSON.parse(readFileSync(new URL('./tungImport.fixture.json', import.meta.url), 'utf8'))
const copy = value => JSON.parse(JSON.stringify(value))

/** The user's message, with the attached model file. */
export const tungUser = () => copy(FIXTURE.user)

/** The finished import call as stored: saved, its files, `seconds` 397.8, started/completed (epoch seconds). */
export const tungDone = () => copy(FIXTURE.tool)

/** The reply that ran it (`started_at`: the turn's start, the status bar's clock). */
export const tungReply = () => copy(FIXTURE.reply)

/**
 * The same call while it ran, `at` seconds into the turn (default 175: "2 min 55 sec"), with `now` the clock: nothing
 * saved, no costume file yet, and the `seconds` of its last progress event (what the card used to show).
 */
export function tungRunning({ now = Date.now(), at = 175.2, lastProgress = 150 } = {}) {
  const done = tungDone()
  const turnStart = now / 1000 - at
  const offset = turnStart - FIXTURE.reply.started_at
  const result = { ...done.result, status: 'running', seconds: lastProgress }
  for (const key of ['saved', 'files', 'choices', 'sheet', 'dat', 'pictures', 'vault_changed', 'flow']) delete result[key]
  const tool = { ...done, status: 'running', started_at: done.started_at + offset, result }
  delete tool.completed_at
  delete tool.elapsed_ms
  const reply = { ...tungReply(), status: 'running', started_at: turnStart }
  return { tool, reply, turnStart }
}

/** A chat of the user's message and a reply carrying `tool`. */
export const tungChat = (tool, reply = tungReply()) => [tungUser(), { ...reply, tools: [tool] }]
