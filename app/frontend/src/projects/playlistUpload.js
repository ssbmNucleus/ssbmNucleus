/**
 * Bulk (multi-file) upload for music playlists, shared by Menu Music and
 * Stage Music.
 *
 * Uploads run STRICTLY ONE AT A TIME. Each POST re-reads the playlist,
 * appends the new track at an equal share and republishes the whole
 * renormalized list in one workspace save — so two requests in flight would
 * both build on the same pre-upload entries and the second would silently
 * drop the first song. Sequential is the correctness requirement, not a
 * politeness one.
 *
 * One bad file does not stop the batch: every file is attempted, and the
 * caller gets back what landed and what didn't.
 */

// Extension-explicit: this module is loaded directly by node --test, which
// (unlike Vite) does not resolve extensionless specifiers.
import { toUploadableAudio } from '../shared/audio/audioConvert.js'

/** Track name shown in the playlist = the file name without its extension. */
export function trackNameOf(file) {
  return (file?.name || '').replace(/\.[^.]+$/, '')
}

/**
 * POST each file to `url` in order.
 *
 * onProgress({index, total, name}) fires before each upload; onAdded(data)
 * fires after each success with the server's fresh playlist, so the list
 * fills in song by song instead of jumping at the end.
 *
 * Resolves to {added: [name], failed: [{name, error}]} — never rejects.
 */
export async function uploadPlaylistTracks({ files, url, onProgress, onAdded }) {
  const list = Array.from(files || [])
  const added = []
  const failed = []

  for (let index = 0; index < list.length; index++) {
    const file = list[index]
    const name = trackNameOf(file)
    onProgress?.({ index, total: list.length, name })
    try {
      const upload = await toUploadableAudio(file)
      const form = new FormData()
      form.append('file', upload)
      form.append('name', name)
      const token = globalThis.window?.electron?.backendToken
        || new URLSearchParams(globalThis.window?.location?.search || '').get('backendToken')
        || ''
      const headers = token ? { 'X-Nucleus-Token': token } : undefined
      const response = await fetch(url, { method: 'POST', body: form, headers })
      const data = await response.json()
      if (!data.success) throw new Error(data.error || 'Failed to add song')
      added.push(name)
      onAdded?.(data)
    } catch (err) {
      failed.push({ name: name || file?.name || 'song', error: err.message })
    }
  }
  return { added, failed }
}

/** "“a” (reason), “b” (reason), and 2 more" — capped so one bad batch
 *  can't push a 30-song wall of text into the modal. */
function listFailures(failed) {
  const shown = failed.slice(0, 3).map(f => `“${f.name}” (${f.error})`)
  const rest = failed.length - shown.length
  return shown.join(', ') + (rest > 0 ? `, and ${rest} more` : '')
}

/** The message shown after a batch finishes. Single-file wording is
 *  unchanged from when only one file could be picked. */
export function summarizeUpload({ added, failed }) {
  const total = added.length + failed.length
  if (!total) return ''

  if (!failed.length) {
    return added.length === 1 ? `Added “${added[0]}”` : `Added ${added.length} songs`
  }
  if (!added.length) {
    if (failed.length === 1) return `Add failed: ${failed[0].error}`
    const reasons = new Set(failed.map(f => f.error))
    // Whole-batch failures (no project open, backend down) repeat one reason.
    if (reasons.size === 1) return `All ${failed.length} songs failed: ${failed[0].error}`
    return `All ${failed.length} songs failed — ${listFailures(failed)}`
  }
  return `Added ${added.length} of ${total} songs — ${listFailures(failed)}`
}
