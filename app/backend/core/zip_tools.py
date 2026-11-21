"""ZIP member edits shared by the vault blueprints.

For a rewrite that must never expose a half-written archive, use
``core.atomic_archive.rewrite_zip_atomic`` instead.
"""

import io
import zipfile
from pathlib import Path


def replace_zip_member(zip_path, member, data):
    """Replace or append one member in a zip, preserving all other entries."""
    src = zipfile.ZipFile(zip_path, 'r')
    buf = io.BytesIO()
    replaced = False
    wanted = member.lower()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename.lower() == wanted:
                dst.writestr(item, data)
                replaced = True
            else:
                dst.writestr(item, src.read(item.filename))
        if not replaced:
            dst.writestr(member, data)
    src.close()
    Path(zip_path).write_bytes(buf.getvalue())
