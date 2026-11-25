"""
Where an added game can run: which of its fighters need code of their own, and so which
Melee Unlocked engine plays it.

    analyze(disc, scratch)                 the fighters an m-ex disc adds, each with or without code
    decide(disc)                           what the shelf stores when the game is added
    effective_engine(entry, client_folder) the engine a launch uses now, and why

Melee Unlocked's Source Port (melee_source.exe) runs the game as native code, so the
PowerPC a custom fighter brings cannot run there: such a fighter needs a native plugin
(`<name>.mufighter`), built from its C. A fighter with no code of its own (a clone: Dr.
Mario's moves on another model) needs none. The test is Melee Unlocked's own
(sourceport/game/akaneia/mu_ak_fighters.c, clone_fighter): the fighter's file has no
`ftFunction` public symbol, and every function MxDt gives it is the game's own (an address
in the retail code range; a smaller word is a number, not an address).

A game whose fighters all need no code, or whose fighters with code all have a plugin in
the game's own fighters folder (``games/<id>/fighters``, the one folder it is started
with), runs on the Source Port. Otherwise it runs on the compatibility engine
(melee_port.exe, slower), and the card says why. Dolphin plays every added game.

Nothing here builds a plugin. A fighter package's C is compiled only by an explicit action
the user confirms (not part of Play yet), never as a side effect of adding a game.

The disc is only read: MxDt.dat and each added fighter's file are extracted to `scratch`
(a folder the add job owns) and removed again.
"""

import logging
import struct
from pathlib import Path

from play import shelf

logger = logging.getLogger(__name__)

MXDT_FILE = 'MxDt.dat'
MEX_ROOT = 'mexData'
FUNCTION_SYMBOL = 'ftFunction'
PLUGIN_EXTENSION = '.mufighter'

RETAIL_KINDS = 33               # Mario .. Sandbag: the retail internal fighter kinds
FIRST_ADDED = 27                # m-ex puts added fighters at Master Hand's kind and shifts the six specials
FUNCTION_TABLES = 46            # the MxDt ftFunction tables Melee Unlocked checks
RETAIL_CODE = (0x80003100, 0x804DEC00)

CODE_NONE = 'none'              # a clone: plays on the Source Port as it is
CODE_OWN = 'own'                # brings code: needs a plugin on the Source Port
CODE_UNKNOWN = 'unknown'        # its file could not be read: treated as bringing code

_MAX_ARCHIVE = 64 * 1024 * 1024


# --------------------------------------------------------------------------- HSD archives

class Archive:
    """An HSD archive (a .dat): its data block, which words are pointers, its public symbols."""

    def __init__(self, raw: bytes):
        if len(raw) < 0x20 or len(raw) > _MAX_ARCHIVE:
            raise ValueError('not an archive')
        _size, data_size, relocs, publics, externs = struct.unpack_from('>IIIII', raw, 0)
        table = 0x20 + data_size + relocs * 4
        names = table + (publics + externs) * 8
        if data_size > len(raw) or relocs > len(raw) // 4 or publics > 4096 or externs > 4096 or names > len(raw):
            raise ValueError('not an archive')
        self.data = raw[0x20:0x20 + data_size]
        self.relocs = set(struct.unpack_from(f'>{relocs}I', raw, 0x20 + data_size))
        self.publics = {}
        for i in range(publics):
            offset, name_at = struct.unpack_from('>II', raw, table + i * 8)
            start = names + name_at
            end = raw.find(b'\0', start)
            if start >= len(raw) or end < 0:
                raise ValueError('bad symbol name')
            self.publics[raw[start:end].decode('ascii', 'replace')] = offset

    def word(self, at):
        if at < 0 or at + 4 > len(self.data):
            raise ValueError('outside the data block')
        return struct.unpack_from('>I', self.data, at)[0]

    def pointer(self, at):
        """The data offset the pointer word at `at` points to, or None (an empty pointer)."""
        if at not in self.relocs:
            return None
        target = self.word(at)
        if target >= len(self.data):
            raise ValueError('pointer outside the data block')
        return target

    def string(self, at):
        if at is None:
            return None
        end = self.data.find(b'\0', at)
        if end < 0:
            raise ValueError('unterminated string')
        return self.data[at:end].decode('ascii', 'replace')


def has_public_symbol(raw: bytes, symbol: str) -> bool:
    return symbol in Archive(raw).publics


def retail_address(value):
    return RETAIL_CODE[0] <= value < RETAIL_CODE[1]


def mex_fighters(mxdt: bytes):
    """The fighters an m-ex MxDt.dat adds: [{internal, name, file, outside}] where `outside` is
    the first function MxDt gives it outside the retail code (None when every one is retail)."""
    archive = Archive(mxdt)
    root = archive.publics.get(MEX_ROOT)
    if root is None:
        raise ValueError('no mexData')
    metadata = archive.pointer(root + 0x0)
    fighter = archive.pointer(root + 0x8)
    functions = archive.pointer(root + 0xC)
    if metadata is None or fighter is None:
        raise ValueError('no fighter tables')
    internal_count = archive.word(metadata + 4)
    external_count = archive.word(metadata + 8)
    if internal_count > 512 or external_count > 512:
        raise ValueError('implausible fighter count')
    added = max(0, internal_count - RETAIL_KINDS)
    names = archive.pointer(fighter + 0x0)
    pl_files = archive.pointer(fighter + 0x4)
    ext_map = archive.pointer(fighter + 0xC)

    name_of = {}
    if names is not None and ext_map is not None:
        for ext in range(external_count):
            if ext_map + 3 * ext >= len(archive.data):
                break
            internal = archive.data[ext_map + 3 * ext]
            if internal not in name_of:
                name_of[internal] = archive.string(archive.pointer(names + 4 * ext))

    out = []
    for slot in range(added):
        internal = FIRST_ADDED + slot
        file = symbol = None
        if pl_files is not None:
            file = archive.string(archive.pointer(pl_files + 8 * internal))
            symbol = archive.string(archive.pointer(pl_files + 8 * internal + 4))
        outside = None
        if functions is not None:
            for table in range(FUNCTION_TABLES):
                words = archive.pointer(functions + 4 * table)
                if words is None or words + 4 * internal + 4 > len(archive.data):
                    continue
                value = archive.word(words + 4 * internal)
                if value >= 0x80000000 and not retail_address(value):
                    outside = value
                    break
        out.append({'internal': internal, 'name': name_of.get(internal) or symbol or file or f'Fighter {internal}',
                    'file': file, 'outside': outside})
    return out


# --------------------------------------------------------------------------- a disc

def _extract(disc: Path, name: str, scratch: Path):
    """The bytes of one file of the disc, or None when it has none. Extracted to `scratch`."""
    from shared.vanilla_extract.vanilla_refs import extract_file_from_iso
    target = scratch / f'{name}.part'
    try:
        if not extract_file_from_iso(disc, name, target):
            return None
        return target.read_bytes()
    finally:
        try:
            target.unlink()
        except OSError:
            pass


def analyze(disc: Path, scratch: Path):
    """{'mex': bool, 'fighters': [{name, file, code, why}]} for a disc (module docstring)."""
    scratch.mkdir(parents=True, exist_ok=True)
    mxdt = _extract(disc, MXDT_FILE, scratch)
    if mxdt is None:
        return {'mex': False, 'fighters': []}
    found = []
    for fighter in mex_fighters(mxdt):
        row = {'name': fighter['name'], 'file': fighter['file']}
        if fighter['outside'] is not None:
            row.update(code=CODE_OWN, why=f'a function outside the game ({fighter["outside"]:08X})')
        elif not fighter['file']:
            row.update(code=CODE_UNKNOWN, why='no fighter file')
        else:
            try:
                raw = _extract(disc, fighter['file'], scratch)
                if raw is None:
                    row.update(code=CODE_UNKNOWN, why='its file is not on the disc')
                elif has_public_symbol(raw, FUNCTION_SYMBOL):
                    row.update(code=CODE_OWN, why='its file carries code (ftFunction)')
                else:
                    row.update(code=CODE_NONE, why='no code of its own')
            except (OSError, ValueError, struct.error) as e:
                row.update(code=CODE_UNKNOWN, why=f'its file could not be read ({e})')
        found.append(row)
    return {'mex': True, 'fighters': found}


def needs_code(entry):
    """The fighters of an entry that bring code of their own (or could not be checked)."""
    return [f for f in entry.get('fighters') or [] if isinstance(f, dict) and f.get('code') != CODE_NONE]


def plugin_name(fighter_name):
    """The plugin file a fighter's code is in: Melee Unlocked's own naming
    (projects/install/melee_unlocked.plugin_ident)."""
    from projects.install.melee_unlocked import plugin_ident
    return plugin_ident(fighter_name) + PLUGIN_EXTENSION


def own_fighters(entry):
    """An added entry's own fighters folder (installed fighters and plugins) when it has one,
    else None: the game is then started with ``--fighters-dir none``. The Melee Unlocked
    folder's own `fighters` is never used by a game on the shelf."""
    if entry.get('builtin') or entry.get('id') in shelf.BUILTIN_IDS:
        return None
    folder = shelf.fighters_dir(entry)
    return folder if folder is not None and folder.is_dir() else None


PLUGIN_SYMBOL = b'mu_fighter_plugin'
PLUGIN_MAGIC = b'MUFT'
_MAX_PLUGIN = 16 * 1024 * 1024
_COFF_AMD64 = 0x8664


def plugin_stamp(path):
    """{'format', 'abi'} a .mufighter was built for, or None when it is not one Nucleus can read.

    A plugin is an x86-64 COFF object. Its `mu_fighter_plugin` record starts with 'MUFT', then
    the plugin format (u32, little-endian) and the 16-byte fighter layout id: the `plugin_format`
    and `plugin_abi` a client's --print-info reports (the game refuses a plugin built for another
    layout: "built for fighter layouts ... build it again for this version"). Only read, bounds
    checked at every step; a file over 16 MB is not looked at."""
    try:
        size = Path(path).stat().st_size
        if size < 20 or size > _MAX_PLUGIN:
            return None
        raw = Path(path).read_bytes()
        machine, sections, _ts, symbols_at, symbols, optional, _flags = struct.unpack_from('<HHIIIHH', raw, 0)
        if machine != _COFF_AMD64 or sections > 512 or symbols > 1 << 20:
            return None
        strings_at = symbols_at + symbols * 18
        if strings_at > len(raw):
            return None
        index = 0
        while index < symbols:
            at = symbols_at + index * 18
            name_raw = raw[at:at + 8]
            if name_raw[:4] == b'\0\0\0\0':
                offset = strings_at + struct.unpack_from('<I', name_raw, 4)[0]
                end = raw.find(b'\0', offset)
                name = raw[offset:end] if 0 <= offset < len(raw) and end >= 0 else b''
            else:
                name = name_raw.rstrip(b'\0')
            value, section, _type, _class, aux = struct.unpack_from('<IhHBB', raw, at + 8)
            if name == PLUGIN_SYMBOL and 1 <= section <= sections:
                header = 20 + optional + (section - 1) * 40
                _vsize, _vaddr, raw_size, raw_at = struct.unpack_from('<IIII', raw, header + 8)
                if value + 24 > raw_size or raw_at + raw_size > len(raw):
                    return None
                record = raw[raw_at + value:raw_at + value + 24]
                if record[:4] != PLUGIN_MAGIC:
                    return None
                return {'format': struct.unpack_from('<I', record, 4)[0], 'abi': record[8:24].hex()}
            index += 1 + aux
    except (OSError, struct.error, ValueError):
        return None
    return None


def plugin_fits(path, info):
    """True when the plugin at `path` was built for the client whose facts are `info`
    (client.facts: plugin_format and plugin_abi). Without those facts nothing can be said, so
    a plugin of the right name counts."""
    if not info or not info.get('plugin_abi') or info.get('plugin_format') is None:
        return True
    stamp = plugin_stamp(path)
    return stamp is not None and stamp['format'] == info['plugin_format'] and stamp['abi'] == info['plugin_abi']


def _plain(names):
    names = [n for n in names if n]
    if len(names) <= 3:
        return ', '.join(names)
    return f"{', '.join(names[:3])} and {len(names) - 3} more"


def _compat_reason(missing, stale=()):
    parts = []
    if missing:
        count = len(missing)
        fighters = 'fighter has' if count == 1 else 'fighters have'
        parts.append(f'{count} {fighters} native code that has not been built '
                     f'({_plain([f.get("name") for f in missing])})')
    if stale:
        count = len(stale)
        plugins = 'fighter has a plugin' if count == 1 else 'fighters have plugins'
        parts.append(f'{count} {plugins} built for another version of Melee Unlocked '
                     f'({_plain([f.get("name") for f in stale])})')
    return f'Runs on the compatibility engine (slower): {"; ".join(parts)}.'


def decide(disc: Path, scratch: Path = None):
    """What the shelf stores for a newly added game: its fighters and the engine they call for
    (before any Melee Unlocked folder is looked at), its targets, and engine choice 'auto'."""
    scratch = scratch or Path(disc).parent
    try:
        found = analyze(Path(disc), scratch)
    except (OSError, ValueError, struct.error) as e:
        logger.warning('Play: could not read the fighter tables of %s: %s', Path(disc).name, e)
        found = {'mex': True, 'fighters': None, 'error': str(e)}
    entry = {
        'mex': found['mex'],
        'fighters': found['fighters'],
        'targets': {shelf.TARGET_MU: {'available': True}, shelf.TARGET_DOLPHIN: {'available': True}},
        'defaultTarget': shelf.TARGET_MU,
        'options': {'engine': 'auto'},
    }
    if found['fighters'] is None:
        entry['engine'] = shelf.ENGINE_COMPAT
        entry['engineReason'] = ('Runs on the compatibility engine (slower): Nucleus could not read which '
                                 'fighters this game adds.')
        return entry
    missing = needs_code(entry)
    entry['engine'] = shelf.ENGINE_COMPAT if missing else shelf.ENGINE_SOURCE
    if missing:
        entry['engineReason'] = _compat_reason(missing)
    for fighter in found['fighters']:
        logger.info('Play: %s (%s): %s', fighter['name'], fighter['file'], fighter['why'])
    return entry


def effective_engine(entry, client_folder=None):
    """(engine, reason) a launch of `entry` uses with the Melee Unlocked folder `client_folder`.

    Built-in games and games added before fighters were checked run on the Source Port. The
    user's own choice in the entry menu wins. Otherwise a fighter with code is covered by a
    plugin of the same name in the entry's own fighters folder (the only one the game reads,
    ``--fighters-dir``) and built for this client's fighter layout (its --print-info
    `plugin_format` and `plugin_abi`: a plugin built for another one counts as missing), or by
    a fighter the client has linked in (`linked_fighters`); one not covered sends the game to
    the compatibility engine. Without the client's facts a plugin of the right name counts.
    The two built-in games always run on the Source Port: the compatibility engine (melee_port.exe)
    is retired and no Nucleus client has it."""
    if entry.get('builtin') or entry.get('id') in shelf.BUILTIN_IDS:
        return shelf.ENGINE_SOURCE, None
    choice = (entry.get('options') or {}).get('engine')
    if choice == shelf.ENGINE_SOURCE:
        return shelf.ENGINE_SOURCE, None
    if choice == shelf.ENGINE_COMPAT:
        return shelf.ENGINE_COMPAT, 'Runs on the compatibility engine (slower): chosen in its menu.'
    if entry.get('builtin') or (entry.get('disc') or {}).get('kind') != 'owned':
        return shelf.ENGINE_SOURCE, None
    if entry.get('fighters') is None:
        if 'fighters' not in entry:
            return entry.get('engine') or shelf.ENGINE_SOURCE, entry.get('engineReason')
        return shelf.ENGINE_COMPAT, entry.get('engineReason')
    needed = needs_code(entry)
    if not needed:
        return shelf.ENGINE_SOURCE, None
    from play import client
    info = client.known_facts(client_folder)
    linked = {str(name).lower() for name in (info or {}).get('linked_fighters') or []}
    plugins = own_fighters(entry)
    missing, stale = [], []
    for fighter in needed:
        name = plugin_name(fighter.get('name'))
        if name[:-len(PLUGIN_EXTENSION)].lower() in linked:
            continue
        path = plugins / name if plugins is not None else None
        if path is None or not path.is_file():
            missing.append(fighter)
        elif not plugin_fits(path, info):
            stale.append(fighter)
    if not missing and not stale:
        return shelf.ENGINE_SOURCE, None
    return shelf.ENGINE_COMPAT, _compat_reason(missing, stale)


def with_engine(public_entry, entry, client_folder=None):
    """A public entry with the engine a launch would use now and why."""
    engine, reason = effective_engine(entry, client_folder)
    out = dict(public_entry)
    out['engine'] = engine
    out['engineChoice'] = (entry.get('options') or {}).get('engine') or 'auto'
    if reason:
        out['engineReason'] = reason
    else:
        out.pop('engineReason', None)
    return out
