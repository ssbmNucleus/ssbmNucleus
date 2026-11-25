/**
 * shelfAdd.js - putting a game on Play's shelf (POST /api/play/shelf/add, a shelf_add job in
 * play/adding.py), shared by the export panel (projects/export/IsoBuilder.jsx) and the Vault's
 * Add to Play (vault/hooks/useVaultShelfAdd.js). Pure: the caller hands in api.post / api.get and
 * its confirm dialog, so neither of them imports play/.
 *
 *   startShelfAdd(fields, { cover, post, confirm })  -> the add route's answer ({ job_id })
 *   findSameGame(name, get)                           -> the added game that name would replace, or null
 *
 * A chosen cover picture goes as multipart (`cover`) with the other fields beside it; without one
 * the body is JSON. The backend checks and re-encodes the picture (play/shelf.py encode_cover).
 *
 * An added game with the same name (play/shelf.py same_game: the name as stored, ignoring case)
 * makes the route answer 409 code `already_on_shelf` with that game ({ id, name }). The person is
 * asked whether to replace it: yes posts again with `replace` (its id); no adds nothing and throws
 * an error marked `kept`, which callers show quietly or not at all.
 */

export const SAME_GAME = 'already_on_shelf'
export const COVER_TYPES = 'image/png,image/jpeg,image/gif,image/webp'
// play/shelf.py MAX_COVER_BYTES: checked here too, so a picture is refused when it is chosen,
// not after a long build. The backend still decodes and checks it.
export const MAX_COVER_BYTES = 8 * 1024 * 1024

/** Why a chosen cover picture cannot be used, or null. */
export function coverProblem(file) {
  if (!file) return null
  if (!COVER_TYPES.split(',').includes(file.type)) return 'Choose a PNG, JPEG, GIF or WebP picture.'
  if (file.size > MAX_COVER_BYTES) return 'That picture is too large. The limit is 8 MB.'
  return null
}

/** The add request's body: JSON fields, or a FormData with the cover picture when one was chosen. */
export function shelfAddBody(fields, cover = null) {
  const clean = Object.fromEntries(Object.entries(fields || {}).filter(([, value]) => value != null))
  if (!cover) return clean
  const form = new FormData()
  for (const [key, value] of Object.entries(clean)) form.append(key, String(value))
  form.append('cover', cover)
  return form
}

/** The game an add refusal says is already on the shelf ({ id, name }), or null for any other error. */
export function sameGame(err) {
  const existing = err?.status === 409 && err?.data?.code === SAME_GAME ? err.data.existing : null
  return existing && typeof existing.id === 'string' ? existing : null
}

/** The question asked before a replace. */
export function replaceQuestion(existing, { cover = null } = {}) {
  const kept = cover
    ? 'Its saves and its place on the shelf are kept, with the new cover.'
    : 'Its saves, its cover and its place on the shelf are kept.'
  const running = existing.running ? ' It is running now: close it before the new one is ready.' : ''
  return `"${existing.name}" is already on your Unlocked shelf. Replace it with this one? ${kept} `
    + `The old version is removed.${running}`
}

export const REPLACE_DIALOG = { title: 'Replace game', confirmText: 'Replace', cancelText: 'Keep it' }

function keptError(existing) {
  const err = new Error(`"${existing.name}" was left as it is.`)
  err.kept = true
  err.data = {}
  return err
}

/** Start the add; on "already on the shelf", ask and replace on a yes. Throws what the route threw. */
export async function startShelfAdd(fields, { cover = null, post, confirm }) {
  try {
    return await post('/api/play/shelf/add', shelfAddBody(fields, cover))
  } catch (err) {
    const existing = sameGame(err)
    if (!existing || fields?.replace) throw err
    const yes = await confirm(replaceQuestion(existing, { cover }), REPLACE_DIALOG)
    if (!yes) throw keptError(existing)
    return post('/api/play/shelf/add', shelfAddBody({ ...fields, replace: existing.id }, cover))
  }
}

/** The added game a new one called `name` would replace ({ id, name, running }), or null. */
export async function findSameGame(name, get) {
  const data = await get('/api/play/shelf/same', { query: { name } })
  const existing = data?.existing
  return existing && typeof existing.id === 'string' ? existing : null
}

/**
 * Before a long build (the export panel): ask now rather than after the build. Returns
 * { go: true, replace: id | null } to start, { go: false } when the person kept the old game.
 * A failed lookup starts anyway: the add itself asks again when it finds the same game.
 */
export async function askBeforeShelfAdd(name, { cover = null, get, confirm }) {
  let existing = null
  try {
    existing = await findSameGame(name, get)
  } catch {
    return { go: true, replace: null }
  }
  if (!existing) return { go: true, replace: null }
  const yes = await confirm(replaceQuestion(existing, { cover }), REPLACE_DIALOG)
  return yes ? { go: true, replace: existing.id } : { go: false }
}

/** The done line for an add job's result ({ name, replaced }). */
export function shelfDoneText(result, fallbackName = 'It') {
  const name = result?.name || fallbackName
  return result?.replaced ? `${name} was replaced on your Unlocked shelf.` : `${name} is on your Unlocked shelf.`
}
