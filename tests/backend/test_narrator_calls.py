"""Announcer name-calls carried by clip CONTENT, not by raw call id (#31).

ACE 2.0 points 29 fighters at one narrator clip ("Bonus Character"). The old
install reused the source build's raw call id (510059) when a clip was
missing, which in another project is whichever name-call was ported sixth --
so everyone was announced as one other character. These tests use a fake
project (SEM + sound groups) and a fake MexCLI that "decodes" clip i to a WAV
whose samples encode i.
"""
from tests.paths import BACKEND
import json
import struct
import sys
import wave
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from mexcli import commands as mexcli_commands
from core import narrator
from vault.importing import custom_character_scan as cc_scan
from projects.routes import custom_characters as cc_install

NR_BANK = 1          # sound groups: 0 = main (10 sounds), 1 = nr_name
MAIN_SOUNDS = 10


def _wav(path, token, rate=12000):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack('<4h', token, token + 1, -token, 7))


def _write_sem(path, banks):
    """banks: list of lists of scripts; script = [(op, value)]."""
    scripts = [s for b in banks for s in b]
    starts, n = [], 0
    for b in banks:
        starts.append(n); n += len(b)
    starts.append(n)
    head = struct.pack('>II', 0, 0) + struct.pack('>I', len(banks)) + struct.pack(f'>{len(starts)}I', *starts)
    table_at = len(head)
    body_at = table_at + 4 * (len(scripts) + 1)
    offsets, body = [], b''
    for sc in scripts:
        offsets.append(body_at + len(body))
        body += b''.join(bytes([op]) + value.to_bytes(3, 'big') for op, value in sc)
    offsets.append(0)
    path.write_bytes(head + struct.pack(f'>{len(offsets)}I', *offsets) + body)


class FakeProject:
    """A project whose narrator bank holds clips identified by integer tokens."""

    def __init__(self, root: Path, clips):
        self.dir = root
        self.clips = list(clips)            # token per narrator sound
        self.scripts = list(range(len(self.clips)))   # script i plays sound i
        (root / 'data' / 'sounds').mkdir(parents=True)
        (root / 'files' / 'audio' / 'us').mkdir(parents=True)
        (root / 'project.mexproj').write_text(json.dumps(
            {'soundSaveMap': {'filePaths': ['000.json', '001.json']}}))
        (root / 'data' / 'sounds' / '000.json').write_text(json.dumps(
            {'fileName': 'main.ssm', 'sounds': [{}] * MAIN_SOUNDS}))
        self.save()

    @property
    def mexproj(self):
        return self.dir / 'project.mexproj'

    def save(self):
        (self.dir / 'data' / 'sounds' / '001.json').write_text(json.dumps(
            {'fileName': 'nr_name.ssm', 'sounds': [{}] * len(self.clips)}))
        ssm = self.dir / 'files' / 'audio' / 'us' / 'nr_name.ssm'
        ssm.write_bytes(json.dumps(self.clips).encode())   # changes size/mtime
        _write_sem(self.dir / 'files' / 'audio' / 'us' / 'smash2.sem',
                   [[[(1, 0), (14, 0)]],
                    [[(1, MAIN_SOUNDS + s), (14, 0)] for s in self.scripts]])

    def call(self, script):
        return NR_BANK * 10000 + script


def fake_run(project):
    """A MexCLI stand-in: ssm-to-wav decodes, set-fighter-announcer[-id] edit."""
    calls = []

    def run(*args):
        args = [str(a) for a in args]
        cmd = args[1] if args[0].endswith('.exe') else args[0]
        rest = args[2:] if args[0].endswith('.exe') else args[1:]
        calls.append([cmd] + rest)

        class R:
            returncode = 0
        if cmd == 'ssm-to-wav':
            idx = int(rest[1])
            if idx >= len(project.clips):
                R.returncode = 1
                return R
            _wav(Path(rest[2]), project.clips[idx])
            return R
        return R
    run.calls = calls
    return run


@pytest.fixture
def proj(tmp_path, monkeypatch):
    p = FakeProject(tmp_path / 'proj', clips=[100 + i for i in range(52)])   # vanilla names
    run = fake_run(p)
    monkeypatch.setattr(narrator, '_decode',
                        lambda mexcli, ssm, index, dest, run_=None: (run('x.exe', 'ssm-to-wav', ssm, index, dest).returncode == 0))

    ported = []

    def mexcli(cli_args, **_kw):
        cmd, rest = cli_args[0], [str(a) for a in cli_args[1:]]
        if cmd == 'set-fighter-announcer':
            # MexCLI re-encodes on the way in: the ported clip's PCM differs.
            src_token = _token(Path(rest[2]))
            p.clips.append(src_token + 5000)
            p.scripts.append(len(p.clips) - 1)
            p.save()
            ported.append(src_token)
            return {'success': True, 'announcerCall': p.call(len(p.scripts) - 1)}
        if cmd == 'set-fighter-announcer-id':
            return {'success': True, 'announcerCall': int(rest[2])}
        return {}
    monkeypatch.setattr(mexcli_commands, 'run_json', mexcli)
    p.ported = ported
    return p


def _token(wav_path):
    with wave.open(str(wav_path)) as w:
        return struct.unpack('<h', w.readframes(1))[0]


def _clip(tmp_path, token, name):
    path = tmp_path / f'{name}.wav'
    _wav(path, token)
    return path


# --- matching ----------------------------------------------------------------

def test_sem_and_bank_resolution(proj):
    assert narrator.narrator_bank(proj.dir)[:2] == (NR_BANK, MAIN_SOUNDS)
    scripts = narrator.narrator_scripts(proj.dir)
    assert scripts[21] == 21 and len(scripts) == 52


def test_project_file_with_its_own_name(proj, tmp_path):
    """A build opened in place keeps its own .mexproj name (ACE ships ace.mexproj).
    Installing a character into it read a hardcoded project.mexproj and failed
    with [Errno 2] (Discord bug-reports, 2026-10-29)."""
    proj.mexproj.rename(proj.dir / 'ace.mexproj')
    assert narrator.narrator_bank(proj.dir)[:2] == (NR_BANK, MAIN_SOUNDS)
    mario = _clip(tmp_path, 100 + 21, 'mario')
    call, how = cc_install._apply_announcer(proj.dir / 'ace.mexproj', 30, mario)
    assert (call, how) == (proj.call(21), 'match')


def test_vanilla_line_is_referenced_not_copied(proj, tmp_path):
    mario = _clip(tmp_path, 100 + 21, 'mario')           # same PCM as vanilla clip 21
    call, how = cc_install._apply_announcer(proj.mexproj, 30, mario)
    assert (call, how) == (proj.call(21), 'match')
    assert proj.ported == []                              # no audio copied


def test_unique_clip_is_ported_once(proj, tmp_path):
    wolf = _clip(tmp_path, 900, 'wolf')
    call, how = cc_install._apply_announcer(proj.mexproj, 30, wolf)
    assert how == 'new' and call == proj.call(52)
    # installing the same character (or the same clip) again reuses the port
    again = _clip(tmp_path, 900, 'wolf_again')
    assert cc_install._apply_announcer(proj.mexproj, 31, again) == (call, 'ported')
    assert proj.ported == [900]


def test_shared_bonus_clip_is_ported_once_for_everyone(proj, tmp_path):
    calls = {cc_install._apply_announcer(proj.mexproj, 30 + i, _clip(tmp_path, 777, f'c{i}'))[0]
             for i in range(5)}
    assert calls == {proj.call(52)} and proj.ported == [777]


def test_distinct_clips_get_distinct_calls(proj, tmp_path):
    a = cc_install._apply_announcer(proj.mexproj, 30, _clip(tmp_path, 901, 'a'))[0]
    b = cc_install._apply_announcer(proj.mexproj, 31, _clip(tmp_path, 902, 'b'))[0]
    assert a != b and proj.ported == [901, 902]


def test_no_clip_gets_bonus_character_added_once(proj, tmp_path, monkeypatch):
    def fake_build(project_dir, mexcli, dest, run=None):
        _wav(Path(dest), 4242)
        return Path(dest)
    monkeypatch.setattr(narrator, 'build_bonus_clip', fake_build)
    first = cc_install._apply_announcer(proj.mexproj, 30, tmp_path / 'missing.wav')
    second = cc_install._apply_announcer(proj.mexproj, 31, tmp_path / 'missing.wav')
    assert first == (proj.call(52), 'bonus-new')
    assert second == (proj.call(52), 'bonus')
    assert proj.ported == [4242]                       # added once
    # a vault clip sample-identical to ours dedupes onto it
    same = _clip(tmp_path, 4242, 'same_as_ours')
    assert cc_install._apply_announcer(proj.mexproj, 32, same) == (proj.call(52), 'ported')
    # a build's own "bonus" clip that merely sounds alike is its own line
    theirs = _clip(tmp_path, 777, 'ace_bonus')
    assert cc_install._apply_announcer(proj.mexproj, 33, theirs)[1] == 'new'


def test_no_clip_and_no_source_banks_keeps_the_m_ex_default(proj, tmp_path):
    # the fake project has no nr_1p/nr_select banks to build the line from
    assert cc_install._apply_announcer(proj.mexproj, 30, tmp_path / 'missing.wav') == (None, 'none')


def test_bonus_splice_follows_the_recipe():
    r = dict(narrator.BONUS_RECIPE, cut=10, lag=5, crossfade=2)
    head = [1000] * 30
    tail = [-1000] * 40
    out = narrator.splice_bonus(head, tail, r)
    assert out[:8] == [1000] * 8                        # head up to cut - fade
    assert out[-1] == -1000 and len(out) == 8 + 4 + (40 - (10 + 2 + 5))
    fade = out[8:12]
    assert fade == sorted(fade, reverse=True) and 1000 > fade[0] and fade[-1] > -1000


def test_a_stale_port_record_is_not_trusted(proj, tmp_path):
    call, _ = cc_install._apply_announcer(proj.mexproj, 30, _clip(tmp_path, 903, 'x'))
    # the project is edited elsewhere: that script now plays a different clip
    proj.clips[proj.scripts[call % 10000]] = 42
    proj.save()
    assert narrator.resolve_call(proj.dir, narrator.pcm_hash(_clip(tmp_path, 903, 'y')),
                                 'x.exe') == (None, 'port')


def test_raw_ids_from_the_source_build_are_never_reused(proj, tmp_path):
    # the fallback that produced "everyone is Lucas TDX" is gone
    assert not hasattr(cc_install, '_find_existing_fighter_with_announcer_call')


def test_batch_plan_ports_each_new_clip_once():
    prepared = [
        {'announcer_hash': 'bonus', 'manifest': {'announcerWav': 'a.wav'}},
        {'announcer_hash': 'wolf', 'manifest': {'announcerWav': 'b.wav'}},
        {'announcer_hash': 'bonus', 'manifest': {'announcerWav': 'c.wav'}},
        {'announcer_hash': 'mario', 'manifest': {'announcerCallReuse': 510021}},
        {'announcer_hash': 'bonus', 'manifest': {'announcerWav': 'd.wav'}},
        {'announcer_hash': None, 'manifest': {}},
    ]
    owners, dupes = cc_install._plan_batch_announcers(prepared)
    assert owners == {'bonus': 0, 'wolf': 1}
    assert dupes == [(2, 0), (4, 0)]
    assert 'announcerWav' not in prepared[2]['manifest']
    assert prepared[0]['manifest']['announcerWav'] == 'a.wav'


# --- scan --------------------------------------------------------------------

def test_scan_extracts_shared_clips_and_refreshes_old_extractions(tmp_path, monkeypatch):
    """No "3+ fighters share it" heuristic: every call resolves to its clip. A
    re-scan replaces a wav an earlier scan decoded (its PCM is one of the build's
    narrator clips) and keeps one the user replaced."""
    decoded = {1529: 777}                  # sfx id -> clip token ("Bonus Character")

    def mexcli(cli_args, **_kw):
        cmd, rest = cli_args[0], [str(a) for a in cli_args[1:]]
        if cmd == 'sem-resolve':
            return {'success': True, 'sfxId': 1529}
        if cmd == 'ssm-to-wav':
            _wav(Path(rest[2]), decoded[1477 + int(rest[1])])
            return {'success': True}
        return {}
    monkeypatch.setattr(mexcli_commands, 'run_json', mexcli)
    scan = tmp_path / 'scan'
    (scan / 'files' / 'audio' / 'us').mkdir(parents=True)
    (scan / 'files' / 'audio' / 'us' / 'smash2.sem').write_bytes(b'')
    ssm_index = [(scan / 'files' / 'audio' / 'us' / 'nr_name.ssm', 1477, 60)]
    fighter = {'name': 'Metal Mario', 'announcerCall': 510059}

    fresh = tmp_path / 'fresh'; fresh.mkdir()
    updates = cc_scan._extract_audio_meta(scan, fighter, fresh, ssm_index, set())
    assert updates['has_announcer'] is True
    assert _token(fresh / 'announcer.wav') == 777

    # an old scan left somebody else's clip (e.g. the band-aid era or a wrong
    # resolution); it's one of the build's clips, so it is refreshed
    old = tmp_path / 'old'; old.mkdir()
    _wav(old / 'announcer.wav', 555)
    known = {narrator.pcm_hash(old / 'announcer.wav')}
    cc_scan._extract_audio_meta(scan, fighter, old, ssm_index, known)
    assert _token(old / 'announcer.wav') == 777

    # a user recording is not a build clip: kept
    mine = tmp_path / 'mine'; mine.mkdir()
    _wav(mine / 'announcer.wav', 4321)
    updates = cc_scan._extract_audio_meta(scan, fighter, mine, ssm_index, known)
    assert _token(mine / 'announcer.wav') == 4321 and 'has_announcer' not in updates
    assert not (mine / '.announcer_scan.wav').exists()
