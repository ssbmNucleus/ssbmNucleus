/**
 * The question a nucleus://import link asks before anything is downloaded (security review 11-19, L2).
 *
 * Any web page can open nucleus://import?url=<https file>, so the window names the site the file comes from and
 * waits for the person to agree before the download is queued. ssbmnucleus.net's own install buttons ask too: the
 * link cannot prove which page opened it.
 */
export const OWN_SITE = 'ssbmnucleus.net'

function hostOf(url) {
  try {
    return new URL(url).host.toLowerCase()
  } catch {
    return ''
  }
}

export function isOwnSite(host) {
  return host === OWN_SITE || host.endsWith(`.${OWN_SITE}`)
}

/** {host, title, message} for an import link's payload, or null when it names no usable URL. */
export function importLinkQuestion({ url, title, name } = {}) {
  const host = hostOf(url)
  if (!host) return null
  const label = String(title || name || '').trim() || 'this file'
  const where = isOwnSite(host) ? `the SSBM Nucleus website (${host})` : host
  const warning = isOwnSite(host) ? '' : ` ${host} is not the SSBM Nucleus website.`
  return {
    host,
    title: 'Import from a website?',
    message: `A web page asked Nucleus to download "${label}" from ${where} into your vault.${warning} `
      + 'Continue only if you just clicked an install button on a site you trust.',
  }
}

/** Ask the person about one import link. -> true to download. `confirm(message, options)` is appConfirm. */
export async function confirmImportLink(data, confirm) {
  const question = importLinkQuestion(data)
  if (!question) return false
  try {
    return (await confirm(question.message, {
      title: question.title, confirmText: 'Import', cancelText: 'Cancel', confirmStyle: 'primary',
    })) === true
  } catch {
    return false
  }
}
