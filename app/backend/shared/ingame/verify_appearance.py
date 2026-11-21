"""
Appearance evidence for a costume verification (verify_costume.py): the
emulator's rendered area in a captured window, the actor's own pixels from the
paired with/without capture, whether it is clipped, the deterministic per-frame
check, and the contact sheet of every captured pose.
"""

from __future__ import annotations

from pathlib import Path
from core.hashing import sha256_file


# --- appearance measurement ---------------------------------------------------- #

def _rgb(png_bytes):
    """(H, W, 3) int16 array for a PNG, or None when it cannot be read."""
    try:
        import io
        import numpy as np
        from PIL import Image
    except Exception:
        return None
    try:
        return np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"),
                          dtype="int16")
    except Exception:
        return None


def _background_mask(pixels, bg_hex, tol=24):
    import numpy as np
    value = int(str(bg_hex), 16)
    background = np.array([(value >> 16) & 0xFF, (value >> 8) & 0xFF,
                           value & 0xFF], dtype="int16")
    return np.abs(pixels - background).sum(2) <= tol


def render_rect(png_bytes, bg_hex, tol=24, min_share=0.8):
    """The emulator's ACTUAL rendered area inside the captured window.

    PrintWindow grabs the whole Dolphin render window, which is wider than the
    game's 4:3 output: the pillarbox bars are black, not the flat --plain-bg
    fill. So the image rectangle is not the framing, and a model cut off at the
    playfield edge sits ~58 px inside the image where an image-rectangle clip
    test calls it comfortably in frame.

    Measure this on the BACKGROUND pass (fighter and particles hidden), where
    the flat fill is at its most visible. Returns (x0, x1, y0, y1), or None
    when the region found is too small to be the framing -- which is
    `unknown`, never a pass.
    """
    pixels = _rgb(png_bytes)
    if pixels is None:
        return None
    flat = _background_mask(pixels, bg_hex, tol)
    if not flat.any():
        return None
    height, width = flat.shape
    rows, cols = flat.any(1).nonzero()[0], flat.any(0).nonzero()[0]
    rect = (int(cols.min()), int(cols.max()), int(rows.min()), int(rows.max()))
    if (rect[1] - rect[0] + 1) < min_share * width \
            or (rect[3] - rect[2] + 1) < min_share * height:
        return None
    return rect


def clip_state(bbox, rect, edge_px):
    """Is `bbox` cut off by, or in contact with, the rendered area `rect`?

    Contact IS clipping here. An actor whose silhouette reaches the rendered
    boundary has no measurable extent beyond it: the frame cannot show whether
    it stops there or continues for another two hundred pixels, and the camera
    is fixed, so nothing may be widened to find out.
    """
    if not bbox or not rect:
        return None
    x0, x1, y0, y1 = bbox
    rx0, rx1, ry0, ry1 = rect
    margin = max(0, int(edge_px) - 1)
    return bool(x0 <= rx0 + margin or x1 >= rx1 - margin
                or y0 <= ry0 + margin or y1 >= ry1 - margin)


def _hud_mask(shape, hud_frac=(0.36, 0.31)):
    """The damage-percent HUD corner: drawn over the playfield, never the actor."""
    import numpy as np
    height, width = shape
    mask = np.zeros(shape, dtype=bool)
    mask[height - int(height * hud_frac[1]):, :int(width * hud_frac[0])] = True
    return mask


def _dilate(mask, radius):
    import numpy as np
    out = mask.copy()
    for step in range(1, int(radius) + 1):
        out[:-step] |= mask[step:]
        out[step:] |= mask[:-step]
        out[:, :-step] |= mask[:, step:]
        out[:, step:] |= mask[:, :-step]
    return out


def actor_measurement(actor_png, background_png, delivered_png, appearance):
    """The actor's own pixels, derived HERE from the retained measurement pair.

    `frameshot.model_extent` cannot be used for this. It builds the effects
    mask over the whole captured window -- pillarbox bars included -- and
    dilates it by two pixels before subtracting, which deletes exactly the
    actor pixels that sit against the rendered boundary. That is the population
    a clipping test is about, so the test could not see the thing it was for:
    the dragon's idle frame reached x 58..1221 inside a 56..1223 render area
    and was recorded as fully in frame.

    Here everything is restricted to the rendered area FIRST, so the bars are
    never part of any mask and the dilation (one pixel, against antialiasing
    along an effect edge) cannot reach across the boundary. The HUD rectangle
    is excluded and reported, because it is drawn over the playfield and an
    actor behind it is unmeasurable rather than absent.

    Returns a dict with `ok`; when False, `reason` says why the actor could not
    be isolated and the caller must return `unknown`.
    """
    import numpy as np
    background = appearance["background"]
    rect = render_rect(background_png, background)
    out = {"schema": "verify-actor-mask-v1", "render_rect": rect}
    if rect is None:
        return dict(out, ok=False, code="unmeasurable_render_area",
                    reason="the rendered area could not be measured from the "
                           "background pass, so nothing can be judged against "
                           "the declared framing")
    actor_pixels = _rgb(actor_png)
    background_pixels = _rgb(background_png)
    delivered_pixels = _rgb(delivered_png)
    if actor_pixels is None or background_pixels is None or delivered_pixels is None:
        return dict(out, ok=False, code="unresolved_isolation",
                    reason="a capture in the measurement group could not be "
                           "read on this machine (numpy/PIL unavailable, or a "
                           "damaged PNG)")
    if not (actor_pixels.shape == background_pixels.shape == delivered_pixels.shape):
        return dict(out, ok=False, code="unresolved_isolation",
                    reason="the captures in the measurement group are not the "
                           "same size, so they are not the same frame")

    x0, x1, y0, y1 = rect
    inside = np.zeros(actor_pixels.shape[:2], dtype=bool)
    inside[y0:y1 + 1, x0:x1 + 1] = True
    hud = _hud_mask(actor_pixels.shape[:2])
    measurable = inside & ~hud

    foreground = (~_background_mask(actor_pixels, background)) & inside
    effects = (~_background_mask(background_pixels, background)) & inside
    out["foreground_px"] = int(foreground.sum())
    out["effects_px"] = int(effects.sum())
    out["hud_px"] = int((hud & inside).sum())
    rect_area = float((x1 - x0 + 1) * (y1 - y0 + 1))
    out["rect_area"] = rect_area

    # Did hiding the fighter actually do anything? A visibility write that did
    # not take effect leaves the two passes identical, and the difference would
    # then read as "the actor is not drawn".
    if out["effects_px"] >= out["foreground_px"]:
        return dict(out, ok=False, code="unresolved_isolation",
                    reason="hiding the fighter removed nothing from the render, "
                           "so the two passes do not isolate an actor")
    # Effects that cover much of the playfield can hide an overflowing limb, or
    # eat enough of the actor to manufacture "not drawn".
    effects_share = out["effects_px"] / rect_area
    out["effects_share"] = effects_share
    if effects_share > appearance["max_effects_share"]:
        return dict(out, ok=False, code="unresolved_isolation",
                    reason=(f"effects cover {effects_share:.2f} of the rendered "
                            f"area, so the actor cannot be separated from them"))

    mask = foreground & ~_dilate(effects, 1) & measurable
    # WHICH BOUNDARIES CAN BE SEEN AT ALL. An effect sitting on the rendered
    # edge, or the HUD rectangle reaching it, hides whatever the actor does
    # there -- and a visible interior subset cannot certify the whole actor.
    # Measured: an actor deliberately run off the right edge, with effects
    # covering only 2 % of the playfield placed over that edge, came back
    # `clipped: False`.
    hidden = _dilate(effects, 1)
    band = max(1, int(appearance["clip_edge_px"]))
    edges = {
        "left": hidden[y0:y1 + 1, x0:x0 + band],
        "right": hidden[y0:y1 + 1, max(x0, x1 - band + 1):x1 + 1],
        "top": hidden[y0:y0 + band, x0:x1 + 1],
        "bottom": hidden[max(y0, y1 - band + 1):y1 + 1, x0:x1 + 1],
    }
    out["occluded_edges"] = sorted(name for name, strip in edges.items()
                                   if bool(strip.any()))
    px = int(mask.sum())
    out["px"] = px
    out["frac"] = px / rect_area
    if px == 0:
        out["bbox"] = None
        out["clipped"] = False
        return dict(out, ok=True)
    rows, cols = mask.any(1).nonzero()[0], mask.any(0).nonzero()[0]
    bbox = (int(cols.min()), int(cols.max()), int(rows.min()), int(rows.max()))
    out["bbox"] = bbox
    out["w"] = (bbox[1] - bbox[0] + 1) / float(x1 - x0 + 1)
    out["h"] = (bbox[3] - bbox[2] + 1) / float(y1 - y0 + 1)
    out["clipped"] = clip_state(bbox, rect, appearance["clip_edge_px"])
    # A PROVEN lower bound still counts: an actor already touching a visible
    # boundary is clipped whatever else is hidden. It is only "the actor is
    # comfortably inside" that an occluded edge cannot support.
    # THE HUD IS A STANDING LIMITATION OF THIS PROFILE, not a per-frame
    # surprise. The damage percentage occupies a fixed bottom-left rectangle
    # that reaches the left and bottom boundaries on every single frame, so
    # treating it as an occluded edge would make every frame unknown and mean
    # nothing at all. Actor geometry that continues underneath it genuinely
    # cannot be seen, so the adjacency is MEASURED and RECORDED here, and the
    # profile says the corner is not observable. Removing the HUD from the
    # render is the actual fix and belongs in v2.
    out["hud_adjacent"] = bool((mask & _dilate(hud, band) & ~hud).any())
    if out["hud_adjacent"]:
        out["hud_limitation"] = (
            "the actor reaches the damage-HUD rectangle, which is drawn over "
            "the playfield and excluded from the mask: whatever the actor does "
            "underneath it is not observable at this profile's settings")
    # EFFECTS on a boundary are the case that manufactures "fully inside": an
    # actor run off the right edge with effects covering 2 % of the playfield
    # placed over that edge came back `clipped: False`.
    out["extent_observable"] = bool(out["clipped"] or not out["occluded_edges"])
    # Does the DELIVERED frame still contain this actor? The delivered frame
    # has its effects on, so every actor pixel must still be non-background
    # there. This is what catches a measurement taken of a different capture
    # than the one that was saved.
    delivered_foreground = ~_background_mask(delivered_pixels, background)
    absent = int((mask & ~delivered_foreground).sum())
    out["absent_from_delivered_px"] = absent
    out["absent_from_delivered_share"] = absent / float(px)
    if out["absent_from_delivered_share"] > appearance["max_composition_drift"]:
        return dict(out, ok=False, code="composition_drift",
                    reason=(f"{out['absent_from_delivered_share']:.2%} of the "
                            f"measured actor is not present in the delivered "
                            f"frame: the measurement and the saved image are "
                            f"different captures"))
    return dict(out, ok=True)


def measure_capture(png_path, appearance, recorded=None, folder=None):
    """Deterministic appearance check for ONE captured frame.

    `recorded` is the measurement group frameshot took at the profile camera:
    the delivered frame, the particle-hidden actor pass, the fighter-hidden
    background pass, the game-frame counter bracketing all three, and the
    camera words read back before and after. Only a group that held together is
    measured; anything else is `unknown`.

    A successful screenshot call is never a pass.
    """
    row = {"path": str(png_path), "status": "unknown", "reason": "",
           "measurement": None, "source": None, "code": "unresolved_isolation"}
    path = Path(png_path)
    folder = Path(folder) if folder else path.parent
    if not path.is_file():
        row["code"] = "capture_missing"
        row["reason"] = "the capture file does not exist"
        return row
    try:
        delivered = path.read_bytes()
    except OSError as exc:
        row["code"] = "capture_unreadable"
        row["reason"] = f"unreadable capture: {exc}"
        return row

    recorded = recorded or {}
    if recorded.get("reframed"):
        row["code"] = "camera_moved"
        row["reason"] = ("the camera moved after the capture; this frame is "
                         "outside the declared profile and cannot be graded")
        return row
    if not recorded.get("group_consistent"):
        row["code"] = "unstable_group"
        row["measurement"] = {k: recorded.get(k) for k in
                              ("settled", "settle_grabs", "game_before",
                               "game_after", "camera_before", "camera_after",
                               "group_consistent")}
        row["reason"] = ("no measurement group held together for this frame "
                         "(the screen never settled, the camera moved, or the "
                         "game advanced between the captures), so the saved "
                         "image is not attributable to the declared camera")
        return row

    pair = {}
    for key, field in (("actor", "actor_file"), ("background", "background_file")):
        name = recorded.get(field)
        target = folder / name if name else None
        if target is None or not target.is_file():
            row["code"] = "measurement_pair_missing"
            row["reason"] = (f"the {key} pass of the measurement group was not "
                             f"retained, so the actor cannot be isolated")
            return row
        pair[key] = target

    row["source"] = "actor isolated from the retained measurement pair"
    measured = actor_measurement(pair["actor"].read_bytes(),
                                 pair["background"].read_bytes(),
                                 delivered, appearance)
    measured["actor_file"] = pair["actor"].name
    measured["background_file"] = pair["background"].name
    measured["actor_sha256"] = sha256_file(pair["actor"])
    measured["background_sha256"] = sha256_file(pair["background"])
    measured["game_frame"] = recorded.get("game_before")
    measured["camera"] = recorded.get("camera_before")
    row["measurement"] = measured
    if not measured.get("ok"):
        row["code"] = measured.get("code", "unresolved_isolation")
        row["reason"] = measured.get("reason", "the actor could not be isolated")
        return row

    frac = measured["frac"]
    if frac < appearance["min_actor_frac"]:
        row["status"] = "fail"
        row["code"] = "actor_not_drawn"
        row["reason"] = (f"the actor is not drawn at the profile camera: "
                         f"{measured['px']} pixels ({frac:.5f} of the rendered "
                         f"area)")
        return row
    if frac > appearance["max_actor_frac"]:
        row["status"] = "fail"
        row["code"] = "gross_overflow"
        row["reason"] = (f"gross overflow: the actor covers {frac:.3f} of the "
                         f"rendered area")
        return row
    if measured["clipped"]:
        # NOT a verdict on the costume. "Leaves the declared framing" is an
        # evidence-usability check: the frame does not show the actor's full
        # extent, and the camera is fixed, so nothing may be widened to find
        # out. Without a same-fighter vanilla control at this exact camera
        # there is no way to tell "this costume is too big" from "this camera
        # is too tight for this fighter" -- the accepted Pikachu fit clips on
        # jab frames 2 and 3 at this distance, and it is a known-good costume.
        # The real extent rule (root-relative spans against the fighter's own
        # vanilla reference) belongs in a v2 profile with those controls.
        row["status"] = "unknown"
        row["code"] = "insufficient_framing"
        row["reason"] = ("the actor reaches the rendered boundary at the "
                         f"declared camera (actor {measured['bbox']} against "
                         f"rendered area {measured['render_rect']}), so this "
                         f"frame does not show its full extent. Without a "
                         f"same-fighter vanilla control at this camera the "
                         f"clipping cannot be attributed to the costume")
        return row
    if not measured.get("extent_observable", True):
        # A visible interior subset cannot certify the whole actor.
        row["status"] = "unknown"
        row["code"] = "unobservable_boundary"
        row["reason"] = ("effects or the HUD sit on the "
                         + ", ".join(measured["occluded_edges"])
                         + " boundary of the rendered area, so whether the "
                           "actor reaches it there cannot be seen; an actor "
                           "that is visibly inside everywhere else is still "
                           "not established as fully in frame")
        return row
    row["status"] = "pass"
    row["code"] = "in_frame"
    row["reason"] = "the actor is fully inside the declared framing"
    return row


def contact_sheet(images, target, columns=4, cell=320):
    """Tile the captures into one labelled image, so every pose is looked at."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    tiles = [p for p in images if Path(p).is_file()]
    if not tiles:
        return None
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell, rows * (cell + 18)), (18, 24, 34))
    draw = ImageDraw.Draw(sheet)
    for position, path in enumerate(tiles):
        x, y = (position % columns) * cell, (position // columns) * (cell + 18)
        try:
            with Image.open(path) as tile:
                tile = tile.convert("RGB")
                tile.thumbnail((cell - 8, cell - 8))
                sheet.paste(tile, (x + 4, y + 4 + (cell - 8 - tile.height) // 2))
        except OSError:
            draw.text((x + 6, y + 6), "unreadable", fill=(200, 120, 120))
        draw.text((x + 6, y + cell + 2), Path(path).stem[:44], fill=(140, 200, 255))
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, format="PNG")
    return str(target)
