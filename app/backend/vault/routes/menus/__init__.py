"""
Menus Blueprint package - Menu mod management (CSS / SSS), vault side.

All routes register on the single `menus_bp` blueprint defined here, split
across cohesive submodules:

    icons.py        CSS icon grid mods (import / edit)
    backgrounds.py  menu background mods (shared CSS/SSS pool)
    doors.py        CSS door textures
    pause.py        pause screen (GmPause) texture mods
    percent.py      percent font / HUD (IfAll) texture mods
    summary.py      per-kind mod counts for the vault's Menus sidebar

Everything that is not a route (storage paths, catalogs, importers, the install
engines, the file checks) is the engine package vault/menus/; route modules
import from it, never from each other.

The project side registers on this same `menus_bp` from projects/routes/menus/:
installing each kind into the open project and restoring vanilla, the "Currently
in MEX" record (installed.py), the CSS and SSS layout editors (layout.py, sss.py)
and the build-change approval card (build_changes.py, the ONLY place an
authorization to write the played build is granted).

`from vault.routes.menus import menus_bp` keeps working exactly as it did when
this was a single menus.py module; the installer API lives in vault/menus/ and
is imported from there.
"""

from flask import Blueprint

menus_bp = Blueprint('menus', __name__)

# Import submodules so their routes register on menus_bp. Order mirrors the
# original single-file layout (icon grid → backgrounds → doors). These imports
# must come after menus_bp is defined.
from . import icons        # noqa: E402,F401
from . import backgrounds  # noqa: E402,F401
from . import doors        # noqa: E402,F401
from . import pause        # noqa: E402,F401
from . import percent      # noqa: E402,F401
from . import summary      # noqa: E402,F401  (vault sidebar counts; imports the others)
# The project side (projects/routes/menus/) adds its routes to menus_bp too.
# Importing it here makes the blueprint complete before anything registers it:
# Flask refuses routes added after registration.
from projects.routes import menus as _project_routes  # noqa: E402,F401

__all__ = ['menus_bp']
