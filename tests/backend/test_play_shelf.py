"""Play's shelf store (play/shelf.py) and its Melee Unlocked folder check (play/client.py):
entries, ids, atomic writes, the link-or-copy of a disc, covers, and which folders count as a
Melee Unlocked install. Everything runs in a temporary Play folder."""
from tests.paths import BACKEND
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(BACKEND))

from play import client, shelf  # noqa: E402


@pytest.fixture
def play(tmp_path, monkeypatch):
    root = tmp_path / 'play'
    monkeypatch.setattr(shelf, 'play_root', lambda: root)
    stub_info(monkeypatch)
    return root


def _added(name='PokeMelee', **extra):
    entry_id, folder = shelf.reserve()
    (folder / shelf.DISC_FILE).write_bytes(b'disc')
    entry = {'id': entry_id, 'name': name, 'description': 'A test game.', 'disc': {'kind': 'owned', 'size': 4},
             'targets': {shelf.TARGET_MU: {'available': True}, shelf.TARGET_DOLPHIN: {'available': True}},
             'defaultTarget': shelf.TARGET_MU, 'engine': shelf.ENGINE_SOURCE, **extra}
    return shelf.add(entry)


# --------------------------------------------------------------------------- entries

def test_a_new_shelf_has_the_two_built_in_games(play):
    entries = shelf.entries()
    assert [e['id'] for e in entries] == ['retail', 'vanilla']
    assert [e['name'] for e in entries] == ['Nucleus Unlocked', 'Vanilla']
    assert all(e['builtin'] for e in entries)
    assert entries[1]['options'] == {'vanilla': True}
    assert entries[1]['targets']['dolphin']['available'] is False
    assert not (play / shelf.SHELF_FILE).exists()      # nothing written just by reading


def test_add_rename_and_remove(play):
    entry = _added()
    assert len(entry['id']) == 12 and entry['builtin'] is False
    assert [e['id'] for e in shelf.entries()][2:] == [entry['id']]
    stored = json.loads((play / shelf.SHELF_FILE).read_text(encoding='utf-8'))
    assert stored['entries'][0]['name'] == 'PokeMelee' and 'builtin' not in stored['entries'][0]

    renamed = shelf.update(entry['id'], name='  PokeMelee 2\n', description='Line one\nLine two\x07')
    assert renamed['name'] == 'PokeMelee 2'
    assert renamed['description'] == 'Line one\nLine two'
    with pytest.raises(shelf.ShelfError):
        shelf.update(entry['id'], name='   ')

    data = shelf.data_dir(entry)
    data.mkdir(parents=True)
    (data / 'save.gci').write_bytes(b'x')
    shelf.remove(entry['id'])
    assert shelf.find(entry['id']) is None
    assert not shelf.game_dir(entry).exists() and not data.exists()


def test_names_are_text_and_capped(play):
    entry = _added(name='<img src=x onerror=alert(1)>' + 'x' * 200)
    assert entry['name'].startswith('<img src=x onerror=alert(1)>')    # stored as given: shown as text
    assert len(entry['name']) == shelf.MAX_NAME
    with pytest.raises(shelf.ShelfError):
        shelf.update(entry['id'], name=['not', 'text'])


def test_built_in_games_cannot_be_renamed_or_removed(play):
    with pytest.raises(shelf.ShelfError):
        shelf.update('retail', name='Mine')
    with pytest.raises(shelf.ShelfError):
        shelf.remove('vanilla')
    with pytest.raises(shelf.ShelfError):
        shelf.set_cover('retail', b'png')
    # They do remember the last place they were played.
    assert shelf.update('retail', last_target='dolphin')['lastTarget'] == 'dolphin'
    assert shelf.get('retail')['lastTarget'] == 'dolphin'
    with pytest.raises(shelf.ShelfError):
        shelf.update('vanilla', last_target='dolphin')     # Vanilla is Melee Unlocked only


@pytest.mark.parametrize('bad', ['../retail', '..', 'retail/..', 'C:\\Windows', 'ABCDEF012345', '0123456789ab/..',
                                 '', None, 5, '0123456789abc'])
def test_an_id_from_a_request_is_only_looked_up(play, bad):
    _added()
    assert shelf.find(bad) is None
    with pytest.raises(shelf.ShelfError) as raised:
        shelf.get(bad)
    assert raised.value.status == 404
    with pytest.raises(shelf.ShelfError):
        shelf.update(bad, name='x')


def test_folders_are_made_from_stored_ids_only(play):
    with pytest.raises(shelf.ShelfError):
        shelf.data_dir({'id': '..\\..\\Windows'})
    with pytest.raises(shelf.ShelfError):
        shelf.game_dir({'id': 'retail'})          # built-in games own no files
    assert shelf.data_dir({'id': 'retail'}) == play / 'data' / 'retail'


def test_stored_entries_with_a_foreign_id_are_ignored(play):
    play.mkdir(parents=True)
    (play / shelf.SHELF_FILE).write_text(json.dumps({'entries': [
        {'id': '../../evil', 'name': 'x'}, {'id': 'abcdefabcdef', 'name': 'Fine'}]}), encoding='utf-8')
    assert [e['id'] for e in shelf.entries()] == ['retail', 'vanilla', 'abcdefabcdef']


def test_reserve_never_reuses_a_folder(play, monkeypatch):
    ids = iter(['aaaaaaaaaaaa', 'aaaaaaaaaaaa', 'bbbbbbbbbbbb'])
    monkeypatch.setattr(shelf.secrets, 'token_hex', lambda n: next(ids))
    first, _ = shelf.reserve()
    second, folder = shelf.reserve()
    assert (first, second) == ('aaaaaaaaaaaa', 'bbbbbbbbbbbb') and folder.is_dir()
    # A reserved entry is not on the shelf until it is added; discard drops its folder.
    assert shelf.find(first) is None
    shelf.discard(first)
    assert not (play / 'games' / first).exists()


def test_add_refuses_an_entry_that_was_not_reserved(play):
    with pytest.raises(shelf.ShelfError):
        shelf.add({'id': 'cccccccccccc', 'name': 'x'})
    with pytest.raises(shelf.ShelfError):
        shelf.add({'id': '../x', 'name': 'x'})


def test_a_replace_swaps_the_games_files_in_one_write(play):
    first, second = _added(), _added(name='Other')
    old_dir = shelf.game_dir(first)
    (old_dir / shelf.FIGHTERS_DIR).mkdir()
    (old_dir / shelf.FIGHTERS_DIR / 'mine.muft').write_bytes(b'plugin')
    shelf.set_cover(first['id'], _png())
    files, new_dir = shelf.reserve()
    (new_dir / shelf.DISC_FILE).write_bytes(b'new disc')
    built = {'id': files, 'name': 'From the build', 'description': 'From the build', 'disc': {'kind': 'owned', 'size': 8},
             'targets': {shelf.TARGET_MU: {'available': True}}, 'defaultTarget': shelf.TARGET_MU,
             'engine': shelf.ENGINE_SOURCE}

    # Refused, and nothing changed: unknown entry, the game running, a folder that was not reserved.
    with pytest.raises(shelf.ShelfError) as raised:
        shelf.replace('0123456789ab', built, files=files)
    assert raised.value.status == 404
    with pytest.raises(shelf.ShelfError) as raised:
        shelf.replace(first['id'], built, files=files, busy=lambda: True)
    assert raised.value.status == 409
    for bad in (second['id'], first['id'], 'dddddddddddd', '../games', None):
        with pytest.raises(shelf.ShelfError):
            shelf.replace(first['id'], built, files=bad)
    assert shelf.folder_of(first['id']) == first['id'] and shelf.get(first['id'])['disc']['size'] == 4

    out, old_files = shelf.replace(first['id'], built, files=files)
    assert old_files == first['id']
    assert (out['id'], out['name'], out['description']) == (first['id'], 'PokeMelee', 'A test game.')
    assert out['files'] == files and out['cover'] is True and out['disc']['size'] == 8
    assert [e['id'] for e in shelf.entries()][2:] == [first['id'], second['id']]        # same place
    assert shelf.game_dir(shelf.get(first['id'])) == new_dir and shelf.folder_of(first['id']) == files
    assert shelf.data_dir(shelf.get(first['id'])) == play / 'data' / first['id']      # its saves stay put
    assert (new_dir / shelf.FIGHTERS_DIR / 'mine.muft').read_bytes() == b'plugin'
    assert (new_dir / shelf.COVER_FILE).is_file()
    # discard removes only a folder no entry uses.
    shelf.discard(files)
    assert new_dir.is_dir()
    shelf.discard(old_files)
    assert not old_dir.exists()
    assert shelf.folder_of('retail') is None and shelf.same_game('pokemelee') == {'id': first['id'],
                                                                                  'name': 'PokeMelee'}
    assert shelf.same_game('Melee') is None                     # a built-in game is never matched


# --------------------------------------------------------------------------- atomic writes

def test_a_failed_write_leaves_the_old_shelf(play, monkeypatch):
    entry = _added()
    before = (play / shelf.SHELF_FILE).read_bytes()

    def broken(src, dst, **kw):
        raise OSError('disk full')
    monkeypatch.setattr(shelf.file_retry, 'replace', broken)
    with pytest.raises(OSError):
        shelf.update(entry['id'], name='Changed')
    assert (play / shelf.SHELF_FILE).read_bytes() == before
    assert [p.name for p in play.iterdir() if p.suffix == '.tmp'] == []


def test_an_unreadable_shelf_is_kept_aside(play):
    play.mkdir(parents=True)
    (play / shelf.SHELF_FILE).write_text('{"entries": [', encoding='utf-8')
    assert [e['id'] for e in shelf.entries()] == ['retail', 'vanilla']
    kept = [p.name for p in play.iterdir() if p.name.startswith('shelf.unreadable-')]
    assert len(kept) == 1
    _added()     # and the shelf works again
    assert len(shelf.entries()) == 3


def test_settings_are_kept_and_cleared(play):
    assert shelf.read_settings() == {}
    shelf.write_settings(clientFolder='C:\\Games\\MU')
    assert shelf.read_settings() == {'clientFolder': 'C:\\Games\\MU'}
    shelf.write_settings(clientFolder=None)
    assert shelf.read_settings() == {}


# --------------------------------------------------------------------------- discs

def test_a_disc_is_hard_linked_when_it_can_be(play, tmp_path):
    source = tmp_path / 'artifact.iso'
    source.write_bytes(b'x' * 1000)
    target = play / 'games' / 'aaaaaaaaaaaa' / shelf.DISC_FILE
    assert shelf.link_or_copy(source, target) == 'linked'
    assert target.read_bytes() == source.read_bytes()
    assert os.stat(target).st_nlink == 2
    source.unlink()                     # the export's own copy can go; the shelf's stays
    assert target.read_bytes() == b'x' * 1000


def test_a_disc_is_copied_when_linking_fails(play, tmp_path, monkeypatch):
    source = tmp_path / 'artifact.iso'
    source.write_bytes(os.urandom(9 * 1024 * 1024))
    target = play / 'games' / 'aaaaaaaaaaaa' / shelf.DISC_FILE

    def no_link(src, dst):
        raise OSError(18, 'Not the same device')
    monkeypatch.setattr(shelf.os, 'link', no_link)
    seen = []
    assert shelf.link_or_copy(source, target, progress=seen.append) == 'copied'
    assert target.read_bytes() == source.read_bytes()
    assert seen[-1] == 1.0 and len(seen) >= 3
    assert not target.with_name(target.name + '.part').exists()


def test_a_cancelled_copy_leaves_nothing(play, tmp_path, monkeypatch):
    source = tmp_path / 'artifact.iso'
    source.write_bytes(b'x' * (9 * 1024 * 1024))
    target = play / 'games' / 'aaaaaaaaaaaa' / shelf.DISC_FILE
    monkeypatch.setattr(shelf.os, 'link', lambda a, b: (_ for _ in ()).throw(OSError('no')))
    with pytest.raises(shelf.ShelfError):
        shelf.link_or_copy(source, target, should_stop=lambda: True)
    assert list(target.parent.iterdir()) == []


def test_link_or_copy_never_overwrites(play, tmp_path):
    source = tmp_path / 'a.iso'
    source.write_bytes(b'new')
    target = tmp_path / 'b.iso'
    target.write_bytes(b'old')
    with pytest.raises(shelf.ShelfError):
        shelf.link_or_copy(source, target)
    assert target.read_bytes() == b'old'


# --------------------------------------------------------------------------- covers

def _png(size=(40, 20), mode='RGB'):
    from PIL import Image
    out = io.BytesIO()
    Image.new(mode, size, (200, 30, 30)).save(out, format='PNG')
    return out.getvalue()


def test_a_cover_is_decoded_and_kept_as_png(play):
    from PIL import Image
    entry = _added()
    jpeg = io.BytesIO()
    Image.new('RGB', (2000, 1000), (10, 20, 30)).save(jpeg, format='JPEG')
    updated = shelf.set_cover(entry['id'], jpeg.getvalue())
    assert updated['cover'] is True
    path = shelf.cover_path(updated)
    with Image.open(path) as kept:
        assert kept.format == 'PNG' and max(kept.size) == shelf.COVER_SIZE
    assert shelf.public(shelf.get(entry['id']))['hasCover'] is True


@pytest.mark.parametrize('raw', [b'', b'<svg onload=alert(1)></svg>', b'MZ\x90\x00' + b'\x00' * 100])
def test_a_cover_that_is_not_a_picture_is_refused(play, raw):
    entry = _added()
    with pytest.raises(shelf.ShelfError):
        shelf.set_cover(entry['id'], raw)
    assert shelf.cover_path(shelf.get(entry['id'])) is None


def test_cover_size_limits(play, monkeypatch):
    entry = _added()
    with pytest.raises(shelf.ShelfError) as raised:
        shelf.encode_cover(b'x' * (shelf.MAX_COVER_BYTES + 1))
    assert raised.value.status == 413
    monkeypatch.setattr(shelf, 'MAX_COVER_PIXELS', 100)
    with pytest.raises(shelf.ShelfError) as raised:
        shelf.set_cover(entry['id'], _png((20, 20)))
    assert raised.value.status == 413


def test_public_view_has_no_paths(play):
    entry = _added(origin={'kind': 'export', 'project': 'PokeMelee'})
    view = shelf.public(shelf.get(entry['id']))
    text = json.dumps(view)
    assert str(play) not in text and 'disc.iso' not in text
    assert view['removable'] is True and view['origin'] == {'kind': 'export', 'project': 'PokeMelee'}


# --------------------------------------------------------------------------- the Melee Unlocked folder

#: What Melee Unlocked 1.0.6 says about itself (melee_source.exe --print-info, MeleeUnlocked-sectest).
INFO_106 = {'version': '1.0.6', 'engine': 'source', 'cpu_baseline': 'AVX2', 'cpu_supported': True,
            'game_library': 'melee_game.dll', 'plugin_format': 2, 'plugin_abi': '5893c5d6ceb0ce7ae2ed556efdcfba98',
            'linked_fighters': [], 'fighters_folder': 'C:\\MU\\fighters', 'fighters_dir': True,
            'no_remember_iso': True, 'no_crash_dialog': True, 'no_dialogs': True}


def stub_info(monkeypatch, **changes):
    """client.read_info answering as Melee Unlocked 1.0.6 would (with `changes`); returns the
    programs it was asked about. The stand-in client of these tests cannot run."""
    asked = []

    def fake(exe, *, cwd):
        asked.append(Path(exe))
        return client.clean_info({**INFO_106, **changes})
    monkeypatch.setattr(client, 'read_info', fake)
    return asked


def fake_plugin(path: Path, *, abi=INFO_106['plugin_abi'], fmt=2, magic=b'MUFT'):
    """A minimal x86-64 COFF object with the mu_fighter_plugin record a .mufighter carries."""
    import struct
    record = magic + struct.pack('<I', fmt) + bytes.fromhex(abi)
    header = struct.pack('<HHIIIHH', 0x8664, 1, 0, 60 + len(record), 1, 0, 0)
    section = b'.rdata\0\0' + struct.pack('<IIIIIIHHI', 0, 0, len(record), 60, 0, 0, 0, 0, 0)
    name = b'mu_fighter_plugin\0'
    symbol = b'\0\0\0\0' + struct.pack('<I', 4) + struct.pack('<IhHBB', 0, 1, 0, 2, 0)
    strings = struct.pack('<I', 4 + len(name)) + name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + section + record + symbol + strings)
    return path


def fake_client(root: Path, *, compat=True):
    root.mkdir(parents=True, exist_ok=True)
    # A stand-in program file that names the launch options, as a 1.0.6 one does (client.mentions).
    (root / client.SOURCE_EXE).write_bytes(b'MZ ' + ' '.join(client.LAUNCH_OPTIONS).encode())
    (root / client.GAME_DLL).write_bytes(b'MZ')
    (root / client.SYS_DIR).mkdir(exist_ok=True)
    if compat:
        (root / client.COMPAT_EXE).write_bytes(b'MZ')
    return root


def test_a_melee_unlocked_folder_is_verified(play, tmp_path):
    folder = fake_client(tmp_path / 'MeleeUnlocked')
    result = client.verify(str(folder))
    assert result['valid'] is True and result['folder'] == str(folder.resolve())
    assert result['engines'] == {'source': True, 'compat': True}
    assert client.executable(client.check_folder(str(folder)), 'source') == folder.resolve() / 'melee_source.exe'
    assert client.executable(client.check_folder(str(folder)), 'compat') == folder.resolve() / 'melee_port.exe'
    # Without the compatibility engine the folder still plays everything else.
    (folder / client.COMPAT_EXE).unlink()
    assert client.verify(str(folder))['engines']['compat'] is False
    with pytest.raises(client.ClientError):
        client.executable(folder, 'compat')


@pytest.mark.parametrize('missing', ['melee_source.exe', 'melee_game.dll', 'Sys'])
def test_a_folder_missing_a_part_is_refused(play, tmp_path, missing):
    folder = fake_client(tmp_path / 'MU')
    target = folder / missing
    target.rmdir() if target.is_dir() else target.unlink()
    result = client.verify(str(folder))
    assert result['valid'] is False and missing in result['error']


@pytest.mark.parametrize('value', [
    '\\\\server\\share\\MU', '//server/share/MU', 'file://server/share/MU', '\\\\?\\C:\\MU', '\\\\.\\C:\\MU',
    '\\??\\C:\\MU', 'MU', '.\\MU', '/MU', '', None, 12])
def test_only_a_folder_on_this_computer_is_accepted(play, value):
    result = client.verify(value)
    assert result['valid'] is False and result['error']


def test_the_clients_facts_are_read_once_per_program(play, tmp_path, monkeypatch):
    asked = stub_info(monkeypatch)
    folder = fake_client(tmp_path / 'MU')
    result = client.verify(str(folder))
    assert result['valid'] is True and result['version'] == '1.0.6'
    assert result['cpuBaseline'] == 'AVX2' and result['cpuSupported'] is True
    assert result['pluginAbi'] == INFO_106['plugin_abi'] and result['pluginFormat'] == 2
    assert result['features'] == {'fighters_dir': True, 'no_remember_iso': True, 'no_crash_dialog': True,
                                  'no_dialogs': True}
    assert result['playback'] is False
    (folder / client.SYS_PLAYBACK_DIR).mkdir()
    assert client.verify(str(folder))['playback'] is True
    client.configured()
    client.status()
    assert len(asked) == 1                         # the same program is not asked again
    cache = json.loads((play / client.INFO_CACHE_FILE).read_text(encoding='utf-8'))
    record = cache[str(folder.resolve() / client.SOURCE_EXE)]
    assert record['stamp'] == client.file_stamp(folder / client.SOURCE_EXE) and record['info']['version'] == '1.0.6'
    # A new program file is asked again.
    (folder / client.SOURCE_EXE).write_bytes(b'MZ newer ' + ' '.join(client.LAUNCH_OPTIONS).encode())
    stub_info(monkeypatch, version='1.0.7')
    assert client.verify(str(folder))['version'] == '1.0.7'
    # Only the newest few programs are remembered.
    for n in range(6):
        client.verify(str(fake_client(tmp_path / f'MU{n}')))
    assert len(json.loads((play / client.INFO_CACHE_FILE).read_text(encoding='utf-8'))) == client._INFO_CACHE_KEEP


def test_a_client_too_old_for_nucleus_is_refused(play, tmp_path, monkeypatch):
    folder = fake_client(tmp_path / 'MU')
    stub_info(monkeypatch, version='1.0.5', fighters_dir=False, no_dialogs=False)
    result = client.verify(str(folder))
    assert result['valid'] is False
    assert result['error'] == ('This Nucleus Unlocked (1.0.5) is too old for SSBM Nucleus: it cannot start each game '
                               'with its own fighters and without message boxes. Update Nucleus Unlocked and try again.')
    with pytest.raises(client.ClientError):
        client.save(str(folder))
    assert client.configured() is None


def test_a_client_that_cannot_say_what_it_is_is_refused_for_a_while(play, tmp_path, monkeypatch):
    folder = fake_client(tmp_path / 'MU')
    calls = []

    def fails(exe, *, cwd):
        calls.append(exe)
        raise client.ClientError('Melee Unlocked did not answer within 10 seconds when asked which version it is.')
    monkeypatch.setattr(client, 'read_info', fails)
    assert 'did not answer' in client.verify(str(folder))['error']
    assert 'did not answer' in client.verify(str(folder))['error']
    assert len(calls) == 1                         # not started again on every look
    cache_file = play / client.INFO_CACHE_FILE
    cache = json.loads(cache_file.read_text(encoding='utf-8'))
    for record in cache.values():
        record['readAt'] = '2020-01-01T00:00:00+00:00'
    cache_file.write_text(json.dumps(cache), encoding='utf-8')
    stub_info(monkeypatch)
    assert client.verify(str(folder))['valid'] is True


class _Ran:
    def __init__(self, stdout=b'', returncode=0):
        self.stdout, self.returncode = stdout, returncode


def _program(tmp_path, *, mentions=True):
    exe = tmp_path / 'MU' / client.SOURCE_EXE
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b'MZ ' + (client.INFO_OPTION.encode() if mentions else b'') + b' --frames')
    return exe


def test_print_info_is_an_argument_list_with_a_scrubbed_environment(tmp_path, monkeypatch):
    seen = {}

    def run(args, **kwargs):
        seen.update(kwargs, args=args)
        return _Ran(json.dumps({**INFO_106, 'extra': 'ignored', 'version': '1.0.6\x07'}).encode() + b'\r\n')
    monkeypatch.setattr(client.subprocess, 'run', run)
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', 'secret-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
    exe = _program(tmp_path)
    info = client.read_info(exe, cwd=tmp_path / 'info')
    assert seen['args'] == [str(exe), '--print-info']
    assert seen['shell'] is False and seen['timeout'] == client.INFO_TIMEOUT
    assert seen['stdin'] == client.subprocess.DEVNULL and seen['stderr'] == client.subprocess.DEVNULL
    assert seen['cwd'] == str(tmp_path / 'info') and (tmp_path / 'info').is_dir()
    assert 'NUCLEUS_UI_APPROVAL_KEY' not in seen['env'] and 'OPENAI_API_KEY' not in seen['env']
    if os.name == 'nt':
        assert seen['creationflags'] & client.subprocess.CREATE_NO_WINDOW
    assert info['version'] == '1.0.6' and 'extra' not in info
    assert info['plugin_abi'] == INFO_106['plugin_abi'] and info['fighters_dir'] is True


def test_a_program_that_does_not_name_print_info_is_never_started(tmp_path, monkeypatch):
    monkeypatch.setattr(client.subprocess, 'run', lambda *a, **k: pytest.fail('started'))
    with pytest.raises(client.ClientError, match='too old for SSBM Nucleus'):
        client.read_info(_program(tmp_path, mentions=False), cwd=tmp_path)


@pytest.mark.parametrize('answer, words', [
    (_Ran(b'{"error": "melee_game.dll is missing"}', 1), 'could not say which version it is: melee_game.dll is missing'),
    (_Ran(b'not json', 0), 'did not say which version it is (exit code 0)'),
    (_Ran(b'["a list"]', 0), 'did not say which version it is'),
    (_Ran(json.dumps(INFO_106).encode(), 5), 'exit code 5'),
    (client.subprocess.TimeoutExpired(['x'], 10), 'did not answer within 10 seconds'),
    (FileNotFoundError(2, 'The system cannot find the file specified'), 'could not be started'),
])
def test_print_info_failures_say_what_happened(tmp_path, monkeypatch, answer, words):
    def run(*args, **kwargs):
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr(client.subprocess, 'run', run)
    with pytest.raises(client.ClientError) as caught:
        client.read_info(_program(tmp_path), cwd=tmp_path)
    assert words in str(caught.value)


def test_clean_info_keeps_only_checked_facts():
    info = client.clean_info({'version': 'x' * 100, 'cpu_supported': 'yes', 'plugin_format': True,
                              'plugin_abi': 'not hex', 'linked_fighters': ['wolf', 3, '', 'a\nb'] + ['z'] * 100,
                              'fighters_dir': 1, 'no_dialogs': True})
    assert len(info['version']) == 40 and info['cpu_supported'] is None and info['plugin_format'] is None
    assert info['plugin_abi'] is None and info['linked_fighters'][:2] == ['wolf', 'ab']
    assert len(info['linked_fighters']) <= 64
    assert info['fighters_dir'] is False and info['no_dialogs'] is True
    # The release-build fields: true, false, or None when the client does not say (or says something else).
    assert info['public_build'] is None and info['game_public_build'] is None
    said = client.clean_info({'public_build': True, 'game_public_build': 'true'})
    assert said['public_build'] is True and said['game_public_build'] is None
    assert client.is_release_build(said) is False
    assert client.is_release_build(client.clean_info({'public_build': True, 'game_public_build': True})) is True
    assert client.clean_info({'plugin_abi': 'ABCDEF01'})['plugin_abi'] == 'abcdef01'
    with pytest.raises(client.ClientError):
        client.clean_info(['not', 'an', 'object'])


def test_a_folder_holding_play_data_is_refused(play, tmp_path):
    folder = fake_client(play / 'games' / 'x')
    assert client.verify(str(folder))['valid'] is False
    outer = fake_client(tmp_path)          # the Play folder is inside this one
    play.mkdir(parents=True, exist_ok=True)
    assert client.verify(str(outer))['valid'] is False


def test_the_saved_folder_is_verified_each_time(play, tmp_path):
    folder = fake_client(tmp_path / 'MU')
    status = client.save(str(folder))
    assert status['set'] and status['valid']
    assert client.configured() == folder.resolve()
    (folder / client.GAME_DLL).unlink()
    assert client.configured() is None
    assert client.status()['valid'] is False
    with pytest.raises(client.ClientError):
        client.save(str(tmp_path / 'nothing-here'))
    assert client.save('')['set'] is False
