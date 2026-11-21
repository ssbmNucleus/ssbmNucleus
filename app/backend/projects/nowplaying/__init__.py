"""Now Playing: when a match starts, a banner with the current song's name
slides in at the top left, holds for four seconds and slides back out (the
idea of the ACE Build's "BGM Display" plugin, implemented clean-room as one
Gecko code).

  now_playing.s        -- the code's source (PowerPC, devkitPPC syntax)
  gen_code.py          -- dev-only: assembles it into code_words.py
  code.py              -- the code's name and its Gecko hex
  previous_versions.py -- the hex of every earlier version, as shipped
  upgrade.py           -- at export, moves a project whose entry is exactly an
                          earlier version to the current hex

New projects get it enabled (projects/install/required_codes.py,
new_project_gecko_codes). See docs/dev/NOW_PLAYING.md.
"""
