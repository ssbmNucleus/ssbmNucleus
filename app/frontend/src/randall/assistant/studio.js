// Reading the model import out of the transcript: import_model's job (rigswap, backend
// model_import/chat/import_job.py) and, in older chats, the v2 studio's stage calls.
//
// An import reply is a plain JSON object tagged `studio_import: {tool, id}`
// (backend model_import/chat/studio_import.py). An older chat's stage reply is `{stage, name, status,
// next, pictures, report, ...}`, a failed one adds `{error, fix_at, findings, rolled_back?}`, and the
// pictures a reply names are registered as chat files in `files` (each with the `path` the reply used).
// Everything here reads those shapes; nothing depends on the old import tools.
import { STUDIO_ONLY_TOOLS, STUDIO_STAGES, elapsedText, isStudioResult, onlyTexturesMissing, studioActivity } from './activity.js'

export { STUDIO_ONLY_TOOLS, STUDIO_STAGE_TOOLS, isStudioCall, isStudioResult } from './activity.js'

/**
 * Whether a call is the studio's. The reply's tag decides. Before a reply
 * arrives (running), or when a call was turned down before it ran, a name only
 * the studio uses decides; for the shared name `test_in_game` its arguments
 * decide, and failing those whether this chat is already running an import.
 */
export function isStudioTool(tool, studioChat = false) {
  if (!tool) return false
  if (isStudioResult(tool.result)) return true
  if (STUDIO_ONLY_TOOLS.has(tool.name)) return true
  // Import mode's one job, before its first progress arrives (the old one-call import no longer runs).
  if (tool.name === 'import_model') return tool.status === 'running'

  if (tool.name !== 'test_in_game') return false
  const args = tool.arguments && typeof tool.arguments === 'object' ? tool.arguments : {}
  if ('project' in args || 'finish_as' in args || 'closeups' in args) return true
  if ('action' in args) return false
  const result = tool.result && typeof tool.result === 'object' ? tool.result : {}
  // The play-session tool's own replies.
  if (result.game_test || result.game_verification || result.items || result.task) return false
  return Boolean(studioChat)
}

const HEX_ID = /^[a-f0-9]{32}$/
export const normPath = value => String(value || '').replace(/\\/g, '/').toLowerCase()
export const pngFiles = result => (Array.isArray(result?.files) ? result.files : [])
  .filter(file => file?.file_id && String(file.extension || '').toLowerCase() === '.png')

/** The fighter a reply shows the model on, when it says. */
export function studioFighterOf(tool) {
  const result = tool?.result && typeof tool.result === 'object' ? tool.result : {}
  const report = result.report && typeof result.report === 'object' ? result.report : {}
  const text = value => typeof value === 'string' && value.trim() ? value.trim() : null
  if (tool?.name === 'import_model') return text(result.fighter) || text(tool.arguments?.fighter)
  const fromLook = Object.values(report.look && typeof report.look === 'object' ? report.look : {})
    .map(entry => entry && typeof entry === 'object' ? text(entry.fighter) : null).find(Boolean)
  return text(report.fighter) || text(report.identity?.fighter) || text(result.measurements?.fighter) || fromLook
    || (tool?.name === 'pick_fighter' && tool.status === 'done' ? text(tool.arguments?.fighter) : null)
}

/**
 * What the whole chat says about its imports, for cards that need more than
 * their own reply: the fighter each import was on at each call, every picture
 * by file ID and by the path the replies used (fresh_eyes names pictures by
 * path), the file the user attached for each import, and when the turn each
 * call ran in started (`turnStart`, by call ID: the start the status bar below
 * the chat counts from).
 */
export function studioContext(messages = []) {
  const files = new Map(), fighterAt = new Map(), fighters = new Map(), sources = new Map(), attachments = new Map()
  const turnStart = new Map()
  let active = false, latestFighter = null
  for (const message of messages || []) {
    for (const file of message?.context?.files || []) if (file?.file_id) attachments.set(file.file_id, file)
    for (const tool of message?.tools || []) {
      const result = tool?.result
      if (tool?.id && message?.started_at !== undefined && message?.started_at !== null) {
        turnStart.set(tool.id, message.started_at)
      }
      if (!isStudioResult(result)) continue
      active = true
      const id = result.studio_import.id || ''
      for (const file of pngFiles(result)) {
        files.set(file.file_id, file)
        if (file.path) files.set(normPath(file.path), file)
      }
      const fighter = studioFighterOf(tool)
      if (fighter) { fighters.set(id, fighter); latestFighter = fighter }
      if (tool.id) fighterAt.set(tool.id, fighters.get(id) || null)
      const source = tool.arguments?.source
      if (id && ['clean_source', 'import_model'].includes(tool.name) && attachments.has(source)) {
        sources.set(id, attachments.get(source).name)
      }
    }
  }
  return { active, files, fighterAt, fighters, sources, latestFighter, turnStart }
}

/** The fighter a call's card names: its own reply's, else the import's at that point. */
export function studioFighter(tool, context) {
  return studioFighterOf(tool) || context?.fighterAt?.get(tool?.id)
    || context?.fighters?.get(tool?.result?.studio_import?.id) || context?.latestFighter || null
}

// -- pictures

const MOVES = {
  idle: 'Idle', wait: 'Idle', run: 'Run', squat: 'Squat', dash: 'Dash', walk: 'Walk', jab: 'Jab', fair: 'Forward air',
  bair: 'Back air', nair: 'Neutral air', uair: 'Up air', dair: 'Down air', upb: 'Up-B', sideb: 'Side-B',
  downb: 'Down-B', neutralb: 'Neutral-B', fsmash: 'Forward smash', usmash: 'Up smash', dsmash: 'Down smash',
  ftilt: 'Forward tilt', utilt: 'Up tilt', dtilt: 'Down tilt', dashattack: 'Dash attack', grab: 'Grab',
  blink: 'Blink', taunt: 'Taunt',
  // Melee's own animation names, as the costume file's pictures are named ("dat-AttackAirN-5").
  wait1: 'Idle', wait2: 'Idle', walkslow: 'Slow walk', walkmiddle: 'Walk', walkfast: 'Fast walk', runbrake: 'Run stop',
  turn: 'Turn', jumpf: 'Jump', jumpb: 'Back jump', jumpaerialf: 'Double jump', jumpaerialb: 'Back double jump',
  fall: 'Fall', squatwait: 'Crouch', landing: 'Landing', guard: 'Shield', guardon: 'Shield',
  attack11: 'Jab', attack12: 'Second jab', attack13: 'Third jab', attack100start: 'Rapid jab', attack100loop: 'Rapid jab',
  attack100end: 'Rapid jab', attackdash: 'Dash attack',
  attacks3s: 'Forward tilt', attacks3hi: 'Forward tilt, angled up', attacks3his: 'Forward tilt, angled up',
  attacks3lw: 'Forward tilt, angled down', attacks3lws: 'Forward tilt, angled down', attackhi3: 'Up tilt',
  attacklw3: 'Down tilt', attacks4s: 'Forward smash', attacks4hi: 'Forward smash, angled up',
  attacks4his: 'Forward smash, angled up', attacks4lw: 'Forward smash, angled down',
  attacks4lws: 'Forward smash, angled down', attackhi4: 'Up smash', attacklw4: 'Down smash',
  attackairn: 'Neutral air', attackairf: 'Forward air', attackairb: 'Back air', attackairhi: 'Up air',
  attackairlw: 'Down air', catch: 'Grab', catchdash: 'Dash grab', throwf: 'Forward throw', throwb: 'Back throw',
  throwhi: 'Up throw', throwlw: 'Down throw', appeal: 'Taunt', appealr: 'Taunt', appeall: 'Taunt',
  escapef: 'Forward roll', escapeb: 'Back roll', escapen: 'Spot dodge', escapeair: 'Air dodge',
  specialn: 'Neutral-B', specials: 'Side-B', specialhi: 'Up-B', speciallw: 'Down-B',
  specialairn: 'Neutral-B in the air', specialairs: 'Side-B in the air', specialairhi: 'Up-B',
  specialairlw: 'Down-B in the air',
}
/** A move's name in words: "AttackAirN" -> "Neutral air"; a name not known as it is (or through `plain`). */
const moveName = (move, plain = text => text) => (Object.hasOwn(MOVES, String(move).toLowerCase())
  ? MOVES[String(move).toLowerCase()] : plain(String(move)))
// A dot before a space is part of a name ("C. Falcon"); one inside a word is a separator.
const words = text => text.replace(/[-_]+|\.(?=\S)/g, ' ').replace(/\s+/g, ' ').trim()
const stem = value => String(value || '').replace(/\.[a-z0-9]+$/i, '')

/** "idle1-run9" -> "Idle, frame 1 · Run, frame 9"; null when it is not that shape. */
export function movesCaption(text) {
  const parts = String(text || '').split('-').filter(Boolean)
  const moves = parts.map(part => part.match(/^([a-z]+)(\d+)$/i))
  if (!parts.length || moves.some(match => !match)) return null
  return moves.map(([, move, frame]) => `${moveName(move)}, frame ${Number(frame)}`).join(' · ')
}

/** A pose the import names ("Wait-1", "AttackAirN-5", "blink") in words: "Idle, frame 1", "Neutral air, frame 5",
    "Blink"; other names as they are. */
export function poseCaption(pose) {
  const match = String(pose || '').match(/^([a-z][a-z0-9]*)-(\d+)$/i)
  if (!match) return moveName(String(pose || ''), words)
  return `${moveName(match[1], words)}, frame ${Number(match[2])}`
}

/** A picture named the way the studio's folders name it, not by its chat file name. */
export function pictureCaption(file) {
  const path = String(file?.path || '').replace(/\\/g, '/')
  const segments = path ? path.split('/') : []
  const at = segments.lastIndexOf('pictures')
  let parts = at >= 0 ? segments.slice(at + 1) : segments.slice(-1)
  if (!parts.length || !parts[parts.length - 1]) {
    // No path: the chat file name flattens the folders with "_".
    const name = stem(file?.name)
    parts = [name.includes('_pictures_') ? name.split('_pictures_').pop() : name]
  }
  const last = stem(parts[parts.length - 1])
  // The written costume file's pictures ("dat/dat-Wait-1", "dat/dat-blink"; by chat file name "dat_dat-blink"): the
  // pose each shows it in.
  const folderAndName = parts.length > 1 ? `${parts[parts.length - 2]}/${last}` : last.replace('_', '/')
  const dat = folderAndName.match(/^dat\/dat-(.+)$/i)
  if (dat) return poseCaption(dat[1])
  const game = last.match(/^game-\d+-(.+)$/)
  if (game) return movesCaption(game[1]) || words(game[1])
  // One in-game capture: "0x00-idle-f01".
  const capture = last.match(/^(?:0x[0-9a-f]+-)?([a-z]+)-f(\d+)$/i)
  if (capture) return `${moveName(capture[1])}, frame ${Number(capture[2])}`
  // `last` is already without its extension; "01-off-the-floor.r_leg.j17" has more dots.
  const shown = [...parts.slice(0, -1), last].map(part => words(part.replace(/^\d+-/, ''))).filter(Boolean)
  return shown.join(' · ') || 'Picture'
}

/** The in-game shots: import and vanilla captures paired when the reply
    carries both as files, and the composed side-by-side pictures as they are. */
export function gamePictures(result) {
  const images = pngFiles(result)
  const sides = new Map(), singles = []
  for (const file of images) {
    const match = normPath(file.path || file.name).match(/(?:^|[/_])(import|vanilla)[/_]([^/]+)$/)
    if (!match) { singles.push(file); continue }
    const key = match[2]
    if (!sides.has(key)) sides.set(key, {})
    sides.get(key)[match[1]] = file
  }
  const pairs = []
  for (const [key, pair] of sides) {
    if (pair.import && pair.vanilla) pairs.push({ key, import: pair.import, vanilla: pair.vanilla })
    else singles.push(pair.import || pair.vanilla)
  }
  return { pairs, singles }
}

/** The pictures fresh_eyes was shown: its arguments name them by path or file ID. */
export function freshEyesPictures(tool, context) {
  const named = Array.isArray(tool?.arguments?.pictures) ? tool.arguments.pictures : []
  const found = [], missing = []
  for (const value of named) {
    const key = String(value || '')
    const file = context?.files?.get(HEX_ID.test(key) ? key : normPath(key))
    if (file && !found.includes(file)) found.push(file)
    else if (!file) missing.push(key)
  }
  return { files: found, missing: missing.length }
}

// -- what a call changed

/** A value in one short line: `{part: r_leg, translation: [0, -0.86, 0]}`. */
export function brief(value, depth = 0) {
  if (value === null || value === undefined) return 'none'
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(Math.round(value * 1000) / 1000)
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (Array.isArray(value)) return depth > 1 ? `[${value.length}]` : `[${value.map(item => brief(item, depth + 1)).join(', ')}]`
  if (typeof value === 'object') {
    if (depth > 1) return '{…}'
    return `{${Object.entries(value).map(([key, item]) => `${key}: ${brief(item, depth + 1)}`).join(', ')}}`
  }
  return String(value)
}
export const clip = (text, size = 140) => text.length > size ? `${text.slice(0, size - 1)}…` : text
const full = value => { try { return JSON.stringify(value) } catch { return String(value) } }

// Parameters that say which import and why, not what to change.
const NOT_A_CHANGE = new Set(['project', 'op', 'arguments', 'selection', 'reason', 'source', 'pictures', 'question',
  'redo_from', 'undo', 'finish_as', 'name', 'value', 'stage'])
const LOOK_KEYS = ['mode', 'stage', 'views', 'poses', 'focus', 'bone', 'by', 'cull', 'selection']

/**
 * The op or choices a call applied, compact.
 * @returns {{kind: string, op?: string, text: string, full: string}[]}
 */
export function studioChanges(tool) {
  const args = tool?.arguments && typeof tool.arguments === 'object' ? tool.arguments : {}
  const rows = []
  const row = (kind, value, extra = {}) => rows.push({ kind, text: clip(typeof value === 'string' ? value : brief(value)),
    full: typeof value === 'string' ? value : full(value), ...extra })
  if (tool?.name === 'look') {
    const view = LOOK_KEYS.filter(key => args[key] !== undefined && args[key] !== null)
      .map(key => `${key} ${brief(args[key])}`).join(' · ')
    if (view) row('View', view)
    return rows
  }
  if (tool?.name === 'decide') {
    if (args.name) row('Choice', `${args.name} → ${brief(args.value)}`)
    return rows
  }
  if (args.undo !== undefined && args.undo !== null) {
    const undo = args.undo
    row('Undo', typeof undo === 'object' ? `change ${brief(undo.op ?? 'last')} of stage ${brief(undo.stage)}`
      : `the last change of stage ${brief(undo)}`)
  }
  if (args.redo_from !== undefined && args.redo_from !== null) row('Redo', `from stage ${brief(args.redo_from)}`)
  if (args.op) {
    const parts = [args.arguments && Object.keys(args.arguments).length ? brief(args.arguments) : '',
      args.selection && Object.keys(args.selection).length ? `on ${brief(args.selection)}` : ''].filter(Boolean)
    rows.push({ kind: 'Change', op: String(args.op), text: clip(parts.join(' ')),
      full: full({ op: args.op, arguments: args.arguments, selection: args.selection }) })
  }
  for (const [key, value] of Object.entries(args)) {
    if (NOT_A_CHANGE.has(key) || value === undefined || value === null) continue
    // clean_source's fighter is the one the user asked for, carried to stage 3, not a stage-2 choice.
    if (tool?.name === 'clean_source' && key === 'fighter') row('Asked for', value)
    else row('Choice', `${key} → ${brief(value)}`)
  }
  if (args.finish_as) row('Save as', String(args.finish_as))
  return rows
}

// -- what a reply warns about

const texts = value => (Array.isArray(value) ? value : value === undefined || value === null ? [] : [value])
  .map(item => typeof item === 'string' ? item : brief(item)).map(item => item.trim()).filter(Boolean)

/** `warnings` are shown; `notes` are one click away. */
export function studioNotes(result) {
  const report = result?.report && typeof result.report === 'object' ? result.report : {}
  const warnings = [...texts(result?.rolled_back), ...texts(result?.op_kept), ...texts(result?.limit),
    ...texts(result?.code_stale), ...texts(result?.unavailable)]
  const notes = [...texts(result?.input_notes), ...texts(report.notes), ...texts(result?.notes),
    ...texts(result?.picture_notes), ...texts(result?.pictures_not_shown), ...texts(result?.note)]
  if (Array.isArray(report.frames)) {
    for (const frame of report.frames) {
      if (frame && frame.frame_match === false) warnings.push(`${frame.move} frame ${frame.frame}: the costume and the original were not caught on the same frame.`)
      if (frame && frame.status && frame.status !== 'captured') warnings.push(`${frame.move} frame ${frame.frame}: ${words(String(frame.status))}.`)
    }
  }
  const slot = report.identity?.import
  if (slot && slot.slot_matches === false) warnings.push(`The game loaded costume slot ${slot.loaded_slot}, not slot ${slot.requested_slot}.`)
  return { warnings, notes }
}

/** Questions the import is waiting on, with the answer it proposes. */
export const studioQuestions = result => (Array.isArray(result?.questions) ? result.questions : [])
  .filter(question => question && typeof question.question === 'string')
  .map(question => ({ id: String(question.id || question.question), question: question.question,
    proposal: question.proposal === undefined || question.proposal === null ? null : clip(brief(question.proposal), 60) }))

/** import_status: one row per stage. */
export const stageRows = result => (Array.isArray(result?.stages) ? result.stages : [])
  .filter(row => row && Number.isInteger(row.stage))
  .map(row => ({ stage: row.stage, title: STUDIO_STAGES[row.stage]?.title || words(String(row.name || '')),
    status: String(row.status || ''), ops: Array.isArray(row.ops) ? row.ops.length : 0,
    failure: typeof row.failure === 'string' ? row.failure : null, outdated: Boolean(row.stale || row.pictures_stale) }))

export const STAGE_STATUS = { done: 'Done', failed: 'Failed', stale: 'Waiting to run', running: 'Running' }

/** The line a card's heading carries on the right. */
export function studioStatusText(tool) {
  const result = tool?.result && typeof tool.result === 'object' ? tool.result : {}
  if (tool?.status === 'running') return 'Working'
  const { outcome } = studioActivity(tool)
  if (outcome === 'refused') return 'Not run'
  if (result.unavailable) return 'Not available'
  if (outcome === 'failed') return 'Failed'
  return STAGE_STATUS[result.status] || { cancelled: 'Stopped', interrupted: 'Interrupted', denied: 'Declined',
    expired: 'Expired' }[tool?.status] || 'Done'
}

/** The next step the studio names, when it names one. */
export const studioNext = result => typeof result?.next === 'string' && result.next.trim() ? result.next.trim() : null

/** Where to fix a failure, when it is another stage than the one reported. */
export function studioFixAt(result) {
  const at = Number(result?.fix_at)
  if (!Number.isInteger(at) || !STUDIO_STAGES[at]) return null
  return `Stage ${at} · ${STUDIO_STAGES[at].title}`
}

// -- import mode's one job (import_model)

const seconds = value => Number.isFinite(Number(value)) ? Number(value) : null
/**
 * How long an import has taken, in the status bar's words ("2 min 55 sec"). While it runs it counts from the turn's
 * start (`startedAt`, epoch seconds; the call's own start without one), the start the status bar below the chat
 * counts from, so the two read the same at every tick; once it is over, the same clock stopped when the call
 * finished. A reply without those times says the import's own `seconds`.
 */
export function importTimeText(tool, { startedAt, now = Date.now() } = {}) {
  const start = Number(startedAt ?? tool?.started_at)
  const known = Number.isFinite(start) && start > 0
  const result = tool?.result && typeof tool.result === 'object' ? tool.result : {}
  if (tool?.status === 'running') {
    if (known) return elapsedText(Math.max(0, now / 1000 - start))
  } else {
    const end = Number(tool?.completed_at)
    if (known && Number.isFinite(end) && end >= start) return elapsedText(end - start)
  }
  const own = seconds(result.seconds)
  return own === null ? null : elapsedText(own)
}
/** "$0.0011": small costs keep their first two significant digits. */
export function costText(value) {
  const usd = Number(value)
  if (!Number.isFinite(usd)) return null
  if (usd === 0) return '$0'
  return usd >= 0.01 ? `$${usd.toFixed(2)}` : `$${usd.toPrecision(2)}`
}

/**
 * An import_model reply, read for its card: what it saved, where it stopped, its cost, the newest progress lines
 * while it runs, and its pictures (its time is `importTimeText`, the status bar's clock). An older chat's v4 reply reads the same way; what only v4 sent (its phases,
 * decisions, choices and picture sheet) is not read, and its pictures are shown as they are.
 */
export function importJob(result) {
  const r = result && typeof result === 'object' ? result : {}
  return {
    status: String(r.status || ''), project: r.project || r.studio_import?.id || null,
    fighter: typeof r.fighter === 'string' ? r.fighter : null,
    saved: r.saved && typeof r.saved === 'object' ? r.saved : null,
    notSaved: typeof r.not_saved === 'string' ? r.not_saved : null,
    cost: costText(r.cost_usd),
    progress: (Array.isArray(r.progress) ? r.progress : []).map(String),
    // The running card's plain step (import_job.STEPS, e.g. "putting it on the fighter"); progress holds raw lines.
    step: typeof r.step === 'string' && r.step.trim() ? r.step.trim() : null,
    pictures: pngFiles(r),
    failed: r.failed && typeof r.failed === 'object' ? r.failed : null,
    // What the import said about the model before it ran (needs_textures: the files it names that did not come with
    // it, its materials file or textures, each named for what it is), or what its own check of the finished costume
    // said: shown as written.
    warning: typeof r.warning === 'string' && r.warning.trim() ? r.warning.trim() : null,
    textures: Array.isArray(r.textures) ? r.textures.map(String) : [],
    // needs_tools: the tools the import runs on are not downloaded (or out of date); the card offers the download.
    tools: r.status === 'needs_tools' && r.tools && typeof r.tools === 'object' ? r.tools : null,
  }
}

/** The status an import_model card carries on the right. */
export function importStatusText(tool) {
  const job = importJob(tool?.result)
  if (tool?.status === 'running') return 'Working'
  if (tool?.status === 'error' || tool?.result?.error || job.status === 'failed') return 'Failed'
  if (job.status === 'needs_textures') return onlyTexturesMissing(tool?.result) ? 'Waiting on its textures' : 'Waiting on its files'
  if (job.status === 'needs_tools') return 'Needs its tools'
  if (job.saved) return 'Saved to your vault'
  if (job.status === 'done') return 'Done, not saved'
  if (job.status === 'cancelled') return 'Stopped'
  return studioStatusText(tool)
}

/** What the workbench calls an import: the file the user attached, else its id. */
export function studioSubjectName(tool, context) {
  // Once the import saved the costume, it is the name in the vault (Randall's name for it, from the user's message),
  // not the attached file's.
  const saved = tool?.result?.saved
  if (saved && typeof saved === 'object' && typeof saved.name === 'string' && saved.name.trim()) return saved.name.trim()
  const id = tool?.result?.studio_import?.id
  const source = context?.sources?.get(id)
  return stem(source || '') || id || 'Your model'
}
