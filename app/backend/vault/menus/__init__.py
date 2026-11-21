"""
Menu mods engine: everything about menu mods except the HTTP routes.

The Vault's menu routes (vault/routes/menus/) and the project-side install routes
(projects/routes/menus/) both import from here, never from each other:

    store.py          where the menu mod library lives, catalog and mod.json persistence
    files.py          zip extraction and export, preview pictures, finding MnSlChr / MnSlMap
    hsd.py            the HSDRawViewer command line, retried when the file is in use
    installed.py      the "Currently in MEX" record and its preview snapshots
    icons.py          CSS icon grid mods: alias table, labelling, import
    backgrounds.py    menu background mods (shared CSS/SSS pool): catalog, import
    doors.py          CSS door textures: catalog, import
    pause.py          pause screen (GmPause) mods: catalog, import, texture set
    pause_install.py  write a pause mod into GmPause.usd (also the in-game capture build)
    percent.py        percent font / HUD (IfAll) mods: catalog, categories, import, glyphs
    percent_install.py write a HUD typeface into IfAll.usd, HUD install bookkeeping
    menu_exports.py   cached HSDRawViewer texture exports of a menu file
    menu_pixels.py    picture comparison for the file checks
    menu_checks.py    file checks: is the recorded CSS/SSS/pause mod still in the project
    hud_verify.py     file checks for the HUD slots

Engine modules with a route counterpart share its name (icons, backgrounds, doors,
pause, percent), so the file checks' `from . import pause` reach the engine.
"""
