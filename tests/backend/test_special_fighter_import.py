"""Costumes for special fighters (Giga Bowser, wireframes, hands, Sandbag) go
to the matching custom character, never to the Characters grid.

Discord 2026-09-09 (.hello_41): a bulk Bowser pack created a nameless "G" tab
in the vault (its PlGkNr.dat had been filed as a `characters` entry), and a
wireframe recolor pack landed under Young Link because the DAT detector
mapped ftDataBoy/ftDataGirl (the wireframes) to Young Link.
"""
import io
import json
import zipfile

from vault.catalog import custom_character_skins as cc_skins


def _costume_zip(dat_name=b'PlGkRe.dat'):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(dat_name.decode(), b'\0' * 64)
        zf.writestr('csp.png', b'\x89PNG\r\n\x1a\n' + b'\0' * 16)
    return buf.getvalue()


def test_missing_custom_character_gives_a_clear_reason():
    meta = {'characters': {}, 'custom_characters': []}
    skin, reason = cc_skins.add_special_fighter_costume(meta, 'Wireframe Male', _costume_zip(b'PlBoRe.dat'), 'Red')
    assert skin is None
    assert 'Wireframe Male' in reason
    assert meta['characters'] == {}          # never filed under the grid


def test_giga_bowser_not_set_up_yet_points_at_setup():
    meta = {'characters': {}, 'custom_characters': []}
    skin, reason = cc_skins.add_special_fighter_costume(meta, 'Giga Bowser', _costume_zip(), 'Red')
    assert skin is None
    assert 'Set up Giga Bowser' in reason


def test_costume_is_routed_to_the_custom_character(tmp_path, monkeypatch):
    monkeypatch.setattr(cc_skins, 'CUSTOM_CHARACTERS_PATH', tmp_path)
    (tmp_path / 'giga-bowser').mkdir()
    (tmp_path / 'giga-bowser' / 'fighter.json').write_text(json.dumps({'name': 'Giga Bowser'}))
    monkeypatch.setattr(cc_skins, '_validate_costume_zip', lambda b: ('PlGkRe.dat', None))
    monkeypatch.setattr(cc_skins, '_extract_skin_previews', lambda d, i, b: (True, False))
    entry = {'slug': 'giga-bowser', 'name': 'Giga Bowser', 'builtin': True}
    meta = {'characters': {}, 'custom_characters': [entry]}

    skin, reason = cc_skins.add_special_fighter_costume(meta, 'Giga Bowser', _costume_zip(), 'Red')
    assert reason is None
    assert skin['slug'] == 'giga-bowser' and skin['color'] == 'Red'
    assert entry['added_skins'][0]['id'] == skin['id']
    assert (tmp_path / 'giga-bowser' / 'skins' / f"{skin['id']}.zip").exists()
    assert 'Giga Bowser' not in meta['characters']


def test_special_names_are_the_non_roster_fighters():
    assert {'Giga Bowser', 'Wireframe Male', 'Wireframe Female'} <= cc_skins.SPECIAL_FIGHTER_NAMES
    assert 'Young Link' not in cc_skins.SPECIAL_FIGHTER_NAMES
