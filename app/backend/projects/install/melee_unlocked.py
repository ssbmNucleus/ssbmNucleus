"""
Melee Unlocked export: a fighter plugin for each of the project's custom
fighters that has its C source in the Vault.

Melee Unlocked's Source Port runs the game as native code, so a custom
fighter's compiled PowerPC (the ftFunction blob in its PlXx.dat) cannot run
there. It loads the fighter's code from a plugin instead: `<name>.mufighter`
in a `fighters` folder beside its game library, built from the same MexTK C
the PowerPC was built from. This module builds those plugins.

What it needs:
  - the fighter's C in the Vault: `custom_characters/<slug>/code/*.c` (the
    entry is fighter.c; item_N.c for articles), optionally with a
    `native.edits` file of hand edits for code that only works on the console;
  - a Melee Unlocked fighter plugin kit (its tools/mexft/mexft_kit.py makes
    one per layout id): headers, lists and the driver `tools/mexft_build.py`;
  - a MinGW-w64 GCC (the kit names the version it wants).

A project fighter is matched to its Vault folder by name (fighter.json "name"
== project fighter name), as the FSM bake does. The plugin names the fighter
the same way, so Melee Unlocked finds it in whatever slot the build gave it.

The plugin is native code the game runs, so only source a person vouched for is
compiled (projects/install/fighter_source.py): source attached in the Nucleus
window, or imported source the user confirmed there for that fighter. Source
that came in a package and was not confirmed is reported as not built, with
where it came from. The check is made on the exact bytes staged for the kit.

Nothing here touches the project or the ISO: the plugins are extra files that
go next to them.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

from core import child_procs, path_safety
from core.child_env import child_environment
from projects.install import fighter_source, mu_kit_runner
from projects.install.fsm_patcher import load_project_fighters

logger = logging.getLogger(__name__)

PLUGIN_EXTENSION = '.mufighter'
CODE_DIR = 'code'
EDITS_FILE = 'native.edits'
KIT_DRIVER = Path('tools') / 'mexft_build.py'


class MeleeUnlockedError(Exception):
    """A problem the user can act on (no kit, no compiler, nothing to build)."""


def plugin_ident(name):
    """A C identifier for a fighter name: the plugin's file and symbol name."""
    ident = re.sub(r'[^a-z0-9]+', '_', (name or '').lower()).strip('_')
    if not ident:
        ident = 'fighter'
    if ident[0].isdigit():
        ident = 'f_' + ident
    return ident


def _local_folder(value, what):
    """A folder the export runs programs from or writes to, through the request-path gate (core/path_safety.py):
    a plain path on this computer, never a share, a device or the NT namespace. Links, junctions and mapped
    drives are followed and the result checked again, so none of them leads to another computer either."""
    try:
        return path_safety.resolve_local(value, field=what)
    except path_safety.NotLocalPath as refused:
        raise MeleeUnlockedError(str(refused)) from None


def read_kit(kit_path):
    """Check a kit folder and return {'path', 'abi'}."""
    if not kit_path:
        raise MeleeUnlockedError('No Melee Unlocked fighter kit folder is set.')
    kit = _local_folder(kit_path, 'The fighter kit folder')
    missing = [str(p) for p in (KIT_DRIVER, Path('flags.json'), Path('abi.txt')) if not (kit / p).is_file()]
    if missing:
        raise MeleeUnlockedError(
            f'{kit} is not a Melee Unlocked fighter kit (missing {", ".join(missing)}).')
    return {'path': kit, 'abi': (kit / 'abi.txt').read_text(encoding='utf-8').strip()}


def check_compiler(gcc_bin):
    """Check the compiler's bin folder and return it."""
    if not gcc_bin:
        raise MeleeUnlockedError('No MinGW-w64 GCC bin folder is set.')
    folder = _local_folder(gcc_bin, 'The compiler folder')
    exe = '.exe' if os.name == 'nt' else ''
    missing = [t for t in ('gcc', 'ld', 'nm', 'objcopy') if not (folder / (t + exe)).is_file()]
    if missing:
        raise MeleeUnlockedError(f'{folder} has no {", ".join(missing)}: it is not a GCC bin folder.')
    return folder


def _vault_sources(custom_characters_dir):
    """fighter name -> {'slug', 'dir', 'dat', 'sources'} for every Vault custom character."""
    found = {}
    root = Path(custom_characters_dir)
    if not root.is_dir():
        return found
    for char_dir in sorted(root.iterdir()):
        fighter_json = char_dir / 'fighter.json'
        if not fighter_json.is_file():
            continue
        try:
            with open(fighter_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f'Melee Unlocked: cannot read {fighter_json}: {e}')
            continue
        name = data.get('name')
        if not name:
            continue
        code = char_dir / CODE_DIR
        sources = sorted(code.glob('*.c')) if code.is_dir() else []
        found[name] = {
            'slug': char_dir.name,
            'dir': char_dir,
            'dat': ((data.get('files') or {}).get('fighterDataPath') or ''),
            'sources': sources,
        }
    return found


def collect_fighters(project_path, custom_characters_dir):
    """The project's custom fighters, split by whether they have C source.

    Returns (buildable, without_source): lists of dicts with `name`, `slug`,
    `ident`, `dat`, and for the ones with source `sources`, `dir` and `trust`
    (fighter_source.status: whether a person vouched for this source, and where
    it came from; :func:`split_by_trust`). A project fighter that is no Vault
    custom character (a retail fighter) is in neither.
    """
    vault = _vault_sources(custom_characters_dir)
    buildable, without_source, seen = [], [], set()
    for _internal_id, name in load_project_fighters(project_path):
        entry = vault.get(name)
        if entry is None or name in seen:
            continue
        seen.add(name)
        row = {'name': name, 'slug': entry['slug'], 'ident': plugin_ident(name), 'dat': entry['dat']}
        if entry['sources']:
            trust = fighter_source.status(custom_characters_dir, entry['slug'],
                                          source_digest(source_files(entry['dir'] / CODE_DIR)))
            buildable.append({**row, 'sources': entry['sources'], 'dir': entry['dir'], 'trust': trust})
        else:
            without_source.append(row)
    # Two fighters whose names reduce to one identifier would overwrite each other's file.
    idents = {}
    for row in buildable:
        idents.setdefault(row['ident'], []).append(row)
    for ident, rows in idents.items():
        for n, row in enumerate(rows[1:], start=2):
            row['ident'] = f'{ident}_{n}'
    return buildable, without_source


def split_by_trust(rows):
    """(trusted, unconfirmed): the rows with source a person vouched for, and the rest."""
    trusted = [r for r in rows if (r.get('trust') or {}).get('trusted')]
    return trusted, [r for r in rows if not (r.get('trust') or {}).get('trusted')]


def unconfirmed_row(row):
    """What the export and the card say about a fighter whose source is not built: who, where it came from, why,
    the sha256 a confirmation must name and the question the window asks."""
    trust = row.get('trust') or {}
    origin = trust.get('origin') or fighter_source.BEFORE_RECORDS
    return {'name': row['name'], 'slug': row['slug'], 'origin': origin, 'recordedAt': trust.get('recordedAt'),
            'sha256': trust.get('sha256'), 'reason': trust.get('reason') or 'its C source has not been confirmed',
            'confirmText': fighter_source.confirmation_text(row['name'], origin)}


#: How long one fighter's build may take before the kit is stopped (a real port compiles in well under a minute).
KIT_TIMEOUT = 10 * 60
BACKEND_ENTRY = Path(__file__).resolve().parents[2] / 'app.py'


def _kit_command(driver, args):
    """The command line that runs the kit's driver in a child (projects/install/mu_kit_runner.py): this packaged
    program with --mu-kit, or this Python with app.py in a checkout."""
    head = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(BACKEND_ENTRY)]
    return head + [mu_kit_runner.FLAG, str(driver)] + [str(a) for a in args]


def _run_driver(kit, args, *, cwd=None, timeout=None):
    """Run the kit's driver in a child process and return what it printed.

    The driver is the kit's Python and compiles the fighter's C, so it does not run in the backend: it gets a
    process of its own (the backend program in its --mu-kit mode, since the installed app has no other Python),
    an environment without the backend token or the window's key (core/child_env.py), and ``timeout`` seconds
    (KIT_TIMEOUT) before it and the compiler it started are stopped. Its exit code decides success."""
    command = _kit_command(Path(kit) / KIT_DRIVER, args)
    limit = timeout or KIT_TIMEOUT
    proc = subprocess.Popen(command, cwd=str(cwd or kit), env=child_environment(same_program=True, python=True),
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            **_hidden(), **child_procs.own_group())
    child_procs.own(proc)
    try:
        out, _ = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        child_procs.stop_tree(proc)
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            out = b''
        printed = (out or b'').decode('utf-8', 'replace').strip()
        took = f'{limit // 60} minutes' if limit >= 120 else f'{limit} seconds'
        raise MeleeUnlockedError((printed[-1000:] + '\n' if printed else '')
                                 + f'The fighter kit took longer than {took} and was stopped.')
    printed = (out or b'').decode('utf-8', 'replace')
    if proc.returncode != 0:
        raise MeleeUnlockedError(printed.strip()[-1500:] or f'The fighter kit stopped with code {proc.returncode}.')
    return printed


def _hidden():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


#: The fighter data file a manifest may name: the game's own naming (PlXx.dat, PlXx_001.dat, PlXx.usd).
DATA_FILE = re.compile(r'Pl\w+\.(?:dat|usd)', re.ASCII)


def manifest_lines(fighter):
    """The kit's mexft.txt for a fighter. The name and the data file come from the fighter's package, and the
    manifest is one setting per line: a name with a line break (or any other control character) could add a
    setting of its own, and a data file name that is not PlXx.dat/.usd is not the game's, so both are refused."""
    name = str(fighter.get('name') or '')
    if not name.strip() or any(unicodedata.category(c)[0] == 'C' or unicodedata.category(c) in ('Zl', 'Zp')
                               for c in name):
        raise MeleeUnlockedError(f'The fighter name {name!r} has a control character or a line break, so it '
                                 'cannot go in the plugin manifest.')
    dat = fighter.get('dat') or 'Pl' + fighter['ident'] + '.dat'
    if not DATA_FILE.fullmatch(dat):
        raise MeleeUnlockedError(f'The fighter data file {dat!r} is not a PlXx.dat or PlXx.usd name, so it cannot '
                                 'go in the plugin manifest.')
    return [f'name {name}', f'file {dat}', f'mex-name {name}']


def stage_fighter(fighter, work_dir):
    """Lay a fighter's source out as the kit's driver reads it: <work>/<ident>/ with the C and
    its headers in code/, the hand edits and a mexft.txt manifest. Returns the folder."""
    lines = manifest_lines(fighter)
    folder = Path(work_dir) / fighter['ident']
    if folder.exists():
        shutil.rmtree(folder)
    (folder / CODE_DIR).mkdir(parents=True)
    for name, data in source_files(fighter['dir'] / CODE_DIR).items():
        (folder / (name if name == EDITS_FILE else Path(CODE_DIR) / name)).write_bytes(data)
    (folder / 'mexft.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    return folder


def staged_digest(folder):
    """The sha256 of the source staged in ``folder`` (stage_fighter), computed as source_digest does for the
    Vault's code folder: the bytes the kit will compile."""
    files = source_files(Path(folder) / CODE_DIR)
    files.pop(EDITS_FILE, None)
    edits = Path(folder) / EDITS_FILE
    if edits.is_file():
        files[EDITS_FILE] = edits.read_bytes()
    return source_digest(files)


def build_plugins(fighters, kit_path, gcc_bin, out_dir, work_dir, progress=None):
    """Build one plugin per fighter into `out_dir`. A fighter that fails does not stop the rest.

    Each fighter's source is checked once more as it is staged (fighter_source.status on the staged
    bytes): source nobody vouched for, or that changed after it was confirmed, is not compiled.

    Returns {'abi', 'built': [{name, slug, file, path}], 'failed': [{name, slug, error}],
    'unconfirmed': [unconfirmed_row]}.
    """
    kit = read_kit(kit_path)
    compiler = check_compiler(gcc_bin)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    built, failed, unconfirmed = [], [], []
    for i, fighter in enumerate(fighters):
        if progress:
            progress(i / max(len(fighters), 1), f"Building {fighter['name']} ({i + 1} of {len(fighters)})")
        target = out_dir / (fighter['ident'] + PLUGIN_EXTENSION)
        try:
            folder = stage_fighter(fighter, work_dir)
            trust = fighter_source.status(Path(fighter['dir']).parent, fighter['slug'], staged_digest(folder))
            if not trust['trusted']:
                shutil.rmtree(folder, ignore_errors=True)
                unconfirmed.append(unconfirmed_row({**fighter, 'trust': trust}))
                logger.warning(f"Melee Unlocked: {fighter['name']} was not built: {trust['reason']}")
                continue
            if target.exists():
                target.unlink()
            printed = _run_driver(kit['path'], [
                '--kit', kit['path'], '--gcc-bin', compiler, '--fighter', folder, '--out', target,
                '--work', Path(work_dir) / (fighter['ident'] + '.build')], cwd=work_dir)
            if not target.is_file():
                raise MeleeUnlockedError(printed.strip()[-1500:] or 'the kit wrote no plugin')
            built.append({'name': fighter['name'], 'slug': fighter['slug'], 'file': target.name,
                          'path': str(target), 'size': target.stat().st_size})
            logger.info(f"Melee Unlocked: built {target.name} for {fighter['name']}")
        except Exception as e:
            failed.append({'name': fighter['name'], 'slug': fighter['slug'], 'error': str(e)})
            logger.warning(f"Melee Unlocked: {fighter['name']} was not built: {e}")
    if progress:
        progress(1.0, 'Fighter plugins built')
    return {'abi': kit['abi'], 'built': built, 'failed': failed, 'unconfirmed': unconfirmed}


def export_plugins(project_path, custom_characters_dir, kit_path, gcc_bin, destination, work_dir,
                   progress=None):
    """The whole export: the project's custom fighters whose source a person vouched for, built into
    `<destination>/fighters/`. Returns build_plugins' result plus `withoutSource`, `folder` and, in
    `unconfirmed`, the fighters whose imported source was not confirmed (not built, with the reason)."""
    with_source, without_source = collect_fighters(project_path, custom_characters_dir)
    trusted, unconfirmed = split_by_trust(with_source)
    folder = _local_folder(destination, 'The destination folder') / 'fighters'
    rest = {'folder': str(folder), 'withoutSource': [{'name': r['name'], 'slug': r['slug']} for r in without_source]}
    if not trusted:
        read_kit(kit_path)
        return {'abi': None, 'built': [], 'failed': [], 'unconfirmed': [unconfirmed_row(r) for r in unconfirmed],
                **rest}
    result = build_plugins(trusted, kit_path, gcc_bin, folder, work_dir, progress=progress)
    result['unconfirmed'] = [unconfirmed_row(r) for r in unconfirmed] + result['unconfirmed']
    return {**result, **rest}


# ---- the fighter's C in the Vault ----

BACKSLASH = chr(92)
SOURCE_SUFFIXES = ('.c', '.h')
MAX_SOURCE_FILES = 64
MAX_SOURCE_BYTES = 2 * 1024 * 1024


def is_source_name(name):
    """A file that belongs in a fighter's code folder: C, a header, or the hand edits."""
    base = str(name).replace(BACKSLASH, '/').split('/')[-1]
    if not base or base.startswith('.') or not re.fullmatch(r'[A-Za-z0-9_.\-]+', base):
        return False
    return base == EDITS_FILE or base.lower().endswith(SOURCE_SUFFIXES)


def save_source(char_dir, files):
    """Replace a Vault custom character's code folder with `files` ({name: bytes}). Names are
    reduced to their base name; anything that is not source is left out. Returns the names kept."""
    kept = {}
    for name, data in files.items():
        base = str(name).replace(BACKSLASH, '/').split('/')[-1]
        if is_source_name(base) and len(data) <= MAX_SOURCE_BYTES:
            kept[base] = data
    if len(kept) > MAX_SOURCE_FILES:
        raise MeleeUnlockedError(f'{len(kept)} source files is more than a fighter has ({MAX_SOURCE_FILES}).')
    if not any(n.lower().endswith('.c') for n in kept):
        raise MeleeUnlockedError('No C source (.c) was found.')
    code = Path(char_dir) / CODE_DIR
    if code.exists():
        shutil.rmtree(code)
    code.mkdir(parents=True)
    for name, data in kept.items():
        (code / name).write_bytes(data)
    return sorted(kept)


def source_files(code_dir):
    """{name: bytes} of the source in a code folder, as save_source keeps it; {} when there is none."""
    code_dir = Path(code_dir)
    if not code_dir.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(code_dir.iterdir())
            if p.is_file() and is_source_name(p.name) and p.stat().st_size <= MAX_SOURCE_BYTES}


def source_digest(files):
    """The sha256 of a fighter's source ({name: bytes}): every name and its bytes, in name order. A
    confirmation (fighter_source.py) is bound to it."""
    digest = hashlib.sha256()
    for name in sorted(files):
        data = files[name]
        digest.update(name.encode('utf-8') + b'\0' + str(len(data)).encode('ascii') + b'\0')
        digest.update(data)
    return digest.hexdigest()


def _record(char_dir, state, origin):
    char_dir = Path(char_dir)
    fighter_source.record(char_dir.parent, char_dir.name, state, origin=origin,
                          digest=source_digest(source_files(char_dir / CODE_DIR)))


def attach_source(char_dir, folder):
    """The attach action (POST /api/mex/melee-unlocked/source/<slug>, which only the window may call): the
    source in a folder on this computer becomes the character's, recorded as attached by the user, so the export
    builds it. Returns the names kept."""
    kept = save_source(char_dir, source_from_folder(folder))
    _record(char_dir, fighter_source.ATTACHED, f'the folder {folder}, attached in the Nucleus window')
    return kept


def keep_imported_source(char_dir, files):
    """Source that came inside a fighter package: kept in the Vault, and recorded as untrusted with where the
    package came from (fighter_source.current_origin), so the export does not build it until the user confirms
    it in the window. Returns the names kept."""
    kept = save_source(char_dir, files)
    _record(char_dir, fighter_source.UNTRUSTED, fighter_source.current_origin())
    return kept


def confirm_source(char_dir, shown_digest):
    """The user confirmed this character's source in the window (POST .../source/<slug>/confirm, window only),
    after being shown its origin and the sha256 ``shown_digest``. Returns the record."""
    char_dir = Path(char_dir)
    files = source_files(char_dir / CODE_DIR)
    if not any(n.lower().endswith('.c') for n in files):
        raise MeleeUnlockedError('This fighter has no C source to confirm.')
    try:
        return fighter_source.confirm(char_dir.parent, char_dir.name, digest=source_digest(files),
                                      shown_digest=shown_digest)
    except ValueError as e:
        raise MeleeUnlockedError(str(e)) from None


def drop_source(char_dir):
    """Remove a character's stored source and what was recorded about it."""
    char_dir = Path(char_dir)
    code = char_dir / CODE_DIR
    if code.is_dir():
        shutil.rmtree(code)
    fighter_source.forget(char_dir.parent, char_dir.name)


def source_from_folder(folder):
    """{name: bytes} of the source files directly in a folder, or in its `code` subfolder."""
    folder = Path(folder)
    if (folder / CODE_DIR).is_dir():
        folder = folder / CODE_DIR
    if not folder.is_dir():
        raise MeleeUnlockedError(f'{folder} is not a folder.')
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())
            if p.is_file() and is_source_name(p.name) and p.stat().st_size <= MAX_SOURCE_BYTES}


def source_from_zip_members(zf, names):
    """{name: bytes} of the members of an open fighter zip that sit in a `code/` folder."""
    found = {}
    for name in names:
        parts = name.replace(BACKSLASH, '/').split('/')
        if len(parts) >= 2 and parts[-2].lower() == CODE_DIR and is_source_name(parts[-1]):
            info = zf.getinfo(name)
            if info.file_size <= MAX_SOURCE_BYTES:
                found[parts[-1]] = zf.read(name)
    return found
