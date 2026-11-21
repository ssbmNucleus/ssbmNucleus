"""Small image helpers shared by the vault blueprints."""

import io
import os
from pathlib import Path


def normalized_png(raw, size):
    """Decode an uploaded image and return PNG bytes resized to `size`."""
    from PIL import Image
    img = Image.open(io.BytesIO(raw))
    img.load()
    img = img.convert('RGBA')
    if img.size != size:
        img = img.resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def resolve_asset_png(assets_dir, asset_ref):
    """The .png an exported package's asset reference names ('css\\icon',
    'sss\\icon_048'), else one of that basename at the folder's top, else None."""
    if not asset_ref or not assets_dir.exists():
        return None
    normalized = asset_ref.replace('\\', '/').replace('/', os.sep)
    png_path = assets_dir / f"{normalized}.png"
    if png_path.exists():
        return png_path
    basename = Path(normalized).name
    candidate = assets_dir / f"{basename}.png"
    if candidate.exists():
        return candidate
    return None
