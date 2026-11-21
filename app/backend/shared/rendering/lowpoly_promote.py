"""Detect and repair Diet-Melee-authored costumes at import time.

Diet Melee (and packs built on it, e.g. Diet Melee 64) ships ISOs whose DOL
entry point is redirected into injected bootstrap code that patches the engine
at runtime — most importantly to force-display the LOW-poly character models.
Skins from those packs therefore:

1. carry their real art in the LOW-poly DObj slots that every normal build
   hides (imported skins silently display as near-vanilla);
2. strip the TObjs from never-shown high-poly materials while leaving the TEX
   render flags set (tools draw those white; hardware follows the null
   pointer);
3. slide the GLOBAL TObj numbering that Melee's eye-blink system addresses
   (ftAnim_80070200 → ftParts_80075240 concatenates every DObj's MObj→TObj
   chain and takes the n-th entry, n from ftData->x8->x8) — on a normal
   engine the lookup misses and the game HANGS at match load
   (ftanim.c:1236 assert).

The repair is HSDRawViewer's `--promote-lowpoly`: an index-stable content
swap (low art into the visible slots), matanim entries remapped along with
their content, TEX-without-TObj flags cleared, and neutral blink shims (a
texanim whose every frame is the texture already at the required walk index)
so the engine's blink writes are satisfied. DObj count and order never
change, so the ftData visibility tables stay valid on any build.

Detection fingerprints (either marks a diet-authored file; both are
impossible for normally-authored skins):
- the source ISO's DOL entry point differs from vanilla (`dol_entry_hacked`);
- the costume has TEX-flagged materials with no TObj chain
  (`stripped_tex_materials`).

Verified end-to-end 2026-08-17 on DM64 v1.03 Ness: raw import hangs a
vanilla-engine build at match load; transformed import boots and plays with
the intended N64 model.
"""

import logging
import re
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .datprobe import DatFile, HEADER_SIZE, decode_image

logger = logging.getLogger(__name__)

VANILLA_DOL_ENTRY = 0x8000522C


# neutral blink shims must tolerate every frame index the engine writes;
# vanilla eye anims are 3-5 frames, this is a safe ceiling
SHIM_FRAMES_FALLBACK = 8

_TEXBITS = 0x0FF0        # RENDER_MODE TEX0..TEX7
_JOBJ_INSTANCE = 1 << 12


# --------------------------------------------------------------------------- #
# fingerprints                                                                #
# --------------------------------------------------------------------------- #

def dol_entry_hacked(iso_path):
    """Whether a GC ISO's main.dol entry point differs from vanilla Melee's —
    the Diet-family bootstrap signature (their injected engine patches run
    from a redirected entry). Returns False on any read error."""
    try:
        with open(iso_path, 'rb') as f:
            f.seek(0x420)
            dol_off = struct.unpack('>I', f.read(4))[0]
            f.seek(dol_off + 0xE0)
            entry = struct.unpack('>I', f.read(4))[0]
        return entry != VANILLA_DOL_ENTRY
    except Exception:
        return False


def _share_joint_root(d):
    """The costume's model root symbol (Ply..._Share_joint, not matanim)."""
    for name, off in d.roots:
        if name.endswith('_Share_joint') and 'matanim' not in name:
            return name, off
    return None, None


def _iter_dobjs(d, root):
    """(global_index, dobj_offset) in renderer/engine tree order.

    Only PTCL (bit 5) and SPLINE (bit 14) jobjs are skipped — their +0x10
    pointer is not a DObj (HSD_JOBJ.Dobj itself returns null for them, so the
    renderer's enumeration skips exactly these). Bit 29 is ROOT_XLU, a render
    -pass flag common on real subtrees (Peach, Marth, Ganondorf) — skipping
    it under-counts DObjs."""
    g = 0
    for j in d._iter_tree(root, 0x08, 0x0C):
        flags = d.u32(j + 0x04)
        if flags & (1 << 5) or flags & (1 << 14):   # PTCL / SPLINE
            continue
        dobj = d.ptr(j + 0x10)
        while dobj is not None:
            yield g, dobj
            dobj = d.ptr(dobj + 0x04)
            g += 1


def stripped_tex_materials(dat_path):
    """Count of materials with TEX render flags set but NO TObj chain — the
    Diet texture-stripping signature (0 on vanilla and normal skins)."""
    try:
        d = DatFile(str(dat_path))
        _, root = _share_joint_root(d)
        if root is None:
            return 0
        count = 0
        for _, dobj in _iter_dobjs(d, root):
            mobj = d.ptr(dobj + 0x08)
            if mobj is None:
                continue
            if d.ptr(mobj + 0x08) is None and (d.u32(mobj + 0x04) & _TEXBITS):
                count += 1
        return count
    except Exception:
        return 0


# --------------------------------------------------------------------------- #
# ftData visibility + blink requirements                                      #
# --------------------------------------------------------------------------- #

def costume_slot_for_code(character, color_code):
    """Vanilla CSS slot index for a costume code suffix ('Nr', 'Bu', ...) —
    the visibility config AND blink list are per-slot for fighters whose alt
    costumes add geometry (Pikachu/Pichu hats, Peach's Daisy). 0 when the
    suffix isn't a vanilla slot of this character."""
    try:
        from core.constants import VANILLA_CSS_COLOR_ORDER
        # VANILLA_CSS_COLOR_ORDER is keyed by display names ('Pikachu',
        # 'C. Falcon') while callers hold internal names ('pikachu') — match
        # on a case/punctuation-insensitive form.
        want = re.sub(r'[^a-z0-9]', '', str(character).lower())
        for key, order in VANILLA_CSS_COLOR_ORDER.items():
            if re.sub(r'[^a-z0-9]', '', key.lower()) == want:
                if order and color_code in order:
                    return order.index(color_code)
                break
    except Exception:
        pass
    return 0


def _rptr(d, off):
    """A pointer only if the field itself is relocated (vanilla DATs pad the
    lookup arrays with non-pointer garbage words)."""
    return d.u32(off) if off in d.relocs else None


def visibility_sets(ftdata_path, costume_slot=0):
    """(high, low) DObj-index sets for `costume_slot` from a fighter's
    Pl<XX>.dat visibility lookup tables (SBM_PlayerModelLookupTables at
    ftData+0x08; HighPoly accessor +0x00, LowPoly +0x04). Returns (None,
    None) if unreadable. The engine clamps the slot and a null config reuses
    config 0 — mirrored here."""
    d = DatFile(str(ftdata_path))
    ft = next((o for n, o in d.roots if n.startswith('ftData')), None)
    if ft is None:
        return None, None
    lookups = d.ptr(ft + 0x08)
    if lookups is None:
        return None, None
    length = d.u32(lookups + 0x00)
    vis_arr = _rptr(d, lookups + 0x04)
    if vis_arr is None or length < 1:
        return None, None

    targets = sorted({d.u32(o) for o in d.relocs})

    def array_len(ptr, elem=0x08, cap=32):
        nxt = next((t for t in targets if t > ptr), None)
        return min((nxt - ptr) // elem, cap) if nxt else 1

    def read_set(config, member):
        arr_ptr = _rptr(d, vis_arr + config * 0x10 + member)
        if arr_ptr is None:
            return None
        idx = set()
        for slot in range(array_len(arr_ptr)):
            stbl = arr_ptr + slot * 0x08
            count = d.u32(stbl + 0x00)
            entries = _rptr(d, stbl + 0x04)
            if entries is None or count <= 0 or count > 64:
                continue
            for i in range(count):
                le = entries + i * 0x08
                n = d.u32(le + 0x00)
                data = _rptr(d, le + 0x04)
                if data is not None and n <= 256:
                    idx.update(d.raw[HEADER_SIZE + data:HEADER_SIZE + data + n])
        return idx or None

    def read_groups(config, member):
        """Per model group: sorted DObj index list (the engine's
        FtPartsVisLookup groups — group 0 = body, later groups =
        costume accessories like Pikachu's hats)."""
        arr_ptr = _rptr(d, vis_arr + config * 0x10 + member)
        if arr_ptr is None:
            return None
        groups = []
        for slot in range(array_len(arr_ptr)):
            stbl = arr_ptr + slot * 0x08
            count = d.u32(stbl + 0x00)
            entries = _rptr(d, stbl + 0x04)
            idx = set()
            if entries is not None and 0 < count <= 64:
                for i in range(count):
                    le = entries + i * 0x08
                    n = d.u32(le + 0x00)
                    data = _rptr(d, le + 0x04)
                    if data is not None and n <= 256:
                        idx.update(d.raw[HEADER_SIZE + data:HEADER_SIZE + data + n])
            groups.append(sorted(idx))
        return groups

    config = min(max(costume_slot, 0), length - 1)
    high = read_set(config, 0x00)
    low = read_set(config, 0x04)
    if low is None and config != 0:
        config = 0
        high, low = read_set(0, 0x00), read_set(0, 0x04)
    if not high or not low:
        return None, None
    d._vis_groups = (read_groups(config, 0x00), read_groups(config, 0x04))
    visibility_sets._last_groups = d._vis_groups
    return sorted(high), sorted(low)


def visibility_groups(ftdata_path, costume_slot=0):
    """Per-model-group (high, low) DObj index lists — group 0 is the body,
    later groups are costume accessories (Pikachu/Pichu hats). None when
    unreadable. Diet builds force LOW display for the BODY group only; the
    accessory groups keep their high art AND show the low accessory pieces,
    so the repair must not swap accessory-group content."""
    if visibility_sets(ftdata_path, costume_slot) == (None, None):
        return None
    high_gs, low_gs = visibility_sets._last_groups
    if not high_gs or not low_gs:
        return None
    n = max(len(high_gs), len(low_gs))
    out = []
    for g in range(n):
        h = high_gs[g] if g < len(high_gs) else []
        l = low_gs[g] if g < len(low_gs) else []
        out.append((h, l))
    return out


def blink_indices(ftdata_path, costume_slot=0):
    """The GLOBAL TObj walk indices the fighter's eye-blink system requires
    to be animated (ftData->x8->x8 per-costume u16 arrays; a null slot entry
    falls back to costume 0, like the engine). [] when the fighter has none
    (e.g. Falcon)."""
    try:
        d = DatFile(str(ftdata_path))
        ft = next((o for n, o in d.roots if n.startswith('ftData')), None)
        if ft is None:
            return []
        x8 = d.ptr(ft + 0x08)
        if x8 is None:
            return []
        count = d.u32(x8 + 0x08)
        arr = d.ptr(x8 + 0x0C)
        if arr is None or count <= 0 or count > 16:
            return []

        def slot_list(c):
            if (arr + c * 4) not in d.relocs:
                return None
            p = d.ptr(arr + c * 4)
            if p is None:
                return None
            return [d.u16(p + i * 2) for i in range(count)]

        return slot_list(costume_slot) or slot_list(0) or []
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# the game's global TObj walk (ftParts_SetupParts order)                      #
# --------------------------------------------------------------------------- #

def _walk_jobjs_game(d, root):
    """ftParts_SetupParts order: DFS child-then-next, no descent past
    INSTANCE jobjs. (Ported from the pokedex campaign's tobj_index_probe,
    which is verified in-game.)"""
    out, stack, jobj = [], [], root
    while jobj is not None:
        out.append(jobj)
        flags = d.u32(jobj + 0x04)
        child = d.ptr(jobj + 0x08)
        if not (flags & _JOBJ_INSTANCE) and child is not None:
            stack.append(jobj)
            jobj = child
            continue
        nxt = d.ptr(jobj + 0x0C)
        if nxt is not None:
            jobj = nxt
            continue
        while True:
            if not stack:
                jobj = None
                break
            parent = stack.pop()
            pn = d.ptr(parent + 0x0C)
            if pn is not None:
                jobj = pn
                break
    return out


def _walk_matanim_joints(d, root):
    """HSD_JObjAddAnimAll pairs the jobj tree with the matanim tree by the
    same child/next recursion, so a plain DFS in the same order is the
    pairing."""
    out, stack, node = [], [], root
    while node is not None:
        out.append(node)
        child = d.ptr(node + 0x00)
        if child is not None:
            stack.append(node)
            node = child
            continue
        nxt = d.ptr(node + 0x04)
        if nxt is not None:
            node = nxt
            continue
        while True:
            if not stack:
                node = None
                break
            parent = stack.pop()
            pn = d.ptr(parent + 0x04)
            if pn is not None:
                node = pn
                break
    return out


def _chain(d, head, next_off):
    out, n = [], head
    while n is not None:
        out.append(n)
        n = d.ptr(n + next_off)
    return out


def animated_walk_indices(dat_path):
    """{global TObj walk index: frame count} for every TObj a matanim texanim
    animates — the set the engine's blink lookup must land in."""
    d = DatFile(str(dat_path))
    jroot = mroot = None
    for n, o in d.roots:
        if n.endswith('_matanim_joint'):
            mroot = o
        elif n.endswith('_Share_joint'):
            jroot = o
    if jroot is None:
        return {}
    jobjs = _walk_jobjs_game(d, jroot)
    mjoints = _walk_matanim_joints(d, mroot) if mroot is not None else []
    animated = {}
    g = 0
    for ji, j in enumerate(jobjs):
        flags = d.u32(j + 0x04)
        dobjs = ([] if flags & ((1 << 5) | (1 << 14))
                 else _chain(d, d.ptr(j + 0x10), 0x04))
        mats = (_chain(d, d.ptr(mjoints[ji] + 0x08), 0x00)
                if ji < len(mjoints) else [])
        for di, dobj in enumerate(dobjs):
            ta_by_id = {}
            if di < len(mats):
                for ta in _chain(d, d.ptr(mats[di] + 0x08), 0x00):
                    if d.ptr(ta + 0x08) is not None:      # has an aobj
                        ta_by_id[d.u32(ta + 0x04)] = d.u16(ta + 0x14)
            mobj = d.ptr(dobj + 0x08)
            for tobj in (_chain(d, d.ptr(mobj + 0x08), 0x04)
                         if mobj is not None else []):
                tid = d.u32(tobj + 0x08)
                if tid in ta_by_id:
                    animated[g] = ta_by_id[tid]
                g += 1
    return animated


def verify_blink(dat_path, required):
    """Whether every ftData-required blink index lands on an animated TObj —
    the offline predictor for the ftanim.c:1236 match-load hang."""
    if not required:
        return True
    animated = animated_walk_indices(dat_path)
    return all(n in animated for n in required)


# --------------------------------------------------------------------------- #
# per-DObj texture comparison (perceptual, re-encode tolerant)                #
# --------------------------------------------------------------------------- #

_GRID = 4          # perceptual descriptor: GRID x GRID mean-RGB cells
_CELL_DELTA = 40   # max per-channel cell delta (0-255) still counted "same"


def _texture_descriptor(d, tobj):
    """(byte_key, perceptual) for one TObj. Perceptual is a mean-RGB cell
    grid, robust to re-encoding; None when the format can't be decoded."""
    img_off = d.ptr(tobj + 0x4C)
    if img_off is None:
        return (b'', None)
    img = d.image_at(img_off)
    tlut_off = d.ptr(tobj + 0x50)
    tlut = d.tlut_at(tlut_off) if tlut_off else None
    key = (img.format, img.width, img.height,
           img.data or b'', (tlut.data if tlut else b'') or b'')
    percep = None
    try:
        rows = decode_image(img, tlut)
        if rows:
            hgt, wid = len(rows), len(rows[0])
            cells = []
            for cy in range(_GRID):
                for cx in range(_GRID):
                    y0 = hgt * cy // _GRID
                    y1 = max(hgt * (cy + 1) // _GRID, y0 + 1)
                    x0 = wid * cx // _GRID
                    x1 = max(wid * (cx + 1) // _GRID, x0 + 1)
                    n = r = g = b = 0
                    for y in range(y0, y1):
                        row = rows[y]
                        for x in range(x0, x1):
                            px = row[x]
                            r += px[0]; g += px[1]; b += px[2]
                            n += 1
                    cells.append((r // n, g // n, b // n))
            percep = cells
    except Exception:
        pass
    return (key, percep)


def _textures_match(a, b):
    if a[0] == b[0]:
        return True
    pa, pb = a[1], b[1]
    if pa is None or pb is None:
        return False
    return all(abs(ca[c] - cb[c]) <= _CELL_DELTA
               for ca, cb in zip(pa, pb) for c in range(3))


def _dobj_textures(dat_path):
    """Per-DObj texture descriptor lists, renderer tree order."""
    d = DatFile(str(dat_path))
    _, root = _share_joint_root(d)
    if root is None:
        return None
    out = []
    for _, dobj in _iter_dobjs(d, root):
        texs = []
        mobj = d.ptr(dobj + 0x08)
        if mobj is not None:
            tobj = d.ptr(mobj + 0x08)
            while tobj is not None:
                try:
                    texs.append(_texture_descriptor(d, tobj))
                except Exception:
                    texs.append((b'?', None))
                tobj = d.ptr(tobj + 0x04)
        out.append(texs)
    return out


# --------------------------------------------------------------------------- #
# plan + apply                                                                #
# --------------------------------------------------------------------------- #

@dataclass
class DietFixPlan:
    promote: bool = False
    stripped: int = 0
    low_set: list = field(default_factory=list)    # BODY-group lows (paired into high slots)
    high_set: list = field(default_factory=list)   # BODY-group highs
    slide_set: list = field(default_factory=list)  # accessory-group lows (pad-slid, highs kept)
    hide_max: int = -1                             # max index any hide list names
    blink: list = field(default_factory=list)   # [(walk index, shim frames)]
    joint_symbol: str = ""
    reason: str = ""


def plan_diet_fix(candidate_dat, vanilla_costume_dat, ftdata_dat,
                  costume_slot=0, diet_source=False):
    """Decide whether (and how) to repair a diet-authored costume. Never
    raises — structural surprises return promote=False with the reason.

    `diet_source` marks files ripped from an ISO whose DOL entry is hacked
    (`dol_entry_hacked`); without it, only the stripped-texture fingerprint
    marks a file as diet-authored."""
    plan = DietFixPlan()
    try:
        plan.stripped = stripped_tex_materials(candidate_dat)
        if not (diet_source or plan.stripped):
            plan.reason = "no diet fingerprint"
            return plan

        high, low = visibility_sets(ftdata_dat, costume_slot)
        if not high or not low:
            plan.reason = "no visibility tables"
            return plan
        # Group-aware split: only the BODY group (0) content-swaps. Accessory
        # groups (Pikachu/Pichu hats) keep their high art — Diet builds show
        # the high accessories PLUS the low accessory pieces — so their lows
        # are pad-slid past the hide lists instead of swapped in.
        groups = visibility_groups(ftdata_dat, costume_slot)
        if groups and len(groups) > 1:
            body_high, body_low = groups[0]
            acc_low = sorted({i for _, l in groups[1:] for i in l})
        else:
            body_high, body_low = high, low
            acc_low = []
        plan.hide_max = max(low)

        d = DatFile(str(candidate_dat))
        joint, _ = _share_joint_root(d)
        if joint is None:
            plan.reason = "no model root"
            return plan
        plan.joint_symbol = joint

        cand = _dobj_textures(candidate_dat)
        ref = _dobj_textures(vanilla_costume_dat)
        if not cand or not ref or len(cand) != len(ref):
            plan.reason = (f"DObj layout differs from vanilla "
                           f"({len(cand or [])} vs {len(ref or [])})")
            return plan
        # Vanilla lookup tables legitimately reference indices past a smaller
        # costume's DObj count (Pikachu Bu: 30 DObjs, its shared hat config
        # names index 31) — the engine just no-ops those. Compare textures on
        # the in-range subset only, but hand the FULL sets to the transform:
        # its pad-slide needs the real hide-list maximum, and it drops
        # out-of-range slots from pairing itself. Lows past the high-slot
        # count are fine too — stranded lows stay on their joints and get
        # slid past the hide list instead of paired.
        low_in = [i for i in low if i < len(cand)]
        high_in = [i for i in high if i < len(cand)]
        if not low_in or not high_in:
            plan.reason = "visibility sets empty after clamping"
            return plan

        def changed(i):
            if len(cand[i]) != len(ref[i]):
                return True
            return not all(_textures_match(a, b)
                           for a, b in zip(cand[i], ref[i]))

        # Diet packs force-display the LOW model for the WHOLE roster, and
        # skins repaint textures largely SHARED between both models — so the
        # low mesh is the intended look even when the low set's own textures
        # barely differ from vanilla (Pichu, the Ice Climbers). Any texture
        # difference at all marks a modded costume worth promoting; only a
        # file whose textures are entirely vanilla (nothing to show) skips.
        low_changed = sum(1 for i in low_in if changed(i)) / len(low_in)
        high_changed = sum(1 for i in high_in if changed(i)) / len(high_in)
        if low_changed == 0 and high_changed == 0:
            plan.reason = "textures identical to vanilla — nothing to promote"
            return plan

        required = blink_indices(ftdata_dat, costume_slot)
        vanilla_frames = animated_walk_indices(vanilla_costume_dat)
        plan.blink = [(n, vanilla_frames.get(n, SHIM_FRAMES_FALLBACK))
                      for n in required]
        plan.low_set = body_low
        plan.high_set = body_high
        plan.slide_set = acc_low
        plan.promote = True
        plan.reason = (f"diet-authored (stripped={plan.stripped}, "
                       f"iso={diet_source}), low {low_changed:.0%} / "
                       f"high {high_changed:.0%} changed")
        return plan
    except Exception as e:
        logger.warning(f"diet-fix plan failed for {candidate_dat}: {e}")
        plan.reason = f"plan error: {e}"
        return plan


def apply_diet_fix(candidate_dat, out_path, plan, hsdraw_exe=None):
    """Run the HSDRawViewer transform and gate the result with the offline
    blink verifier. Raises on any failure — callers keep the original file."""
    if hsdraw_exe is None:
        from core.config import HSDRAW_EXE
        hsdraw_exe = HSDRAW_EXE
    from core.config import get_subprocess_args
    cmd = [
        str(hsdraw_exe), "--promote-lowpoly", str(candidate_dat),
        plan.joint_symbol,
        ",".join(str(i) for i in plan.low_set),
        ",".join(str(i) for i in plan.high_set),
        ",".join(str(i) for i in plan.slide_set) or "-",
        str(plan.hide_max),
        str(out_path),
        ",".join(f"{n}:{f}" for n, f in plan.blink),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                          **get_subprocess_args())
    if proc.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError(
            f"promote-lowpoly failed: {proc.stdout or proc.stderr}")
    if not verify_blink(out_path, [n for n, _ in plan.blink]):
        raise RuntimeError(
            "transformed DAT fails the blink-index check (would hang in-game)")
    logger.info(f"Diet-fix applied to {Path(candidate_dat).name}: "
                f"{len(plan.low_set)} low DObjs promoted, "
                f"{plan.stripped} stripped materials sanitized, "
                f"{len(plan.blink)} blink indices verified")
