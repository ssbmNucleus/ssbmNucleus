"""
Extras engine: per-character effect mods (colors, models, textures), everything
except the HTTP routes in vault/routes/extras/.

    helpers.py          the configuration init_extras_api() sets (storage root, project
                        files, HSDRawViewer) and the vanilla-reference comparisons that
                        need it: write safety, resolved current colors, recolor status,
                        restoring vanilla color bytes; find_dat_file
    offsets.py          where each effect's colors live in a DAT (scanned, cached)
    color_read.py       reading an effect's current colors and the vanilla/custom verdict
    color_patch.py      writing effect colors (the generic hex patcher, shine slots,
                        sparkle, model TEV colors) and the offset guard / mask spans
    derive.py           remaking an extra's modifications from a modded DAT
    apply.py            applying every selected extra to a project at export time
    relocate.py         offset relocation and the vanilla-byte guard
    textures.py         hue-shift texture extras (HSDRawViewer export/import)
    texture_recolor.py  raw texel / palette recolors (charge ball, EfCo fire)
    texture_region.py   whole-texture byte replacement (the shield bubble)
    effect_model.py     image effect models (Fox/Falco image shines)
    models.py           model extract / import through HSDRawViewer
    unit_parts.py       extras that own parts of another extra's file

Modules with a route counterpart keep its name (effect_model, models), so the
engine's `from . import effect_model` reaches the engine.
"""
