"""Shared detection of HSDRawViewer's silent blank render.

Under GPU pressure the renderer sometimes reports success but writes a tiny or
fully transparent PNG (the blank / T-pose failure mode). Two call sites need
exactly this rule — the render pool, which retries the job, and the vault
retake, which refuses to show it in the review grid — so it lives here once.

NOT the same thing as ``vault.importing.iso_scanner._validate_csp_preview``:
that one is a much stricter *content* check (visible-pixel ratio, silhouette
bounding box, solid-frame colour variance) used to decide whether a scanned
costume's thumbnail is good enough to keep. Blank output is a subset of what it
rejects; merging the two would change what an ISO scan accepts.
"""
import os

# Below this size the output PNG cannot be a real portrait (a blank 4x render
# is ~1.7KB; the smallest real SD portrait is >10KB).
MIN_RENDER_BYTES = 2000


def blank_reason(png_bytes: bytes):
    """Why this PNG is a blank render, or None when it looks real.

    Raises whatever PIL raises on an unreadable image — the retake path treats
    that as a failed render and surfaces it, so it must not be swallowed here.
    `file_looks_blank` is the tolerant wrapper for callers that only want a bool.
    """
    if len(png_bytes) < MIN_RENDER_BYTES:
        return f'portrait render came back blank ({len(png_bytes)} bytes)'
    from io import BytesIO

    from PIL import Image
    with Image.open(BytesIO(png_bytes)) as img:
        if 'A' in img.getbands() and img.getchannel('A').getextrema()[1] == 0:
            return 'portrait render came back fully transparent'
    return None


def file_looks_blank(path) -> bool:
    """True when the rendered file is missing, tiny, or fully transparent."""
    if not path or not os.path.exists(path):
        return True
    if os.path.getsize(path) < MIN_RENDER_BYTES:
        return True
    try:
        with open(path, 'rb') as fh:
            return blank_reason(fh.read()) is not None
    except Exception:
        # PIL unavailable or the PNG unreadable: the size gate above already
        # passed, so accept it — the pool's historical behaviour.
        return False
