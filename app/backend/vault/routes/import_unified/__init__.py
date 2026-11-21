"""
Import Unified Blueprint package - Unified file import endpoint.

Handles importing both character costumes and stage mods from ZIP/7z files,
with auto-detection and slippi safety validation.

The one route, /api/mex/import/file, is routes.py and registers on the
`import_bp` blueprint defined here. The import engine behind it (detection,
normalization, the per-kind importers, archive dispatch) is
vault/importing/unified/.

`from vault.routes.import_unified import import_bp` keeps working exactly as it
did when this was a single import_unified.py module; the helper API lives in
vault/importing/unified/ and is imported from there.
"""

from flask import Blueprint

import_bp = Blueprint('import', __name__)

# Import route module so its routes register on import_bp. This import must
# come after import_bp is defined.
from . import routes  # noqa: E402,F401

__all__ = ['import_bp']
