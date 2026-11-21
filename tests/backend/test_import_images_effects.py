"""Loose images and effect DATs through the ONE import button.

Covers the classifier's image rules (door / pause picture / glyph + word
packs / effect pictures), effect-file candidate ranking against vanilla, the
multi-file upload packing, and the choice-dialog protocol the route uses
when an upload is genuinely ambiguous.
"""
import io
import zipfile

import pytest
from flask import Flask
from PIL import Image

import vault.routes.import_unified.routes as routes
import vault.importing.unified.detected_effects as detected_effects
import vault.importing.unified.menu_import as menu_import
import vault.importing.unified.archive as unified_archive
import vault.importing.unified.detection as detection
import vault.importing.unified.effect_detect as effect_detect
from vault.routes.import_unified import import_bp


# ── helpers ───────────────────────────────────────────────────────────────────

def _png(w, h, color=(200, 30, 30, 255)):
    buf = io.BytesIO()
    Image.new('RGBA', (w, h), color).save(buf, format='PNG')
    return buf.getvalue()


def _zip_path(tmp_path, members, name='upload.zip'):
    p = tmp_path / name
    with zipfile.ZipFile(p, 'w') as zf:
        for member, payload in members.items():
            zf.writestr(member, payload)
    return p


def _client():
    app = Flask(__name__)
    app.register_blueprint(import_bp)
    return app.test_client()


def _quiet_other_phases(monkeypatch):
    monkeypatch.setattr(unified_archive, 'detect_character_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, 'detect_stage_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, 'import_vanilla_stage_dats', lambda *_a, **_k: [])
    monkeypatch.setattr(unified_archive, 'looks_like_pause_zip', lambda _p: False)
    monkeypatch.setattr(menu_import, 'looks_like_pause_zip', lambda _p: False)
    monkeypatch.setattr(unified_archive, 'looks_like_percent_zip', lambda _p: False)
    monkeypatch.setattr(detection, 'detect_character_from_zip', lambda _p: [])
    monkeypatch.setattr(detection, 'detect_stage_from_zip', lambda _p: [])


def _post(client, files, **form):
    data = {'file': [(io.BytesIO(payload), name) for name, payload in files]}
    data.update(form)
    return client.post('/api/mex/import/file', data=data,
                       content_type='multipart/form-data')


# ── detection: images ─────────────────────────────────────────────────────────

def test_lone_image_sized_like_a_door_is_a_door(tmp_path):
    verdict = detection.detect_content_type(_zip_path(tmp_path, {'thing.png': _png(128, 200)}))
    assert verdict['type'] == 'css_doors'
    assert verdict['confidence'] == 'high'


def test_lone_image_named_pause_is_a_pause_picture(tmp_path):
    verdict = detection.detect_content_type(_zip_path(tmp_path, {'my pause.jpg': _png(640, 480)}))
    assert verdict['type'] == 'pause_picture'
    assert verdict['confidence'] == 'high'


def test_ten_digit_images_are_a_glyph_pack(tmp_path):
    members = {f'{d}.png': _png(32, 32) for d in range(10)}
    members['readme.txt'] = b'digits'
    verdict = detection.detect_content_type(_zip_path(tmp_path, members))
    assert verdict['type'] == 'percent_font'
    assert verdict['detail']['pack'] == 'glyphs'
    assert verdict['confidence'] == 'high'


def test_word_banners_are_a_ready_go_pack(tmp_path):
    members = {'ready.png': _png(280, 84), 'go!.png': _png(376, 188), 'game2.png': _png(528, 144)}
    verdict = detection.detect_content_type(_zip_path(tmp_path, members))
    assert verdict['type'] == 'percent_font'
    assert verdict['detail']['pack'] == 'words'
    assert verdict['detail']['category'] == 'readygo'


def test_image_named_shield_is_the_shield_texture(tmp_path):
    verdict = detection.detect_content_type(_zip_path(tmp_path, {'cool shield.png': _png(128, 128)}))
    assert verdict['type'] == 'effect_image'
    assert verdict['detail']['extra_type'] == 'common_shield'
    assert verdict['detail']['character'] == 'Fox'
    assert verdict['confidence'] == 'high'


def test_shine_sized_image_is_a_medium_effect_candidate(tmp_path):
    verdict = detection.detect_content_type(_zip_path(tmp_path, {'x.png': _png(256, 256)}))
    assert verdict['type'] == 'effect_image'
    assert verdict['detail']['extra_type'] == 'shine'
    assert verdict['confidence'] == 'medium'
    assert 'pause_picture' in verdict['candidates']


def test_unnamed_wide_image_is_ambiguous(tmp_path):
    verdict = detection.detect_content_type(_zip_path(tmp_path, {'x.png': _png(300, 200)}))
    assert verdict['type'] == 'pause_picture'
    assert verdict['confidence'] != 'high'
    assert set(verdict['candidates']) >= {'pause_picture', 'css_doors'}


def test_several_door_named_images_are_all_doors(tmp_path):
    members = {'door a.png': _png(128, 200), 'door b.png': _png(128, 200)}
    verdict = detection.detect_content_type(_zip_path(tmp_path, members))
    assert verdict['type'] == 'css_doors'
    assert verdict['confidence'] == 'high'
    assert verdict['detail']['images'] == ['door a.png', 'door b.png']


# ── detection: effect files ───────────────────────────────────────────────────

def test_match_target_accepts_decorated_ef_names_and_bare_pl_files():
    assert effect_detect.match_target('EfFxDataBRAT.dat')[0] == 'EfFxData.dat'
    assert effect_detect.match_target('EfCoData rainbow fire.dat')[0] == 'EfCoData.dat'
    assert effect_detect.match_target('PlFx.dat')[0] == 'PlFx.dat'
    assert effect_detect.match_target('PlFx (v2).dat')[0] == 'PlFx.dat'
    # a costume is never an effect file
    assert effect_detect.match_target('PlFxNr.dat') == (None, [])
    assert effect_detect.match_target('GrNBa.dat') == (None, [])


def _fake_signatures(monkeypatch, vanilla_path, readings):
    """readings: {extra_type: (mod_sig, vanilla_sig | None)}; unlisted types
    are unreadable."""
    def fake_sig(path, cfg):
        if cfg['id'] not in readings:
            return None
        mod_sig, van_sig = readings[cfg['id']]
        return van_sig if str(path) == str(vanilla_path) else mod_sig
    monkeypatch.setattr(effect_detect, '_signature', fake_sig)


def _effx_types():
    """Two extra types that really target EfFxData.dat (shine + another)."""
    ids = [cfg['id'] for _owner, cfg in effect_detect.match_target('EfFxData.dat')[1]]
    assert 'shine' in ids and len(ids) >= 2
    other = next(i for i in ids if i != 'shine')
    return 'shine', other


def test_candidate_effects_ranks_differing_types_first(monkeypatch, tmp_path):
    shine, other = _effx_types()
    vanilla = tmp_path / 'EfFxData.dat'
    vanilla.write_bytes(b'v')
    monkeypatch.setattr(effect_detect, '_vanilla_ref', lambda _t: vanilla)
    _fake_signatures(monkeypatch, vanilla, {
        other: (('colors', {'a': 1}), ('colors', {'a': 1})),      # unchanged
        shine: (('colors', {'hex': 2}), ('colors', {'hex': 1})),  # recolored
    })
    cands = effect_detect.candidate_effects(b'mod', 'EfFxData.dat')
    assert [c['extra_type'] for c in cands] == [shine, other]
    assert cands[0]['differs'] is True and cands[0]['character'] == 'Fox'
    assert cands[1]['differs'] is False


def test_candidate_effects_is_undecidable_without_a_vanilla_reference(monkeypatch, tmp_path):
    shine, _other = _effx_types()
    monkeypatch.setattr(effect_detect, '_vanilla_ref', lambda _t: None)
    _fake_signatures(monkeypatch, tmp_path / 'none', {shine: (('colors', {'a': 1}), None)})
    cands = effect_detect.candidate_effects(b'mod', 'EfFxData.dat')
    assert [c['extra_type'] for c in cands] == [shine]
    assert cands[0]['differs'] is None


# ── route: images ─────────────────────────────────────────────────────────────

def test_a_loose_picture_always_asks_with_the_best_guess_preselected(vault, monkeypatch):
    # Even a door-shaped, door-named PNG is never filed on a guess from the
    # global Import button; the "+" card on the Doors kind is the no-questions path.
    _quiet_other_phases(monkeypatch)
    monkeypatch.setattr(menu_import, 'import_door_image',
                        lambda *_a, **_k: pytest.fail('door importer must not run without an answer'))
    resp = _post(_client(), [('blue door.png', _png(128, 200))])
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body['type'] == 'choice_dialog'
    assert body['default'] == 'css_doors'
    assert {o['key'] for o in body['options']} >= {'css_doors', 'pause_picture'}


def test_kind_hint_files_pictures_without_asking(vault, monkeypatch):
    # The Menus page's "+ New Door" card: explicit mod_type, several pictures at once.
    _quiet_other_phases(monkeypatch)
    calls = []
    monkeypatch.setattr(menu_import, 'import_door_image',
                        lambda data, name, description='': calls.append(name) or {'id': name, 'name': name})
    files = [(f'door{i}.png', _png(128, 200)) for i in range(3)]
    body = _post(_client(), files, mod_type='css_doors').get_json()
    assert body['success'] is True
    assert body['menu_mod_type'] == 'css_doors'
    assert body['imported_count'] == 3
    assert calls == ['door0', 'door1', 'door2']
    assert 'Doors' in body['message']


def test_ambiguous_picture_asks_then_honors_the_answer(vault, monkeypatch):
    _quiet_other_phases(monkeypatch)
    pause_calls = []
    monkeypatch.setattr(menu_import, 'import_pause_picture',
                        lambda data, name, description='': pause_calls.append(name) or {'id': 'p1', 'name': name})
    monkeypatch.setattr(menu_import, 'import_door_image',
                        lambda *_a, **_k: pytest.fail('door importer must not run'))
    client = _client()
    resp = _post(client, [('x.png', _png(300, 200))])
    body = resp.get_json()
    assert resp.status_code == 200
    assert body['type'] == 'choice_dialog'
    keys = [o['key'] for o in body['options']]
    assert 'pause_picture' in keys and 'css_doors' in keys
    assert body['default'] == 'pause_picture'

    answer = next(o for o in body['options'] if o['key'] == 'pause_picture')['hints']
    body2 = _post(client, [('x.png', _png(300, 200))], **answer).get_json()
    assert body2['success'] is True
    assert body2['menu_mod_type'] == 'pause_screen'
    assert pause_calls == ['x']


def test_mnslchr_only_zip_asks_icon_grid_or_background(vault, monkeypatch):
    _quiet_other_phases(monkeypatch)
    installs = []
    monkeypatch.setattr(unified_archive, 'install_icon_grid_mod',
                        lambda p, name=None, description='': installs.append(name) or [{'id': 'ig', 'name': name}])
    client = _client()
    body = _post(client, [('MnSlChr.dat', b'not really a dat')]).get_json()
    assert body['type'] == 'choice_dialog'
    assert body['default'] == 'css_icon_grid'
    assert [o['key'] for o in body['options']] == ['css_icon_grid', 'css_background']

    body2 = _post(client, [('MnSlChr.dat', b'not really a dat')], mod_type='css_icon_grid').get_json()
    assert body2['success'] is True and body2['menu_mod_type'] == 'css_icon_grid'
    assert installs == ['MnSlChr']


def test_effect_picture_by_name_is_offered_first_then_imported(vault, monkeypatch):
    _quiet_other_phases(monkeypatch)
    seen = {}

    def fake_import(temp_zip, character, effect_type, custom_title):
        seen.update(character=character, effect_type=effect_type)
        return {'success': True, 'type': 'effect', 'imported_count': 1, 'message': 'ok'}, 200
    monkeypatch.setattr(unified_archive, '_import_effect_image', fake_import)
    client = _client()
    body = _post(client, [('neon shield.png', _png(128, 128))]).get_json()
    assert body['type'] == 'choice_dialog'
    first = body['options'][0]
    assert body['default'] == first['key']
    assert first['hints'] == {'mod_type': 'effect_image', 'character': 'Fox', 'effect_type': 'common_shield'}

    body2 = _post(client, [('neon shield.png', _png(128, 128))], **first['hints']).get_json()
    assert body2['success'] is True
    assert seen == {'character': 'Fox', 'effect_type': 'common_shield'}


# ── route: effect files ───────────────────────────────────────────────────────

def _effect_upload(monkeypatch, candidates):
    _quiet_other_phases(monkeypatch)
    monkeypatch.setattr(effect_detect, 'candidate_effects', lambda data, basename: candidates)
    monkeypatch.setattr(unified_archive, '_effect_duplicate_response', lambda *_a, **_k: None)
    monkeypatch.setattr(detected_effects, '_effect_duplicate_response', lambda *_a, **_k: None)


def test_effect_dat_imports_every_differing_type(vault, monkeypatch):
    _effect_upload(monkeypatch, [
        {'character': 'Fox', 'extra_type': 'shine', 'name': 'Shine Color', 'differs': True},
        {'character': 'Fox', 'extra_type': 'laser', 'name': 'Laser Color', 'differs': True},
        {'character': 'Fox', 'extra_type': 'sideb', 'name': 'Side-B', 'differs': False},
    ])
    calls = []

    def fake_effect_import(zip_path, zip_name, effect_type, custom_title=None):
        calls.append((zip_name, effect_type, custom_title))
        return {'success': True, 'type': 'effect', 'imported_count': 1,
                'character': 'Fox', 'effect_type': effect_type, 'message': f'{effect_type} ok'}
    monkeypatch.setattr(unified_archive, '_import_effect_mod', fake_effect_import)
    monkeypatch.setattr(detected_effects, '_import_effect_mod', fake_effect_import)

    body = _post(_client(), [('EfFxDataBRAT.dat', b'x' * 64)]).get_json()
    assert body['success'] is True and body['type'] == 'effect'
    assert body['imported_count'] == 2
    assert calls == [
        ('Fox_EfFxDataBRAT.zip', 'shine', 'EfFxDataBRAT (Shine Color)'),
        ('Fox_EfFxDataBRAT.zip', 'laser', 'EfFxDataBRAT (Laser Color)'),
    ]
    assert 'Characters › Fox › Extras' in body['message']


def test_effect_dat_matching_vanilla_everywhere_is_refused(vault, monkeypatch):
    _effect_upload(monkeypatch, [
        {'character': 'Fox', 'extra_type': 'shine', 'name': 'Shine Color', 'differs': False},
    ])
    monkeypatch.setattr(unified_archive, '_import_effect_mod',
                        lambda *_a, **_k: pytest.fail('nothing should be imported'))
    monkeypatch.setattr(detected_effects, '_import_effect_mod',
                        lambda *_a, **_k: pytest.fail('nothing should be imported'))
    resp = _post(_client(), [('EfFxData.dat', b'x' * 64)])
    assert resp.status_code == 400
    assert 'matches vanilla' in resp.get_json()['error']


def test_effect_dat_without_vanilla_reference_asks(vault, monkeypatch):
    _effect_upload(monkeypatch, [
        {'character': 'Fox', 'extra_type': 'shine', 'name': 'Shine Color', 'differs': None},
        {'character': 'Fox', 'extra_type': 'laser', 'name': 'Laser Color', 'differs': None},
    ])
    body = _post(_client(), [('EfFxData.dat', b'x' * 64)]).get_json()
    assert body['type'] == 'choice_dialog'
    assert [o['hints'] for o in body['options']] == [
        {'mod_type': 'effect', 'effect_type': 'shine', 'character': 'Fox'},
        {'mod_type': 'effect', 'effect_type': 'laser', 'character': 'Fox'},
    ]


def test_explicit_effect_hint_with_character_names_the_archive(vault, monkeypatch):
    _quiet_other_phases(monkeypatch)
    monkeypatch.setattr(unified_archive, '_effect_duplicate_response', lambda *_a, **_k: None)
    monkeypatch.setattr(detected_effects, '_effect_duplicate_response', lambda *_a, **_k: None)
    seen = {}

    def fake_effect_import(zip_path, zip_name, effect_type, custom_title=None):
        seen.update(zip_name=zip_name, effect_type=effect_type)
        return {'success': True, 'type': 'effect', 'imported_count': 1,
                'character': 'Fox', 'effect_type': effect_type, 'message': 'ok'}
    monkeypatch.setattr(unified_archive, '_import_effect_mod', fake_effect_import)
    monkeypatch.setattr(detected_effects, '_import_effect_mod', fake_effect_import)
    body = _post(_client(), [('EfFxData.dat', b'x' * 64)],
                 mod_type='effect', effect_type='shine', character='Fox').get_json()
    assert body['success'] is True
    assert seen == {'zip_name': 'Fox_EfFxData.zip', 'effect_type': 'shine'}


def test_character_file_without_extras_is_explained(vault, monkeypatch, tmp_path):
    # PlPe.dat is Peach's data file; no extra type reads it (yet).
    verdict = detection.detect_content_type(_zip_path(tmp_path, {'PlPe (turnip).dat': b'x' * 64}))
    assert verdict['type'] == 'effect_unsupported'
    assert verdict['detail']['characters'] == ['Peach']

    _quiet_other_phases(monkeypatch)
    resp = _post(_client(), [('PlPe.dat', b'x' * 64)])
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['type'] == 'effect_unsupported'
    assert 'Peach' in body['error']


def test_unsupported_extension_is_rejected_up_front(vault):
    resp = _post(_client(), [('song.mp3', b'ID3')])
    assert resp.status_code == 400
    assert 'image' in resp.get_json()['error']
