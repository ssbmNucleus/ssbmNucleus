// The one place Randall's activity is named in words a person who has never
// modded Melee would use. Nothing in the chat surface may fall back to a tool
// name: a card that says `model_mesh` is asking the user to learn our internals
// to find out what happened to their costume.
//
// Every entry is a phrase, not a noun for an internal object: `working` is what
// is happening now, `done` is what happened. `ACTIVITY` must cover every tool in
// backend/randall/assistant/tools.py -- activity.test.js reads that file and fails when
// a tool arrives without a phrase, which is the only thing keeping this honest.
//
// The vault is the mod collection saved on this computer. It is named the same
// way everywhere (download receipts already said "Added to vault"), and it is
// never confused with a playable build: adding to the vault changes nothing the
// user can play.
export const ACTIVITY = {
  // -- the mod website
  search_website_mods: { working: 'Searching the mod website', done: 'Mods from the website' },
  inspect_website_mod: { working: 'Opening a mod page', done: 'A mod from the website' },
  download_website_mod: { working: 'Adding a mod to your vault', done: 'Added to your vault' },
  download_website_mods: { working: 'Adding mods to your vault', done: 'Added to your vault' },
  set_website_mod_like: { working: 'Saving your like', done: 'Saved your like' },
  // -- the vault
  search_vault: { working: 'Looking through your vault', done: 'Your vault' },
  inspect_mod: { working: 'Checking a mod in your vault', done: 'Checked a mod in your vault' },
  present_vault_skins: { working: 'Getting skins to show you', done: 'Skins from your vault' },
  organize_skins: { working: 'Tidying skins into a folder', done: 'Tidied skins into a folder' },
  save_mod_copy: { working: 'Saving a copy to your vault', done: 'Saved a copy to your vault' },
  open_vault_file: { working: 'Opening a mod from your vault', done: 'Opened a mod from your vault' },
  open_vanilla_file: { working: 'Opening an original Melee costume', done: 'An original Melee costume' },
  // -- builds (a Nucleus project is the modded copy of the game)
  list_projects: { working: 'Checking your builds', done: 'Your builds' },
  inspect_project: { working: 'Looking inside a build', done: 'Looked inside a build' },
  create_project: { working: 'Starting a new build', done: 'Started a new build' },
  install_project_mods: { working: 'Adding costumes to a build', done: 'Added costumes to a build' },
  deliver_to_game: { working: 'Putting it into the game you play', done: 'Put into the game you play' },
  undo_delivery: { working: 'Taking it back out of your game', done: 'Taken back out of your game' },
  // -- help and pictures
  search_docs: { working: 'Reading Nucleus help', done: 'Read Nucleus help' },
  preview_portrait: { working: 'Making a character-select portrait', done: 'Character-select portrait' },
  // -- appearance editing
  generate_material: { working: 'Drawing a new material', done: 'A new material' },
  skin_material: { working: 'Putting the material on', done: 'Material on the skin' },
  skin_lab_open: { working: 'Opening the skin', done: 'Opened the skin' },
  skin_lab: { working: 'Working on the skin', done: 'Worked on the skin' },
  stage_lab_open: { working: 'Opening the stage', done: 'Opened the stage' },
  stage_lab: { working: 'Working on the stage', done: 'Worked on the stage' },
  // -- bringing an outside model in
  model_source: { working: 'Reading the model you sent', done: 'Read the model you sent' },
  model_probe: { working: 'Measuring the model', done: 'Measured the model' },
  import_model: { working: 'Putting your model on a fighter', done: 'Your model on a fighter' },
  model_fit: { working: 'Fitting the model to a fighter', done: 'Fitted to a fighter' },
  model_mesh: { working: 'Choosing which parts to keep', done: 'Chose which parts to keep' },
  model_region: { working: 'Marking part of the costume', done: 'Marked part of the costume' },
  model_prop: { working: 'Sorting out what it is holding', done: 'Sorted out what it is holding' },
  model_physics: { working: 'Setting up cloth and hanging pieces', done: 'Set up cloth and hanging pieces' },
  model_poses: { working: 'Checking how the costume moves', done: 'Checked how the costume moves' },
  model_render: { working: 'Making pictures of the costume', done: 'Pictures of the costume' },
  model_review: { working: 'Looking the costume over', done: 'Looked the costume over' },
  model_revise: { working: 'Repairing the costume', done: 'Repaired the costume' },
  model_candidate: { working: 'Preparing the costume file', done: 'The costume file' },
  model_script: { working: 'Running a small fix on the model', done: 'Ran a small fix on the model' },
  // -- mod files
  hsdraw: { working: 'Working on a mod file', done: 'Worked on a mod file' },
  hsdraw_capabilities: { working: 'Checking what the model tools can do', done: 'Checked what the model tools can do' },
  inspect_mod_file: { working: 'Looking inside a mod file', done: 'Looked inside a mod file' },
  unpack_mod_file: { working: 'Unpacking a mod file', done: 'Unpacked a mod file' },
  // -- the game itself
  test_in_game: { working: 'Checking it in the game', done: 'Checked it in the game' },
  create_clone_character: { working: 'Building a new character', done: 'Built a new character' },
}

// Said when a tool arrives that this map has not been taught yet. It is vague on
// purpose: a vague true sentence beats a precise internal name.
export const UNNAMED = { working: 'Working on your request', done: 'Finished a step' }

// Steps that produce working material rather than something to look at. They
// collapse into one evolving activity line; the drafts, comparisons and results
// they lead to stay on screen.
export const INTERMEDIATE_TOOLS = new Set([
  'model_source', 'model_probe', 'model_mesh', 'model_region', 'model_prop',
  'model_script', 'model_poses', 'model_physics',
  'hsdraw', 'hsdraw_capabilities', 'inspect_mod_file', 'unpack_mod_file',
  'open_vault_file', 'open_vanilla_file',
])

// -- the model import
//
// Every import reply is tagged `studio_import` (backend
// model_import/chat/studio_import.py), and that tag is how a result is
// recognised. Today's import is one call, import_model (rigswap). Chats from
// before it hold the v2 studio's calls: numbered stages by tools the backend no
// longer has, one of them reusing the name `test_in_game`, so a name alone
// cannot say which tool answered. Their phrases stay for those chats.
export const STUDIO_STAGE_TOOLS = { clean_source: 2, pick_fighter: 3, line_up: 4, parts: 5, weight: 6,
  check_moves: 7, melee_safe: 8, export: 9, test_in_game: 10 }
// Names only the studio uses: a call by one of these is a studio call even
// before its reply arrives. `test_in_game` is not one of them.
export const STUDIO_ONLY_TOOLS = new Set([...Object.keys(STUDIO_STAGE_TOOLS).filter(name => name !== 'test_in_game'),
  'import_status', 'look', 'fresh_eyes', 'decide'])

export const isStudioResult = result => Boolean(result && typeof result === 'object'
  && result.studio_import && typeof result.studio_import === 'object' && !Array.isArray(result.studio_import))

const onFighter = fighter => fighter || 'the fighter'
// Each stage by what it does to the user's model. `fighter` is the fighter the
// model is going on, once the import has one.
export const STUDIO_STAGES = {
  2: { title: 'Clean up', working: () => 'Cleaning up the model you sent',
    done: () => 'Cleaned up the model you sent', failed: () => 'Could not clean up the model you sent' },
  3: { title: 'Fighter', working: () => 'Choosing a fighter for your model',
    done: fighter => fighter ? `Picked ${fighter} for your model` : 'Picked a fighter for your model',
    failed: () => 'Could not pick a fighter for your model' },
  4: { title: 'Line up', working: fighter => `Lining up the model on ${onFighter(fighter)}`,
    done: fighter => `Lined up the model on ${onFighter(fighter)}`,
    failed: fighter => `Could not line up the model on ${onFighter(fighter)}` },
  5: { title: 'Parts', working: () => 'Sorting out what moves with what',
    done: () => 'Sorted out what moves with what', failed: () => 'Could not sort out what moves with what' },
  6: { title: 'Weights', working: fighter => `Making the model bend with ${onFighter(fighter)}`,
    done: fighter => `Made the model bend with ${onFighter(fighter)}`,
    failed: fighter => `Could not make the model bend with ${onFighter(fighter)}` },
  7: { title: 'Move check', working: fighter => `Checking the model in ${onFighter(fighter)}'s moves`,
    done: fighter => `Checked the model in ${onFighter(fighter)}'s moves`,
    failed: fighter => `Could not check the model in ${onFighter(fighter)}'s moves` },
  8: { title: 'Melee limits', working: () => 'Fitting the costume within what Melee can load',
    done: () => 'Fitted the costume within what Melee can load',
    failed: () => 'Could not fit the costume within what Melee can load' },
  9: { title: 'Costume file', working: () => 'Writing the costume file',
    done: () => 'Wrote the costume file', failed: () => 'Could not write the costume file' },
  10: { title: 'In game', working: () => 'Trying the costume in the game',
    done: fighter => `Tried the costume in the game beside the original ${fighter || 'fighter'}`,
    failed: () => 'Could not try the costume in the game' },
}

// The studio calls that are not one stage's run.
export const STUDIO_ACTIVITY = {
  import_status: { working: 'Checking where the import is', done: 'Checked where the import is',
    failed: 'Could not check where the import is' },
  look: { working: 'Taking a closer look', done: 'Took a closer look', failed: 'Could not take that closer look' },
  fresh_eyes: { working: 'Asking for a second opinion', done: 'Got a second opinion',
    failed: 'Could not get a second opinion' },
  decide: { working: 'Recording a choice for the import', done: 'Recorded a choice for the import',
    failed: 'Could not record that choice' },
  // import_status with undo / redo_from, and test_in_game with finish_as.
  undo: { working: 'Taking back a change', done: 'Took back a change', failed: 'Took back a change, then a stage failed' },
  redo: { working: 'Running the import again', done: 'Ran the import again', failed: 'Ran the import again, then a stage failed' },
  finish: { working: 'Saving the costume to your vault', done: 'Saved the costume to your vault',
    failed: 'Could not save the costume to your vault' },
  // Import mode's one job (backend model_import/chat/import_job.py): rigswap, then the vault.
  import_model: { working: 'Importing your model', done: 'Imported your model',
    failed: 'Could not import your model' },
  // A change to a finished import (import_model with `change`: what the user said looks wrong): built again.
  change: { working: 'Changing your import', done: 'Changed your import', failed: 'Could not change your import' },
  // A model without the texture files it names: nothing ran, the user is asked for them (import_job.textures_reply).
  textures: { working: 'Importing your model', done: 'Your model came without its textures',
    failed: 'Could not import your model' },
  // The same, when what is missing is not only textures (an OBJ's .mtl, its materials file; a glTF's .bin).
  files: { working: 'Importing your model', done: 'Your model came without files it needs',
    failed: 'Could not import your model' },
  // The model import's tools (Blender, Python) are not downloaded, or are out of date: nothing ran, the card offers
  // the download (import_job.tools_reply; Settings > Model import tools).
  tools: { working: 'Importing your model', done: 'Model import needs its tools',
    failed: 'Could not import your model' },
  // An import that stopped before it saved (the user's Stop).
  stopped: { working: 'Importing your model', done: 'Your model import stopped before it saved',
    failed: 'Could not import your model' },
}

// The files a needs_textures reply names that are not textures (backend textures.kind): an OBJ's materials file, a
// glTF's data. 0.9.0 smoke: a missing Clank.mtl was called a texture file.
const NOT_TEXTURE = /\.(mtl|bin)$/i

/** Whether every file a needs_textures reply names (its `textures`) is a texture, so the card can say "textures". */
export function onlyTexturesMissing(result) {
  const names = Array.isArray(result?.textures) ? result.textures.map(name => String(name).trim()) : []
  return !names.some(name => NOT_TEXTURE.test(name))
}

const stageOf = value => Number.isInteger(value) && STUDIO_STAGES[value] ? value : null
const given = value => value !== undefined && value !== null

/**
 * What one studio call is doing or did, in words.
 * @returns {{phrase: string, stage: number|null, title: string|null,
 *   outcome: 'working'|'done'|'failed'|'refused'|'waiting'}}
 * `stage` is the stage the reply is about: a call reruns earlier stages that
 * went stale first, so a `weight` call can come back as stage 4 failing.
 * `refused` is a call the studio turned down before any stage ran.
 * `waiting` is an import that started nothing and waits on the user (a model
 * without its textures, or tools still to download): neither done nor failed.
 */
export function studioActivity(tool, fighter) {
  const result = tool?.result && typeof tool.result === 'object' ? tool.result : {}
  const args = tool?.arguments && typeof tool.arguments === 'object' ? tool.arguments : {}
  const running = tool?.status === 'running'
  const stageReply = Boolean(stageOf(result.stage) && typeof result.status === 'string' && !('mode' in result))
  const failed = !running && (tool?.status === 'error' || Boolean(result.error) || result.status === 'failed'
    || Boolean(result.failed) || Boolean(result.unavailable))
  const mode = running ? 'working' : failed ? 'failed' : 'done'
  const outcome = running ? 'working' : !failed ? 'done'
    : stageReply || result.failed || result.unavailable ? 'failed' : 'refused'
  const pick = (phrases, stage = null) => ({ phrase: phrases[mode], stage, title: stage ? STUDIO_STAGES[stage].title : null, outcome })
  const name = tool?.name
  if (name === 'import_model') {
    // Nothing ran: waiting on the user (0.9.0 smoke: its heading showed a ✓ over "Waiting on its textures").
    if (!running && !failed && result.status === 'needs_textures') {
      return { ...pick(onlyTexturesMissing(result) ? STUDIO_ACTIVITY.textures : STUDIO_ACTIVITY.files), outcome: 'waiting' }
    }
    // Nothing ran either: the tools it runs on are to be downloaded first (0.9.0: an optional download).
    if (!running && !failed && result.status === 'needs_tools') return { ...pick(STUDIO_ACTIVITY.tools), outcome: 'waiting' }
    // Neither done nor failed: stopped before it saved (cancelled; an older chat's import that stopped on a question).
    if (!running && !failed && result.status !== 'done') return { ...pick(STUDIO_ACTIVITY.stopped), outcome: 'done' }
    if (typeof args.change === 'string' && args.change) return pick(STUDIO_ACTIVITY.change)
    const done = !running && !failed && fighter ? `Imported your model onto ${fighter}` : null
    return { ...pick(STUDIO_ACTIVITY.import_model), phrase: done || STUDIO_ACTIVITY.import_model[mode] }
  }
  if (name === 'test_in_game' && args.finish_as) return pick(STUDIO_ACTIVITY.finish)
  if (name === 'import_status' && given(args.undo)) return pick(STUDIO_ACTIVITY.undo, stageReply ? result.stage : null)
  if (name === 'import_status' && given(args.redo_from)) return pick(STUDIO_ACTIVITY.redo, stageReply ? result.stage : null)
  if (name === 'look') return pick(STUDIO_ACTIVITY.look, stageOf(result.stage) || stageOf(args.stage))
  if (name === 'decide') {
    return pick(STUDIO_ACTIVITY.decide, stageOf(Number(args.stage))
      || stageOf(Number(String(result.decided || result.cleared || '').split(':')[0])))
  }
  if (STUDIO_ACTIVITY[name] && !stageReply) return pick(STUDIO_ACTIVITY[name])
  const stage = stageReply ? result.stage : STUDIO_STAGE_TOOLS[name] || null
  if (!stage) return { phrase: running ? UNNAMED.working : UNNAMED.done, stage: null, title: null, outcome }
  return { phrase: STUDIO_STAGES[stage][mode](fighter), stage, title: STUDIO_STAGES[stage].title, outcome }
}

/** One line: "Lined up the model on Fox (stage 4)". */
export function studioActivityLabel(tool, fighter) {
  const { phrase, stage } = studioActivity(tool, fighter)
  return stage ? `${phrase} (stage ${stage})` : phrase
}

/** A studio call by its reply's tag, or by a name only the studio uses. */
export const isStudioCall = tool => Boolean(tool) && (isStudioResult(tool.result) || STUDIO_ONLY_TOOLS.has(tool.name))

export const phraseFor = name => ACTIVITY[name] || UNNAMED

// skin_material edits a Stage Lab session too: its result then carries `stage_target`
// (backend assistant/continuity.record_stage_result), and "on the skin" would be wrong.
const STAGE_MATERIAL = { working: ACTIVITY.skin_material.working, done: 'Material on the stage' }

/** The phrase for one call, aware of what it worked on (a material on a stage, not a skin). */
export const phraseForTool = tool => tool?.name === 'skin_material' && tool?.result?.stage_target
  ? STAGE_MATERIAL : phraseFor(tool?.name)

/** `context.fighter` names the fighter a studio import is going on. */
export function activityLabel(tool, context) {
  if (!tool) return UNNAMED.done
  if (isStudioCall(tool)) return studioActivityLabel(tool, context?.fighter)
  const phrase = phraseForTool(tool)
  return tool.status === 'running' ? phrase.working : phrase.done
}

// Statuses that end a tool without it having done what was asked. Each one gets
// the same three-part sentence (ASTRA-BIGPICTURE, "Failure should have three
// parts"): the honest sentence, what was preserved, and one thing to do next.
export const SETTLED_STATUSES = ['error', 'denied', 'expired', 'cancelled', 'interrupted']

/** A backend error as a sentence, whatever shape it arrived in. */
export function errorText(error) {
  if (!error) return ''
  if (typeof error === 'string') return error.trim()
  if (typeof error !== 'object') return String(error)
  const said = error.message || error.detail || error.error || error.reason || error.code
  return typeof said === 'string' ? said.trim() : ''
}

const KEPT = 'Everything finished before this is kept.'

export function settledLines(tool) {
  if (!tool || !SETTLED_STATUSES.includes(tool.status)) return null
  const phrase = phraseFor(tool.name)
  const doing = phrase.working.charAt(0).toLowerCase() + phrase.working.slice(1)
  // A backend error is as often `{code, message, ...}` as it is a string, and
  // calling .trim() on the object threw while rendering the card that was
  // supposed to explain the failure (ASTRA-REVIEW-BB finding 10).
  const reported = errorText(tool.result?.error)
  // A refusal the backend could explain (`refusal`: a usage limit, the request's images used up;
  // assistant/refusals.py) already says in its one sentence what to do next, and asking Randall to
  // "try this again" in the same request is exactly what cannot work.
  const refused = Boolean(tool.result?.refusal)
  switch (tool.status) {
    case 'error':
      return { sentence: reported || `Randall could not finish ${doing}.`,
        preserved: KEPT,
        alternative: (typeof tool.result?.error === 'object' && tool.result.error?.recovery)
          || (refused ? '' : 'Tell Randall what to try instead, or ask him to try this again.') }
    case 'denied':
      return { sentence: `You said no to ${doing}.`,
        preserved: 'Nothing was changed.', alternative: 'Ask for a different option whenever you want.' }
    case 'expired':
      return { sentence: `This request sat unanswered too long, so Randall stopped ${doing}.`,
        preserved: KEPT, alternative: 'Ask Randall to prepare it again and it will come back with fresh details.' }
    case 'cancelled':
      return { sentence: `You stopped ${doing}.`,
        preserved: KEPT, alternative: 'Say what to do differently and Randall picks up from here.' }
    default:
      return { sentence: `${phrase.working} was interrupted before it finished.`,
        preserved: KEPT, alternative: 'Ask Randall to carry on and he restarts this step.' }
  }
}

// The four postconditions of the task envelope, said as a person would hear
// them (assistant/tasks/contracts.py POSTCONDITIONS). They are independent
// facts, never a four-step progress bar.
export const ACHIEVED_LABELS = {
  prepared: { yes: 'Ready to save or install', no: 'Not ready to save or install yet' },
  // `exported` is set when the bytes were written out, which happens BEFORE
  // anything is promoted to the place the user plays. Only `installed` may
  // speak about the game they play.
  exported: { yes: 'A file was written', no: 'No file written yet' },
  installed: { yes: 'In your playable game, and checked', no: 'Not in your playable game yet' },
  previewed: { yes: 'You have a preview of the result', no: 'No preview of the result yet' },
}

// A measured check, in words. `unknown` is never softened into a pass: it means
// the measurement could not be taken.
export const CHECK_LABELS = {
  structural_validity: 'The file is built correctly',
  native_round_trip: 'Melee can read the file back',
  fit_verdict_shippable: 'The fit is good enough to build',
  fit_usability: 'The costume is usable',
  review_evidence_current: 'The pictures match this version',
  posture: 'It stands the way a fighter stands',
  extent: 'It is the right size',
  game_verification: 'Checked while the game was running',
  visual_assessment: 'Someone looked at the pictures',
  // What a delivery checks, and what it says it did not (delivery/deliver_checks.py).
  costume_in_disc_image: 'The costume is in the rebuilt game',
  saved_copy_matches_build: 'Your game file matches the build',
  slippi_online_label: 'Safe for online play',
  automated_movement_checks: 'Tested in a match',
  interactive_play: 'Played by you',
  full_build_checks: 'The rest of the game re-checked',
  costume_slot_mapping: 'The colour slot it shows in',
}

export const CHECK_STATUS_LABELS = {
  pass: 'Passed', fail: 'Failed', warn: 'Worth a look',
  unknown: 'Could not check', not_applicable: 'Does not apply',
}

export const checkLabel = check => CHECK_LABELS[check?.check_id]
  || (check?.check_id ? 'A check on the costume' : 'A check')

// Seconds -> "1 min 20 sec". Elapsed time is shown because it is measured; an
// estimate is only ever shown when the backend supplies one.
export function elapsedText(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0))
  if (total < 60) return `${total} sec`
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return rest ? `${minutes} min ${rest} sec` : `${minutes} min`
}

// null/undefined is "nothing was reported", which is not $0.00: a zero there
// is a measurement, and showing one we never took is the whole problem.
export const moneyText = amount => amount === null || amount === undefined || amount === ''
  || !Number.isFinite(Number(amount)) ? null : `$${Number(amount).toFixed(2)}`
