"""
Tests for DAS stage-skin detection (vault/importing/stage_detector.py).

Two shapes matter and both used to be rejected outright with "Could not detect
mod type. ZIP does not contain any recognized files":

  * A plain Pokemon Stadium skin as '.dat'. The detector demanded '.usd' for
    GrPs, which is backwards -- the m-ex DAS loader only accepts '.dat' alts
    and every current export writes '.dat' (see the .usd migration in
    projects/install/das.py).
  * A per-transformation Stadium bundle: '<Variant>.dat' plus a sibling folder
    '<Variant>/GrPs1..4.dat'. The base names the variant, not the stage, so
    nothing in the filename scan could see it.
"""
import io
import zipfile

import pytest

from vault.importing.stage_detector import (
    detect_stage_from_zip,
    find_stadium_bundle_bases,
)


def make_zip(tmp_path, members, name='mod.zip'):
    path = tmp_path / name
    with zipfile.ZipFile(path, 'w') as zf:
        for member, data in members.items():
            zf.writestr(member, data)
    return str(path)


def png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (16, 9)).save(buf, format='PNG')
    return buf.getvalue()


# ---------- extension handling ----------

@pytest.mark.parametrize('member,code', [
    ('GrPs.dat', 'GrPs'),            # what current Stadium exports write
    ('GrPs.usd', 'GrPs'),            # legacy spelling, still readable
    ('GrPs_MHStadium.dat', 'GrPs'),  # code as a prefix of a longer name
    ('GrNBa.dat', 'GrNBa'),
    ('GrOp2.dat', 'GrOp'),           # a Dream Land variant, not a transform
    ('GrSt.usd', 'GrSt'),
])
def test_single_stage_files_detect(tmp_path, member, code):
    infos = detect_stage_from_zip(make_zip(tmp_path, {member: b'stage'}))
    assert [i['stage_code'] for i in infos] == [code]
    assert infos[0]['stage_file'] == member


@pytest.mark.parametrize('member', ['GrPs.png', 'GrNBa.txt', 'readme.dat'])
def test_non_stage_members_ignored(tmp_path, member):
    assert detect_stage_from_zip(make_zip(tmp_path, {member: b'x'})) == []


# ---------- every versus stage, not just the six ----------

@pytest.mark.parametrize('member,code,folder', [
    ('GrGr.dat', 'GrGr', 'green_greens'),         # Green Greens
    ('Legal Big Blue GrBb.dat', 'GrBb', 'big_blue'),
    ('GrCn.usd', 'GrCn', 'corneria'),             # English-language root
    ('GrI2.dat', 'GrI2', 'mushroom_kingdom_ii'),  # digit-final code
    ('GrOk_remix.dat', 'GrOk', 'kongo_jungle_n64'),
])
def test_non_tournament_stage_dats_detect_as_stage_skins(tmp_path, member, code, folder):
    infos = detect_stage_from_zip(make_zip(tmp_path, {member: b'stage'}))
    assert [(i['stage_code'], i['folder']) for i in infos] == [(code, folder)]


@pytest.mark.parametrize('member', [
    'GrGreatPlateau.dat',   # 'GrGr' must not match as a prefix of a longer word
    'GrKgX.dat',            # nor with a trailing letter
    'GrTzd.dat',            # unknown custom-stage code
])
def test_code_must_be_a_whole_token(tmp_path, member):
    assert detect_stage_from_zip(make_zip(tmp_path, {member: b'x'})) == []


def test_named_stadium_requires_real_stage_root(tmp_path):
    from vault.echo.datroot import build
    data = build(bytes(64), [], [(0, 'map_head')], [])
    infos = detect_stage_from_zip(make_zip(tmp_path, {'GrPsCoO.usd': data, 'preview.png': png_bytes()}))
    assert len(infos) == 1 and infos[0]['stage_code'] == 'GrPs'
    assert infos[0]['screenshot'] == 'preview.png'
    for invalid in [b'not a DAT map_head', build(bytes(64), [], [(0, 'ftDataFox')], []), data[:35]]:
        assert detect_stage_from_zip(make_zip(tmp_path, {'GrPsCoO.usd': invalid})) == []


# ---------- Stadium transformation bundles ----------

BUNDLE = {
    'Minecraft.dat': b'base',
    'Minecraft/GrPs1.dat': b'fire',
    'Minecraft/GrPs2.dat': b'grass',
    'Minecraft/GrPs3.dat': b'water',
    'Minecraft/GrPs4.dat': b'rock',
}


def test_bundle_detects_as_one_stadium_variant(tmp_path):
    infos = detect_stage_from_zip(make_zip(tmp_path, BUNDLE))

    # ONE variant, not five: the base is the stage, the four forms ride along
    # (import_stage_mod re-reads them from the source zip).
    assert len(infos) == 1
    assert infos[0]['stage_code'] == 'GrPs'
    assert infos[0]['folder'] == 'pokemon_stadium'
    assert infos[0]['stage_file'] == 'Minecraft.dat'


def test_bundle_nested_under_a_folder(tmp_path):
    nested = {f'skins/{k}': v for k, v in BUNDLE.items()}
    infos = detect_stage_from_zip(make_zip(tmp_path, nested))
    assert [i['stage_file'] for i in infos] == ['skins/Minecraft.dat']


def test_bundle_still_matches_a_screenshot(tmp_path):
    members = dict(BUNDLE, **{'preview.png': png_bytes()})
    infos = detect_stage_from_zip(make_zip(tmp_path, members))
    assert len(infos) == 1
    assert infos[0]['screenshot'] == 'preview.png'


def test_transformation_files_are_never_standalone_variants(tmp_path):
    # A bare forms folder with no base: the loader switches all four paths off
    # GrPs1, so these are not four Stadium skins and must not be imported as
    # such. Detecting nothing is the correct, honest answer.
    forms = {k: v for k, v in BUNDLE.items() if k != 'Minecraft.dat'}
    assert detect_stage_from_zip(make_zip(tmp_path, forms)) == []


def test_partial_form_set_is_not_a_bundle(tmp_path):
    partial = {
        'Minecraft.dat': b'base',
        'Minecraft/GrPs1.dat': b'fire',
        'Minecraft/GrPs2.dat': b'grass',
    }
    # Three of four forms would load garbage for the fourth, so the base is not
    # claimed as a bundle -- and it names no stage code, so nothing matches.
    assert find_stadium_bundle_bases(list(partial)) == set()
    assert detect_stage_from_zip(make_zip(tmp_path, partial)) == []


def test_bundle_alongside_an_unrelated_stage(tmp_path):
    members = dict(BUNDLE, **{'GrNBa.dat': b'battlefield'})
    infos = detect_stage_from_zip(make_zip(tmp_path, members))
    assert sorted(i['stage_file'] for i in infos) == ['GrNBa.dat', 'Minecraft.dat']


def test_find_bundle_bases_requires_all_four(tmp_path):
    assert find_stadium_bundle_bases(list(BUNDLE)) == {'Minecraft'}
    # Root-level forms have no owning folder and so form no bundle.
    assert find_stadium_bundle_bases(
        ['GrPs1.dat', 'GrPs2.dat', 'GrPs3.dat', 'GrPs4.dat']) == set()
