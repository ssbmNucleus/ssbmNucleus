"""
Extras API - Character effect color modifications (lasers, side-B, shine, etc.),
3D model replacements, and hue-shifted textures.

Route modules (all register on `extras_bp`):
- colors.py:         the stored color extras library (list, create, delete)
- models.py:         model extras (create, install, delete)
- texture_routes.py: hue-shift textures, raw texel recolors and whole-texture
                     region mods
- effect_model.py:   the effect image PNG (Fox/Falco image shines)

Color extras in the open project (current colors, install, restore vanilla) are
projects/routes/extras.py, which adds its routes to this blueprint; the last
line of this module imports it.

Everything that is not a route is the engine package vault/extras/ (the
configuration set by vault.extras.helpers.init_extras_api, offset detection,
color reading and patching, the texture engines, image effect models, unit
parts).
"""

from flask import Blueprint

# Blueprint for extras routes (same blueprint name as the old extras_api module)
extras_bp = Blueprint('extras', __name__)

# Import submodules so their routes register on extras_bp
from . import colors  # noqa: E402,F401
from . import models  # noqa: E402,F401
from . import texture_routes  # noqa: E402,F401
from . import effect_model  # noqa: E402,F401

__all__ = ['extras_bp']

# The project half (color extras in the open project: current colors, install,
# restore vanilla) lives in projects/routes/extras.py and adds its routes to
# extras_bp. Importing it here makes the blueprint complete before anything
# registers it: Flask refuses routes added after registration.
from projects.routes import extras as _project_routes  # noqa: E402,F401
