"""
The Gecko codes every exported build carries by default (injected before an
export, listed as required by the project Codes routes), and the codes a NEW
project starts with (added once, when the project is created).
"""

import logging

logger = logging.getLogger(__name__)

# Default-on Gecko codes. As of the Slippi update on 2025-10-13, an m-ex build's
# stage-select screen crashes on Slippi Dolphin unless Slippi is told to load the
# SSS from disc instead of injecting its own -- see "$Skip Slippi SSS [KELLZ]" in
# the community Animelee build guide. But the same code crashes some Slippi
# Nintendont (console) setups at stage select (tracker #89), so it is a default,
# not a lock: the user can disable it in the Codes menu. Injected via `mexcli
# add-code`, which skips if a code with the same name already exists -- enabled
# OR disabled -- so a project whose codes.ini carries it disabled keeps it off.
REQUIRED_GECKO_CODES = [
    ("Skip Slippi SSS [KELLZ]",
     "C20166B4 00000016\n"
     "3D808001 618C6204\n"
     "7D8903A6 4E800421\n"
     "7C7E1B78 7C0802A6\n"
     "90010004 9421FF00\n"
     "BE810008 3C60801A\n"
     "60635014 80630000\n"
     "3C804082 60840010\n"
     "7C032000 4182005C\n"
     "80610000 80630000\n"
     "80630000 82830004\n"
     "3C608025 6063A9DC\n"
     "7C141800 41820018\n"
     "3C608025 6063A9EC\n"
     "7C141800 41820008\n"
     "48000028 BA810008\n"
     "80010104 38210100\n"
     "7C0803A6 7FC3F378\n"
     "3D808001 618C66BC\n"
     "7D8903A6 4E800420\n"
     "BA810008 80010104\n"
     "38210100 7C0803A6\n"
     "7FC3F378 00000000\n"
     "C20163F8 00000016\n"
     "3D808001 618C6204\n"
     "7D8903A6 4E800421\n"
     "7C7E1B78 7C0802A6\n"
     "90010004 9421FF00\n"
     "BE810008 3C60801A\n"
     "60635014 80630000\n"
     "3C804082 60840010\n"
     "7C032000 4182005C\n"
     "80610000 80630000\n"
     "80630000 82830004\n"
     "3C608025 6063A9DC\n"
     "7C141800 41820018\n"
     "3C608025 6063A9EC\n"
     "7C141800 41820008\n"
     "48000028 BA810008\n"
     "80010104 38210100\n"
     "7C0803A6 7FC3F378\n"
     "3D808001 618C6400\n"
     "7D8903A6 4E800420\n"
     "BA810008 80010104\n"
     "38210100 7C0803A6\n"
     "7FC3F378 00000000"),
]


# Codes a NEW project starts with, enabled. Unlike REQUIRED_GECKO_CODES these are
# added once, when the project is created, and export never re-adds them: an
# existing project is left as it is, and a user who turns one off or deletes it
# keeps that choice. They are ordinary entries in the project's codes.ini.
def new_project_gecko_codes():
    """[(full header, Gecko hex)] for a project being created."""
    from projects.nowplaying import code as now_playing
    return [(now_playing.CODE_HEADER, now_playing.source())]


def _iso_has_file(iso_path, name):
    from shared.vanilla_extract.vanilla_refs import list_files_in_iso
    return any(e['name'].lower() == name.lower()
               for e in list_files_in_iso(iso_path, contains=name))


def add_new_project_gecko_codes(project_file, source_iso=None):
    """Add new_project_gecko_codes() to a just-created project with `mexcli
    add-code`. Best-effort: a failure is logged and the project is still created.

    A pack that already shows the song name itself (the ACE Build's
    plugins/bgm_display.dat, kept when its m-ex engine is adopted) does not get
    Now Playing, which would draw the name twice.
    """
    import subprocess
    from core import config
    from projects.nowplaying import code as now_playing

    mexcli = config.MEXCLI_PATH
    if not mexcli.exists():
        logger.warning(f"MexCLI not found at {mexcli}; skipping new-project Gecko codes")
        return []
    skip = set()
    if source_iso is not None:
        try:
            if _iso_has_file(source_iso, 'bgm_display.dat'):
                skip.add(now_playing.CODE_HEADER)
                logger.info("[create] source already displays the song name; "
                            "Now Playing not added")
        except Exception as e:
            logger.warning(f"[create] could not check the source ISO for a song display: {e}")
    added = []
    for name, hex_source in new_project_gecko_codes():
        if name in skip:
            continue
        try:
            result = subprocess.run(
                [str(mexcli), 'add-code', str(project_file), name, hex_source],
                capture_output=True, text=True, timeout=60,
                cwd=str(config.PROJECT_ROOT), **config.get_subprocess_args())
            logger.info(f"[create] add-code '{name}' exit={result.returncode} "
                        f"stdout={(result.stdout or '')[:300]}")
            if result.returncode == 0:
                added.append(name)
            elif result.stderr:
                logger.warning(f"[create] add-code '{name}' stderr={result.stderr[:300]}")
        except Exception as e:
            logger.warning(f"[create] could not add Gecko code '{name}': {e}")
    return added
