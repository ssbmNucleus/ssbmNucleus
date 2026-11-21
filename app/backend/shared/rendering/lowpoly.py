"""Which live Skin Lab textures a fighter never shows by default -- from data.

Every fighter's Pl<XX>.dat carries, per costume slot, model lookup tables that
partition the costume's DObjs (SBM_PlayerModelLookupTables at ftData+0x08):

  * HighPoly slots: each lists the DObjs of option 0 (shown by default) and of
    alternate options that moves swap in (Link's sword in and out, Falco's
    blaster, spare hands);
  * LowPoly: the off-screen magnifier bubble and the shadow, never on the fighter.

So which textures are hidden is data in the files, not something to guess from
a render. Randall recoloured Ganondorf's low-poly face copy and Burger King
Falco's hidden accent textures because nothing it was given said so, and a
render-based census proved flaky (texture writes land a frame late).

The Skin Creator reads the same tables per texture -- drawn by the high-poly
model, the low-poly one or both (texture_models) -- to section its texture list.

Texture indices are the viewer's own: it numbers each image in DObj tree order,
merging TObjs that share the SAME image data (by identity, not by content: two
identical-looking images stay separate). This walk does the same and is checked
against the live list; any mismatch returns None rather than a wrong answer.
"""
import logging

from .datprobe import DatFile, HEADER_SIZE
from .lowpoly_promote import _iter_dobjs, _rptr, _share_joint_root

logger = logging.getLogger(__name__)


def _lookup_options(ftdata_path, costume_slot):
    """(high options, low set) for a costume slot: high options is a list of
    slots, each a list of per-option DObj index sets; low is the LowPoly set.
    None when unreadable. Mirrors lowpoly_promote.visibility_sets, keeping the
    options apart instead of flattening them."""
    d = DatFile(str(ftdata_path))
    ft = next((o for n, o in d.roots if n.startswith('ftData')), None)
    lookups = d.ptr(ft + 0x08) if ft is not None else None
    if lookups is None:
        return None
    length = d.u32(lookups + 0x00)
    vis_arr = _rptr(d, lookups + 0x04)
    if vis_arr is None or length < 1:
        return None
    targets = sorted({d.u32(o) for o in d.relocs})

    def slots(config, member):
        arr_ptr = _rptr(d, vis_arr + config * 0x10 + member)
        if arr_ptr is None:
            return None
        nxt = next((t for t in targets if t > arr_ptr), None)
        out = []
        for slot in range(min((nxt - arr_ptr) // 0x08, 32) if nxt else 1):
            table = arr_ptr + slot * 0x08
            count = d.u32(table)
            entries = _rptr(d, table + 0x04)
            options = []
            if entries is not None and 0 < count <= 64:
                for i in range(count):
                    n = d.u32(entries + i * 0x08)
                    data = _rptr(d, entries + i * 0x08 + 0x04)
                    options.append(set(d.raw[HEADER_SIZE + data:HEADER_SIZE + data + n])
                                   if data is not None and n <= 256 else set())
            out.append(options)
        return out

    config = min(max(costume_slot, 0), length - 1)
    high, low = slots(config, 0x00), slots(config, 0x04)
    if not low and config:   # a null config reuses config 0, as the engine does
        high, low = slots(0, 0x00), slots(0, 0x04)
    if not high or not low:
        return None
    return high, set().union(*(o for options in low for o in options))


def hidden_objects(ftdata_path, costume_slot):
    """{DObj index: 'low-poly' | 'alternate'} for the DObjs a fighter does not show by
    default -- its low-poly model, and the alternate model options a match only swaps in
    for some moves (Link's sheathed sword, a face) -- or None when unknown.

    DObj indices are the renderer's material numbering (`Model:<i>`): every DObj of the
    costume's model in joint pre-order, as `lowpoly_promote._iter_dobjs` counts them. A
    DObj no table names is shown."""
    try:
        tables = _lookup_options(ftdata_path, costume_slot)
    except Exception as exc:   # an unreadable table only means "unknown"
        logger.info('[lowpoly] %s', exc)
        return None
    if tables is None:
        return None
    high, low = tables
    default = set().union(*(options[0] for options in high if options))
    out = {i: 'alternate' for options in high for option in options[1:] for i in option if i not in default}
    out.update({i: 'low-poly' for i in low})
    return out


def _texture_users(costume_path):
    """The viewer's material texture numbering (module doc) and who draws each:
    ([(width, height)] per texture index, {texture index: {DObj indices}}), or
    None when the costume has no model root."""
    d = DatFile(str(costume_path))
    _, root = _share_joint_root(d)
    if root is None:
        return None
    order, users = {}, {}
    for dobj_index, dobj in _iter_dobjs(d, root):
        mobj = d.ptr(dobj + 0x08)
        tobj = d.ptr(mobj + 0x08) if mobj is not None else None
        seen = set()
        while tobj is not None and tobj not in seen:
            seen.add(tobj)
            image = d.ptr(tobj + 0x4C)
            data = d.ptr(image) if image is not None else None
            if data is not None:
                index = order.setdefault(data, (len(order), d.u16(image + 4), d.u16(image + 6)))[0]
                users.setdefault(index, set()).add(dobj_index)
            tobj = d.ptr(tobj + 0x04)
    return [(w, h) for _, w, h in sorted(order.values())], users


def texture_models(costume_path, ftdata_path, costume_slot):
    """Which of the fighter's two models draws each material texture, in the
    viewer's own numbering: [{'width', 'height', 'model'}], one row per texture
    of the costume's model, or None when unknown. The viewer lists these first;
    another root of the costume it also draws (Jigglypuff's hats) follows them,
    then its animation frames.

    'low': only the low-poly model draws it (the LowPoly table's DObjs). 'high':
    only the model a match shows (every HighPoly option, and any DObj no table
    names). 'both': one image both models draw -- Melee's low-poly models mostly
    reuse the high model's images, so one edit paints both. The Skin Creator
    sections its texture list by it."""
    try:
        tables = _lookup_options(ftdata_path, costume_slot)
        walk = _texture_users(costume_path) if tables is not None else None
        if walk is None:
            return None
        high, low = tables
        listed_high = set().union(*(o for options in high for o in options))
        shapes, users = walk
        rows = []
        for index, (width, height) in enumerate(shapes):
            dobjs = users[index]
            in_low = bool(dobjs & low)
            in_high = bool(dobjs - low) or bool(dobjs & low & listed_high)
            rows.append({'width': width, 'height': height,
                         'model': 'both' if in_low and in_high else 'low' if in_low else 'high'})
        return rows
    except Exception as exc:   # an unreadable table only means "unknown"
        logger.info('[lowpoly] %s', exc)
        return None


def hidden_textures(costume_path, ftdata_path, costume_slot, live_textures):
    """{'lowpoly': [...], 'alternate': [...]} live texture indices that only
    hidden DObjs use -- low-poly ones, and alternate model options a match only
    swaps in for some moves -- or None when unknown."""
    try:
        tables = _lookup_options(ftdata_path, costume_slot)
        if tables is None:
            return None
        high, low = tables
        default = set().union(*(options[0] for options in high if options))
        alternate = set().union(*(o for options in high for o in options[1:])) - default
        walk = _texture_users(costume_path)
        if walk is None:
            return None
        shapes, users = walk
        # The viewer lists the same images, in the same order, before its
        # animation frames; check the shapes line up before trusting indices.
        base = [t for t in live_textures if not t.get('matAnim')]
        if len(base) < len(shapes) or [(t['width'], t['height']) for t in base[:len(shapes)]] != shapes:
            logger.info('[lowpoly] texture numbering does not match the viewer; skipped')
            return None
        live = [t['index'] for t in base]
        shown = lambda dobjs: bool(dobjs - low - alternate)   # any default-visible user
        return {'lowpoly': sorted(live[i] for i, u in users.items() if not shown(u) and u <= low),
                'alternate': sorted(live[i] for i, u in users.items() if not shown(u) and not u <= low)}
    except Exception as exc:   # an unreadable table only means "unknown"
        logger.info('[lowpoly] %s', exc)
        return None
