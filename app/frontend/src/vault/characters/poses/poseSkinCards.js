/**
 * The portrait a Generate CSPs card shows (PoseSkinSelectorModal.jsx).
 *
 * 0.9.0 hand-check: the cards went stale. The dialog read the skins once when it opened, so after Generate the cards
 * still showed the old portraits; and rendering a pose again writes the same `<skin>_csp_alt_<N>.png`
 * (core/active_portrait.put_pose_portrait), so even a fresh list gave the same URL and the browser kept its cached
 * picture. The dialog now re-reads the skins after Generate, and each card's URL carries the version of the file it
 * shows: the alternate's timestamp, which put_pose_portrait renews on every rewrite.
 */

/** The ?v= for a skin's shown portrait: its alternate's timestamp, or undefined for the original portrait. */
export function skinCspVersion(skin) {
  const url = skin?.cspUrl
  if (!url) return undefined
  const shown = (skin.alternateCsps || []).find(alt => alt?.url === url)
  return shown?.timestamp || undefined
}
