"""Hidden textures read from the fighter's own model tables (shared.rendering.lowpoly).

Needs the vanilla reference DATs; skips cleanly where no vanilla ISO is recorded.
"""
import pytest

from shared.rendering import lowpoly
from shared.rendering.datprobe import DatFile
from shared.rendering.lowpoly_promote import _iter_dobjs, _share_joint_root


def _ref(name):
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    try:
        path = ensure_vanilla_ref(name)
    except Exception:
        path = None
    if not path:
        pytest.skip(f'no vanilla reference available for {name}')
    return path


def _live(costume):
    """The viewer's texture list as the viewer builds it: one entry per image
    (shared image data merged), in DObj tree order."""
    d = DatFile(str(costume))
    _, root = _share_joint_root(d)
    seen, live = set(), []
    for _, dobj in _iter_dobjs(d, root):
        mobj = d.ptr(dobj + 0x08)
        tobj = d.ptr(mobj + 0x08) if mobj is not None else None
        while tobj is not None:
            image = d.ptr(tobj + 0x4C)
            data = d.ptr(image) if image is not None else None
            if data is not None and data not in seen:
                seen.add(data)
                live.append({'index': len(live), 'width': d.u16(image + 4), 'height': d.u16(image + 6)})
            tobj = d.ptr(tobj + 0x04)
    return live


def test_ganondorfs_low_poly_face_copy_is_known():
    """Randall recoloured texture 43 -- a low-poly copy of the face."""
    costume = _ref('PlGnNr.dat')
    hidden = lowpoly.hidden_textures(costume, _ref('PlGn.dat'), 0, _live(costume))
    assert hidden == {'lowpoly': [41, 42, 43, 44, 45], 'alternate': []}


def test_bowsers_spare_hands_are_alternates_not_low_poly():
    costume = _ref('PlKpNr.dat')
    hidden = lowpoly.hidden_textures(costume, _ref('PlKp.dat'), 0, _live(costume))
    assert hidden['lowpoly'] == [34, 35, 37, 48]
    assert set(hidden['alternate']) == {36, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47}


def test_a_numbering_that_does_not_line_up_is_unknown_not_wrong():
    costume = _ref('PlGnNr.dat')
    live = _live(costume)
    live[3] = {**live[3], 'width': live[3]['width'] * 2}
    assert lowpoly.hidden_textures(costume, _ref('PlGn.dat'), 0, live) is None
