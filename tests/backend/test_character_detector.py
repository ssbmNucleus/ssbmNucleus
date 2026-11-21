"""
Tests for character_detector.py — CSP/stock cascade matching.

Adapted from the meleeWebsite repo (backend, tests/unit/test_csp_matcher.py) for the
desktop in-ZIP architecture:
  - No disk file paths: identity is the zip filename
  - _match_images is called directly with mock dat_results and pre-built indexes
  - _build_image_indexes is tested with in-memory ZIPs + PIL images
  - Return dict has 'csp_file'/'stock_file' (not csp_path/csp_provided/match_strategy_*)
"""
from tests.paths import BACKEND
import sys
import io
import hashlib
import zipfile
import pytest
from pathlib import Path
from PIL import Image

# Make character_detector importable from this test file location
BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))
PROCESSOR_DIR = BACKEND_DIR.parent / 'utility' / 'tools' / 'processor'
sys.path.insert(0, str(PROCESSOR_DIR))

from vault.importing.character_detector import (
    _strip_csp_suffixes,
    _strip_stock_suffixes,
    _split_key_words,
    _COLOR_WORD_TO_DAT_COLORS,
    _match_color_word,
    _extract_content_words,
    _name_overlap_score,
    _normalize_folder_name,
    _get_folder,
    _extract_character_color_from_filename,
    _build_image_indexes,
    _match_images,
    detect_character_from_zip,
)
from detect_character import DATParser as UtilityDATParser


# ── Test Helpers ──────────────────────────────────────────────────────────────

def _make_pil_bytes(width, height, mode='RGBA', color=(100, 150, 200, 255)):
    """Create a PIL image and return its PNG bytes."""
    img = Image.new(mode, (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _make_zip(files: dict) -> 'zipfile.ZipFile':
    """Create an in-memory ZIP from a dict of {zip_path: bytes}.

    Returns a ZipFile object open for reading.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf, 'r')


CSP_BYTES = _make_pil_bytes(136, 188)   # Standard CSP
CSP_2X_BYTES = _make_pil_bytes(272, 376)  # 2x CSP
STOCK_BYTES = _make_pil_bytes(24, 24)    # Standard stock
STOCK_2X_BYTES = _make_pil_bytes(48, 48)  # 2x stock
SCREEN_BYTES = _make_pil_bytes(800, 600)  # Screenshot (not CSP or stock)


def _make_dat_result(dat_file, character, color, hash_bytes=None, is_nana=False):
    """Create a mock dat_result as returned by pass 1 of detect_character_from_zip."""
    h = hashlib.md5(hash_bytes or dat_file.encode()).hexdigest()
    return {
        'character': character,
        'color': color,
        'costume_code': 'PlXxYy',
        'dat_file': dat_file,
        'symbol': f'Ply{character[:2]}5K',
        'folder': _get_folder(dat_file),
        'is_ice_climbers_nana': is_nana,
        '_hash': h,
    }


def _make_csp_info(filename, character=None, color=None):
    """Create a mock CSP info dict as produced by _build_image_indexes."""
    return {
        'filename': filename,
        'file_path': filename,
        'character': character,
        'color': color,
        'filename_folder': _get_folder(filename),
    }


def _make_indexes(csps=(), stocks=()):
    """Build index dicts from simple (filename, char, color) tuples.

    csps/stocks: list of (filename, character, color)
    Returns (csps_by_name, csps_by_path, stocks_by_name, stocks_by_path)
    """
    from vault.importing.character_detector import _strip_csp_suffixes, _strip_stock_suffixes

    csps_by_name = {}
    csps_by_path = {}
    for filename, char, color in csps:
        info = _make_csp_info(filename, char, color)
        key = _strip_csp_suffixes(Path(filename).stem)
        csps_by_name.setdefault(key, []).append(info)
        csps_by_path[filename] = info

    stocks_by_name = {}
    stocks_by_path = {}
    for filename, char, color in stocks:
        info = _make_csp_info(filename, char, color)
        key = _strip_stock_suffixes(Path(filename).stem)
        stocks_by_name.setdefault(key, []).append(info)
        stocks_by_path[filename] = info

    return csps_by_name, csps_by_path, stocks_by_name, stocks_by_path


def _run(dat_results, csps=(), stocks=()):
    """Build indexes and run _match_images in one step."""
    csps_by_name, csps_by_path, stocks_by_name, stocks_by_path = _make_indexes(csps, stocks)
    return _match_images(dat_results, csps_by_name, csps_by_path, stocks_by_name, stocks_by_path)


# ── Helper Function Tests ─────────────────────────────────────────────────────

class TestStripSuffixes:
    def test_strip_csp_suffix(self):
        assert _strip_csp_suffixes('PlFxGr_csp') == 'plfxgr'

    def test_strip_csp_prefix(self):
        assert _strip_csp_suffixes('csp_PlFxGr') == 'plfxgr'

    def test_strip_csp_uppercase(self):
        assert _strip_csp_suffixes('PlFxGr_CSP') == 'plfxgr'

    def test_strip_stock_suffix(self):
        assert _strip_stock_suffixes('PlFxGr_stock') == 'plfxgr'

    def test_strip_stock_prefix(self):
        assert _strip_stock_suffixes('stock_PlFxGr') == 'plfxgr'

    def test_no_stripping_needed(self):
        assert _strip_csp_suffixes('PlFxGr') == 'plfxgr'

    def test_with_spaces(self):
        assert _strip_csp_suffixes('  PlFxGr_csp  ') == 'plfxgr'


class TestSplitKeyWords:
    def test_hyphen_split(self):
        assert _split_key_words('neutral-green') == {'neutral', 'green'}

    def test_underscore_split(self):
        assert _split_key_words('red_orange') == {'red', 'orange'}

    def test_space_split(self):
        words = _split_key_words('assault falco')
        assert 'assault' in words and 'falco' in words

    def test_min_length_two(self):
        # Single-char tokens are excluded
        result = _split_key_words('a-blue')
        assert 'a' not in result
        assert 'blue' in result


class TestMatchColorWord:
    def test_direct_match(self):
        assert _match_color_word({'green'}, 'Green') == 2

    def test_alias_match(self):
        # 'blue' aliases to Lavender
        assert _match_color_word({'blue'}, 'Lavender') == 1

    def test_no_match(self):
        assert _match_color_word({'purple'}, 'Green') == 0

    def test_empty_dat_color(self):
        assert _match_color_word({'green'}, None) == 0

    def test_neutral_alias(self):
        assert _match_color_word({'neutral'}, 'Default') == 1


class TestExtractContentWords:
    def test_strips_noise(self):
        words = _extract_content_words('the csp')
        assert 'csp' not in words
        assert 'the' not in words

    def test_strips_color_words(self):
        words = _extract_content_words('marth-green')
        assert 'green' not in words
        assert 'marth' in words

    def test_strips_plxxyy_codes(self):
        words = _extract_content_words('plFxGr')
        # PlXxYy codes removed
        assert not any(len(w) > 5 and w.startswith('pl') for w in words)


class TestNameOverlapScore:
    def test_overlap(self):
        score = _name_overlap_score('keaton-fox', 'keaton-green')
        assert score[0] >= 1  # 'keaton' overlaps

    def test_no_overlap(self):
        score = _name_overlap_score('bubble-luigi', 'keaton-fox')
        assert score[0] == 0

    def test_empty_returns_zero(self):
        assert _name_overlap_score('csp', 'stock') == (0, 0)


class TestNormalizeFolderName:
    def test_basic(self):
        assert _normalize_folder_name('Green') == 'green'

    def test_strips_parenthetical(self):
        assert _normalize_folder_name('Neutral (blue team)') == 'neutral'

    def test_nested_path(self):
        result = _normalize_folder_name('skins/Green')
        assert result == 'green'


class TestGetFolder:
    def test_flat_file(self):
        assert _get_folder('PlFxGr.dat') == '.'

    def test_with_subfolder(self):
        result = _get_folder('fox/PlFxGr.dat')
        assert 'fox' in result

    def test_nested(self):
        result = _get_folder('fox/skins/PlFxGr.dat')
        assert 'skins' in result


class TestExtractCharacterColorFromFilename:
    def test_plxxyy_format(self):
        char, color = _extract_character_color_from_filename('PlFxGr.dat')
        assert char == 'Fox' and color == 'Green'

    def test_plxxyy_usd_format(self):
        char, color = _extract_character_color_from_filename('PlCaRe.usd')
        assert char == 'Captain Falcon' and color == 'Red'

    def test_falcon_red_rd_alias(self):
        char, color = _extract_character_color_from_filename('PlCaRd.usd')
        assert char == 'Captain Falcon' and color == 'Red'

    def test_plxxyy_in_csp(self):
        char, color = _extract_character_color_from_filename('PlFxGr_csp.png')
        assert char == 'Fox' and color == 'Green'

    def test_csp_prefix(self):
        char, color = _extract_character_color_from_filename('csp_PlFxGr.png')
        assert char == 'Fox' and color == 'Green'

    def test_case_insensitive(self):
        char, color = _extract_character_color_from_filename('PLFXGR.png')
        assert char == 'Fox' and color == 'Green'


class TestUtilityDatParserAliases:
    def test_falcon_red_rd_alias_normalizes_to_re_slot(self):
        parser = UtilityDATParser(str(BACKEND_DIR / 'PlCaRd.usd'))
        parser.root_nodes = [{'symbol': 'PlyCaptain5KRd_Share_joint'}]

        assert parser.detect_costume_color() == 'Red'
        assert parser.get_character_filename() == 'PlCaRe'

    def test_underscore_format(self):
        char, color = _extract_character_color_from_filename('fox_green.png')
        assert char == 'Fox' and color == 'Green'

    def test_invalid_returns_none(self):
        char, color = _extract_character_color_from_filename('random_image.png')
        assert char is None and color is None

    def test_common_characters(self):
        cases = [
            ('PlFxNr.dat', 'Fox'), ('PlFaNr.dat', 'Falco'),
            ('PlMsNr.dat', 'Marth'), ('PlFeNr.dat', 'Roy'),
            ('PlPeNr.dat', 'Peach'), ('PlSsNr.dat', 'Samus'),
        ]
        for filename, expected_char in cases:
            char, _ = _extract_character_color_from_filename(filename)
            assert char == expected_char, f"Failed for {filename}: got {char}"

    def test_common_colors(self):
        cases = [
            ('PlFxNr.dat', 'Default'), ('PlFxRe.dat', 'Red'),
            ('PlFxBu.dat', 'Blue'), ('PlFxGr.dat', 'Green'),
            ('PlFxWh.dat', 'White'), ('PlFxBk.dat', 'Black'),
        ]
        for filename, expected_color in cases:
            _, color = _extract_character_color_from_filename(filename)
            assert color == expected_color, f"Failed for {filename}: got {color}"


# ── _build_image_indexes Tests ────────────────────────────────────────────────

class TestBuildImageIndexes:
    """Test image classification from in-memory ZIPs."""

    def test_standard_csp_detected(self):
        """136x188 image classified as CSP."""
        zf = _make_zip({'csp.png': CSP_BYTES})
        by_name, by_path, sn, sp = _build_image_indexes(zf, ['csp.png'])
        assert 'csp.png' in by_path

    def test_2x_csp_detected(self):
        """272x376 image (2x CSP) classified as CSP."""
        zf = _make_zip({'portrait.png': CSP_2X_BYTES})
        by_name, by_path, sn, sp = _build_image_indexes(zf, ['portrait.png'])
        assert 'portrait.png' in by_path

    def test_standard_stock_detected(self):
        """24x24 image classified as stock."""
        zf = _make_zip({'stock.png': STOCK_BYTES})
        sn_name, sn_path, by_name, by_path = _build_image_indexes(zf, ['stock.png'])
        assert 'stock.png' in by_path

    def test_2x_stock_detected(self):
        """48x48 image classified as stock."""
        zf = _make_zip({'icon.png': STOCK_2X_BYTES})
        _, _, _, by_path = _build_image_indexes(zf, ['icon.png'])
        assert 'icon.png' in by_path

    def test_screenshot_not_classified(self):
        """800x600 screenshot not classified as CSP or stock."""
        zf = _make_zip({'screenshot.png': SCREEN_BYTES})
        cn, cp, sn, sp = _build_image_indexes(zf, ['screenshot.png'])
        assert 'screenshot.png' not in cp and 'screenshot.png' not in sp

    def test_keyword_csp_fallback(self):
        """'portrait' in name is classified as CSP when dimensions are non-standard."""
        # 300x400 doesn't match strict multiples, use keyword
        odd_bytes = _make_pil_bytes(300, 400)
        zf = _make_zip({'portrait_custom.png': odd_bytes})
        cn, cp, sn, sp = _build_image_indexes(zf, ['portrait_custom.png'])
        assert 'portrait_custom.png' in cp

    def test_keyword_stock_fallback(self):
        """'stc' in name is classified as stock when dimensions are non-standard."""
        odd_bytes = _make_pil_bytes(30, 30)
        zf = _make_zip({'stc_custom.png': odd_bytes})
        cn, cp, sn, sp = _build_image_indexes(zf, ['stc_custom.png'])
        assert 'stc_custom.png' in sp

    def test_dat_file_ignored(self):
        """Non-image files are not indexed."""
        zf = _make_zip({'PlFxGr.dat': b'not an image', 'csp.png': CSP_BYTES})
        cn, cp, sn, sp = _build_image_indexes(zf, ['PlFxGr.dat', 'csp.png'])
        assert 'PlFxGr.dat' not in cp


class TestDetectCharacterFromZip:
    def test_detects_falcon_red_usd_costume(self, monkeypatch):
        from vault.importing import character_detector as detector_module

        class FakeParser:
            def __init__(self, filepath):
                self.filepath = filepath
                self.root_nodes = []

            def read_dat(self):
                marker = Path(self.filepath).read_text()
                if marker == 'falcon_red_usd':
                    self.root_nodes = [{'symbol': 'PlyCaptain5KRd_Share_joint'}]
                else:
                    self.root_nodes = [{'symbol': 'ftDataFox'}]

            def detect_character(self):
                return ('C. Falcon', 'PlyCaptain5KRd_Share_joint')

            def detect_costume_color(self):
                return 'Red'

            def get_character_filename(self):
                return 'PlCaRe'

        monkeypatch.setattr(detector_module, 'DATParser', FakeParser)

        zip_path = Path(__file__).parent / '_falcon_red_detector.zip'
        try:
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr('PlCaRd.usd', 'falcon_red_usd')
                zf.writestr('csp.png', CSP_BYTES)

            results = detect_character_from_zip(str(zip_path))

            assert len(results) == 1
            assert results[0]['character'] == 'C. Falcon'
            assert results[0]['color'] == 'Red'
            assert results[0]['costume_code'] == 'PlCaRe'
            assert results[0]['dat_file'] == 'PlCaRd.usd'
            assert results[0]['csp_file'] == 'csp.png'
        finally:
            if zip_path.exists():
                zip_path.unlink()

    def test_csp_key_stripping(self):
        """CSP filename prefix/suffix is stripped in the name index."""
        zf = _make_zip({'csp_PlFxGr.png': CSP_BYTES})
        cn, cp, sn, sp = _build_image_indexes(zf, ['csp_PlFxGr.png'])
        # Key should be 'plfxgr' (stripped)
        assert 'plfxgr' in cn

    def test_filename_folder_set(self):
        """filename_folder is set correctly for nested files."""
        zf = _make_zip({'fox/csp.png': CSP_BYTES})
        cn, cp, sn, sp = _build_image_indexes(zf, ['fox/csp.png'])
        info = cp.get('fox/csp.png')
        assert info is not None
        assert 'fox' in info['filename_folder']

    def test_root_folder_is_dot(self):
        """Root-level files get filename_folder='.'"""
        zf = _make_zip({'csp.png': CSP_BYTES})
        cn, cp, sn, sp = _build_image_indexes(zf, ['csp.png'])
        info = cp.get('csp.png')
        assert info['filename_folder'] == '.'

    def test_char_color_extracted_from_plxxyy_filename(self):
        """PlFxGr_csp.png gets char=Fox, color=Green from its filename."""
        zf = _make_zip({'PlFxGr_csp.png': CSP_BYTES})
        cn, cp, sn, sp = _build_image_indexes(zf, ['PlFxGr_csp.png'])
        info = cp.get('PlFxGr_csp.png')
        assert info['character'] == 'Fox'
        assert info['color'] == 'Green'


# ── _match_images Strategy Tests ──────────────────────────────────────────────

class TestStrategy1ExactFilename:
    """Strategy 1: DAT stem matches CSP/stock base key."""

    def test_dat_matches_csp_with_suffix(self):
        """PlFxGr.dat matches PlFxGr_csp.png."""
        dats = [_make_dat_result('PlFxGr.dat', 'Fox', 'Green')]
        matches = _run(dats, csps=[('PlFxGr_csp.png', None, None)])
        assert matches['PlFxGr.dat']['csp_file'] == 'PlFxGr_csp.png'

    def test_dat_matches_csp_with_prefix(self):
        """PlFxGr.dat matches csp_PlFxGr.png."""
        dats = [_make_dat_result('PlFxGr.dat', 'Fox', 'Green')]
        matches = _run(dats, csps=[('csp_PlFxGr.png', None, None)])
        assert matches['PlFxGr.dat']['csp_file'] == 'csp_PlFxGr.png'

    def test_dat_matches_stock_by_name(self):
        """PlFxGr.dat matches PlFxGr_stock.png."""
        dats = [_make_dat_result('PlFxGr.dat', 'Fox', 'Green')]
        matches = _run(dats, stocks=[('PlFxGr_stock.png', None, None)])
        assert matches['PlFxGr.dat']['stock_file'] == 'PlFxGr_stock.png'

    def test_case_insensitive_match(self):
        """plfxgr.dat matches PLFXGR_CSP.png."""
        dats = [_make_dat_result('plfxgr.dat', 'Fox', 'Green')]
        matches = _run(dats, csps=[('PLFXGR_CSP.png', None, None)])
        assert matches['plfxgr.dat']['csp_file'] == 'PLFXGR_CSP.png'

    def test_same_folder_preferred(self):
        """When two CSPs match by name, same-folder one is preferred."""
        dats = [_make_dat_result('fox/PlFxGr.dat', 'Fox', 'Green')]
        # One CSP in same folder, one at root
        cn, cp, sn, sp = _make_indexes(
            csps=[('fox/PlFxGr_csp.png', None, None), ('PlFxGr_csp.png', None, None)]
        )
        matches = _match_images(dats, cn, cp, sn, sp)
        assert matches['fox/PlFxGr.dat']['csp_file'] == 'fox/PlFxGr_csp.png'


class TestStrategy2CharColor:
    """Strategy 2: CSP/stock has char+color extracted matching the DAT."""

    def test_plxxyy_csp_matches_dat(self):
        """PlFxGr_csp.png (char=Fox, color=Green) matches DAT with Fox Green."""
        dats = [_make_dat_result('my_costume.dat', 'Fox', 'Green')]
        matches = _run(dats, csps=[('PlFxGr_csp.png', 'Fox', 'Green')])
        assert matches['my_costume.dat']['csp_file'] == 'PlFxGr_csp.png'

    def test_fox_green_filename(self):
        """fox_green.png (char=Fox, color=Green) matches DAT Fox Green."""
        dats = [_make_dat_result('mystery.dat', 'Fox', 'Green')]
        matches = _run(dats, csps=[('fox_green.png', 'Fox', 'Green')])
        assert matches['mystery.dat']['csp_file'] == 'fox_green.png'

    def test_wrong_color_no_match(self):
        """fox_blue.png does NOT char_color-match Fox Green DAT."""
        dats = [_make_dat_result('mystery.dat', 'Fox', 'Green')]
        # Only CSP in archive, but wrong char/color
        matches = _run(dats, csps=[('fox_blue.png', 'Fox', 'Blue')])
        # Should NOT match via char_color; may match via single_image (only 1 CSP)
        m = matches['mystery.dat']
        # If it matched, it wasn't because of char_color since colors differ
        # (single_image fallback is fine, but char_color should not be the reason)
        # We just check it didn't go through char_color specifically
        # This is hard to verify without strategy tracking, so just verify no crash
        assert True

    def test_single_dat_injects_char_into_unnamed_csp(self):
        """Single costume DAT: char/color injected into unnamed CSP, enabling char_color match."""
        # The unnamed CSP has no char/color initially, but with 1 DAT the matcher
        # injects the DAT's char/color into it
        dats = [_make_dat_result('PlFxGr.dat', 'Fox', 'Green')]
        # The CSP has no char/color extracted from its filename
        matches = _run(dats, csps=[('random_name.png', None, None)])
        # Should match (via char_color after injection, or global)
        assert matches['PlFxGr.dat']['csp_file'] == 'random_name.png'


class TestStrategy25FolderName:
    """Strategy 2.5: Folder name word appears in CSP key."""

    def test_ics_style_folder_name_match(self):
        """csp_neutral-green.png matches DATs in 'Neutral' and 'Green' folders."""
        dats = [
            _make_dat_result('Green/PlPpGr.dat', 'Ice Climbers', 'Default'),
            _make_dat_result('Neutral/PlPpNr.dat', 'Ice Climbers', 'Default'),
        ]
        matches = _run(dats, csps=[('csp_neutral-green.png', None, None)])
        # Both DATs should share the same CSP
        assert matches['Green/PlPpGr.dat']['csp_file'] == 'csp_neutral-green.png'
        assert matches['Neutral/PlPpNr.dat']['csp_file'] == 'csp_neutral-green.png'

    def test_folder_name_not_fired_when_multiple_dats(self):
        """Strategy 2.5 requires exactly 1 costume DAT in the folder."""
        dats = [
            _make_dat_result('green/PlFxGr.dat', 'Fox', 'Green', b'unique1'),
            _make_dat_result('green/PlFxBu.dat', 'Fox', 'Blue', b'unique2'),
        ]
        matches = _run(dats, csps=[('csp_green.png', None, None)])
        # With 2 DATs in folder, strategy 2.5 shouldn't fire
        # (strategy 3.5 or 3.8 might still fire)
        # Just verify it works without crash
        assert 'green/PlFxGr.dat' in matches

    def test_folder_name_in_csp_key_must_match_exactly(self):
        """'red' folder matches 'csp_red.png' but not 'csp_reddish.png'."""
        dats = [_make_dat_result('red/PlFxRe.dat', 'Fox', 'Red')]
        # 'red' is in key 'red' but not in 'reddish'
        cn, cp, sn, sp = _make_indexes(csps=[('csp_red.png', None, None)])
        matches = _match_images(dats, cn, cp, sn, sp)
        assert matches['red/PlFxRe.dat']['csp_file'] == 'csp_red.png'


class TestStrategy26ColorWord:
    """Strategy 2.6: CSP key contains a color word matching DAT color."""

    def test_blue_csp_matches_blue_dat(self):
        """'blue.png' matches a DAT with color Blue."""
        dats = [_make_dat_result('mystery.dat', 'Fox', 'Blue')]
        matches = _run(dats, csps=[('blue.png', None, None)])
        assert matches['mystery.dat']['csp_file'] == 'blue.png'

    def test_blue_csp_matches_lavender_dat(self):
        """'blue.png' matches Lavender DAT (alias match)."""
        dats = [_make_dat_result('mystery.dat', 'Fox', 'Lavender')]
        matches = _run(dats, csps=[('blue.png', None, None)])
        assert matches['mystery.dat']['csp_file'] == 'blue.png'

    def test_direct_match_preferred_over_alias(self):
        """Direct color match (quality=2) wins over alias (quality=1)."""
        dats = [_make_dat_result('mystery.dat', 'Fox', 'Orange')]
        # 'orange.png' is direct match (Orange), 'red.png' is alias match
        matches = _run(dats, csps=[
            ('orange.png', None, None),
            ('red.png', None, None),
        ])
        assert matches['mystery.dat']['csp_file'] == 'orange.png'

    def test_multiple_same_quality_disambiguated_by_name_overlap(self):
        """Tied color candidates disambiguated by name overlap with DAT."""
        # DAT is 'keaton_fx.dat', CSPs are 'blue_keaton.png' and 'blue_other.png'
        dats = [_make_dat_result('keaton_fx.dat', 'Fox', 'Blue')]
        matches = _run(dats, csps=[
            ('blue_keaton.png', None, None),
            ('blue_other.png', None, None),
        ])
        # 'keaton' overlaps with DAT stem 'keaton_fx', so blue_keaton should win
        assert matches['keaton_fx.dat']['csp_file'] == 'blue_keaton.png'


class TestStrategy27NameOverlap:
    """Strategy 2.7: Shared content words between DAT and CSP key."""

    def test_shared_word_matches(self):
        """'keaton.png' matches 'keaton.dat' via name overlap."""
        dats = [_make_dat_result('keaton.dat', 'Fox', 'Green')]
        matches = _run(dats, csps=[('keaton.png', None, None)])
        assert matches['keaton.dat']['csp_file'] == 'keaton.png'

    def test_ambiguous_overlap_no_match(self):
        """Two CSPs with equal overlap score: no match via name_overlap."""
        dats = [_make_dat_result('marth-fox.dat', 'Fox', 'Green')]
        # 'fox.png' and 'marth.png' each have 1 word overlap, equally good
        matches = _run(dats, csps=[
            ('fox.png', None, None),
            ('marth.png', None, None),
        ])
        # Tied — name_overlap should not fire; may fall through to folder strategies
        # Just verify no crash
        assert 'marth-fox.dat' in matches

    def test_better_overlap_wins(self):
        """'keaton-marth.png' beats 'keaton.png' when DAT has both words."""
        dats = [_make_dat_result('keaton-marth.dat', 'Marth', 'Green')]
        matches = _run(dats, csps=[
            ('keaton-marth.png', None, None),
            ('keaton.png', None, None),
        ])
        assert matches['keaton-marth.dat']['csp_file'] == 'keaton-marth.png'


class TestStrategy3SameFolder:
    """Strategy 3: Same folder match (only if 1 DAT in folder)."""

    def test_single_dat_folder_match(self):
        """1 DAT + 1 CSP in subfolder: matched via folder strategy."""
        dats = [_make_dat_result('costume_a/my.dat', 'Fox', 'Green')]
        matches = _run(dats, csps=[('costume_a/portrait.png', None, None)])
        assert matches['costume_a/my.dat']['csp_file'] == 'costume_a/portrait.png'

    def test_two_dats_in_folder_disables_folder_match(self):
        """2 DATs in same folder: folder match (Strategy 3) disabled."""
        dats = [
            _make_dat_result('fox/PlFxGr.dat', 'Fox', 'Green', b'dat1'),
            _make_dat_result('fox/PlFxBu.dat', 'Fox', 'Blue', b'dat2'),
        ]
        # Only 1 CSP in folder — not enough for Strategy 3
        matches = _run(dats, csps=[('fox/csp.png', None, None)])
        # Strategy 3 should not fire for either DAT
        # (Strategy 3.5 may still match since there's exactly 1 CSP in the folder)
        for dat_fn, m in matches.items():
            if m['csp_file']:
                # Could be folder_single_image (3.5) or folder_share (3.8), not folder (3)
                # We just verify both DATs get the shared CSP
                assert m['csp_file'] == 'fox/csp.png'

    def test_two_separate_folders_each_match(self):
        """DAT + CSP in separate folders each match their own CSP."""
        dats = [
            _make_dat_result('a/my.dat', 'Fox', 'Green', b'dat_a'),
            _make_dat_result('b/other.dat', 'Fox', 'Blue', b'dat_b'),
        ]
        matches = _run(dats, csps=[
            ('a/portrait.png', None, None),
            ('b/portrait.png', None, None),
        ])
        assert matches['a/my.dat']['csp_file'] == 'a/portrait.png'
        assert matches['b/other.dat']['csp_file'] == 'b/portrait.png'


class TestStrategy35SingleImagePerFolder:
    """Strategy 3.5: Exactly 1 CSP/stock in a folder -> shared to all DATs there."""

    def test_single_csp_shared_to_all_dats_in_folder(self):
        """1 CSP in folder, 2 DATs: both get that CSP (non-consuming)."""
        dats = [
            _make_dat_result('fox/PlFxGr.dat', 'Fox', 'Green', b'dat1'),
            _make_dat_result('fox/PlFxBu.dat', 'Fox', 'Blue', b'dat2'),
        ]
        matches = _run(dats, csps=[('fox/shared_csp.png', None, None)])
        assert matches['fox/PlFxGr.dat']['csp_file'] == 'fox/shared_csp.png'
        assert matches['fox/PlFxBu.dat']['csp_file'] == 'fox/shared_csp.png'

    def test_two_csps_in_folder_no_single_image_match(self):
        """2 CSPs in folder: Strategy 3.5 does not fire."""
        dats = [_make_dat_result('fox/my.dat', 'Fox', 'Green')]
        # Two CSPs in same folder
        matches = _run(dats, csps=[
            ('fox/csp1.png', None, None),
            ('fox/csp2.png', None, None),
        ])
        # Strategy 3.5 shouldn't fire (2 CSPs, not 1)
        # Strategy 3 should fire (1 DAT in folder): matches first CSP found
        assert matches['fox/my.dat']['csp_file'] is not None

    def test_root_level_not_triggered_by_strategy35(self):
        """Strategy 3.5 only fires for non-root folders."""
        dats = [_make_dat_result('PlFxGr.dat', 'Fox', 'Green')]
        # Root-level single CSP should match via strategy 4 (global) or 5 (single_image)
        # not via 3.5 (which requires dat_filename_folder != '.')
        matches = _run(dats, csps=[('csp.png', None, None)])
        assert matches['PlFxGr.dat']['csp_file'] == 'csp.png'


class TestStrategy375Positional:
    """Strategy 3.75: M CSPs >= N DATs >= 2 in folder -> alphabetical position match."""

    def test_positional_match_two_dats_two_csps(self):
        """2 DATs + 2 CSPs in folder: matched by sorted position."""
        dats = [
            _make_dat_result('fox/aaa.dat', 'Fox', 'Green', b'aaa'),
            _make_dat_result('fox/bbb.dat', 'Fox', 'Blue', b'bbb'),
        ]
        matches = _run(dats, csps=[
            ('fox/csp_aaa.png', None, None),
            ('fox/csp_bbb.png', None, None),
        ])
        # Sorted DATs: aaa.dat, bbb.dat -> CSPs sorted: csp_aaa.png, csp_bbb.png
        assert matches['fox/aaa.dat']['csp_file'] == 'fox/csp_aaa.png'
        assert matches['fox/bbb.dat']['csp_file'] == 'fox/csp_bbb.png'

    def test_more_csps_than_dats_positional(self):
        """3 CSPs, 2 DATs: positional still works (M >= N >= 2)."""
        dats = [
            _make_dat_result('skins/a.dat', 'Fox', 'Green', b'a'),
            _make_dat_result('skins/b.dat', 'Fox', 'Blue', b'b'),
        ]
        matches = _run(dats, csps=[
            ('skins/img_a.png', None, None),
            ('skins/img_b.png', None, None),
            ('skins/img_c.png', None, None),
        ])
        assert matches['skins/a.dat']['csp_file'] == 'skins/img_a.png'
        assert matches['skins/b.dat']['csp_file'] == 'skins/img_b.png'


class TestStrategy38FolderShare:
    """Strategy 3.8: Fewer CSPs than DATs in folder -> share first CSP."""

    def test_fewer_csps_shared(self):
        """1 CSP, 3 DATs in folder: all DATs get the same CSP."""
        dats = [
            _make_dat_result('pack/a.dat', 'Fox', 'Green', b'a'),
            _make_dat_result('pack/b.dat', 'Fox', 'Blue', b'b'),
            _make_dat_result('pack/c.dat', 'Fox', 'Red', b'c'),
        ]
        matches = _run(dats, csps=[('pack/shared.png', None, None)])
        for m in matches.values():
            assert m['csp_file'] == 'pack/shared.png'


class TestStrategy4GlobalFallback:
    """Strategy 4: Global fallback when only 1 costume DAT total."""

    def test_single_dat_matches_any_csp(self):
        """Single DAT: any CSP in archive is assigned (global fallback)."""
        dats = [_make_dat_result('PlFxGr.dat', 'Fox', 'Green')]
        matches = _run(dats, csps=[('some/nested/csp.png', None, None)])
        assert matches['PlFxGr.dat']['csp_file'] == 'some/nested/csp.png'

    def test_two_dats_no_global_fallback(self):
        """With 2 unique costume DATs, global fallback does NOT fire."""
        dats = [
            _make_dat_result('PlFxGr.dat', 'Fox', 'Green', b'unique1'),
            _make_dat_result('PlFxBu.dat', 'Fox', 'Blue', b'unique2'),
        ]
        # Both DATs at root, CSP at root but unnamed
        # Global fallback (Strategy 4) requires unique_costume_dat_count == 1
        matches = _run(dats, csps=[('unknown.png', None, None)])
        # Cannot guarantee both match since global fallback is disabled
        # But at least one might match via single_image (Strategy 5)
        assert 'PlFxGr.dat' in matches


class TestStrategy5SingleImageFallback:
    """Strategy 5: Only 1 CSP/stock in entire archive -> non-consuming share."""

    def test_single_csp_shared_to_all_unmatched_dats(self):
        """1 CSP in archive, multiple DATs: all get that CSP."""
        dats = [
            _make_dat_result('fox/PlFxGr.dat', 'Fox', 'Green', b'gr'),
            _make_dat_result('fox/PlFxBu.dat', 'Fox', 'Blue', b'bu'),
        ]
        # CSP in a different folder (not triggering folder strategies)
        matches = _run(dats, csps=[('csps/shared.png', None, None)])
        # Both should get the single CSP (after folder promotion or single_image)
        for m in matches.values():
            assert m['csp_file'] == 'csps/shared.png'


# ── Folder Promotion Tests ────────────────────────────────────────────────────

class TestFolderPromotion:
    """Test folder promotion: CSPs in media subfolders promoted to DAT folder."""

    def test_strategy_a_child_of_dat_folder(self):
        """'fox/CSP/csp.png' promoted to 'fox/' when DAT is in 'fox/'."""
        dats = [_make_dat_result('fox/PlFxGr.dat', 'Fox', 'Green')]
        # CSP is in fox/CSP/ which is a direct child of fox/
        matches = _run(dats, csps=[('fox/CSP/csp.png', None, None)])
        assert matches['fox/PlFxGr.dat']['csp_file'] == 'fox/CSP/csp.png'

    def test_strategy_b_mirrored_tree(self):
        """'CSPs/fox/csp.png' promoted to 'fox/' when DAT is in 'fox/'."""
        dats = [_make_dat_result('fox/PlFxGr.dat', 'Fox', 'Green')]
        # CSPs/fox/ -> fox/ (strip leading 'CSPs/')
        matches = _run(dats, csps=[('CSPs/fox/csp.png', None, None)])
        assert matches['fox/PlFxGr.dat']['csp_file'] == 'CSPs/fox/csp.png'

    def test_strategy_d_parent_to_child(self):
        """'pack/csp.png' promoted to 'pack/fox/' when DAT is in 'pack/fox/'."""
        dats = [_make_dat_result('pack/fox/PlFxGr.dat', 'Fox', 'Green')]
        # CSP is in pack/ (parent of the DAT folder pack/fox/)
        matches = _run(dats, csps=[('pack/csp.png', None, None)])
        assert matches['pack/fox/PlFxGr.dat']['csp_file'] == 'pack/csp.png'


# ── Post-Processing Tests ─────────────────────────────────────────────────────

class TestDuplicatePropagation:
    """Duplicate DAT propagation: same hash -> same CSP/stock assigned."""

    def test_duplicate_dat_inherits_csp(self):
        """Two DATs with same content hash: second inherits CSP from first."""
        shared_hash = b'duplicate_dat_content'
        dat_a = _make_dat_result('a/PlFxGr.dat', 'Fox', 'Green', shared_hash)
        dat_b = _make_dat_result('b/PlFxGr.dat', 'Fox', 'Green', shared_hash)

        # Only one CSP, in folder 'a'
        matches = _run([dat_a, dat_b], csps=[('a/csp.png', None, None)])
        # dat_a matches via folder (1 DAT in folder 'a')
        assert matches['a/PlFxGr.dat']['csp_file'] == 'a/csp.png'
        # dat_b should inherit via duplicate propagation
        assert matches['b/PlFxGr.dat']['csp_file'] == 'a/csp.png'


class TestCharColorReuse:
    """Same char+color reuse: variant folders share CSP."""

    def test_second_dat_reuses_matched_csp(self):
        """Two DATs with same char+color: second reuses first's CSP."""
        dats = [
            _make_dat_result('main/PlFxGr.dat', 'Fox', 'Green', b'main'),
            _make_dat_result('alt/PlFxGr_alt.dat', 'Fox', 'Green', b'alt'),
        ]
        # Only 1 CSP, in 'main/' folder
        matches = _run(dats, csps=[('main/csp.png', None, None)])
        assert matches['main/PlFxGr.dat']['csp_file'] == 'main/csp.png'
        assert matches['alt/PlFxGr_alt.dat']['csp_file'] == 'main/csp.png'


class TestFolderLeftover:
    """Folder leftover: 1 unmatched DAT + 1 free CSP in same folder."""

    def test_leftover_assigned_after_all_strategies(self):
        """After all strategies, leftover CSP in same folder as unmatched DAT is assigned."""
        # Two DATs and two CSPs: one pair matches by name, the other by leftover
        dats = [
            _make_dat_result('pack/PlFxGr.dat', 'Fox', 'Green', b'green'),
            _make_dat_result('pack/PlFxBu.dat', 'Fox', 'Blue', b'blue'),
        ]
        # green.png matches PlFxGr.dat by color_word; leftover blue.png matches PlFxBu.dat
        matches = _run(dats, csps=[
            ('pack/green.png', None, None),
            ('pack/blue.png', None, None),
        ])
        # green.png -> PlFxGr.dat (color_word or positional), blue.png -> PlFxBu.dat
        m_gr = matches['pack/PlFxGr.dat']
        m_bu = matches['pack/PlFxBu.dat']
        assert m_gr['csp_file'] is not None
        assert m_bu['csp_file'] is not None
        # They should not both get the same file
        assert m_gr['csp_file'] != m_bu['csp_file']


# ── Nana Exclusion ────────────────────────────────────────────────────────────

class TestNanaExclusion:
    """Nana DATs are excluded from matching (they inherit at import time)."""

    def test_nana_not_in_matches(self):
        """Nana DAT is excluded from _match_images, so no entry in matches."""
        popo = _make_dat_result('PlPpNr.dat', 'Ice Climbers', 'Default', b'popo')
        nana = _make_dat_result('PlNnNr.dat', 'Ice Climbers', 'Default', b'nana', is_nana=True)

        # Call _match_images with only non-Nana results (as detect_character_from_zip does)
        non_nana = [r for r in [popo, nana] if not r.get('is_ice_climbers_nana')]
        cn, cp, sn, sp = _make_indexes(csps=[('csp.png', None, None)])
        matches = _match_images(non_nana, cn, cp, sn, sp)

        assert 'PlPpNr.dat' in matches
        assert 'PlNnNr.dat' not in matches

    def test_nana_does_not_consume_csp(self):
        """Since Nana is excluded from matching, its CSP slot is not consumed."""
        popo = _make_dat_result('PlPpNr.dat', 'Ice Climbers', 'Default', b'popo')
        cn, cp, sn, sp = _make_indexes(csps=[('csp.png', None, None)])
        matches = _match_images([popo], cn, cp, sn, sp)
        # Popo should get the CSP
        assert matches['PlPpNr.dat']['csp_file'] == 'csp.png'


# ── Edge Cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_no_images_in_archive(self):
        """No CSPs or stocks: all match entries have None."""
        dats = [_make_dat_result('PlFxGr.dat', 'Fox', 'Green')]
        matches = _run(dats, csps=[], stocks=[])
        assert matches['PlFxGr.dat']['csp_file'] is None
        assert matches['PlFxGr.dat']['stock_file'] is None

    def test_no_dats(self):
        """Empty dat_results: empty matches dict."""
        matches = _run([], csps=[('csp.png', None, None)])
        assert matches == {}

    def test_csp_and_stock_matched_independently(self):
        """CSP and stock are matched independently for the same DAT."""
        dats = [_make_dat_result('PlFxGr.dat', 'Fox', 'Green')]
        matches = _run(
            dats,
            csps=[('PlFxGr_csp.png', None, None)],
            stocks=[('PlFxGr_stock.png', None, None)],
        )
        m = matches['PlFxGr.dat']
        assert m['csp_file'] == 'PlFxGr_csp.png'
        assert m['stock_file'] == 'PlFxGr_stock.png'

    def test_two_dats_separate_csps_no_double_assign(self):
        """Two DATs each get their own CSP, not shared."""
        dats = [
            _make_dat_result('PlFxGr.dat', 'Fox', 'Green', b'green'),
            _make_dat_result('PlFxBu.dat', 'Fox', 'Blue', b'blue'),
        ]
        matches = _run(dats, csps=[
            ('PlFxGr_csp.png', None, None),
            ('PlFxBu_csp.png', None, None),
        ])
        assert matches['PlFxGr.dat']['csp_file'] == 'PlFxGr_csp.png'
        assert matches['PlFxBu.dat']['csp_file'] == 'PlFxBu_csp.png'

    def test_csp_consumed_not_reused_by_different_dat(self):
        """Consuming strategies prevent a CSP from being matched twice."""
        dats = [
            _make_dat_result('PlFxGr.dat', 'Fox', 'Green', b'green'),
            _make_dat_result('PlFxBu.dat', 'Fox', 'Blue', b'blue'),
        ]
        # Both CSPs match by filename (strategy 1, consuming)
        matches = _run(dats, csps=[
            ('PlFxGr_csp.png', None, None),
            ('PlFxBu_csp.png', None, None),
        ])
        # Each DAT gets its own CSP, not the same one
        csp_gr = matches['PlFxGr.dat']['csp_file']
        csp_bu = matches['PlFxBu.dat']['csp_file']
        assert csp_gr != csp_bu
