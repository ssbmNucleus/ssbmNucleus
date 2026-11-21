// What the stage picker (StagePicker.jsx) offers and what a stage pick is.
// Pure: no React, no fetch, no backend URL (paths are backend-relative; the
// component turns them into URLs). Extensioned imports so node's test runner loads it.
//
// The stages are `status.recolor_stages` (the Stage Lab's own list, backend
// randall/recolor/stage_lab.supported_stages): {code, name, folder, legal, art}.
// The variants are the Vault's stage list, `GET /api/mex/das/storage/variants`
// (vault/routes/das.py): one row per variant whose archive is on disk, keyed
// `stageCode`, with `id` (the archive's stem), `name`, `hasScreenshot` and
// `screenshotUrl`, plus folder rows (`type: 'folder'`) that are not picks.
//
// A pick: {kind: 'stage', stage: <code>, stageName, id, name, image} for a vault
// variant, {kind: 'stage', stage: <code>, stageName, vanilla: true, name, image}
// for the stock stage. `image` is backend-relative or null.

/** The stages to offer, in the backend's order; malformed rows dropped. */
export function stageRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => row && typeof row.code === 'string' && row.code && typeof row.name === 'string' && row.name)
}

/** One stage's vault variants as picks, in vault order. Folder rows are skipped. */
export function vaultStageVariants(variants, stage) {
  if (!stage?.code) return []
  return (Array.isArray(variants) ? variants : [])
    .filter((row) => row && row.type !== 'folder' && row.stageCode === stage.code && typeof row.id === 'string' && row.id)
    .map((row) => ({
      kind: 'stage', stage: stage.code, stageName: stage.name, id: row.id,
      name: row.name || row.id,
      image: row.hasScreenshot && row.screenshotUrl ? row.screenshotUrl : null,
    }))
}

/** The stock stage as a pick: the game's own stage, pictured by its stage art. */
export function stockStage(stage) {
  if (!stage?.code) return null
  return { kind: 'stage', stage: stage.code, stageName: stage.name, vanilla: true, name: stage.name, image: stage.art || null }
}

/** The grid value of a stage pick: `v:<variant id>` or `s:<stage code>`. */
export function stagePickValue(pick) {
  if (pick?.kind !== 'stage') return ''
  if (pick.vanilla) return `s:${pick.stage}`
  return pick.id ? `v:${pick.id}` : ''
}

/** "Battlefield · Night Sky" or "Battlefield (stock)". */
export function stagePickLabel(pick) {
  if (pick?.kind !== 'stage' || !pick.stage) return ''
  const stage = pick.stageName || pick.stage
  return pick.vanilla ? `${stage} (stock)` : `${stage} · ${pick.name || pick.id}`
}

/** How many vault variants each stage code has (folder rows not counted). */
export function variantCounts(variants) {
  const counts = {}
  for (const row of Array.isArray(variants) ? variants : []) {
    if (row && row.type !== 'folder' && typeof row.stageCode === 'string' && row.id) {
      counts[row.stageCode] = (counts[row.stageCode] || 0) + 1
    }
  }
  return counts
}

/** Grid options for the stages, each badged with its vault variant count. */
export function stageOptions(stages, variants, url = (path) => path) {
  const counts = variantCounts(variants)
  return stageRows(stages).map((stage) => ({
    value: stage.code, label: stage.name, icon: stage.art ? url(stage.art) : undefined,
    ...(counts[stage.code] ? { badge: String(counts[stage.code]) } : {}),
  }))
}

/** Grid options for one stage: its vault variants first, then the stock stage (badged). */
export function variantOptions(vault, stock, url = (path) => path) {
  return [
    ...vault.map((pick) => ({ value: stagePickValue(pick), label: pick.name, icon: pick.image ? url(pick.image) : undefined })),
    ...(stock ? [{ value: stagePickValue(stock), label: stock.name, icon: stock.image ? url(stock.image) : undefined, badge: 'Stock' }] : []),
  ]
}
