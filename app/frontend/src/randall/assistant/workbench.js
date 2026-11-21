// What Randall is working on right now, read from the transcript alone.
//
// The workbench panel beside the chat shows the thing being made: the costume
// or stage file loaded in the 3D viewer, the pictures Randall rendered to judge
// it, and a live game test. Everything it needs already arrives in tool
// results; this turns them into one "subject" so the panel never has to know
// which tool produced what.
//
// A model import is one call (import_model: rigswap, one AI look). The chat's
// import card shows its steps while it runs, so the panel shows an import only
// once it has written its costume file: that file in 3D, on its fighter, and
// In game when it is tested. It has no Pictures: its one picture is the saved
// portrait, which the card already shows. Pictures belong to Skin Lab and Stage
// Lab, where Randall really works in steps and renders each to judge it.
import { phraseForTool } from './activity.js'
import { isStudioCall, studioContext, studioFighter, studioSubjectName } from './studio.js'

// The import's call, and in chats from before the one-call import (2026-09/10) the step-by-step importer's calls: none
// of them runs any more, but an old chat's exported costume file still shows in 3D.
const MODEL_TOOLS = new Set(['import_model', 'model_fit', 'model_candidate', 'model_mesh', 'model_revise',
  'model_poses', 'model_render', 'model_review', 'model_script', 'model_source', 'model_probe', 'model_prop',
  'model_region', 'model_physics'])
const SKIN_TOOLS = new Set(['skin_lab_open', 'skin_lab', 'skin_material'])
const STAGE_TOOLS = new Set(['stage_lab_open', 'stage_lab'])
// The tools whose steps and pictures the panel shows (Pictures, the step under the title).
const LAB_TOOLS = new Set([...SKIN_TOOLS, ...STAGE_TOOLS, 'preview_portrait'])
// The subjects that have Pictures: a costume in Skin Lab, a stage in Stage Lab.
export const LAB_KINDS = new Set(['costume', 'stage'])

// Melee's costume colour codes, in words (PlFxOr is Fox's orange costume).
const COLORS = { Nr: 'default', Re: 'red', Bu: 'blue', Gr: 'green', Wh: 'white', Bk: 'black', Ye: 'yellow',
  Or: 'orange', La: 'lavender', Pi: 'pink', Aq: 'aqua', Gy: 'grey', Pu: 'purple', Br: 'brown', Rd: 'red' }
const vanillaName = (character, color) => COLORS[color] ? `${character} (${COLORS[color]})` : `${character} ${color || ''}`.trim()
const pngs = result => (result.files || []).filter(file => file?.extension === '.png' && file.file_id)
const datOf = result => (result.files || []).find(file => file?.extension === '.dat' && file.file_id) || null
const stem = name => String(name || '').replace(/\.[^.]+$/, '')
// What the viewer is showing: the file it loaded.
export const viewKey = model => model?.fileId || ''

// Consecutive texture-only edits the view can still catch up on in one go.
const MAX_SWAP_CHAIN = 8
const COLOUR_TYPES = new Set(['setVertexColors', 'setAnimationColors', 'setLightColors'])
const MATERIAL_COLOUR_FIELDS = ['ambient', 'diffuse', 'specular']
const strings = value => Array.isArray(value) && value.every(item => typeof item === 'string')
// A colour edit the lab's renderer took in place: the id of its stored stream messages, their types, and the
// objects whose material colours they set (backend continuity.keep_colours).
const validColours = colours => colours === undefined || Boolean(colours && typeof colours.id === 'string'
  && /^[a-f0-9]{32}$/.test(colours.id) && strings(colours.types) && colours.types.length
  && colours.types.every(type => COLOUR_TYPES.has(type)) && strings(colours.objects))
const validSwap = swap => Boolean(swap && typeof swap.from === 'string' && swap.from && Array.isArray(swap.textures)
  && swap.textures.every(texture => Number.isInteger(texture?.index) && texture.index >= 0
    && typeof texture.file_id === 'string' && texture.file_id)
  && (swap.materials === undefined || (Array.isArray(swap.materials) && swap.materials.every(edit =>
    typeof edit?.id === 'string' && typeof edit.field === 'string'
    && (typeof edit.value === 'string' || Number.isFinite(edit.value)))))
  && validColours(swap.colours))

/**
 * What takes the 3D view from what it shows to `model` without restarting its renderer (6-10 s), or null
 * when it has to reload. The backend names what each edit changed (`viewer_update` on a lab checkpoint: the
 * checkpoint it applies on top of, each changed texture as a PNG file, each changed material field with
 * its new value, and for a vertex colour, colour key or light edit the lab's renderer took in place, its
 * stored stream messages), and `model.swaps` keeps the unbroken chain of them. A plan exists only when the
 * view shows a checkpoint in that chain, of the same fighter or stage, in a single-model view (never the Ice
 * Climbers pair, which loads two files), with the renderer up, and -- when the chain has colour messages --
 * a renderer that takes them (`supports(type)`: an older viewer reloads). Each texture and each material
 * field appears once, with its newest value; colour messages are sent in chain order, before the material
 * values, and a material value older than a colour edit setting the same object's colours is dropped (the
 * colour edit's value is newer).
 * -> {textures: [{index, file_id}], materials: [{id, field, value}], colours?: [{id, types}]} (all possibly
 *    empty: the same content under a new file; `colours` only when the chain has some) | null
 */
export function swapPlan(shown, model, { connected = false, pair = false, supports = () => false } = {}) {
  const swaps = model?.swaps
  if (!connected || pair || !shown?.fileId || !model?.fileId || model.fileId === shown.fileId
      || !Array.isArray(swaps) || (shown.character || '') !== (model.character || '')
      || (shown.stageCode || '') !== (model.stageCode || '')) return null
  const start = swaps.findIndex(swap => swap.from === shown.fileId)
  if (start < 0) return null
  const textures = new Map(), materials = new Map(), colours = []
  for (const swap of swaps.slice(start)) {
    for (const texture of swap.textures) {
      textures.delete(texture.index)
      textures.set(texture.index, { index: texture.index, file_id: texture.file_id })
    }
    if (swap.colours) {
      if (!swap.colours.types.every(type => supports(type))) return null
      for (const id of swap.colours.objects)
        for (const field of MATERIAL_COLOUR_FIELDS) materials.delete(`${id}\u0000${field}`)
      colours.push({ id: swap.colours.id, types: [...swap.colours.types] })
    }
    for (const edit of swap.materials || []) {
      const key = `${edit.id}\u0000${edit.field}`
      materials.delete(key)
      materials.set(key, { id: edit.id, field: edit.field, value: edit.value })
    }
  }
  return { textures: [...textures.values()], materials: [...materials.values()], ...(colours.length ? { colours } : {}) }
}

/**
 * Whether the view can show `model` by loading its file into the renderer already running (protocol 2
 * `loadDat`, about 0.5 s instead of a 2-5 s restart): a single-model view of the same kind (a stage after a
 * stage, a costume after a costume; the camera stays), connected, with a renderer that announced it.
 */
export function canLoadInPlace(shown, model, { connected = false, pair = false, supports = () => false } = {}) {
  return Boolean(connected && !pair && shown && model?.fileId
    && Boolean(shown.stageCode) === Boolean(model.stageCode) && supports('loadDat'))
}

/**
 * The animation the list shows: the one loaded when the list has it, else none ('': the rest pose). A fighter's
 * animations are its own, so once a model on another fighter is loaded the last fighter's symbol names nothing,
 * and a list given it as its value fell back to its first entry ("Jab 1") while the model stood still.
 */
export const listedAnimation = (symbols, loaded) =>
  (loaded && Array.isArray(symbols) && symbols.includes(loaded) ? loaded : '')

/**
 * The animation to play again when a renderer's list arrives ({symbol, subject}: what the user picked, and on what):
 * only while the view shows the subject it was picked on. Another chat's model starts in its pose, as it starts with
 * its own camera; a Jab picked in a Mario chat used to play again in the next Mario chat, a Pichu chat between them.
 */
export const wantedAnimation = (wanted, subject) =>
  (wanted?.symbol && (wanted.subject || '') === (subject || '') ? wanted.symbol : '')

/**
 * Whether a file loaded into the running renderer takes a fresh camera (`loadDat` with `reframe`): when it is
 * another subject (another chat's costume), which appeared wherever the last one's view had been left, even off
 * the edge; and when it is on another fighter (or another stage), whose own framing is nothing like the last one's
 * (Fox's camera sits 22 units away at 70 degrees, Bowser's 1747 at 2: kept, it shows the next fighter's knees). The
 * next file of the subject being worked on, on the same fighter, keeps the view the user set up.
 * `shown` and `next`: {subject, character, stageCode}; `shown` null when nothing is shown yet.
 */
export function freshCamera(shown, next) {
  if (!next) return false
  if (next.subject && shown?.subject !== next.subject) return true
  return Boolean(shown) && ((shown.character || '') !== (next.character || '')
    || (shown.stageCode || '') !== (next.stageCode || ''))
}

/**
 * The camera move that puts the view back where it was after a reset to its first framing (`resetView` also puts
 * the camera back; "Pose" in the animation list asks only for the pose). `before` and `home` are the renderer's
 * camera (exportScene: x, y, scale, rotationXRadians, rotationYRadians) before the reset and after it.
 * -> the `camera` message's deltas [rotX degrees, rotY degrees, zoom factor - 1, x, y], or null (nothing to undo, or
 *    a camera not read)
 */
export function cameraBack(before, home) {
  const read = camera => camera && ['x', 'y', 'scale', 'rotationXRadians', 'rotationYRadians']
    .every(key => Number.isFinite(Number(camera[key]))) && Number(camera.scale) > 0
  if (!read(before) || !read(home)) return null
  const delta = key => Number(before[key]) - Number(home[key])
  const degrees = radians => radians * 180 / Math.PI
  const deltas = [degrees(delta('rotationXRadians')), degrees(delta('rotationYRadians')),
    Number(before.scale) / Number(home.scale) - 1, delta('x'), delta('y')]
  return deltas.some(value => Math.abs(value) > 1e-6) ? deltas : null
}

/**
 * What the 3D view does when it goes on or off screen (another app tab, the Pictures or In game tab) or its model
 * changes.
 * Off screen, a view that is up and idle stays up ('keep'): its surface pauses the renderer, so coming back shows
 * the same view at once instead of relaunching it (2-5 s, the "Updating" badge). A view still starting, swapping
 * or loading stops ('stop', as every hide used to) and starts again when shown, as does one on the legacy native
 * overlay (not `streaming`: Electron shows its window again whenever the app window takes focus). Back on screen, a kept view is
 * checked first ('resume': the app runs one renderer, and another tab's 3D view replaces it without telling this
 * one); otherwise the view follows its model ('show': nothing when it already shows it, else a swap, a load or a
 * launch). A model that changed while off screen is shown on the way back.
 * -> 'keep' | 'stop' | 'resume' | 'show'
 */
export function screenAction({ active, wasActive = false, session = false, shown = false, connected = false,
  streaming = false, busy = false }) {
  if (!active) return session && shown && connected && streaming && !busy ? 'keep' : 'stop'
  return !wasActive && session ? 'resume' : 'show'
}

/**
 * The tabs the panel shows for `state` (workbenchState), in order, each with whether it can be opened: 3D (the
 * subject's file), Pictures (Skin Lab and Stage Lab only: a model import is one call, and its one picture, the saved
 * portrait, is on its card) and In game (while a test runs). A game test with nothing else has only In game.
 * -> [[id, label, ready]]
 */
export function workbenchTabs(state) {
  const kind = state?.subject?.kind
  return [
    ...(kind === 'game' ? [] : [['3d', '3D', Boolean(state?.model)]]),
    ...(LAB_KINDS.has(kind) ? [['pictures', 'Pictures', (state.gallery || []).length > 0]] : []),
    ...(state?.game ? [['game', 'In game', true]] : []),
  ]
}

/**
 * Whether the panel opens itself: for an import that wrote its costume while its chat was on screen (`arrival`
 * changed within the same chat), also when the user had hidden the panel. Opening a chat, or the app starting on
 * one, shows what it holds as the panel was left. `last`: {chat, arrival} as the panel last saw them (null at first).
 */
export const opensFor = (last, chatId, arrival) => Boolean(last && arrival && last.chat === chatId
  && last.arrival !== arrival)

// A skin session is named by the costume it came from, never by its code.
function skinTitle(named, character) {
  if (named?.name) return named.name
  return character ? `${character} costume` : 'A costume'
}

const onFighter = (name, character) => character ? `${name} on ${character}` : name

/**
 * @returns {{
 *   subject: {kind: 'costume'|'model'|'stage'|'game', key: string, title: string} | null,
 *   model: {fileId: string, character?: string, stageCode?: string, revision: number, swaps?: object[]} | null,
 *   pictures: {files: {file_id: string, name: string}[], image?: string, seq: number} | null,
 *   gallery: {key: string, file?: object, image?: string, name: string, group: {id, label, subject}}[],
 *   step: {label: string, running: boolean} | null,
 *   game: string | null,
 *   seq: number,
 *   focus: '3d'|'pictures'|'game'|null,
 *   arrival: string | null,
 * }}
 * `model` is what the viewer shows: the subject's newest file (a costume or stage DAT). A model import (`kind`
 * 'model') is a subject only once it wrote its costume file: while it runs, or when it replies without one (it
 * failed, the model came without its textures, its tools are not downloaded, it was stopped), the panel stays as it
 * was. `pictures`, `gallery` and `step` are the labs' only (`LAB_KINDS`): the renders Randall made in Skin Lab and
 * Stage Lab, grouped by the step that made them, and the step under way. `seq` counts changes so the panel can pick a
 * tab when something new arrives; `focus` is that tab. `arrival` names the newest import to become the subject (its
 * key and costume file): the panel opens for one that arrives while the chat is on screen.
 */
export function workbenchState(messages = [], liveGameTool = null) {
  let subject = null, model = null, pictures = null, step = null, seq = 0, focus = null, arrival = null
  // The step-by-step importer of older chats: the model it was on and the entry picked from the user's file.
  let oldImport = null
  // Every lab picture of the whole chat, oldest first, grouped by the step that
  // made it. `pictures` is only the newest batch, and switching subject drops
  // it, so without this an earlier step could no longer be looked at.
  const gallery = [], seen = new Set()
  // What each opened file is, by file id: a vault costume's own name and
  // fighter, so the session editing it can be titled and shown in 3D.
  const named = new Map(), sessions = new Map()
  const tools = messages.flatMap(message => message?.tools || [])
  const studio = studioContext(messages)
  for (const tool of tools) {
    const result = tool?.result || {}
    const name = tool?.name
    if (name === 'open_vault_file' && result.vault_item?.character) {
      for (const file of result.files || []) named.set(file.file_id, { character: result.vault_item.character, name: result.vault_item.name })
    } else if (name === 'open_vanilla_file' && result.character) {
      for (const file of result.files || []) named.set(file.file_id, { character: result.character, name: vanillaName(result.character, result.color) })
    }
    const studioCall = isStudioCall(tool)
    const lab = !studioCall && LAB_TOOLS.has(name)
    if (!studioCall && !lab && !MODEL_TOOLS.has(name)) continue
    const running = tool.status === 'running'
    if (lab && (running || !result.error)) step = { label: result.progress_label
      || phraseForTool(tool)[running ? 'working' : 'done'], running }
    if (running || result.error) continue
    let next = null, dat = null
    if (studioCall || MODEL_TOOLS.has(name)) {
      // A model import: its costume file in 3D, on its fighter. Its pictures stay on its card.
      const file = datOf(result)
      if (studioCall) {
        const id = result.studio_import?.id
        const fighter = studioFighter(tool, studio)
        if (!id || !file || !fighter) continue
        next = { kind: 'model', key: `studio:${id}`, studio: id, character: fighter,
          title: onFighter(studioSubjectName(tool, studio), fighter) }
        dat = { fileId: file.file_id, character: fighter }
      } else {
        // Not every old model step named its source, so one continues the model before it unless its source differs.
        const source = result.source_file_id
        const same = oldImport && (!source || !oldImport.source || source === oldImport.source)
        oldImport = { key: same ? oldImport.key : `model:${source || tool.id}`, source: source || (same ? oldImport.source : undefined),
          entry: result.selected_entry || (same ? oldImport.entry : undefined),
          character: result.character || (same ? oldImport.character : undefined) }
        if (!file || !oldImport.character) continue
        next = { kind: 'model', key: oldImport.key, character: oldImport.character,
          title: onFighter(stem(oldImport.entry) || 'Your model', oldImport.character) }
        dat = { fileId: file.file_id, character: oldImport.character }
      }
      // Opening the costume in Texture Lab keeps the import's name.
      named.set(file.file_id, { character: dat.character, name: next.title })
    } else if (SKIN_TOOLS.has(name) && !result.stage_target) {
      const sid = result.session_id || tool.arguments?.session_id
      if (name === 'skin_lab_open' && sid) sessions.set(sid, named.get(tool.arguments?.file_id) || named.get(result.source_file_id))
      const opened = sessions.get(sid)
      const character = result.skin_target?.character || opened?.character
      // A call that does not say what it edits (a save, a check) keeps the title the session already has.
      const kept = !opened?.name && !character && subject?.key === `skin:${sid}` ? subject.title : null
      if (sid) next = { kind: 'costume', key: `skin:${sid}`, character, title: kept || skinTitle(opened, character) }
      const fileId = result.checkpoint_file?.file_id || (name === 'skin_lab_open' ? result.source_file_id : null)
      if (fileId && character) dat = { fileId, character }
    } else if (STAGE_TOOLS.has(name) || result.stage_target) {
      // (skin_material also edits a Stage Lab session; its result then carries the stage target.)
      const target = result.stage_target
      const sid = result.session_id || tool.arguments?.session_id
      if (sid) next = { kind: 'stage', key: `stage:${sid}`,
        title: target?.name || target?.stage_code || (subject?.key === `stage:${sid}` && subject.title) || 'A stage' }
      if (result.checkpoint_file?.file_id && target?.stage_code) dat = { fileId: result.checkpoint_file.file_id, stageCode: target.stage_code }
    }
    if (next && next.key !== subject?.key) {
      // A different thing: what the last one showed no longer applies.
      subject = next; model = null; pictures = null; seq += 1
      focus = LAB_KINDS.has(next.kind) ? 'pictures' : '3d'
      if (next.kind === 'model') { step = null; arrival = `${next.key}|${viewKey(dat)}` }
    } else if (next) subject = { ...subject, ...next, character: next.character || subject.character }
    if (dat && viewKey(dat) !== viewKey(model)) {
      // An edit that only changed textures says so (`viewer_update`): the view can swap them in place
      // (swapPlan). The chain stays unbroken only while each edit applies on top of the one before.
      const swap = result.viewer_update
      const chained = validSwap(swap) && model?.fileId && swap.from === model.fileId
        && (model.character || '') === (dat.character || '') && (model.stageCode || '') === (dat.stageCode || '')
      model = { ...dat, revision: (model?.revision || 0) + 1,
        ...(chained ? { swaps: [...(model.swaps || []), swap].slice(-MAX_SWAP_CHAIN) } : {}) }
      seq += 1; focus = '3d'
    }
    if (!lab) continue
    const images = pngs(result)
    if (images.length || result.image) {
      pictures = { files: images, image: result.image || null, seq: (pictures?.seq || 0) + 1 }
      seq += 1
      if (!model) focus = 'pictures'
      const group = { id: tool.id, label: phraseForTool(tool).done, subject: subject?.title || '' }
      if (result.image && !seen.has(result.image)) {
        seen.add(result.image)
        gallery.push({ key: `image:${tool.id}`, image: result.image, name: 'Portrait', group })
      }
      for (const file of images) {
        if (seen.has(file.file_id)) continue
        seen.add(file.file_id)
        gallery.push({ key: file.file_id, file, name: file.name, group })
      }
    }
  }
  const game = liveGameTool && tools.some(tool => tool?.id === liveGameTool) ? liveGameTool : null
  if (game) focus = 'game'
  if (!subject && !game) return { subject: null, model: null, pictures: null, gallery: [], step: null, game: null, seq: 0,
    focus: null, arrival: null }
  const labSubject = LAB_KINDS.has(subject?.kind)
  return { subject: subject || { kind: 'game', key: `game:${game}`, title: 'Game test' }, model,
    pictures: labSubject ? pictures : null, gallery: labSubject ? gallery : [], step: labSubject ? step : null,
    game, seq: seq + (game ? 1 : 0), focus, arrival }
}
