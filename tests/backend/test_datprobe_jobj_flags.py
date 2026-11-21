"""Every costume texture walk skips only the joints whose +0x10 is not a DObj.

HSD_JObj flags (dat_colours.py, effect_model.py): PTCL is bit 5, SPLINE bit 14. Bit 29 is
ROOT_XLU, a render pass, and a root joint with any translucent mesh sets it: walking past
such a root left a costume looking textureless, and left the facade's texture_index out of
step with HSDRaw's own numbering. datprobe.jobj_textures, mod_files.texture_inventory and
part_identity._walk_material_tobjs read the rule the same way.
"""
from tests.paths import BACKEND
import struct
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from shared.mod_files import texture_inventory                    # noqa: E402
from shared.rendering import datprobe as dp, part_identity                   # noqa: E402

PLAIN, PTCL, SPLINE, ROOT_XLU = 0, 1 << 5, 1 << 14, 1 << 29
SLOT = 0xF0


def _dat_with_joints(tmp_path, flags):
    """Sibling joints, each carrying one DObj > MObj > TObj > image, told apart by width."""
    data = bytearray(len(flags) * SLOT)
    for i, joint_flags in enumerate(flags):
        jobj = i * SLOT
        dobj, mobj, tobj, image = jobj + 0x40, jobj + 0x50, jobj + 0x70, jobj + 0xD0
        struct.pack_into('>I', data, jobj + 0x04, joint_flags)
        if i + 1 < len(flags):
            struct.pack_into('>I', data, jobj + 0x0C, jobj + SLOT)
        struct.pack_into('>I', data, jobj + 0x10, dobj)
        struct.pack_into('>I', data, dobj + 0x08, mobj)
        struct.pack_into('>I', data, mobj + 0x08, tobj)
        struct.pack_into('>I', data, tobj + 0x4C, image)
        struct.pack_into('>HH', data, image + 0x04, 8 * (i + 1), 8)
    body = bytes(data) + struct.pack('>II', 0, 0) + b'PlXxNr_Share_joint\0'
    header = struct.pack('>IIIII', 0x20 + len(body), len(data), 0, 1, 0) + b'\0' * 12
    path = tmp_path / 'joints.dat'
    path.write_bytes(header + body)
    return path


def test_only_particle_and_spline_joints_are_left_out(tmp_path):
    dat = dp.DatFile(_dat_with_joints(tmp_path, [PLAIN, PTCL, ROOT_XLU, SPLINE]))
    listed = dat.jobj_textures(dat.roots[0][1])
    assert [t.jobj_index for t in listed] == [0, 2]


def test_meshes_on_a_root_xlu_root_are_textured(tmp_path):
    assert dp.samples_textures(_dat_with_joints(tmp_path, [ROOT_XLU]))


def test_the_facade_walkers_skip_the_same_joints(tmp_path):
    path = _dat_with_joints(tmp_path, [PLAIN, PTCL, ROOT_XLU, SPLINE])
    dat = dp.DatFile(path)
    walked = list(part_identity._walk_material_tobjs(dat, dat.roots[0][1]))
    listed = texture_inventory(path)
    assert [row[1] for row in walked] == [0, 2]                # the joints
    assert [row[0] for row in walked] == [t['texture_index'] for t in listed] == [0, 1]
    assert [t['width'] for t in listed] == [8, 24]


def test_the_facade_walkers_agree_on_a_vanilla_root_xlu_costume():
    try:
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        path = ensure_vanilla_ref('PlCaNr.dat')
    except Exception:                       # pragma: no cover - env dependent
        path = None
    if not path or not Path(path).exists():
        pytest.skip('no vanilla ISO / PlCaNr.dat available')
    dat = dp.DatFile(path)
    node, root = part_identity._model_roots(dat)[0]
    assert any(dat.u32(j + 4) & ROOT_XLU for j in dat._iter_tree(root, 0x08, 0x0C))

    walked = list(part_identity._walk_material_tobjs(dat, root))
    listed = [t for t in texture_inventory(path) if t['node'] == node]
    assert [row[0] for row in walked] == [t['texture_index'] for t in listed]
    assert len(walked) == len(dat.jobj_textures(root))

    # vanilla_parts.json was authored on the full list: its signature only fits this walk
    mapping = part_identity.build_map(path, {'costume_code': 'PlCaNr', 'character': 'C. Falcon'})
    assert part_identity.label_parts(mapping)
