"""
The character select portrait frame: the SD and HD CSP sizes, cropping a picture
to the 136:188 aspect, and deriving both portraits from one source image.
"""


# Vanilla CSP texture size; HD previews are capped at 4x that
CSP_SD_SIZE = (136, 188)
CSP_HD_SIZE = (544, 752)


def crop_to_csp_aspect(img):
    """Center-crop a PIL image to the CSP's 136:188 aspect (no distortion).

    Every portrait in the vault shares that frame, so an off-ratio upload is
    cropped to it rather than letterboxed or stretched."""
    width, height = img.size
    target = CSP_SD_SIZE[0] / CSP_SD_SIZE[1]
    if abs(width / height - target) < 1e-3:
        return img
    if width / height > target:          # too wide: trim the sides
        new_w = max(1, round(height * target))
        left = (width - new_w) // 2
        return img.crop((left, 0, left + new_w, height))
    new_h = max(1, round(width / target))  # too tall: trim top/bottom
    top = (height - new_h) // 2
    return img.crop((0, top, width, top + new_h))


def derive_csp_versions(image_bytes):
    """Derive (sd_png_bytes, hd_png_bytes_or_None) from one uploaded image.

    The source is center-cropped to the CSP's 136:188 aspect first. SD is
    always exactly 136x188 (the vanilla texture size). The HD preview is kept
    only when the cropped source is at least ~2x the SD size -- upscaling a
    small image would just make a blurry "HD" -- and is capped at 4x (544x752).
    """
    from io import BytesIO
    from PIL import Image

    with Image.open(BytesIO(image_bytes)) as src:
        img = crop_to_csp_aspect(src.convert('RGBA'))

    width, height = img.size

    sd = img if img.size == CSP_SD_SIZE else img.resize(CSP_SD_SIZE, Image.LANCZOS)
    sd_buf = BytesIO()
    sd.save(sd_buf, format='PNG')

    hd_bytes = None
    if width >= CSP_SD_SIZE[0] * 2 and height >= CSP_SD_SIZE[1] * 2:
        hd = img.resize(CSP_HD_SIZE, Image.LANCZOS) if (width > CSP_HD_SIZE[0] or height > CSP_HD_SIZE[1]) else img
        hd_buf = BytesIO()
        hd.save(hd_buf, format='PNG')
        hd_bytes = hd_buf.getvalue()

    return sd_buf.getvalue(), hd_bytes
