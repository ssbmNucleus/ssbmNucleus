"""
The import endpoint's engine (the route is vault/routes/import_unified/routes.py):
turn whatever the user, a website link or Randall hands over into vault mods.

    normalize.py         one entry point: magic-byte sniffing, wrap raw files, convert 7z/RAR
    protocol.py          nucleus:// import links and approved chat downloads
    detection.py         classify an archive or DAT (character, stage, menu, effect, ...)
    effect_detect.py     which extra a modded effect DAT belongs to
    archive.py           import one archive: dispatch to the importers, recurse into
                         container archives; 7z conversion, budgets, error sentences
    characters.py        character costume import, Ice Climbers pairing
    stages.py            stage mod import
    effects.py           effect / model mod import (extras)
    detected_effects.py  the effects detected in an upload, their duplicate check, images
    menu_import.py       menu mods through the endpoint (vault/menus/ does the work)
    dialogs.py           the "what is this?" choice dialogs
    helpers.py           filename sanitizing, DAT hashing, duplicate detection
"""
