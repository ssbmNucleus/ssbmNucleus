"""Existing projects move off an earlier Now Playing version on export
(projects/nowplaying/upgrade.py, called from mexcli.project.MexManager).

The "current" code here is a stand-in passed in or monkeypatched, so these tests
do not depend on what code_words.py holds today."""
import subprocess
import sys

import pytest

from tests.paths import BACKEND
from core.gecko import parse_ini, validate_source
from mexcli import project as mexcli_project
from projects.nowplaying import code, upgrade
from projects.nowplaying.previous_versions import (PREVIOUS_SOURCES, V1_2026_10_19,
                                                   V2_2026_11_20)

OLD = V1_2026_10_19
OLD_VERSIONS = pytest.mark.parametrize('old', [V1_2026_10_19, V2_2026_11_20], ids=['v1', 'v2'])
NEW = 'C22F3A60 00000002\n9421FFE0 7C0802A6\n4E800020 00000000'
NP = 'QOL | Now Playing (Song Name at Match Start) [SSBM Nucleus]'
KELLZ = ('Skip Slippi SSS [KELLZ]', 'C20166B4 00000001\n3D808001 00000000')
OTHER = ('Some Other Code [Someone]', '04263384 48000010')


def _ini(entries, nl='\r\n', inner=None):
    """codes.ini the way MexCLI's ToINI writes it: header, *description lines,
    hex lines, then a blank line. `inner` is the newline between hex lines
    (add-code keeps the caller's '\\n' there; a later save makes them `nl`)."""
    out = ''
    for header, enabled, desc, source in entries:
        out += f'${"!" if enabled else ""}{header}{nl}'
        out += ''.join(f'*{d}{nl}' for d in desc)
        out += (inner or nl).join(source.split('\n')) + nl + nl
    return out


def _project(tmp_path, text):
    proj = tmp_path / 'proj'
    (proj / 'files').mkdir(parents=True)
    mexproj = proj / 'project.mexproj'
    mexproj.write_text('{}')
    ini = proj / 'files' / 'codes.ini'
    ini.write_bytes(text if isinstance(text, bytes) else text.encode('utf-8'))
    return mexproj, ini


@pytest.mark.parametrize('old, n_lines', [(V1_2026_10_19, 106), (V2_2026_11_20, 183)],
                         ids=['v1', 'v2'])
def test_the_recorded_old_versions_are_valid_c2s_at_the_hud_hook(old, n_lines):
    assert validate_source(old)['ok'] and validate_source(NEW)['ok']
    lines = old.split('\n')
    assert lines[0] == f'C22F3A60 {len(lines) - 1:08X}' and len(lines) == n_lines
    assert old in PREVIOUS_SOURCES


def test_the_versions_are_listed_oldest_first_and_the_current_code_is_none_of_them():
    assert PREVIOUS_SOURCES == (V1_2026_10_19, V2_2026_11_20)
    assert len({upgrade._words(p) for p in PREVIOUS_SOURCES}) == len(PREVIOUS_SOURCES)
    assert upgrade._words(code.source()) not in {upgrade._words(p) for p in PREVIOUS_SOURCES}


@OLD_VERSIONS
@pytest.mark.parametrize('enabled', [True, False])
def test_an_exact_old_entry_gets_the_current_hex_and_keeps_its_state(tmp_path, enabled, old):
    entries = [(*KELLZ[:1], True, [], KELLZ[1]),
               (NP, enabled, ['Shows the song name.'], old),
               (OTHER[0], False, [], OTHER[1])]
    mexproj, ini = _project(tmp_path, _ini(entries))

    assert upgrade.upgrade_project(mexproj, current=NEW) == 1

    codes = parse_ini(ini.read_text(encoding='utf-8'))
    assert [c['name'] for c in codes] == ['Skip Slippi SSS', code.CODE_NAME, 'Some Other Code']
    np = codes[1]
    assert np['enabled'] is enabled
    assert np['description'] == 'Shows the song name.'
    assert np['source'].split('\n') == NEW.split('\n')


def test_the_file_is_kept_byte_for_byte_outside_the_entry(tmp_path):
    before = [(*KELLZ[:1], True, [], KELLZ[1]),
              (NP, True, [], OLD),
              (OTHER[0], False, ['a description'], OTHER[1])]
    after = [before[0], (NP, True, [], NEW), before[2]]
    for nl in ('\r\n', '\n'):
        mexproj, ini = _project(tmp_path / nl.encode().hex(), _ini(before, nl))
        upgrade.upgrade_project(mexproj, current=NEW)
        assert ini.read_bytes() == _ini(after, nl).encode('utf-8')


def test_an_add_code_entry_keeps_its_mixed_line_endings_and_odd_bytes(tmp_path):
    # Just after `mexcli add-code`: '\n' between the hex lines, '\r\n' after the
    # last one. Around it: a BOM, a non-UTF-8 byte and no final newline.
    head = b'\xef\xbb\xbf$!' + KELLZ[0].encode() + b'\r\n*caf\xe9\r\n' + \
        KELLZ[1].replace('\n', '\r\n').encode() + b'\r\n\r\n'
    tail = b'$' + OTHER[0].encode() + b'\r\n' + OTHER[1].encode()
    entry = '$!{}\r\n{}\r\n\r\n'
    mexproj, ini = _project(tmp_path, head + entry.format(NP, OLD).encode() + tail)

    assert upgrade.upgrade_project(mexproj, current=NEW) == 1
    assert ini.read_bytes() == head + entry.format(NP, NEW).encode() + tail


@OLD_VERSIONS
def test_a_project_made_with_either_version_moves_to_the_shipped_code(tmp_path, old):
    """No stand-in: what the app writes into the build is code.source()."""
    entries = [(*KELLZ[:1], True, [], KELLZ[1]), (NP, True, [], old)]
    mexproj, ini = _project(tmp_path, _ini(entries))
    assert upgrade.upgrade_project(mexproj) == 1
    after = parse_ini(ini.read_text(encoding='utf-8'))
    assert after[1]['source'] == code.source() and after[1]['enabled'] is True
    assert after[0]['source'] == KELLZ[1]
    assert upgrade.upgrade_project(mexproj) == 0


@OLD_VERSIONS
@pytest.mark.parametrize('edit', [
    lambda s: s.replace('9421FFE0', '9421FFD0', 1),          # one word changed
    lambda s: s.rsplit('\n', 1)[0],                          # a line dropped
    lambda s: s + '\n60000000 00000000',                     # a line added
    lambda s: s.replace('\n', '\n\n', 1),                    # a blank line inside
])
def test_an_edited_entry_is_left_alone(tmp_path, edit, old):
    text = _ini([(NP, True, [], edit(old)), (OTHER[0], True, [], OTHER[1])])
    mexproj, ini = _project(tmp_path, text)
    assert upgrade.upgrade_project(mexproj, current=NEW) == 0
    assert ini.read_bytes() == text.encode('utf-8')


def test_case_and_spacing_are_no_edit(tmp_path):
    loose = '\n'.join('  ' + line.lower().replace(' ', '\t') for line in OLD.split('\n'))
    mexproj, ini = _project(tmp_path, _ini([(NP, True, [], loose)]))
    assert upgrade.upgrade_project(mexproj, current=NEW) == 1
    assert parse_ini(ini.read_text(encoding='utf-8'))[0]['source'] == NEW


def test_a_project_without_now_playing_is_unchanged(tmp_path):
    text = _ini([(*KELLZ[:1], True, [], KELLZ[1]), (OTHER[0], True, [], OTHER[1])])
    mexproj, ini = _project(tmp_path, text)
    stamp = ini.stat().st_mtime_ns
    assert upgrade.upgrade_project(mexproj, current=NEW) == 0
    assert ini.read_bytes() == text.encode('utf-8') and ini.stat().st_mtime_ns == stamp
    assert upgrade.upgrade_project(tmp_path / 'none' / 'project.mexproj', current=NEW) == 0


def test_running_it_twice_changes_nothing_the_second_time(tmp_path):
    mexproj, ini = _project(tmp_path, _ini([(NP, False, [], OLD), (OTHER[0], True, [], OTHER[1])]))
    assert upgrade.upgrade_project(mexproj, current=NEW) == 1
    once = ini.read_bytes()
    assert upgrade.upgrade_project(mexproj, current=NEW) == 0
    assert ini.read_bytes() == once


def test_nothing_happens_while_the_current_code_is_still_the_old_one(tmp_path):
    text = _ini([(NP, True, [], OLD)])
    mexproj, ini = _project(tmp_path, text)
    assert upgrade.upgrade_project(mexproj, current=OLD) == 0
    assert ini.read_bytes() == text.encode('utf-8')


def test_a_build_that_draws_the_song_name_itself_is_left_alone(tmp_path):
    text = _ini([(NP, True, [], OLD)])
    mexproj, ini = _project(tmp_path, text)
    (mexproj.parent / 'files' / 'plugins').mkdir()
    (mexproj.parent / 'files' / 'plugins' / 'bgm_display.dat').write_bytes(b'\0')
    assert upgrade.upgrade_project(mexproj, current=NEW) == 0
    assert ini.read_bytes() == text.encode('utf-8')


def test_the_default_current_is_the_codes_own_source(monkeypatch):
    monkeypatch.setattr(code, 'source', lambda: NEW)
    text, count = upgrade.upgrade_text(_ini([(NP, True, [], OLD)]))
    assert count == 1 and parse_ini(text)[0]['source'] == NEW


# ---- the hook: every export (and save) through MexManager ----

class _FakeExport:
    def __init__(self):
        self.stdout = iter(['{"status": "completed", "success": true}\n'])
        self.stderr = None
        self.returncode = 0

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def manager(tmp_path, monkeypatch):
    cli = tmp_path / 'mexcli.exe'
    cli.write_bytes(b'')
    mexproj, ini = _project(tmp_path, _ini([(NP, True, [], OLD), (OTHER[0], True, [], OTHER[1])]))
    monkeypatch.setattr(code, 'source', lambda: NEW)
    return mexcli_project.MexManager(str(cli), str(mexproj)), ini


def test_export_upgrades_codes_ini_before_mexcli_reads_it(manager, monkeypatch):
    mex, ini = manager
    seen = []
    monkeypatch.setattr(mexcli_project.subprocess, 'Popen',
                        lambda cmd, **kw: (seen.append((cmd[1], ini.read_text(encoding='utf-8'))),
                                           _FakeExport())[1])
    mex.export_iso(str(ini.parent / 'out.iso'))
    assert seen[0][0] == 'export'
    assert parse_ini(seen[0][1])[0]['source'] == NEW


def test_save_upgrades_too(manager, monkeypatch):
    mex, ini = manager
    monkeypatch.setattr(mex, '_run_command', lambda *args: {'success': True, 'args': args})
    assert mex.save_project()['args'][0] == 'save'
    assert parse_ini(ini.read_text(encoding='utf-8'))[0]['source'] == NEW


def test_the_upgrade_imports_no_core():
    # MexManager runs it, and standalone workers use MexManager without the
    # app's configuration (see test_backend_layout).
    subprocess.run([
        sys.executable, '-c',
        'import sys; import projects.nowplaying.upgrade; '
        "assert not any(n == 'core' or n.startswith('core.') for n in sys.modules)",
    ], cwd=BACKEND, check=True, timeout=30)


def test_a_failed_upgrade_never_stops_the_export(manager, monkeypatch):
    mex, ini = manager
    before = ini.read_bytes()

    def broken(*a, **kw):
        raise OSError('codes.ini is locked')
    monkeypatch.setattr(upgrade, 'upgrade_project', broken)
    monkeypatch.setattr(mexcli_project.subprocess, 'Popen', lambda cmd, **kw: _FakeExport())
    assert mex.export_iso(str(ini.parent / 'out.iso'))['success'] is True
    assert ini.read_bytes() == before
