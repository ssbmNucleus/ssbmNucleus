"""Which model draws each costume texture (shared.rendering.lowpoly.texture_models),
read from the fighter's model lookup tables, and its trip to the Skin Creator with
the viewer paths (shared.routes.viewer, `textureModels`).

Synthetic DATs only: a costume of six DObjs on two joints, and an ftData whose
tables put them in the high-poly model, its low-poly copy, both, or neither.
"""
import shutil
import struct
import uuid
import zipfile
from pathlib import Path

import pytest
from flask import Flask

import shared.routes.viewer as viewer
import core.viewer_tools as viewer_tools
from shared.rendering import lowpoly


class _Archive:
    """A minimal HSD archive: a data section, its relocations and named roots."""

    def __init__(self):
        self.data, self.relocs, self.roots = bytearray(), [], []

    def alloc(self, size):
        offset = len(self.data)
        self.data += bytes((size + 3) & ~3)
        return offset

    def u32(self, offset, value):
        struct.pack_into('>I', self.data, offset, value)

    def u16(self, offset, value):
        struct.pack_into('>H', self.data, offset, value)

    def ptr(self, offset, target):
        self.u32(offset, target)
        self.relocs.append(offset)

    def save(self, path):
        strings, names = bytearray(), []
        for name, _ in self.roots:
            names.append(len(strings))
            strings += name.encode('ascii') + b'\0'
        body = (bytes(self.data) + b''.join(struct.pack('>I', r) for r in self.relocs)
                + b''.join(struct.pack('>II', offset, at) for (_, offset), at in zip(self.roots, names))
                + bytes(strings))
        header = struct.pack('>IIIII', 0x20 + len(body), len(self.data), len(self.relocs), len(self.roots), 0)
        path.write_bytes(header + bytes(0x20 - len(header)) + body)
        return path


def _costume(path):
    """Six DObjs on two joints. Textures in walk order: A (DObj 0), B (DObj 1),
    C (DObj 2), D (DObj 3), E (DObj 5); DObj 4 draws B's image data through an
    image header of its own, and DObj 5 draws A again after E."""
    dat = _Archive()

    def image(width, height, data=None):
        header = dat.alloc(0x18)
        if data is None:
            data = dat.alloc(16)
        dat.ptr(header, data)
        dat.u16(header + 4, width)
        dat.u16(header + 6, height)
        return header, data

    a, _ = image(64, 64)
    b, b_data = image(32, 32)
    c, _ = image(32, 16)
    d, _ = image(16, 16)
    e, _ = image(8, 8)
    b_again, _ = image(32, 32, b_data)

    def dobj(*images):
        tobjs = [dat.alloc(0x5C) for _ in images]
        for tobj, img in zip(tobjs, images):
            dat.ptr(tobj + 0x4C, img)
        for tobj, after in zip(tobjs, tobjs[1:]):
            dat.ptr(tobj + 0x04, after)
        mobj, node = dat.alloc(0x18), dat.alloc(0x10)
        dat.ptr(mobj + 0x08, tobjs[0])
        dat.ptr(node + 0x08, mobj)
        return node

    def chain(nodes):
        for node, after in zip(nodes, nodes[1:]):
            dat.ptr(node + 0x04, after)
        return nodes[0]

    root, child = dat.alloc(0x40), dat.alloc(0x40)
    dat.ptr(root + 0x08, child)
    dat.ptr(root + 0x10, chain([dobj(a), dobj(b), dobj(c)]))
    dat.ptr(child + 0x10, chain([dobj(d), dobj(b_again), dobj(e, a)]))
    dat.roots.append(('PlFcNr_Share_joint', root))
    return dat.save(path)


# Per config: (HighPoly options of its one slot, LowPoly DObjs).
CONFIGS = [
    ([{0, 1}, {2}], {3, 4}),       # slot 0: DObj 2 an alternate option, 3 and 4 low, 5 in no table
    ([{0, 1, 3}, {2}], {3}),       # slot 1: DObj 3 in both tables, 4 in none
]


def _ftdata(path, configs=CONFIGS):
    dat = _Archive()
    ft, lookups = dat.alloc(0x10), dat.alloc(0x10)
    dat.ptr(ft + 0x08, lookups)
    dat.u32(lookups, len(configs))
    table = dat.alloc(0x10 * len(configs))
    dat.ptr(lookups + 0x04, table)

    def slot(options):
        # The reader sizes a slot array by the next pointer target after it, so
        # the entries follow straight on.
        array, entries = dat.alloc(0x08), dat.alloc(0x08 * len(options))
        dat.u32(array, len(options))
        dat.ptr(array + 0x04, entries)
        for i, option in enumerate(options):
            ids = dat.alloc(len(option))
            dat.data[ids:ids + len(option)] = bytes(sorted(option))
            dat.u32(entries + i * 8, len(option))
            dat.ptr(entries + i * 8 + 4, ids)
        return array

    for n, (high, low) in enumerate(configs):
        dat.ptr(table + n * 0x10, slot(high))
        dat.ptr(table + n * 0x10 + 0x04, slot([low]))
    dat.roots.append(('ftDataFalco', ft))
    return dat.save(path)


@pytest.fixture
def tmp_path():
    # Ordinary mkdir also works with the Windows workspace ACL (mode 0700 does not).
    root = Path(__file__).parent / ('.tmp-texture-models-' + uuid.uuid4().hex)
    root.mkdir()
    yield root
    assert root.parent.resolve() == Path(__file__).parent.resolve()
    shutil.rmtree(root)


def _models(rows):
    return [(row['width'], row['height'], row['model']) for row in rows]


def test_each_texture_is_high_low_or_both(tmp_path):
    rows = lowpoly.texture_models(_costume(tmp_path / 'PlFcNr.dat'), _ftdata(tmp_path / 'PlFc.dat'), 0)
    assert _models(rows) == [
        (64, 64, 'high'),   # A: DObj 0 and 5 (in no table: shown)
        (32, 32, 'both'),   # B: DObj 1 high, DObj 4 low, one image
        (32, 16, 'high'),   # C: an alternate high-poly option
        (16, 16, 'low'),    # D
        (8, 8, 'high'),     # E
    ]


def test_the_costume_slot_picks_its_own_tables(tmp_path):
    rows = lowpoly.texture_models(_costume(tmp_path / 'PlFcRe.dat'), _ftdata(tmp_path / 'PlFc.dat'), 1)
    # B's low user is in no table now; D is listed in both tables.
    assert [row['model'] for row in rows] == ['high', 'high', 'high', 'both', 'high']
    # A slot past the tables is clamped to the last, as the engine does.
    assert lowpoly.texture_models(tmp_path / 'PlFcRe.dat', tmp_path / 'PlFc.dat', 7) == rows


def test_unreadable_tables_or_costume_are_unknown(tmp_path):
    costume, ftdata = _costume(tmp_path / 'PlFcNr.dat'), _ftdata(tmp_path / 'PlFc.dat')
    assert lowpoly.texture_models(costume, tmp_path / 'missing.dat', 0) is None
    assert lowpoly.texture_models(tmp_path / 'missing.dat', ftdata, 0) is None
    assert lowpoly.texture_models(costume, costume, 0) is None          # no ftData root
    no_tables = _Archive()
    no_tables.roots.append(('ftDataFalco', no_tables.alloc(0x10)))   # +0x08 (the lookup tables) null
    assert lowpoly.texture_models(costume, no_tables.save(tmp_path / 'PlXx.dat'), 0) is None


def test_hidden_textures_reads_the_same_walk(tmp_path):
    costume, ftdata = _costume(tmp_path / 'PlFcNr.dat'), _ftdata(tmp_path / 'PlFc.dat')
    live = [{'index': i, 'width': w, 'height': h}
            for i, (w, h, _) in enumerate(_models(lowpoly.texture_models(costume, ftdata, 0)))]
    live.append({'index': 5, 'width': 4, 'height': 4, 'matAnim': True})
    assert lowpoly.hidden_textures(costume, ftdata, 0, live) == {'lowpoly': [3], 'alternate': [2]}
    live[1] = {**live[1], 'width': 16}
    assert lowpoly.hidden_textures(costume, ftdata, 0, live) is None


@pytest.fixture
def client(tmp_path, monkeypatch):
    vanilla, storage = tmp_path / 'vanilla', tmp_path / 'storage'
    for module in (viewer, viewer_tools):
        monkeypatch.setattr(module, 'VANILLA_ASSETS_DIR', vanilla)
        monkeypatch.setattr(module, 'STORAGE_PATH', storage)
    ftdata = _ftdata(tmp_path / 'PlFc.dat')
    monkeypatch.setattr(viewer, 'find_scene_file', lambda _: None)
    monkeypatch.setattr(viewer, 'find_aj_file', lambda _: None)
    monkeypatch.setattr(viewer, 'find_fighter_data_file', lambda character: ftdata if character == 'Falco' else None)

    def make_temp(**_):
        path = tmp_path / uuid.uuid4().hex
        path.mkdir()
        return str(path)
    monkeypatch.setattr(viewer.tempfile, 'mkdtemp', make_temp)
    app = Flask(__name__)
    app.register_blueprint(viewer.viewer_bp)
    return app.test_client(), vanilla, storage


def test_the_vanilla_editor_paths_carry_texture_models(client):
    http, vanilla, _ = client
    for code in ('PlFcNr', 'PlFcRe'):
        (vanilla / 'Falco' / code).mkdir(parents=True)
        _costume(vanilla / 'Falco' / code / f'{code}.dat')
    nr = http.post('/api/mex/viewer/paths-vanilla', json={'character': 'Falco', 'costumeCode': 'PlFcNr'}).json
    assert [row['model'] for row in nr['textureModels']] == ['high', 'both', 'high', 'low', 'high']
    assert nr['textureModels'][0] == {'width': 64, 'height': 64, 'model': 'high'}
    # Red is Falco's second slot: its own tables.
    re = http.post('/api/mex/viewer/paths-vanilla', json={'character': 'Falco', 'costumeCode': 'PlFcRe'}).json
    assert [row['model'] for row in re['textureModels']] == ['high', 'high', 'high', 'both', 'high']


def test_the_vault_editor_reads_the_slot_from_the_costume_dat(client, tmp_path):
    http, _, storage = client
    (storage / 'Falco').mkdir(parents=True)
    with zipfile.ZipFile(storage / 'Falco' / 'red.zip', 'w') as archive:
        archive.writestr('PlFcRe.dat', _costume(tmp_path / 'PlFcRe.dat').read_bytes())
    data = http.post('/api/mex/viewer/paths-vault', json={'character': 'Falco', 'costumeId': 'red'}).json
    assert data['success'] and [row['model'] for row in data['textureModels']] == ['high', 'high', 'high', 'both', 'high']


def test_no_fighter_data_means_no_sections(client):
    http, vanilla, _ = client
    (vanilla / 'Fox' / 'PlFxNr').mkdir(parents=True)
    _costume(vanilla / 'Fox' / 'PlFxNr' / 'PlFxNr.dat')
    data = http.post('/api/mex/viewer/paths-vanilla', json={'character': 'Fox', 'costumeCode': 'PlFxNr'}).json
    assert data['success'] and data['textureModels'] is None


@pytest.mark.parametrize('origin', [{'character': 'Falco', 'costume_code': 'PlFcRe'}, 'model_import_v2', None])
def test_a_working_copy_opens_whatever_its_origin(client, tmp_path, monkeypatch, origin):
    """Randall's working DATs: a dict origin names the costume slot; a plain label
    (the importer's 'model_import_v2') or none falls back to the DAT's own name."""
    from shared import mod_files
    http, _, _ = client
    source = _costume(tmp_path / 'PlFcNr.dat')
    monkeypatch.setattr(viewer, '_prune_checkpoint_copies', lambda: None)
    monkeypatch.setattr(mod_files, 'resolve', lambda file_id: (source, {
        'extension': '.dat', 'name': 'PlFcNr.dat', **({'origin': origin} if origin else {})}))
    response = http.post('/api/mex/viewer/paths-checkpoint', json={'character': 'Falco', 'fileId': 'f1'})
    assert response.status_code == 200
    expected = 'both' if isinstance(origin, dict) else 'low'
    assert response.json['textureModels'][3]['model'] == expected


def test_a_bad_costume_code_only_drops_the_sections(client):
    http, vanilla, _ = client
    (vanilla / 'Falco' / 'PlFcNr').mkdir(parents=True)
    _costume(vanilla / 'Falco' / 'PlFcNr' / 'PlFcNr.dat')
    assert viewer._texture_models(vanilla / 'Falco' / 'PlFcNr' / 'PlFcNr.dat', viewer.find_fighter_data_file('Falco'),
                                  'Falco', 42)[3]['model'] == 'low'
    assert viewer._texture_models(vanilla / 'missing.dat', viewer.find_fighter_data_file('Falco'), 'Falco') is None
