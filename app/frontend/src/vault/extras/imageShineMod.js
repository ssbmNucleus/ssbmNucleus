/**
 * Is a stored extras mod an IMAGE mod rather than a color mod?
 *
 * The Fox/Falco shine holds both kinds in one list (they patch the same
 * effect model), so every place that renders a mod -- the card preview, the
 * editor -- has to ask. This mirrors `effect_model.is_image_mod` on the
 * backend, including the older shape: mods imported before the image format
 * existed carry no `format`, and are recognized by the `image` key the
 * derive/heal path writes into `modifications`.
 */
export function isImageShineMod(mod) {
  if (!mod) return false
  return mod.format === 'effect_model' || mod.type === 'effect_model'
    || !!mod.modifications?.image
}

/** Does this extra type support image mods at all? (config-driven, not by id) */
export function supportsImageMod(extraType) {
  return !!extraType?.imageModel
}
