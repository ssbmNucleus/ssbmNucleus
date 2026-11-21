"""Menu DATs are recognised by their ROOT SYMBOLS, not just their filenames.

A YouTube report (2026-09-14): downloading the "Halo 3 Matchmaking Lobby" CSS
(a MnSlChr saved as `Halo3CSS.dat`) and importing it through the main Import
button failed with "can't be imported (unsupported file type)", while the
Menus page's own picker accepted the same file.
"""
import io
import struct
import zipfile

from vault.importing.unified import detection


def _dat(root_symbols, data_size=0x40):
    """A minimal HAL DAT: header, a zeroed data block, no relocations, one
    root per symbol, string table."""
    strings = b''
    offsets = []
    for sym in root_symbols:
        offsets.append(len(strings))
        strings += sym.encode() + b'\0'
    roots = b''.join(struct.pack('>II', 0, off) for off in offsets)
    body = b'\0' * data_size + roots + strings
    header = struct.pack('>5I', 0x20 + len(body), data_size, 0, len(root_symbols), 0) + b'\0' * 12
    return header + body


def _zip_with(name, data):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(name, data)
    return buf.getvalue()


def test_dat_root_symbols_reads_the_root_table():
    assert detection.dat_root_symbols(_dat(['MnSelectChrDataTable'])) == ['MnSelectChrDataTable']
    assert detection.dat_root_symbols(_dat(['DmgNum_scene_models', 'lupe'])) == ['DmgNum_scene_models', 'lupe']
    assert detection.dat_root_symbols(b'not a dat') == []
    assert detection.dat_root_symbols(b'') == []


def test_arbitrarily_named_mnslchr_is_a_css_background(tmp_path):
    path = tmp_path / 'Halo3CSS.zip'
    path.write_bytes(_zip_with('Halo3CSS.dat', _dat(['MnSelectChrDataTable'])))
    verdict = detection.detect_content_type(str(path), deep=False)
    assert 'css_background' in verdict['candidates']
    assert verdict['all_details']['css_background']['source'] == 'css'


def test_arbitrarily_named_menu_files_map_to_their_kind(tmp_path):
    cases = {
        'stagepick.dat': (['MnSelectMapDataTable'], 'css_background', 'sss'),
        'pausey.usd': (['ScGamPause_scene_data'], 'pause_screen', None),
        'numbers.dat': (['DmgNum_scene_models', 'ScInfDmg_scene_data'], 'percent_font', None),
    }
    for name, (roots, kind, source) in cases.items():
        path = tmp_path / (name + '.zip')
        path.write_bytes(_zip_with(name, _dat(roots)))
        verdict = detection.detect_content_type(str(path), deep=False)
        assert kind in verdict['candidates'], (name, verdict['candidates'])
        if source:
            assert verdict['all_details'][kind]['source'] == source


def test_costume_dats_are_not_mistaken_for_menus(tmp_path):
    path = tmp_path / 'PlCaNr.zip'
    path.write_bytes(_zip_with('PlCaNr.dat', _dat(['PlyCaptain5K_Share_joint'])))
    verdict = detection.detect_content_type(str(path), deep=False)
    assert 'css_background' not in verdict['candidates']
    assert 'percent_font' not in verdict['candidates']
