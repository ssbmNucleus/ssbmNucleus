"""
The table of texture extras that ride inside a sibling color extra's editor
(SIBLING_TEXTURE_EXTRAS). Extras are patched into a project when they are
installed, never at export time.
"""

# Sibling texture extras: some `type: "texture"` extras (textures.py) have no
# standalone editor card -- their color control is NESTED inside a sibling
# color extra's modal under a fixed modification key (e.g. Fox/Falco's
# UpBEditorModal ships an extra "Fire Texture" ColorPicker alongside the
# `upb` extra's own layers; C. Falcon's DualColorEditorModal does the same
# for `falcon_punch`). This maps sibling_extra_id -> (nested key,
# texture_extra_id) so install/restore-vanilla can apply both, generically,
# instead of hardcoding a single 'fire'/'upb_texture' special case (task #12
# migration, 2026-07-02 -- punch_texture had NO wiring here before, meaning
# any saved fire-texture color on a falcon_punch mod silently never applied).
SIBLING_TEXTURE_EXTRAS = {
    'upb': ('fire', 'upb_texture'),
    'falcon_punch': ('fire', 'punch_texture'),
}
