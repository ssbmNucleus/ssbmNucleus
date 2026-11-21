// Resolve old receipt folders and newer stage codes against the live catalog.
export function resolveStageNavigation(item, catalog, variants) {
  const stage = catalog.find(stage => item.stageCode ? stage.code === item.stageCode : stage.folder === item.folder)
  if (!stage) throw new Error('This stage is not available in Stage Creator.')
  const variant = variants.find(variant => variant.stageCode === stage.code && variant.id === item.id && variant.type !== 'folder' && variant.visible !== false)
  if (!variant) throw new Error('This stage skin is no longer in the vault.')
  return { stage, variant }
}
