"""Named vanilla parts, served instead of rediscovered.

The point of the map is that Randall never has to explore a stock costume, so
the tests care about three things: an exact vanilla costume is named outright;
anything the map is not sure about is offered as a guess to confirm, never as
fact; and a costume whose texture LAYOUT differs gets nothing -- including the
case that motivated signatures, where two slots of one character have the same
texture count but a different order.
"""
import json

import pytest

from shared.rendering import part_map


def textures(*sizes):
    return [{'index': i, 'width': w, 'height': h} for i, (w, h) in enumerate(sizes)]


NR = textures((128, 128), (64, 64), (32, 32), (190, 190))
# Same four textures, reordered -- what Yoshi and DK do between colour slots.
BU = textures((64, 64), (128, 128), (190, 190), (32, 32))


@pytest.fixture
def mapped(tmp_path, monkeypatch):
    data = {'version': 2, 'costumes': {
        'PlYsNr': {'character': 'Yoshi', 'signature': part_map.signature(NR),
                   'groups': {'body': [0], 'shell': [1], 'shoes': [2], 'eyes': [3]}},
        'PlYsBu': {'character': 'Yoshi', 'signature': part_map.signature(BU),
                   'groups': {'body': [1], 'shell': [0], 'shoes': [3], 'eyes': [2]}},
    }}
    path = tmp_path / 'vanilla_parts.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(part_map, 'DATA', path)
    part_map.reset()
    yield
    part_map.reset()


def test_a_stock_costume_is_named_outright(mapped):
    known = part_map.describe(NR, {'character': 'Yoshi', 'costume_code': 'PlYsNr'})
    assert known['source'] == 'vanilla'
    assert known['parts'] == {'body': [0], 'shell': [1], 'shoes': [2], 'eyes': [3]}
    assert 'no need to explore' in known['note']


def test_each_slot_is_named_in_its_own_index_space(mapped):
    known = part_map.describe(BU, {'character': 'Yoshi', 'costume_code': 'PlYsBu'})
    assert known['source'] == 'vanilla'
    assert known['parts']['body'] == [1], 'Bu keeps the body at index 1, not Nr\'s index 0'


def test_a_reordered_slot_never_borrows_another_slot_s_labels(mapped):
    # Claims to be Nr, but its layout is Bu's: the claim is not trusted.
    known = part_map.describe(BU, {'character': 'Yoshi', 'costume_code': 'PlYsNr'})
    assert known['source'] == 'likely'
    assert known['parts']['body'] == [1], 'matched by layout, so it gets the layout\'s labels'


def test_a_retexture_is_only_a_starting_guess(mapped):
    known = part_map.describe(NR, {'character': 'Yoshi'})
    assert known['source'] == 'likely'
    assert known['parts']['body'] == [0]
    assert 'Confirm' in known['note'] and 'ONE highlight' in known['note']


@pytest.mark.parametrize('live,origin', [
    (textures((128, 128), (64, 64), (32, 32), (190, 190), (8, 8)), {'character': 'Yoshi'}),
    (textures((128, 128), (64, 64), (32, 32)), {'character': 'Yoshi'}),
    (textures((128, 128), (64, 64), (32, 32), (256, 256)), {'character': 'Yoshi'}),  # resized
    (NR, {'character': 'Mario'}),       # right layout, wrong character
    (NR, {}),                            # nothing to go on
    (NR, None),
])
def test_anything_that_does_not_line_up_is_not_guessed_at(mapped, live, origin):
    assert part_map.describe(live, origin) is None


def test_a_missing_or_broken_data_file_is_simply_no_map(tmp_path, monkeypatch):
    monkeypatch.setattr(part_map, 'DATA', tmp_path / 'absent.json')
    part_map.reset()
    assert part_map.describe(NR, {'character': 'Yoshi'}) is None
    broken = tmp_path / 'broken.json'
    broken.write_text('{not json', encoding='utf-8')
    monkeypatch.setattr(part_map, 'DATA', broken)
    part_map.reset()
    assert part_map.describe(NR, {'character': 'Yoshi'}) is None
    part_map.reset()


def test_the_shipped_map_is_well_formed():
    """Every built entry must be internally consistent, or it will mislabel a
    real costume in front of a user."""
    data = json.loads(part_map.DATA.read_text(encoding='utf-8'))
    assert data['version'] == 2
    assert data['costumes'], 'the shipped map is empty'
    for code, entry in data['costumes'].items():
        count = len(entry['signature'].split())
        seen = {}
        for name, indices in entry['groups'].items():
            assert indices, f'{code}/{name} is empty'
            for index in indices:
                assert isinstance(index, int) and 0 <= index < count, f'{code}/{name}: {index}'
                assert index not in seen, (f'{code}: texture {index} is in both '
                                           f'{seen[index]!r} and {name!r}')
                seen[index] = name


def test_shared_textures_are_listed_per_part(tmp_path, monkeypatch):
    data = {'version': 2, 'costumes': {'PlMrNr': {
        'character': 'Mario', 'signature': part_map.signature(NR),
        'groups': {'cap': [0], 'cap emblem': [1], 'eyes': [3]},
        'masked': {'cap': [1], 'skin': [3, 9]}}}}
    path = tmp_path / 'vanilla_parts.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(part_map, 'DATA', path)
    part_map.reset()
    known = part_map.describe(NR, {'character': 'Mario', 'costume_code': 'PlMrNr'})
    part_map.reset()
    assert known['masked_parts'] == {'cap': [1], 'skin': [3]}, 'index 9 does not exist here'
    assert 'surrounding' in known['note']


def test_textures_outside_every_part_are_named_as_invisible(tmp_path, monkeypatch):
    live = textures((128, 128), (64, 64), (32, 32), (190, 190), (16, 16))
    data = {'version': 2, 'costumes': {'PlKpNr': {
        'character': 'Bowser', 'signature': part_map.signature(live),
        'groups': {'skin': [0, 1]}, 'masked': {'skin': [2]}}}}
    path = tmp_path / 'vanilla_parts.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(part_map, 'DATA', path)
    part_map.reset()
    known = part_map.describe(live, {'character': 'Bowser', 'costume_code': 'PlKpNr'})
    assert known['unlisted'] == [3, 4], 'masked textures are named too'
    assert 'never stale' in known['note']
    # A guessed (retexture) match makes no such claim: its layout may differ.
    guess = part_map.describe(live, {'character': 'Bowser'})
    assert 'unlisted' not in guess and 'never stale' not in guess['note']
    part_map.reset()


def _geometry(*rows):
    """{index: {mapped_triangles, bounds}} as texture_usage reports it."""
    return {i: {'mapped_triangles': n, 'bounds': {'min': [x, 0., 0.], 'max': [x + 1., 1., 1.]}}
            for i, (n, x) in enumerate(rows)}


def _stored(geometry):
    """As part_map_build writes it: "triangles min max", one line per texture."""
    return {str(i): ' '.join([str(row['mapped_triangles']),
                              ','.join(str(v) for v in row['bounds']['min']),
                              ','.join(str(v) for v in row['bounds']['max'])])
            for i, row in geometry.items()}


@pytest.fixture
def upscaled(tmp_path, monkeypatch):
    """A costume whose textures were upscaled: same geometry, different sizes."""
    geometry = _geometry((264, 0.), (238, 4.), (80, 8.))
    data = {'version': 2, 'costumes': {'PlCaNr': {
        'character': 'C. Falcon', 'signature': part_map.signature(textures((128, 128), (128, 128), (64, 32))),
        'geometry': _stored(geometry), 'groups': {'suit': [0], 'gauntlets': [1]}, 'masked': {'skin': [2]}}}}
    path = tmp_path / 'vanilla_parts.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(part_map, 'DATA', path)
    part_map.reset()
    yield geometry
    part_map.reset()


def test_an_upscaled_costume_is_still_named(upscaled):
    """Sizes change with an upscale; which triangles a texture covers does not.
    A user's upscaled Falcon matched no signature, so a lava recolour was aimed
    by eye and landed on the gauntlets while calling them arms."""
    live = textures((256, 256), (256, 256), (128, 64))
    assert part_map.describe(live, {'character': 'C. Falcon', 'costume_code': 'PlCaNr'}) is None
    known = part_map.describe(live, {'character': 'C. Falcon', 'costume_code': 'PlCaNr'}, upscaled)
    assert known['parts'] == {'suit': [0], 'gauntlets': [1]}
    assert known['masked_parts'] == {'skin': [2]} and known['source'] == 'likely'


def test_geometry_names_follow_the_textures_that_moved(upscaled):
    """Reordered textures take their names with them, by geometry."""
    moved = {0: upscaled[2], 1: upscaled[0], 2: upscaled[1]}
    known = part_map.describe(textures((64, 32), (128, 128), (128, 128)),
                              {'character': 'C. Falcon'}, moved)
    assert known['parts'] == {'suit': [1], 'gauntlets': [2]}


def test_a_different_body_is_not_named_from_geometry(upscaled):
    """Nothing lines up: no names, rather than confident wrong ones."""
    other = _geometry((900, 40.), (30, 60.), (12, 80.))
    assert part_map.describe(textures((256, 256), (256, 256), (128, 64)),
                             {'character': 'C. Falcon'}, other) is None


def test_the_map_is_read_from_the_bundled_assets_dir():
    """The installed app bundles backend/assets at _MEIPASS/backend/assets while
    part_map's __file__ sits at _MEIPASS/shared/rendering. A __file__-relative path missed
    it there and every costume read as "no part map" (preview.8, Mario recolor).
    config.BACKEND_ASSETS_DIR is the one place that knows both layouts."""
    from pathlib import Path
    from core import config
    assert part_map.DATA == Path(config.BACKEND_ASSETS_DIR) / 'vanilla_parts.json'
    assert part_map.DATA.is_file()
