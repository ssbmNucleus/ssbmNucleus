"""Which engine an added Play game runs on (play/routing.py): the fighters an m-ex disc adds,
which of them bring code of their own (Melee Unlocked's own clone test: no ftFunction symbol,
every MxDt function in the retail code), and the engine a launch then uses. The discs and
archives are small stand-ins built here; nothing is compiled."""
from tests.paths import BACKEND
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(BACKEND))

from play import launch, routing, shelf  # noqa: E402
from tests.backend.test_play_shelf import fake_plugin, stub_info  # noqa: E402
from vault.echo.datroot import build as build_archive  # noqa: E402

RETAIL_FN = 0x800D0000        # inside the retail code
MOD_FN = 0x80700000           # past it: code a mod brought
NUMBER = 0x00000042           # a number in a table, not an address


def _disc(path: Path, files: dict):
    """A GameCube disc holding `files` ({name: bytes}) in a flat FST."""
    names = bytearray()
    entries = [struct.pack('>BxxxII', 1, 0, len(files) + 1)]
    offset = 0x8000
    blobs = []
    for name, blob in files.items():
        entries.append(bytes([0]) + len(names).to_bytes(3, 'big') + struct.pack('>II', offset, len(blob)))
        names += name.encode() + b'\0'
        blobs.append((offset, blob))
        offset += (len(blob) + 0x1F) & ~0x1F
    fst = b''.join(entries) + bytes(names)
    data = bytearray(offset)
    data[0:6] = b'GALE01'
    struct.pack_into('>II', data, 0x424, 0x2000, len(fst))
    data[0x2000:0x2000 + len(fst)] = fst
    for at, blob in blobs:
        data[at:at + len(blob)] = blob
    path.write_bytes(bytes(data))
    return path


def _mxdt(added):
    """An MxDt.dat adding `added` fighters: [(name, file, {table: word})]."""
    internal_count = routing.RETAIL_KINDS + len(added)
    external_count = 26 + len(added) + 6
    data = bytearray(0x4000 + routing.FUNCTION_TABLES * internal_count * 4)
    relocs = []
    strings = 0x3000

    def pointer(at, target):
        struct.pack_into('>I', data, at, target)
        relocs.append(at)

    def string(text):
        nonlocal strings
        at = strings
        data[at:at + len(text)] = text.encode()
        strings += len(text) + 1
        return at

    meta, fighter, names, pl_files, ext_map, tables, words = 0x40, 0x80, 0x100, 0x400, 0x800, 0x900, 0x4000
    pointer(0x0, meta)
    pointer(0x8, fighter)
    pointer(0xC, tables)
    struct.pack_into('>II', data, meta + 4, internal_count, external_count)
    pointer(fighter + 0x0, names)
    pointer(fighter + 0x4, pl_files)
    pointer(fighter + 0xC, ext_map)
    for table in range(routing.FUNCTION_TABLES):
        pointer(tables + 4 * table, words + table * internal_count * 4)
    for slot, (name, file, functions) in enumerate(added):
        internal = routing.FIRST_ADDED + slot
        ext = 26 + slot
        pointer(names + 4 * ext, string(name))
        data[ext_map + 3 * ext] = internal
        pointer(pl_files + 8 * internal, string(file))
        pointer(pl_files + 8 * internal + 4, string('ftData' + name.replace(' ', '')))
        for table in range(routing.FUNCTION_TABLES):
            value = functions.get(table, RETAIL_FN if table % 2 else NUMBER)
            struct.pack_into('>I', data, words + table * internal_count * 4 + 4 * internal, value)
    return build_archive(bytes(data), sorted(relocs), [(0, routing.MEX_ROOT)], [])


def _fighter_file(symbols=('ftDataClone',)):
    return build_archive(bytes(0x40), [], [(0, s) for s in symbols], [])


@pytest.fixture
def play(tmp_path, monkeypatch):
    root = tmp_path / 'play'
    monkeypatch.setattr(shelf, 'play_root', lambda: root)
    stub_info(monkeypatch)
    return root


def _game(tmp_path, added, files):
    return _disc(tmp_path / 'game.iso', {'MxDt.dat': _mxdt(added), **files})


# --------------------------------------------------------------------------- reading the disc

def test_clones_need_no_code_and_others_do(tmp_path):
    disc = _game(tmp_path, [
        ('Plusle', 'PlPs.dat', {}),                                   # a clone
        ('Wolf', 'PlWf.dat', {}),                                     # its file carries ftFunction
        ('Hooked', 'PlHk.dat', {5: MOD_FN}),                          # MxDt points past the game
        ('Lost', 'PlLs.dat', {}),                                     # its file is not on the disc
    ], {'PlPs.dat': _fighter_file(), 'PlWf.dat': _fighter_file(('ftDataWolf', 'ftFunction')),
        'PlHk.dat': _fighter_file()})
    scratch = tmp_path / 'scratch'
    found = routing.analyze(disc, scratch)
    assert found['mex'] is True
    assert [(f['name'], f['file'], f['code']) for f in found['fighters']] == [
        ('Plusle', 'PlPs.dat', 'none'), ('Wolf', 'PlWf.dat', 'own'),
        ('Hooked', 'PlHk.dat', 'own'), ('Lost', 'PlLs.dat', 'unknown')]
    assert '80700000' in found['fighters'][2]['why']
    assert list(scratch.iterdir()) == []                              # nothing left behind


def test_a_disc_without_mex_adds_no_fighters(tmp_path):
    disc = _disc(tmp_path / 'plain.iso', {'opening.bnr': b'BNR1'})
    assert routing.analyze(disc, tmp_path / 's') == {'mex': False, 'fighters': []}
    entry = routing.decide(disc, tmp_path / 's')
    assert entry['engine'] == shelf.ENGINE_SOURCE and 'engineReason' not in entry


def test_decide_sends_code_to_the_compatibility_engine_and_says_why(tmp_path):
    disc = _game(tmp_path, [('Plusle', 'PlPs.dat', {}), ('Wolf', 'PlWf.dat', {}), ('Ike', 'PlIk.dat', {})],
                 {'PlPs.dat': _fighter_file(), 'PlWf.dat': _fighter_file(('ftFunction',)),
                  'PlIk.dat': _fighter_file(('ftFunction',))})
    entry = routing.decide(disc, tmp_path / 's')
    assert entry['engine'] == shelf.ENGINE_COMPAT
    assert entry['engineReason'] == ('Runs on the compatibility engine (slower): 2 fighters have native code '
                                     'that has not been built (Wolf, Ike).')
    assert entry['targets'][shelf.TARGET_DOLPHIN]['available'] is True
    assert entry['options'] == {'engine': 'auto'}

    clones = _game(tmp_path, [('Plusle', 'PlPs.dat', {})], {'PlPs.dat': _fighter_file()})
    assert routing.decide(clones, tmp_path / 's')['engine'] == shelf.ENGINE_SOURCE


def test_an_unreadable_fighter_table_is_not_trusted(tmp_path):
    disc = _disc(tmp_path / 'broken.iso', {'MxDt.dat': b'\x00' * 8})
    entry = routing.decide(disc, tmp_path / 's')
    assert entry['fighters'] is None and entry['engine'] == shelf.ENGINE_COMPAT
    assert 'could not read' in entry['engineReason']


def test_archive_reading_refuses_nonsense():
    with pytest.raises(ValueError):
        routing.Archive(b'short')
    with pytest.raises(ValueError):
        routing.Archive(struct.pack('>IIIII', 0, 0xFFFFFF, 0, 0, 0) + bytes(12))
    with pytest.raises(ValueError):
        routing.mex_fighters(_fighter_file())                         # no mexData root


# --------------------------------------------------------------------------- the engine a launch uses

def _owned(fighters, **extra):
    entry_id, _folder = shelf.reserve()
    return shelf.add({'id': entry_id, 'name': 'Game', 'disc': {'kind': 'owned'}, 'fighters': fighters,
                      'engine': 'compat', 'options': {'engine': 'auto'},
                      'targets': {'mu': {'available': True}, 'dolphin': {'available': True}}, **extra})


def test_plugins_in_the_games_own_folder_cover_fighters_with_code(play, tmp_path):
    entry = _owned([{'name': 'Plusle', 'code': 'none'}, {'name': 'Wolf', 'code': 'own'},
                    {'name': 'Dark Samus', 'code': 'own'}])
    client = tmp_path / 'MU'
    assert routing.effective_engine(entry, None)[0] == shelf.ENGINE_COMPAT
    # Plugins in the Melee Unlocked folder's own `fighters` are never read by a game on the shelf.
    (client / 'fighters').mkdir(parents=True)
    (client / 'fighters' / 'wolf.mufighter').write_bytes(b'plugin')
    (client / 'fighters' / 'dark_samus.mufighter').write_bytes(b'plugin')
    engine, reason = routing.effective_engine(entry, client)
    assert engine == shelf.ENGINE_COMPAT and '2 fighters' in reason
    assert routing.own_fighters(entry) is None

    own = shelf.fighters_dir(entry)
    own.mkdir(parents=True)
    assert routing.own_fighters(entry) == own
    fake_plugin(own / 'wolf.mufighter')
    engine, reason = routing.effective_engine(entry, client)
    assert engine == shelf.ENGINE_COMPAT and reason.endswith('1 fighter has native code that has not been built (Dark Samus).')
    fake_plugin(own / 'dark_samus.mufighter')
    assert routing.effective_engine(entry, client) == (shelf.ENGINE_SOURCE, None)


def test_a_plugin_built_for_another_layout_counts_as_missing(play, tmp_path, monkeypatch):
    entry = _owned([{'name': 'Wolf', 'code': 'own'}, {'name': 'Shulk', 'code': 'own'}])
    own = shelf.fighters_dir(entry)
    fake_plugin(own / 'wolf.mufighter')
    fake_plugin(own / 'shulk.mufighter', abi='00' * 16)
    client = tmp_path / 'MU'
    engine, reason = routing.effective_engine(entry, client)
    assert engine == shelf.ENGINE_COMPAT
    assert reason == ('Runs on the compatibility engine (slower): 1 fighter has a plugin built for another '
                      'version of Melee Unlocked (Shulk).')
    fake_plugin(own / 'shulk.mufighter', fmt=1)                     # the right layout, an old format
    assert routing.effective_engine(entry, client)[0] == shelf.ENGINE_COMPAT
    (own / 'shulk.mufighter').write_bytes(b'not a plugin')
    assert routing.effective_engine(entry, client)[0] == shelf.ENGINE_COMPAT
    fake_plugin(own / 'shulk.mufighter')
    assert routing.effective_engine(entry, client) == (shelf.ENGINE_SOURCE, None)
    # Without the client's facts only the name can be checked.
    fake_plugin(own / 'shulk.mufighter', abi='00' * 16)
    assert routing.effective_engine(entry, None) == (shelf.ENGINE_SOURCE, None)
    # A fighter the client has linked in needs no plugin.
    stub_info(monkeypatch, linked_fighters=['shulk'])
    (play / 'client-info.json').unlink()
    assert routing.effective_engine(entry, client) == (shelf.ENGINE_SOURCE, None)


def test_plugin_stamps_are_read_from_the_record(tmp_path):
    path = fake_plugin(tmp_path / 'wolf.mufighter', abi='0f' * 16, fmt=7)
    assert routing.plugin_stamp(path) == {'format': 7, 'abi': '0f' * 16}
    assert routing.plugin_stamp(fake_plugin(tmp_path / 'x.mufighter', magic=b'NOPE')) is None
    for junk in (b'', b'MZ' * 40, b'\x64\x86' + b'\xff' * 60):
        (tmp_path / 'junk.mufighter').write_bytes(junk)
        assert routing.plugin_stamp(tmp_path / 'junk.mufighter') is None
    assert routing.plugin_stamp(tmp_path / 'missing.mufighter') is None
    truncated = (tmp_path / 'wolf.mufighter').read_bytes()[:70]
    (tmp_path / 'cut.mufighter').write_bytes(truncated)
    assert routing.plugin_stamp(tmp_path / 'cut.mufighter') is None
    # The built-in games have no fighters folder.
    assert routing.own_fighters(shelf.get('retail')) is None and routing.own_fighters(shelf.get('vanilla')) is None


def test_the_users_choice_wins_and_old_entries_keep_theirs(play):
    entry = _owned([{'name': 'Wolf', 'code': 'own'}])
    shelf.update(entry['id'], engine_choice='source')
    assert routing.effective_engine(shelf.get(entry['id']))[0] == shelf.ENGINE_SOURCE
    shelf.update(entry['id'], engine_choice='compat')
    assert routing.effective_engine(shelf.get(entry['id']))[0] == shelf.ENGINE_COMPAT
    with pytest.raises(shelf.ShelfError):
        shelf.update(entry['id'], engine_choice='turbo')
    with pytest.raises(shelf.ShelfError):
        shelf.update('retail', engine_choice='compat')
    assert routing.effective_engine(shelf.get('retail')) == (shelf.ENGINE_SOURCE, None)
    entry_id, _ = shelf.reserve()
    older = shelf.add({'id': entry_id, 'name': 'Phase 2', 'disc': {'kind': 'owned'}, 'engine': 'source'})
    assert routing.effective_engine(older) == (shelf.ENGINE_SOURCE, None)


def test_a_launch_uses_the_engine_and_names_the_games_own_fighters(play, tmp_path, monkeypatch):
    from tests.backend.test_play_shelf import fake_client
    client_folder = fake_client(tmp_path / 'MU')
    entry = _owned([{'name': 'Wolf', 'code': 'own'}])
    (shelf.game_dir(entry) / shelf.DISC_FILE).write_bytes(b'disc')
    monkeypatch.setattr(launch.client, 'supported', lambda: True)
    shelf.write_settings(clientFolder=str(client_folder))
    monkeypatch.setattr(launch, 'retail_iso', lambda: tmp_path / 'retail.iso')
    (client_folder / 'fighters').mkdir()
    (client_folder / 'fighters' / 'wolf.mufighter').write_bytes(b'plugin')
    command = launch.plan(entry)
    assert Path(command.args[0]).name == 'melee_port.exe'
    assert command.args[1:5] == ['--iso', str(shelf.disc_path(entry)), '--mod-base-iso', str(tmp_path / 'retail.iso')]
    assert launch.PLUGINS_ENV not in command.env_set and launch.PLUGINS_ENV in command.env_unset
    # The stand-in compatibility engine names none of the launch options, so it gets none.
    assert '--fighters-dir' not in command.args and '--no-dialogs' not in command.args

    own = shelf.fighters_dir(entry)
    fake_plugin(own / 'wolf.mufighter')
    command = launch.plan(entry)
    assert Path(command.args[0]).name == 'melee_source.exe' and '--mod-iso' in command.args
    assert command.args[command.args.index('--fighters-dir') + 1] == str(own)
    assert launch.PLUGINS_ENV not in command.environment({launch.PLUGINS_ENV: 'C:\\elsewhere'})
