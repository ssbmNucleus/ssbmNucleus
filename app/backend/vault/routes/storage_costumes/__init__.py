"""
Storage Costumes Blueprint - Storage vault costume operations.

All routes register on the single `storage_costumes_bp` blueprint defined here,
split by purpose:

    library.py   the costume grid's metadata, list, delete, rename
    csp.py       character select portraits: upload, HD capture, alternates,
                 re-render from a pose, batch retake
    stock.py     stock icons: upload, generate
    slippi.py    the Slippi safety check: retest, override
    order.py     ordering and folders
    animelee.py  detecting Animelee (outline) costumes and filing them

`from vault.routes.storage_costumes import storage_costumes_bp` keeps working
exactly as it did when this was a single storage_costumes.py module. Non-route
code: the CSP frame is shared/rendering/csp_frame.py, skin folders
vault/catalog/costume_folders.py.
"""

from flask import Blueprint

from core.config import PROCESSOR_DIR, SERVICES_DIR

import sys
sys.path.insert(0, str(PROCESSOR_DIR))
sys.path.insert(0, str(SERVICES_DIR))


storage_costumes_bp = Blueprint('storage_costumes', __name__)

# Import the route modules so their routes register on storage_costumes_bp.
# These imports must come after storage_costumes_bp is defined (and after the
# sys.path entries above: csp.py renders portraits, slippi.py loads dat_processor).
from . import library   # noqa: E402,F401
from . import csp       # noqa: E402,F401
from . import stock     # noqa: E402,F401
from . import slippi    # noqa: E402,F401
from . import order     # noqa: E402,F401
from . import animelee  # noqa: E402,F401
