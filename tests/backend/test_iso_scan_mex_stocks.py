"""
Tests for ISO-scan stock-icon extraction off an m-ex disc.

m-ex replaces the vanilla `Stc_scemdls` stock table with its own `Stc_icns`,
keyed `reserved + costumeId * stride + internalId`, and keeps the costume order
that costumeId indexes in MxDt rather than main.dol. Every modded disc worth
scanning is an m-ex build, so this is the path that decides whether an imported
skin arrives with its real icon or a generated stand-in.
"""
from tests.paths import BACKEND
import sys
from pathlib import Path

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from vault.importing import iso_scanner as scanner
import vault.importing.iso_slot_art as slot_art

# Trimmed shape of `HSDRawViewer --mex-css-info export`: Mario is internal 0,
# Link internal 6 with one costume past vanilla's five.
CSS_INFO = {
    'fighter_costumes': [
        {'internal_id': 0, 'costumes': [
            {'costume_id': 0, 'file_name': 'PlMrNr.dat'},
            {'costume_id': 1, 'file_name': 'PlMrYe.dat'},
        ]},
        {'internal_id': 6, 'costumes': [
            {'costume_id': 0, 'file_name': 'PlLkNr.dat'},
            {'costume_id': 5, 'file_name': 'PlLkFd.dat'},
        ]},
    ]
}


def test_frames_follow_the_mex_stock_formula():
    frames = slot_art.mex_costume_stock_frames(CSS_INFO, reserved=11, stride=39)
    assert frames['plmrnr'] == 11                    # 11 + 0*39 + 0
    assert frames['plmrye'] == 11 + 39               # second Mario costume
    assert frames['pllknr'] == 11 + 6                # Link, first costume
    assert frames['pllkfd'] == 11 + 5 * 39 + 6       # the added sixth costume


def test_unusable_entries_are_skipped_not_fatal():
    frames = slot_art.mex_costume_stock_frames({'fighter_costumes': [
        {'internal_id': None, 'costumes': [{'costume_id': 0, 'file_name': 'PlFxNr.dat'}]},
        {'internal_id': 1, 'costumes': [
            {'costume_id': 'x', 'file_name': 'PlFxNr.dat'},   # unparseable id
            {'costume_id': 0, 'file_name': ''},               # no file name
            {'costume_id': 2, 'file_name': 'PlFxLa.dat'},     # the good one
        ]},
    ]}, reserved=11, stride=39)
    assert frames == {'plfxla': 11 + 2 * 39 + 1}


def test_missing_tables_yield_no_frames():
    assert slot_art.mex_costume_stock_frames({}, 11, 39) == {}
    assert slot_art.mex_costume_stock_frames({'fighter_costumes': None}, 11, 39) == {}


def test_mex_manifest_reads_costume_order_from_mxdt(tmp_path, monkeypatch):
    (tmp_path / 'files').mkdir()
    (tmp_path / 'files' / 'MxDt.dat').write_bytes(b'mxdt')
    monkeypatch.setattr(slot_art, '_run_mex_css_info', lambda *_: CSS_INFO)

    frames = slot_art._costume_frames_for_manifest(
        tmp_path, {'format': 'mex', 'reserved': 11, 'stride': 39}, tmp_path / 'out')

    assert frames['pllkfd'] == 11 + 5 * 39 + 6


def test_mex_disc_without_mxdt_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(slot_art, '_run_mex_css_info',
                        lambda *_: pytest_fail('MxDt is absent; nothing to read'))
    assert slot_art._costume_frames_for_manifest(
        tmp_path, {'format': 'mex', 'reserved': 11, 'stride': 39}, tmp_path) == {}


def test_mex_stock_table_without_geometry_is_skipped(tmp_path, monkeypatch):
    (tmp_path / 'MxDt.dat').write_bytes(b'mxdt')
    monkeypatch.setattr(slot_art, '_run_mex_css_info',
                        lambda *_: pytest_fail('reserved/stride are required first'))
    assert slot_art._costume_frames_for_manifest(tmp_path, {'format': 'mex'}, tmp_path) == {}


def test_vanilla_discs_still_read_the_dol(tmp_path, monkeypatch):
    (tmp_path / 'main.dol').write_bytes(b'dol')
    monkeypatch.setattr(slot_art, '_read_dol_costume_stock_frames', lambda _: {'plfxnr': 1})
    assert slot_art._costume_frames_for_manifest(
        tmp_path, {'format': 'vanilla'}, tmp_path) == {'plfxnr': 1}


def test_unknown_stock_table_is_skipped(tmp_path):
    assert slot_art._costume_frames_for_manifest(tmp_path, {'format': 'martian'}, tmp_path) == {}


def pytest_fail(message):
    raise AssertionError(message)
