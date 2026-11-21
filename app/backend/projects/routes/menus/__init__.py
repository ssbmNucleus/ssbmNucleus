"""
Menus, project side: the menu mod routes that read or write the open project.

These register on the single `menus_bp` from vault/routes/menus/ (the vault's
menu mod library, which imports this package so the blueprint is complete
before it is registered), so URLs and endpoint names are unchanged:

    icons.py          install a CSS icon grid, one icon per fighter
    backgrounds.py    install a background into the CSS or SSS, CSS status, restore vanilla
    doors.py          install CSS door textures
    pause.py          install a pause screen (GmPause) mod
    percent.py        install a HUD typeface (IfAll), restore vanilla Percent Font / Ready-Go
    installed.py      the "Currently in MEX" record, file checks, preview snapshots
    layout.py         CSS layout editor + fighter icons
    sss.py            SSS layout editor + stage icons
    build_changes.py  the approval card for a build change, and the ONLY place
                      an authorization to write the played build is granted

The shared menu code (paths, catalogs, the HSDRawViewer runner, the install
engines, the file checks) is the engine package vault/menus/.
"""

from . import icons          # noqa: F401
from . import backgrounds    # noqa: F401
from . import sss            # noqa: F401
from . import layout         # noqa: F401
from . import doors          # noqa: F401
from . import pause          # noqa: F401
from . import percent        # noqa: F401
from . import installed      # noqa: F401
# The approval card for a change the assistant proposed (nucleus_api.builds)
# exists only where the assistant does: a stable build carries no nucleus_api.
from core import gates as _gates
if _gates.enabled('assistant'):
    from . import build_changes  # noqa: F401
