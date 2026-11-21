"""Now Playing (song name at match start): the committed Gecko code and how a
new project gets it."""
import re
import subprocess

import pytest

from core import config
from core.gecko import validate_source
from projects.install import required_codes
from projects.nowplaying import code, gen_code
from projects.nowplaying.code_words import WORDS


def test_source_is_one_valid_c2_at_the_hud_setup_blr():
    src = code.source()
    assert validate_source(src)['ok']
    first, *rest = src.splitlines()
    assert first == f'C22F3A60 {len(rest):08X}'
    assert WORDS[-1] == 0x4E800020          # returns with the replaced blr
    assert rest[-1].endswith('00000000')


@pytest.mark.skipif(not gen_code.AS.exists(), reason='devkitPPC not installed')
def test_committed_words_match_the_assembly_source():
    assert tuple(gen_code.assemble()) == WORDS


def _asm():
    return (gen_code.HERE / 'now_playing.s').read_text(encoding='utf-8')


def _asm_sets():
    """The integer `.set NAME, value` constants of now_playing.s."""
    out = {}
    for m in re.finditer(r'^\s*\.set\s+(\w+),\s*([^#\n]+)', _asm(), re.M):
        try:
            out[m.group(1)] = int(eval(m.group(2), {}, dict(out)))  # constants only
        except Exception:
            pass
    return out


def test_name_budget_fits_the_games_encode_buffer_and_the_state_block():
    """Every glyph the copy writes encodes to 3 bytes in Text_AddSubtext's
    128-byte stack buffer (terminator included), and the copied name (2 bytes
    a glyph at most, plus its terminator) fits the state block."""
    s = _asm_sets()
    assert 3 * s['NAME_MAX'] + 1 <= 128
    assert s['ST_NAME'] + 2 * s['NAME_MAX'] + 1 <= s['ST_SIZE']


def _asm_floats():
    """The `d_name: .float value` constants of now_playing.s's data block."""
    return {m.group(1): float(m.group(2)) for m in re.finditer(
        r'^(d_\w+):\s*\.float\s+(-?[\d.]+)', _asm(), re.M)}


CLOCK_DIGITS_TOP = 55        # a timed match's clock: first row of its digits (640x480)
OVERSCAN_TOP = 14            # nothing above this; CRTs can cut it off


def test_the_bar_and_rule_clear_a_timed_matchs_clock():
    """The bar and the gold rule under it end a visible gap above the clock's
    digits, whatever the name's length (only the width depends on it), and
    stay below the overscan line; the name's glyphs sit inside the bar at a
    size as readable as the look the owner approved (0.54 of a 32 px line)."""
    f = _asm_floats()
    bar_top, bar_bottom = f['d_bar_y'], f['d_bar_y'] + f['d_bar_h']
    assert bar_top >= OVERSCAN_TOP
    assert f['d_rule_y'] == bar_bottom                     # the rule hangs under the bar
    assert CLOCK_DIGITS_TOP - (f['d_rule_y'] + f['d_rule_h']) >= 5
    glyph_top = bar_top + f['d_name_y'] + 32 * (1 - f['d_name_sy'])
    glyph_bottom = glyph_top + 32 * f['d_name_sy']
    assert bar_top < glyph_top and glyph_bottom < bar_bottom
    assert 32 * f['d_name_sy'] >= 17 and f['d_name_sx'] >= 0.56


# gm_803DA888[1]: the p_links whose procs the scene loop stops while a match
# is paused (gm_801A48A4 for pause bit 1; decomp gm/gm_1A45.c).
MATCH_PAUSE_STOPS = 0x82FFFA


def test_the_banner_runs_while_paused_so_it_can_hide():
    """The HUD's p_link (15) stops during a pause, which left the banner frozen
    on screen; the banner's GObj is on one that keeps running. Its pause test
    covers a match's pause and Training's (bits 1 and 2, fn_8016CA68) but not
    bit 0, the debug freeze frame-stepping uses (so captures still see it)."""
    s = _asm_sets()
    assert MATCH_PAUSE_STOPS >> 15 & 1
    assert not MATCH_PAUSE_STOPS >> s['GOBJ_PLINK'] & 1
    assert s['PAUSED'] & 0b110 == 0b110 and not s['PAUSED'] & 1
    # the hook makes its GObj there, and the proc reads the scene's pause bits
    assert WORDS[5:7] == (0x38600000 | s['GOBJ_CLASS'], 0x38800000 | s['GOBJ_PLINK'])
    assert s['PAUSE_BITS'] == 0x80479D68                   # gm_80479D58.unk_10.x0
    read = (0x3C800000 | ((s['PAUSE_BITS'] + 0x8000) >> 16),   # lis r4, @ha
            0x88840000 | (s['PAUSE_BITS'] & 0xFFFF),           # lbz r4, @l(r4)
            0x70840000 | s['PAUSED'])                          # andi. r4, r4, PAUSED
    assert any(WORDS[i:i + 3] == read for i in range(len(WORDS)))


def test_every_printable_symbol_has_a_full_width_pair():
    """The copy sends letters as they are, digits as 0x82 pairs and looks every
    other printable ASCII byte up in d_pairs; a byte missing there would show
    as '?', so the table covers all of them, once each."""
    block = _asm().split('d_pairs:', 1)[1].split('.set NPAIRS', 1)[0]
    nums = [int(x, 16) for x in re.findall(r'0x([0-9A-Fa-f]{2})', block)]
    firsts = nums[0::2]
    wanted = [c for c in range(0x20, 0x7F) if not chr(c).isalnum()]
    assert sorted(firsts) == wanted
    assert _asm_sets()['NPAIRS'] == len(firsts)


def test_new_projects_start_with_now_playing():
    assert required_codes.new_project_gecko_codes() == [(code.CODE_HEADER, code.source())]
    assert code.CODE_HEADER.lower() not in {
        name.lower() for name, _ in required_codes.REQUIRED_GECKO_CODES}


def _fake_mexcli(tmp_path, monkeypatch):
    cli = tmp_path / 'mexcli'
    cli.write_bytes(b'placeholder')
    monkeypatch.setattr(config, 'MEXCLI_PATH', cli)
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw: (
        calls.append(cmd), subprocess.CompletedProcess(cmd, 0, '', ''))[1])
    return calls


def test_add_runs_add_code_for_each_starter_code(tmp_path, monkeypatch):
    calls = _fake_mexcli(tmp_path, monkeypatch)
    project = tmp_path / 'project.mexproj'
    added = required_codes.add_new_project_gecko_codes(project)
    assert added == [code.CODE_HEADER]
    assert calls == [[str(config.MEXCLI_PATH), 'add-code', str(project),
                      code.CODE_HEADER, code.source()]]


def test_a_pack_with_its_own_song_display_does_not_get_a_second(tmp_path, monkeypatch):
    calls = _fake_mexcli(tmp_path, monkeypatch)
    monkeypatch.setattr(required_codes, '_iso_has_file',
                        lambda iso, name: name == 'bgm_display.dat')
    added = required_codes.add_new_project_gecko_codes(
        tmp_path / 'project.mexproj', source_iso=tmp_path / 'ace.iso')
    assert added == [] and calls == []
