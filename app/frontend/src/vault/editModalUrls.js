export function toAbsoluteMediaUrl(url, backendBase) {
  if (typeof url !== 'string') return url
  return url.startsWith('/') ? `${backendBase}${url}` : url
}

export function resolveDisplayCspUrl(data, backendBase) {
  if (!data) return null

  if (data.active_csp_id && data.alternateCsps) {
    const activeAltHd = data.alternateCsps.find(
      alt => alt.poseName && alt.isHd &&
      data.alternateCsps.some(
        other => other.id === data.active_csp_id && other.poseName === alt.poseName
      )
    )
    if (activeAltHd) return toAbsoluteMediaUrl(activeAltHd.url, backendBase)

    const activeAlt = data.alternateCsps.find(alt => alt.id === data.active_csp_id)
    if (activeAlt) return toAbsoluteMediaUrl(activeAlt.url, backendBase)
  }

  if (data.has_hd_csp) {
    const hdUrl = data.hdCspUrl || data.cspUrl?.replace('_csp.png', '_csp_hd.png')
    return toAbsoluteMediaUrl(hdUrl, backendBase)
  }
  return toAbsoluteMediaUrl(data.cspUrl, backendBase)
}

/** The just-retaken portrait the modal should keep showing instead of the
 * vault file: `appliedCsp` is only honoured while its stamp is still the live
 * cache-buster, so any later image write (a stock generate, a Portraits swap)
 * retires it and the URL takes over again. Returns null when there is none. */
export function heldPortraitSrc(appliedCsp, lastImageUpdate) {
  if (!appliedCsp || !appliedCsp.dataUri) return null
  return appliedCsp.stamp === lastImageUpdate ? appliedCsp.dataUri : null
}
