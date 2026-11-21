"""GET /storage/extras/current reads where a guarded install writes.

The "Currently in MEX" card used to seek raw config offsets and compare to
the config's representative swatches. That showed garbage "Custom" colors or
a false "Vanilla" whenever a DAT's layout moved (HSDRaw re-saves, fighter
DATs with a non-vanilla layout), and 27 extras read "Custom" on an untouched
vanilla project. These tests pin the fixed behavior on real vanilla files
(storage/test-base/files; copies only, never modified in place).
"""
from tests.paths import APP
import struct
from pathlib import Path

import pytest

from vault.routes.extras import colors
from vault.extras import helpers
from vault.extras import color_patch, color_read
from core.extra_types import EXTRA_TYPES
from core.extra_lookup import get_extra_type
from shared.rendering import ptcl_parse
from shared.vanilla_extract import vanilla_refs

VANILLA_DIR = APP / 'storage' / 'test-base' / 'files'


def _vanilla(name):
    path = VANILLA_DIR / name
    if not path.exists():
        pytest.skip(f'Vanilla {name} unavailable')
    return path


@pytest.fixture
def project(vault, monkeypatch):
    """A temp MEX project + a temp vault whose test-base holds the vanilla
    references. `put(name, data=None)` drops a project file (vanilla copy by
    default); `get(character, extra)` calls the endpoint."""
    files = vault.path('project', 'files')
    files.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(helpers, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(helpers, 'get_project_files_dir', lambda: files)
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref',
                        lambda name, **kwargs: (VANILLA_DIR / name) if (VANILLA_DIR / name).exists() else None)
    client = vault.client(colors, 'extras_bp')

    class Project:
        def __init__(self):
            self.client = client

        def put(self, name, data=None, reference=True):
            source = _vanilla(name)
            if reference:
                vault.touch('test-base', 'files', name, data=source.read_bytes())
            target = files / name
            target.write_bytes(source.read_bytes() if data is None else data)
            return target

        def get(self, character, extra):
            response = client.get(f'/api/mex/storage/extras/current/{character}/{extra}')
            body = response.get_json()
            assert response.status_code == 200 and body['success'], body
            return body

    return Project()


def _color_extras():
    """One (character, extra) per distinct configured color extra that reads
    through `offsets` (texture/model/region types have their own paths)."""
    seen, cases = set(), []
    for character, types in EXTRA_TYPES.items():
        for cfg in types:
            if not cfg.get('offsets') or cfg.get('type') in ('model', 'texture'):
                continue
            if cfg.get('format') in ('texture_recolor', 'texture_region'):
                continue
            key = (cfg['id'], cfg['target_file'])
            if key not in seen:
                seen.add(key)
                cases.append((character, cfg['id']))
    return cases


def _fill(info, byte='5A'):
    """A synthetic custom color of the right length for one layer."""
    fmt = info.get('format', 'RGBY')
    if 'size' in info:
        return byte * info['size']
    if fmt == '42_48':
        return byte * 12
    if fmt in ('RGB', 'CF', '070707'):
        return byte * 3
    return byte * 2  # RGBY matrices


def _shift_ef_file(data, pad=32):
    """A structurally valid Ef*Data.dat with `pad` bytes inserted before the
    particle bank (effect-table pointers and header sizes fixed up), so every
    ptcl color operand moves -- what an HSDRaw re-save does to offsets.
    Same construction as test_extras_offset_relocation.shifted_copy."""
    data = bytearray(data)
    ds = ptcl_parse.DATA_START
    fsize, dsize = struct.unpack_from('>II', data, 0)
    part_ptr, tex_ptr = struct.unpack_from('>II', data, ds)
    insert_at = ds + 8
    assert insert_at <= ds + part_ptr
    new = bytearray(data[:insert_at]) + b'\0' * pad + data[insert_at:]
    struct.pack_into('>II', new, 0, fsize + pad, dsize + pad)
    struct.pack_into('>II', new, ds, part_ptr + pad, tex_ptr + pad)
    return bytes(new)


# ---------------------------------------------------------------------------
# Untouched vanilla project
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('character,extra', _color_extras())
def test_every_color_extra_reads_vanilla_on_a_vanilla_project(project, character, extra):
    cfg = get_extra_type(character, extra)
    project.put(cfg['target_file'])
    body = project.get(character, extra)
    assert body['status'] == 'vanilla', body
    assert body['isVanilla'] is True
    assert body['unknownLayers'] == []
    assert body['layoutVerified'] is True


# ---------------------------------------------------------------------------
# Installed recolor on an unshifted file
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('character,extra', [
    ('Mario', 'mario_fireball'),      # fan-out RGB operands (+ color1/color2 summary keys)
    ('Fox', 'laser_ring'),            # direct size spans + detection
    ('C. Falcon', 'falcon_punch'),    # mixed operand / raw layers
    ('Marth', 'sword'),               # fighter DAT raw spans
])
def test_installed_recolor_reads_custom_with_its_colors(project, character, extra):
    cfg = get_extra_type(character, extra)
    target = project.put(cfg['target_file'])
    offsets = helpers.get_dynamic_offsets(target, extra, cfg['offsets'])
    layer = next(k for k in cfg['vanilla'] if k in offsets)
    color = _fill(offsets[layer])
    safety = helpers.make_write_safety(target, extra, cfg['target_file'], cfg['vanilla'])
    assert color_patch.apply_hex_patches(target, offsets, {layer: {'color': color}}, safety=safety) == []

    body = project.get(character, extra)
    assert body['status'] == 'custom'
    assert body['isVanilla'] is False
    if 'end' not in offsets[layer] and 'ranges' not in offsets[layer]:
        assert body['colors'][layer] == color.upper()


def test_restore_vanilla_reads_vanilla_again(project):
    """Restore writes the exact reference bytes; the config's representative
    swatch for upb `body` (FFFFFF) is not those bytes, which used to make a
    restored Up-B read Custom forever."""
    cfg = get_extra_type('Fox', 'upb')
    target = project.put(cfg['target_file'])
    offsets = helpers.get_dynamic_offsets(target, 'upb', cfg['offsets'])
    safety = helpers.make_write_safety(target, 'upb', cfg['target_file'], cfg['vanilla'])
    color_patch.apply_hex_patches(target, offsets, {'trail': {'color': '123456'}}, safety=safety)
    assert project.get('Fox', 'upb')['status'] == 'custom'
    assert helpers.restore_extra_color_bytes(target, cfg) == []
    assert target.read_bytes() == _vanilla(cfg['target_file']).read_bytes()
    assert project.get('Fox', 'upb')['status'] == 'vanilla'


@pytest.mark.parametrize('target_file', ['EfCaData.dat', 'EfCoData.dat', 'EfGnData.dat',
                                         'EfLgData.dat', 'EfMrData.dat', 'EfSsData.dat',
                                         'PlFx.dat', 'PlMr.dat', 'PlNs.dat', 'PlPk.dat'])
def test_recoloring_sibling_extras_does_not_make_an_extra_unknown(project, target_file):
    """Reads prove a layer's position by its vanilla neighborhood. Recolors of
    OTHER extras in the same file only change their own color spans, which
    are masked -- so they must not turn this extra Unknown (or Custom)."""
    extras = {}
    for character, types in EXTRA_TYPES.items():
        for cfg in types:
            if (cfg['target_file'] == target_file and cfg.get('offsets')
                    and cfg.get('format') not in ('shine_gradient', 'texture_recolor')):
                extras.setdefault(cfg['id'], (character, cfg))
    if len(extras) < 2:
        pytest.skip('fewer than two color extras in this file')
    for extra, (character, _cfg) in extras.items():
        target = project.put(target_file)
        own = set()
        for other, (other_char, other_cfg) in extras.items():
            offsets = helpers.get_dynamic_offsets(target, other, other_cfg['offsets'])
            if other == extra:
                own = {span for span in helpers.compute_mask_spans(offsets)}
                continue
            spans = helpers.compute_mask_spans(offsets)
            if any(a < b + m and b < a + n for a, n in spans for b, m in own):
                continue  # genuinely shares bytes: a recolor there IS a change
            safety = helpers.make_write_safety(target, other, target_file, other_cfg['vanilla'])
            color_patch.apply_hex_patches(
                target, offsets,
                {layer: {'color': _fill(info)} for layer, info in offsets.items()},
                safety=safety)
        body = project.get(character, extra)
        assert body['status'] == 'vanilla', (extra, body['unknownLayers'], body['colors'])


def test_unit_status_covers_its_parts(project):
    """Up-B's charge flames live in EfCoData.dat: a recolor there makes the
    move Custom even though EfFxData.dat is untouched."""
    project.put('EfFxData.dat')
    target = project.put('EfCoData.dat')
    body = project.get('Fox', 'upb')
    assert body['status'] == 'vanilla'
    assert body['parts']['charge_flames']['status'] == 'vanilla'

    cfg = get_extra_type('Fox', 'charge_flames')
    safety = helpers.make_write_safety(target, 'charge_flames', 'EfCoData.dat', cfg['vanilla'])
    layer = next(k for k in cfg['vanilla'] if k in cfg['offsets'])
    color_patch.apply_hex_patches(target, cfg['offsets'], {layer: {'color': '12AB34'}}, safety=safety)
    body = project.get('Fox', 'upb')
    assert body['parts']['charge_flames']['status'] == 'custom'
    assert body['status'] == 'custom' and body['isVanilla'] is False


def test_unit_with_a_missing_primary_file_is_a_404_not_a_crash(project):
    project.put('EfCoData.dat')  # EfFxData.dat (the Up-B primary) is missing
    response = project.client.get('/api/mex/storage/extras/current/Fox/upb')
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Shifted layout
# ---------------------------------------------------------------------------

def test_shifted_file_reads_relocated_operands_not_stale_offsets(project):
    """Charge flames (EfCoData particle operands): after a layout shift the
    install relocates by operand identity -- the read must follow it."""
    cfg = get_extra_type('Fox', 'charge_flames')
    shifted = _shift_ef_file(_vanilla('EfCoData.dat').read_bytes())
    target = project.put('EfCoData.dat', data=shifted)
    safety = helpers.make_write_safety(target, 'charge_flames', 'EfCoData.dat', cfg['vanilla'])
    layer = next(k for k in cfg['vanilla'] if k in cfg['offsets'])
    assert color_patch.apply_hex_patches(target, cfg['offsets'], {layer: {'color': '12AB34'}},
                                     safety=safety) == []

    stale = helpers.read_current_colors(target, {layer: cfg['offsets'][layer]})[layer]
    assert stale != '12AB34'  # the old reader looked at the wrong bytes

    body = project.get('Fox', 'charge_flames')
    assert body['colors'][layer] == '12AB34'
    assert body['status'] == 'custom'
    assert body['unknownLayers'] == []


def test_shifted_untouched_file_still_reads_vanilla(project):
    cfg = get_extra_type('Fox', 'charge_flames')
    project.put('EfCoData.dat', data=_shift_ef_file(_vanilla('EfCoData.dat').read_bytes()))
    body = project.get('Fox', 'charge_flames')
    assert body['status'] == 'vanilla', body['unknownLayers']


def test_shifted_raw_layers_are_unknown_not_garbage(project):
    """Raw spans (written in place, no relocation) in a file whose layout
    moved: the old reader returned whatever bytes sat at the stale offset."""
    cfg = get_extra_type('Marth', 'sword')
    project.put(cfg['target_file'], data=b'\0' * 64 + _vanilla(cfg['target_file']).read_bytes())
    body = project.get('Marth', 'sword')
    assert body['status'] == 'unknown'
    assert body['isVanilla'] is False
    compared = [k for k in cfg['vanilla'] if k in cfg['offsets']]
    assert set(compared) <= set(body['unknownLayers'])
    assert not set(body['colors']) & set(body['unknownLayers'])


def test_unrelated_file_is_unknown(project):
    cfg = get_extra_type('Mario', 'mario_fireball')
    project.put(cfg['target_file'], data=b'\xAB' * 4096)
    body = project.get('Mario', 'mario_fireball')
    assert body['status'] == 'unknown'
    assert body['colors'] == {}


def test_shine_reads_channels_by_vertex_identity_in_a_moved_file(project):
    cfg = get_extra_type('Fox', 'shine')
    target = project.put('EfFxData.dat',
                         data=b'\0' * 96 + _vanilla('EfFxData.dat').read_bytes())
    helpers.patch_shine_color_slots(target, cfg, {'primary': {'color': 'FC00'},
                                                  'secondary': {'color': '03FF'}})
    body = project.get('Fox', 'shine')
    assert body['colors']['primary'] == 'FC00'
    assert body['colors']['secondary'] == '03FF'
    assert body['status'] == 'custom'


def test_shine_vanilla_and_unidentifiable(project):
    project.put('EfFxData.dat')
    assert project.get('Fox', 'shine')['status'] == 'vanilla'
    project.put('EfFxData.dat', data=b'\xAB' * 4096)
    body = project.get('Fox', 'shine')
    assert body['status'] == 'unknown'
    assert {'primary', 'secondary'} <= set(body['unknownLayers'])


# ---------------------------------------------------------------------------
# Types without color offsets: texture recolors, the shield texture, models
# ---------------------------------------------------------------------------

def _texture_recolor_extras():
    seen, cases = set(), []
    for character, types in EXTRA_TYPES.items():
        for cfg in types:
            if cfg.get('format') == 'texture_recolor' and cfg['id'] not in seen:
                seen.add(cfg['id'])
                cases.append((character, cfg['id']))
    return cases


@pytest.mark.parametrize('character,extra', _texture_recolor_extras())
def test_texture_recolor_verdict_comes_from_bytes_not_the_hue_estimate(project, character, extra):
    """The dominant-hue swatch is an estimate: on untouched files it differs
    from the config swatch for some textures (charge ball, coins), which made
    them read Custom. The verdict is now the texture's exact bytes."""
    from vault.extras import texture_recolor
    cfg = get_extra_type(character, extra)
    target = project.put(cfg['target_file'])
    prop = cfg['properties'][0]['id']

    body = project.get(character, extra)
    assert body['status'] == 'vanilla', body
    assert body['colors'] == {prop: cfg['vanilla'][prop]}
    assert body['approximate'] is False

    tex_cfg = dict(cfg['texture'], _target_file=cfg['target_file'])
    texture_recolor.apply_texture_recolor(target, tex_cfg, '00FF40')
    body = project.get(character, extra)
    assert body['status'] == 'custom' and body['isVanilla'] is False
    assert body['approximate'] is True
    assert len(body['colors'][prop]) == 6

    texture_recolor.restore_texture_recolor(target, tex_cfg)
    assert project.get(character, extra)['status'] == 'vanilla'


def test_texture_recolor_in_a_moved_file_is_unknown(project):
    cfg = get_extra_type('Mario', 'mario_coins')
    project.put(cfg['target_file'], data=b'\0' * 64 + _vanilla(cfg['target_file']).read_bytes())
    body = project.get('Mario', 'mario_coins')
    assert body['status'] == 'unknown'
    assert body['colors'] == {}
    assert body['detail']


def test_texture_recolor_without_a_reference_is_unknown(project, monkeypatch):
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name, **kwargs: None)
    cfg = get_extra_type('Mario', 'mario_coins')
    project.put(cfg['target_file'], reference=False)
    assert project.get('Mario', 'mario_coins')['status'] == 'unknown'


def test_shield_texture_region(project, monkeypatch):
    from vault.extras import texture_region
    cfg = get_extra_type('Fox', 'common_shield')
    target = project.put(cfg['target_file'])
    body = project.get('Fox', 'common_shield')
    assert body['status'] == 'vanilla' and body['isVanilla'] is True

    region = texture_region.read_region(target, cfg)
    texture_region.write_region(target, cfg, bytes(b ^ 0xFF for b in region))
    body = project.get('Fox', 'common_shield')
    assert body['status'] == 'custom' and body['isVanilla'] is False

    # No reference to compare with: it used to report Vanilla here.
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name, **kwargs: None)
    body = project.get('Fox', 'common_shield')
    assert body['status'] == 'unknown' and body['isVanilla'] is False
    assert body['detail']


def test_model_extras_are_not_claimed_vanilla(project):
    cfg = get_extra_type('Fox', 'gun')
    project.put(cfg['target_file'])
    body = project.get('Fox', 'gun')
    assert body['status'] == 'unknown'
    assert body['isVanilla'] is False
    assert body['detail']


# ---------------------------------------------------------------------------
# No vanilla reference: previous behavior, flagged unverified
# ---------------------------------------------------------------------------

def test_without_a_vanilla_reference_reads_in_place_like_before(project, monkeypatch):
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name, **kwargs: None)
    cfg = get_extra_type('Mario', 'mario_fireball')
    target = project.put(cfg['target_file'], reference=False)
    body = project.get('Mario', 'mario_fireball')
    assert body['layoutVerified'] is False
    assert body['colors'] == helpers.read_current_colors(target, cfg['offsets'])
    assert body['unknownLayers'] == []


# ---------------------------------------------------------------------------
# current_verdict
# ---------------------------------------------------------------------------

def test_verdict_ignores_summary_swatches_without_layers():
    offsets = {'a_c1': {}, 'a_c2': {}}
    vanilla = {'color1': 'FFFFFF', 'color2': '000000', 'a_c1': '111111', 'a_c2': '222222'}
    assert color_read.current_verdict({'a_c1': '111111', 'a_c2': '222222'}, vanilla, offsets) == 'vanilla'


def test_verdict_prefers_reference_bytes():
    offsets = {'a': {}}
    assert color_read.current_verdict({'a': '123456'}, {'a': 'FFFFFF'}, offsets,
                                   reference={'a': '123456'}) == 'vanilla'
    assert color_read.current_verdict({'a': 'FFFFFF'}, {'a': 'FFFFFF'}, offsets,
                                   reference={'a': '123456'}) == 'custom'


def test_verdict_unknown_rules():
    offsets = {'a': {}, 'b': {}}
    vanilla = {'a': '11', 'b': '22'}
    # an unread compared layer and nothing proven custom -> unknown
    assert color_read.current_verdict({'a': '11'}, vanilla, offsets, ['b']) == 'unknown'
    # a proven-different layer is Custom even if another is unread
    assert color_read.current_verdict({'a': '99'}, vanilla, offsets, ['b']) == 'custom'
    # nothing to compare at all -> unknown, never a guessed Vanilla
    assert color_read.current_verdict({'a': '11'}, {}, offsets) == 'unknown'
