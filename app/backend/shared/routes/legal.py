"""
Legal Blueprint - third-party license notices.

Most of the libraries this app ships (MIT, Ms-PL, Apache-2.0, Zlib) require their
license text and copyright line to reach the user, not just live in the repo.
This serves THIRD_PARTY_NOTICES.md so the Settings > Credits card can display it,
which means the file is the single source of truth -- there is no second copy of
the license text in the frontend to drift out of date.
"""

import logging
import sys
from pathlib import Path

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

legal_bp = Blueprint('legal', __name__)

NOTICES_FILENAME = 'THIRD_PARTY_NOTICES.md'


def _notices_path():
    """Locate THIRD_PARTY_NOTICES.md across dev, PyInstaller, and packaged layouts."""
    candidates = []

    # Frozen: bundled into the PyInstaller archive by mex_backend.spec
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(Path(meipass) / NOTICES_FILENAME)

    # Dev: backend/shared/routes/legal.py -> backend -> app/
    candidates.append(Path(__file__).resolve().parents[3] / NOTICES_FILENAME)

    # Packaged: alongside the executable via electron extraResources
    candidates.append(Path(sys.executable).resolve().parent / NOTICES_FILENAME)

    for p in candidates:
        if p.is_file():
            return p
    return None


@legal_bp.route('/api/legal/notices', methods=['GET'])
def get_notices():
    """Return the third-party notices as markdown text."""
    path = _notices_path()
    if path is None:
        logger.warning('%s not found in any known location', NOTICES_FILENAME)
        return jsonify({
            'error': 'notices file not found',
            'markdown': '',
        }), 404

    try:
        return jsonify({'markdown': path.read_text(encoding='utf-8')})
    except OSError as e:
        logger.error('failed reading %s: %s', path, e)
        return jsonify({'error': str(e), 'markdown': ''}), 500
