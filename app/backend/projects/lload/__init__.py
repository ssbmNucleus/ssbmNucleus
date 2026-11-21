"""L-load: on the character select screen, tapping L scrolls a player through
their fighter's group of alternates (Luigi -> Luigi & Boo -> Dr. Luigi -> Luigi).

  groups.py  -- the project's groups (`nucleus_lload.json`, by fighter name) and
                resolving them to the build's external ids
  layout.py  -- "tucked" icons: each alternate's CSS icon hidden behind its base
  code.py    -- the per-project Gecko code (fixed words + the group table)
  export.py  -- the export step that applies both, and the remove-fighter repair

The mechanism, the in-game evidence and the design are in docs/dev/L_LOAD.md.
"""
