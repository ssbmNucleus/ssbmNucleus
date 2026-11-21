import { api } from '../../shared/transport/api.js'
import { backendMediaUrl } from '../../shared/config/config.js'

export async function downloadPatchFile(patchId) {
  if (!patchId) throw new Error('No completed patch is available to download')
  const path = `/xdelta/download-patch/${encodeURIComponent(patchId)}`
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 10000)
  try {
    // This endpoint keeps the stored patch on HEAD and GET. Check it before
    // handing the download to the browser so HTTP failures reach the UI.
    await api.request(path, { method: 'HEAD', signal: controller.signal })
  } catch (error) {
    if (controller.signal.aborted) throw new Error('Patch download check timed out. Please retry.')
    throw error
  } finally {
    clearTimeout(timeout)
  }
  const link = document.createElement('a')
  link.href = backendMediaUrl(api.url(path))
  link.download = '' // keep the filename supplied by Content-Disposition
  document.body.appendChild(link)
  try { link.click() } finally { link.remove() }
}
