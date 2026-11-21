"""Melee-derived UI sprites for nucleOME, extracted straight from the user's
vanilla ISO -- no emulator, no bundled game art.

Two sprite sets, both read from DAT files with the pure-Python HSD reader in
shared.rendering.datprobe:

  * randall -- the Yoshi's Story cloud (GrSt.dat map_head model group 2).
    Its three 64x64 CMPR face textures (default + two blink frames) come from
    the group's texture-swap material animation, along with the decoded
    151-key blink track (frame -> texture index) so the UI can reproduce the
    exact in-game blink rhythm.

  * shine -- Fox/Falco's Reflector (EfFxData.dat effect table; Falco shares
    Fox's effect bank). The hexagon carries NO textures: it is raw GX
    geometry with per-vertex RGBA6 colors modulated by an ice-blue material
    diffuse, animated by FOBJ tracks. We parse the display lists and key
    buffers and rasterize each animation frame to a transparent PNG:
      - model 0 = the held-down-B loop (efSync id 1160): a 6-frame scale
        pulse stepping the hexagon ring through three sizes.
      - model 2 = the reflect flash (efSync id 1162): 3 triangles snapping
        60 degrees every 2 frames over a 12-frame loop (the hexagram
        flicker). Decomp ground truth: ftFx_SpecialLw.c -> efalt.c cases
        0x488/0x48A -> internal ids 3000/3002 -> table entries 0/2.

Everything is derived lazily into STORAGE_PATH/nucleome/sprites/ from the
recorded vanilla ISO (vanilla_refs), the same self-healing pattern the extras
write-safety references use: first-run setup warms it, existing installs
derive on first API request.
"""

import json
import logging
import math
import struct
import threading
from pathlib import Path

import file_retry
from core.config import STORAGE_PATH
from shared.rendering.datprobe import DatFile, decode_image, save_png
from shared.vanilla_extract import vanilla_refs

logger = logging.getLogger(__name__)

# bump when the derivation output changes so existing installs regenerate
SPRITES_VERSION = 1

SHINE_SIZE = 256        # rendered sprite edge in px
_SUPERSAMPLE = 4        # rasterize at N x and downscale for clean edges

_derive_lock = threading.Lock()


def sprites_dir(storage_path=None) -> Path:
    return Path(storage_path or STORAGE_PATH) / "nucleome" / "sprites"


# --------------------------------------------------------------------------- #
# FOBJ key decoding (ported from HSDRaw FOBJ_Decoder / FOBJ_Player)            #
# --------------------------------------------------------------------------- #
def _read_packed(buf, p):
    """7-bit little-endian varint."""
    result = shift = 0
    while True:
        b = buf[p]; p += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            return result, p


def _parse_val(buf, p, flag):
    """One key value: format in the flag's top 3 bits, 1/2^shift scale below."""
    fmt, scale = flag & 0xE0, float(1 << (flag & 0x1F))
    if fmt == 0x00:
        return struct.unpack_from('<f', buf, p)[0], p + 4
    if fmt == 0x20:
        return struct.unpack_from('<h', buf, p)[0] / scale, p + 2
    if fmt == 0x40:
        return struct.unpack_from('<H', buf, p)[0] / scale, p + 2
    if fmt == 0x60:
        return struct.unpack_from('<b', buf, p)[0] / scale, p + 1
    if fmt == 0x80:
        return buf[p] / scale, p + 1
    raise ValueError(f"unknown FOBJ value format 0x{fmt:02X}")


def _decode_fobj(dat, off):
    """FOBJDesc at data offset `off` -> (track_type, [key dicts]).
    Track type is at +0x0C, value/tangent flags at +0x0D/+0x0E (HSD_FOBJDesc)."""
    ttype = dat.raw[0x20 + off + 0x0C]
    vflag = dat.raw[0x20 + off + 0x0D]
    tflag = dat.raw[0x20 + off + 0x0E]
    length = dat.u32(off + 4)
    buf_off = dat.ptr(off + 0x10)
    if ttype == 40 or buf_off is None:      # HSD_A_J_PTCL: opaque particle ref
        return ttype, []
    buf = dat.raw[0x20 + buf_off: 0x20 + buf_off + length]
    keys = []
    clock = 0.0
    p = 0
    while p < len(buf):
        typ, p = _read_packed(buf, p)
        interp = typ & 0x0F                 # GXInterpolationType
        n = (typ >> 4) + 1
        if interp == 0:
            break
        for _ in range(n):
            val = tan = 0.0
            t = 0
            if interp in (1, 2, 3):         # CON / LIN / SPL0
                val, p = _parse_val(buf, p, vflag)
                t, p = _read_packed(buf, p)
            elif interp == 4:               # SPL
                val, p = _parse_val(buf, p, vflag)
                tan, p = _parse_val(buf, p, tflag)
                t, p = _read_packed(buf, p)
            elif interp == 5:               # SLP
                tan, p = _parse_val(buf, p, tflag)
            elif interp == 6:               # KEY
                val, p = _parse_val(buf, p, vflag)
            keys.append({"frame": clock, "value": val, "tan": tan,
                         "interp": interp})
            clock += t
    return ttype, keys


def _track_value(keys, frame, default=0.0):
    """Evaluate a decoded track at `frame` (port of FOBJ_Player.GetValue)."""
    if not keys:
        return default
    if len(keys) == 1 or frame <= keys[0]["frame"]:
        return keys[0]["value"]
    if frame >= keys[-1]["frame"]:
        return keys[-1]["value"]
    hi = next(i for i, k in enumerate(keys) if k["frame"] > frame)
    p0 = p1 = d0 = d1 = t0 = t1 = 0.0
    last_op = op = 1
    for i in range(hi + 1):
        k = keys[i]
        op = k["interp"]
        if op in (1, 2):
            p0 = p1; p1 = k["value"]
            if last_op != 5:
                d0 = d1; d1 = 0.0
            t0 = t1; t1 = k["frame"]
        elif op == 3:
            p0 = p1; d0 = d1; p1 = k["value"]; d1 = 0.0
            t0 = t1; t1 = k["frame"]
        elif op == 4:
            p0 = p1; d0 = d1; p1 = k["value"]; d1 = k["tan"]
            t0 = t1; t1 = k["frame"]
        elif op == 5:
            d0 = d1; d1 = k["tan"]
        elif op == 6:
            p0 = p1 = k["value"]
        last_op = op
    if frame <= t0:
        return p0
    if frame >= t1:
        return p1
    if t0 == t1 or last_op in (1, 6):
        return p0
    time = frame - t0
    fterm = t1 - t0
    if last_op == 2:
        return p0 + (p1 - p0) / fterm * time
    inv = 1.0 / fterm                        # Hermite spline (SPL/SPL0/SLP)
    fv1 = time * time
    fv2 = inv * inv * fv1 * time
    fv3 = 3.0 * fv1 * inv * inv
    fv4 = fv2 - fv1 * inv
    fv2 = 2.0 * fv2 * inv
    return (d1 * fv4 + d0 * (time + (fv4 - fv1 * inv))
            + p0 * (1.0 + (fv2 - fv3)) + p1 * (-fv2 + fv3))


# --------------------------------------------------------------------------- #
# Randall (GrSt.dat)                                                           #
# --------------------------------------------------------------------------- #
_RANDALL_GROUP = 2   # vanilla GrSt.dat map_head model group for the cloud


def _derive_randall(dat, out_dir):
    """Decode the cloud's face textures + blink track. Returns manifest dict."""
    map_head = dict(dat.roots).get("map_head")
    if map_head is None:
        raise ValueError("GrSt.dat has no map_head root")
    groups_off = dat.ptr(map_head + 0x08)
    group_count = dat.u32(map_head + 0x0C)
    if not (0 <= _RANDALL_GROUP < group_count):
        raise ValueError(f"map_head has {group_count} groups")
    gobj = groups_off + _RANDALL_GROUP * 0x34   # SBM_Map_GOBJ stride

    # texture-swap animation: MaterialAnimations null-terminated pointer array
    matanim_arr = dat.ptr(gobj + 0x08)
    images, blink_keys = [], []
    idx = 0
    while matanim_arr is not None:
        maj = dat.ptr(matanim_arr + idx * 4)
        idx += 1
        if maj is None:
            break
        for ta in dat.matanim_texanims(maj):
            if len(ta.images) > len(images):
                images = ta.images
        # blink timing: the TexAnim AOBJ's image-index FOBJ (HSD_A_T_TIMG=1)
        for joint in dat._iter_tree(maj, 0x00, 0x04):
            ma = dat.ptr(joint + 0x08)
            while ma is not None and not blink_keys:
                ta = dat.ptr(ma + 0x08)
                while ta is not None and not blink_keys:
                    aobj = dat.ptr(ta + 0x08)
                    fobj = dat.ptr(aobj + 8) if aobj is not None else None
                    while fobj is not None:
                        ttype, keys = _decode_fobj(dat, fobj)
                        if ttype == 1 and keys:
                            blink_keys = keys
                            break
                        fobj = dat.ptr(fobj + 0x00)
                    ta = dat.ptr(ta + 0x00)
                ma = dat.ptr(ma + 0x00)
    if not images:
        raise ValueError("no texture-swap frames found for Randall's group")

    frames = []
    for i, img in enumerate(images):
        name = f"randall_face{i}.png"
        save_png(decode_image(img), out_dir / name)
        frames.append(name)
    # CON-interpolated index track: [frame, texture index] pairs
    track = [[round(k["frame"], 3), int(round(k["value"]))] for k in blink_keys]
    return {
        "frames": frames,
        "width": images[0].width,
        "height": images[0].height,
        "blink_track": track,
        "blink_loop_frames": track[-1][0] if track else 0,
    }


# --------------------------------------------------------------------------- #
# Shine (EfFxData.dat)                                                         #
# --------------------------------------------------------------------------- #
def _effect_model_geometry(dat, model_idx):
    """Triangles of an effect-table model's child JOBJ as
    [((x,y,z), (r,g,b,a)), ...] triples, vertex colors modulated by the
    material diffuse. Only handles the shine's vertex layout: POS INDEX8 s16
    + CLR0 DIRECT RGBA6 (asserted)."""
    root_off = dat.roots[0][1]
    moff = root_off + 8 + model_idx * 0x14   # SBM_EffectModel stride
    rj = dat.ptr(moff + 4)
    child = dat.ptr(rj + 0x08)

    def f32(off):
        return struct.unpack_from('>f', dat.raw, 0x20 + off)[0]

    def s16(off):
        return struct.unpack_from('>h', dat.raw, 0x20 + off)[0]

    base_scale = (f32(child + 0x20), f32(child + 0x24), f32(child + 0x28))
    triangles = []
    dobj = dat.ptr(child + 0x10)
    while dobj is not None:
        dif = (255, 255, 255, 255)
        mobj = dat.ptr(dobj + 0x08)
        if mobj is not None:
            matp = dat.ptr(mobj + 0x0C)
            if matp is not None:
                dif = tuple(dat.raw[0x20 + matp + 4: 0x20 + matp + 8])
        pobj = dat.ptr(dobj + 0x0C)
        while pobj is not None:
            attrs = []
            a = dat.ptr(pobj + 0x08)
            while True:
                name = dat.u32(a)
                if name == 0xFF:                     # GX_VA_NULL terminator
                    break
                attrs.append({
                    "name": name, "atype": dat.u32(a + 4),
                    "comp_type": dat.u32(a + 12),
                    "shift": dat.raw[0x20 + a + 16],
                    "stride": dat.u16(a + 18), "array": dat.ptr(a + 20),
                })
                a += 24
            pos = next(x for x in attrs if x["name"] == 9)      # GX_VA_POS
            clr = next(x for x in attrs if x["name"] == 11)     # GX_VA_CLR0
            assert pos["atype"] == 2 and pos["comp_type"] == 3, \
                "shine POS must be INDEX8 s16"
            assert clr["atype"] == 1 and clr["comp_type"] == 4, \
                "shine CLR0 must be DIRECT RGBA6"
            div = float(1 << pos["shift"])

            dl_off = dat.ptr(pobj + 0x10)
            dl = dat.raw[0x20 + dl_off: 0x20 + dl_off + dat.u16(pobj + 0x0E) * 32]
            p = 0
            while p < len(dl):
                op = dl[p]
                if op == 0:
                    break
                count = struct.unpack_from('>H', dl, p + 1)[0]
                p += 3
                verts = []
                for _ in range(count):
                    vi = dl[p]; p += 1
                    base = pos["array"] + vi * pos["stride"]
                    xyz = (s16(base) / div, s16(base + 2) / div,
                           s16(base + 4) / div)
                    r6 = dl[p] >> 2
                    g6 = ((dl[p] & 3) << 4) | (dl[p + 1] >> 4)
                    b6 = ((dl[p + 1] & 0xF) << 2) | (dl[p + 2] >> 6)
                    a6 = dl[p + 2] & 0x3F
                    p += 3
                    col = tuple(v * 255 // 63 for v in (r6, g6, b6, a6))
                    col = tuple(col[i] * dif[i] // 255 for i in range(4))
                    verts.append((xyz, col))
                if op == 0x90:                       # GX_TRIANGLES
                    for i in range(0, len(verts) - 2, 3):
                        triangles.append((verts[i], verts[i + 1], verts[i + 2]))
                elif op == 0x98:                     # GX_TRIANGLESTRIP
                    for i in range(len(verts) - 2):
                        v = (verts[i], verts[i + 1], verts[i + 2])
                        triangles.append(v if i % 2 == 0 else (v[1], v[0], v[2]))
                elif op == 0xA0:                     # GX_TRIANGLEFAN
                    for i in range(1, len(verts) - 1):
                        triangles.append((verts[0], verts[i], verts[i + 1]))
                elif op == 0x80:                     # GX_QUADS
                    for i in range(0, len(verts) - 3, 4):
                        triangles.append((verts[i], verts[i + 1], verts[i + 2]))
                        triangles.append((verts[i], verts[i + 2], verts[i + 3]))
            pobj = dat.ptr(pobj + 0x04)
        dobj = dat.ptr(dobj + 0x04)
    return triangles, base_scale


def _effect_model_tracks(dat, model_idx):
    """The child joint's decoded anim tracks {track_type: keys} + loop length."""
    root_off = dat.roots[0][1]
    moff = root_off + 8 + model_idx * 0x14
    janim = dat.ptr(moff + 8)
    child_aj = dat.ptr(janim + 0x00)
    tracks, end_frame = {}, 0.0
    aobj = dat.ptr(child_aj + 0x08)
    if aobj is not None:
        end_frame = struct.unpack_from('>f', dat.raw, 0x20 + aobj + 4)[0]
        fobj = dat.ptr(aobj + 8)
        while fobj is not None:
            ttype, keys = _decode_fobj(dat, fobj)
            tracks[ttype] = keys
            fobj = dat.ptr(fobj + 0x00)
    return tracks, end_frame


def _render_shine_frames(triangles, base_scale, tracks, n_frames, size):
    """Rasterize the animated hexagon face-on with additive blending onto a
    transparent canvas -- gouraud via numpy barycentric weights, supersampled.
    Scale tracks (SCAX/SCAY/SCAZ = 8/9/10) REPLACE the joint's base scale;
    rotation tracks (ROTX/Y/Z = 1/2/3) are radians."""
    import numpy as np
    from PIL import Image

    smax = max(base_scale[0], base_scale[1])
    for t in (8, 9):
        if tracks.get(t):
            smax = max(smax, max(abs(k["value"]) for k in tracks[t]))
    max_r = max(max(abs(v[0][0]), abs(v[0][1]))
                for tri in triangles for v in tri) * smax * 1.05

    W = size * _SUPERSAMPLE
    px_scale = (W / 2) / max_r
    out = []
    for f in range(n_frames):
        frame = float(f)
        rx = _track_value(tracks.get(1, []), frame)
        ry = _track_value(tracks.get(2, []), frame)
        rz = _track_value(tracks.get(3, []), frame)
        sx = _track_value(tracks.get(8, []), frame, base_scale[0])
        sy = _track_value(tracks.get(9, []), frame, base_scale[1])
        sz = _track_value(tracks.get(10, []), frame, base_scale[2])
        cx_, sx_ = math.cos(rx), math.sin(rx)
        cy_, sy_ = math.cos(ry), math.sin(ry)
        cz_, sz_ = math.cos(rz), math.sin(rz)
        R = (np.array([[cz_, -sz_, 0], [sz_, cz_, 0], [0, 0, 1]])
             @ np.array([[cy_, 0, sy_], [0, 1, 0], [-sy_, 0, cy_]])
             @ np.array([[1, 0, 0], [0, cx_, -sx_], [0, sx_, cx_]]))
        rgb = np.zeros((W, W, 3), dtype=np.float32)
        alpha = np.zeros((W, W), dtype=np.float32)
        for tri in triangles:
            pts, cols = [], []
            for (x, y, z), c in tri:
                v = R @ np.array([x * sx, y * sy, z * sz])
                pts.append((W / 2 + v[0] * px_scale, W / 2 - v[1] * px_scale))
                cols.append(c)
            (x0, y0), (x1, y1), (x2, y2) = pts
            area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area) < 1e-9:
                continue
            minx = max(int(min(x0, x1, x2)), 0)
            maxx = min(int(max(x0, x1, x2)) + 1, W)
            miny = max(int(min(y0, y1, y2)), 0)
            maxy = min(int(max(y0, y1, y2)) + 1, W)
            if minx >= maxx or miny >= maxy:
                continue
            ys, xs = np.mgrid[miny:maxy, minx:maxx]
            xs = xs + 0.5
            ys = ys + 0.5
            w0 = ((x1 - xs) * (y2 - ys) - (x2 - xs) * (y1 - ys)) / area
            w1 = ((x2 - xs) * (y0 - ys) - (x0 - xs) * (y2 - ys)) / area
            w2 = 1.0 - w0 - w1
            m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not m.any():
                continue
            c = np.array(cols, dtype=np.float32)
            r = w0 * c[0, 0] + w1 * c[1, 0] + w2 * c[2, 0]
            g = w0 * c[0, 1] + w1 * c[1, 1] + w2 * c[2, 1]
            b = w0 * c[0, 2] + w1 * c[1, 2] + w2 * c[2, 2]
            a = (w0 * c[0, 3] + w1 * c[1, 3] + w2 * c[2, 3]) / 255.0
            sub = rgb[miny:maxy, minx:maxx]
            sub_a = alpha[miny:maxy, minx:maxx]
            sub[..., 0][m] = np.minimum(sub[..., 0][m] + r[m] * a[m], 255)
            sub[..., 1][m] = np.minimum(sub[..., 1][m] + g[m] * a[m], 255)
            sub[..., 2][m] = np.minimum(sub[..., 2][m] + b[m] * a[m], 255)
            sub_a[m] = np.minimum(sub_a[m] + a[m] * 255, 255)
        img = np.dstack([rgb, alpha[..., None]]).astype(np.uint8)
        out.append(Image.fromarray(img, 'RGBA').resize((size, size),
                                                       Image.LANCZOS))
    return out


_SHINE_MODELS = {
    # name -> (effect table model index, frames)
    "shine_loop": (0, 6),        # held down-B pulse (efSync 1160)
    "shine_reflect": (2, 12),    # reflect flash hexagram (efSync 1162)
}


def _derive_shine(dat, out_dir):
    manifest = {}
    for name, (model_idx, default_frames) in _SHINE_MODELS.items():
        triangles, base_scale = _effect_model_geometry(dat, model_idx)
        tracks, end_frame = _effect_model_tracks(dat, model_idx)
        n = int(round(end_frame)) or default_frames
        frames = _render_shine_frames(triangles, base_scale, tracks, n,
                                      SHINE_SIZE)
        names = []
        for i, im in enumerate(frames):
            fname = f"{name}_f{i:02d}.png"
            im.save(out_dir / fname)
            names.append(fname)
        manifest[name] = {"frames": names, "size": SHINE_SIZE,
                          "loop_frames": n, "fps": 60}
    return manifest


# --------------------------------------------------------------------------- #
# public API                                                                   #
# --------------------------------------------------------------------------- #
def load_manifest(storage_path=None):
    """The current manifest dict, or None if never derived / wrong version."""
    try:
        data = json.loads((sprites_dir(storage_path) / "manifest.json")
                          .read_text(encoding="utf-8"))
        return data if data.get("version") == SPRITES_VERSION else None
    except Exception:
        return None


def ensure_sprites(storage_path=None, force=False):
    """Derive the sprite set if missing/stale. Returns the manifest dict, or
    None when derivation is impossible (no vanilla ISO recorded yet) or
    failed. Never raises: callers treat sprites as optional flavor."""
    existing = None if force else load_manifest(storage_path)
    if existing is not None:
        return existing
    with _derive_lock:
        existing = None if force else load_manifest(storage_path)
        if existing is not None:
            return existing
        try:
            grst = vanilla_refs.ensure_vanilla_ref("GrSt.dat", storage_path)
            effx = vanilla_refs.ensure_vanilla_ref("EfFxData.dat", storage_path)
            if grst is None or effx is None:
                logger.info("[sprites] no vanilla ISO recorded yet; skipping")
                return None
            out_dir = sprites_dir(storage_path)
            out_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "version": SPRITES_VERSION,
                "randall": _derive_randall(DatFile(grst), out_dir),
                **_derive_shine(DatFile(effx), out_dir),
            }
            tmp = out_dir / "manifest.json.tmp"
            tmp.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
            file_retry.replace(tmp, out_dir / "manifest.json")
            logger.info(f"[sprites] derived sprite set v{SPRITES_VERSION} "
                        f"into {out_dir}")
            return manifest
        except Exception as e:
            logger.warning(f"[sprites] derivation failed: {e}", exc_info=True)
            return None


def sprite_path(name, storage_path=None):
    """Path of a derived sprite PNG by bare filename, or None if the name is
    not one the current manifest produced (no arbitrary file serving)."""
    manifest = load_manifest(storage_path)
    if manifest is None or Path(name).name != name:
        return None
    known = set()
    for section in manifest.values():
        if isinstance(section, dict):
            known.update(section.get("frames") or [])
    if name not in known:
        return None
    p = sprites_dir(storage_path) / name
    return p if p.is_file() else None
