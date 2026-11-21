/**
 * Publish the Upload page's package to ssbmnucleus.net through the app
 * backend (POST /api/mex/publish). The backend owns the heavy lifting —
 * resolving vault files, files.zip/thumbnails, Supabase RPCs, R2 uploads —
 * because it has the vault on disk and dodges browser CORS entirely.
 * We just ship it the metadata, the local-file blobs, and the screenshots.
 */
import { api, authenticatedFetch } from '../shared/transport/api'
import { getAccessToken } from '../shared/account/account'

const isManualItem = item => String(item.key).startsWith('manual:')

async function fetchBlob(url) {
  const resp = await authenticatedFetch(url)
  if (!resp.ok) throw new Error(`Could not read screenshot (${resp.status})`)
  return resp.blob()
}

/**
 * @param {Object} opts
 * @param {Array}  opts.items       selected catalog items (vault + manual)
 * @param {Array}  opts.screenshots [{url, file?}] in display order (first = cover)
 * @param {string} opts.title
 * @param {string} opts.description
 * @param {Array}  opts.tags        final tag list (routing tags + user tags)
 * @param {boolean} [opts.dryRun]
 * @returns {Promise<{postId, url, status}>}
 */
export async function publishPackage({ items, screenshots, title, description, tags, dryRun = false }) {
  // No site login is fine: the backend publishes with the Discord
  // session instead, and answers 401 when neither exists.
  const accessToken = await getAccessToken()

  const vaultItems = items.filter(item => !isManualItem(item)).map(item => ({
    key: item.key,
    kind: item.kind,
    name: item.name,
    character: item.character || null
  }))

  const form = new FormData()
  form.append('payload', JSON.stringify({
    accessToken,
    title,
    description,
    tags,
    items: vaultItems,
    dryRun
  }))

  items.filter(isManualItem).forEach((item, i) => {
    if (item.file) form.append(`manual_${i}`, item.file, item.filename || item.file.name)
  })

  for (let i = 0; i < screenshots.length; i++) {
    const shot = screenshots[i]
    const blob = shot.file || await fetchBlob(shot.url)
    const name = shot.name || `screenshot_${i}.png`
    form.append(`screenshot_${i}`, blob, name)
  }

  return api.post('/publish', form)
}
