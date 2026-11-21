"""Melee menu screens: the CSS (character select) and SSS (stage select) backdrops.

A menu background is not a flat image - it is a 3D model bundle
(``background.dat``) that lives inside ``MnSlChr.usd`` (CSS) or ``MnSlMap.usd``
(SSS). Nucleus swaps the bundle; it cannot paste a PNG onto the screen.

The offline workflow, all inside the workspace:

    packs = menus.list_background_mods()                 # already-imported pool
    bg    = menus.export_background_mod(packs[0]['id'], 'out/background.dat')
    # or, from a mod downloaded off the website:
    bg    = menus.extract_background('out/halo-css.zip', 'out/background.dat')['path']

    src   = menus.list_menu_files()                      # MnSlChr.usd / MnSlMap.usd
    out   = menus.install_background(bg, 'out/MnSlChr.usd', menu_type='css',
                                     menu_file=src[0]['path'])['path']
"""
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

from core.hashing import sha256_file, sha256_stream
from ._workspace import TrustedPath, in_path, library_path, out_path, read_input

MENU_FILES = {'css': 'MnSlChr', 'sss': 'MnSlMap'}


def _hsdraw(args, timeout=180):
    from core.config import HSDRAW_EXE, get_subprocess_args
    exe = Path(HSDRAW_EXE)
    if not exe.is_file():
        raise ValueError('HSDRaw is unavailable in this installation.')
    result = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True,
                            timeout=timeout, **get_subprocess_args())
    if result.returncode != 0:
        raise ValueError(f'HSDRaw {args[0]} failed: {(result.stdout or "")[-800:]} {(result.stderr or "")[-400:]}')
    return result.stdout


def _pool():
    from core import config
    return (config.STORAGE_PATH.resolve() / 'menus' / 'css' / 'background')


def list_background_mods(menu_type=None):
    """List the menu background bundles already imported into this Nucleus install.

    Args:
        menu_type: 'css', 'sss', or None for both. A CSS backdrop and an SSS
            backdrop are different models.

    Returns:
        list[dict]: ``{'id', 'name', 'description', 'source' ('css'|'sss'),
        'dat_path' (the background.dat, read-only), 'screenshot_path' (or None)}``.

    Example:
        >>> from nucleus_api import menus
        >>> menus.list_background_mods('css')
        [{'id': '2602dc69', 'name': 'Halo 3 Matchmaking Lobby', 'source': 'css', ...}]
    """
    root = _pool()
    catalog_path = root / 'metadata.json'
    if not catalog_path.is_file():
        return []
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    rows = []
    for entry in catalog.get('mods', []):
        source = entry.get('source')
        if menu_type in ('css', 'sss') and source and source != menu_type:
            continue
        dat = root / entry['id'] / 'background.dat'
        shot = root / entry['id'] / (entry.get('screenshot') or '')
        rows.append({'id': entry['id'], 'name': entry.get('name', ''),
                     'description': entry.get('description', ''), 'source': source,
                     'dat_path': str(dat) if dat.is_file() else None,
                     'screenshot_path': str(shot) if entry.get('screenshot') and shot.is_file() else None})
    return rows


def export_background_mod(mod_id, destination=None):
    """Copy an imported background bundle out of the pool into the workspace.

    Args:
        mod_id: the ``id`` from :func:`list_background_mods`.
        destination: workspace .dat path. Defaults to ``out/background.dat``.

    Returns:
        str: absolute path of the copy.

    Example:
        >>> menus.export_background_mod('2602dc69', 'out/background.dat')
        'C:/.../workspace/out/background.dat'
    """
    match = next((m for m in list_background_mods() if m['id'] == mod_id), None)
    if not match or not match['dat_path']:
        raise ValueError(f'No background bundle with id {mod_id!r}.')
    target = out_path(destination, default_name='background.dat')
    shutil.copyfile(match['dat_path'], target)
    return str(target)


def preview_background_mod(mod_id, destination=None):
    """Copy a background mod's preview screenshot into the workspace, if it has one.

    Background bundles have no offline renderer, so this returns the screenshot
    that shipped with the mod, or None when it shipped without one.

    Args:
        mod_id: the ``id`` from :func:`list_background_mods`.
        destination: workspace PNG path. Defaults to ``out/<mod_id>-preview.png``.

    Returns:
        str | None: absolute path of the image, or None if the mod has no preview.

    Example:
        >>> menus.preview_background_mod('2602dc69', 'out/halo-preview.png')
        None   # this one shipped without a screenshot
    """
    match = next((m for m in list_background_mods() if m['id'] == mod_id), None)
    if not match:
        raise ValueError(f'No background bundle with id {mod_id!r}.')
    if not match['screenshot_path']:
        return None
    source = Path(match['screenshot_path'])
    target = out_path(destination, default_name=f'{mod_id}-preview{source.suffix}')
    shutil.copyfile(source, target)
    return str(target)


def extract_background(pack_path, destination=None, menu_type='css'):
    """Pull the background bundle out of a downloaded menu mod.

    Accepts a ZIP containing MnSlChr/MnSlMap (.dat or .usd), or such a file on
    its own. This is the same extraction the app's menu-mod import runs; here it
    writes to the workspace instead of the pool.

    Args:
        pack_path: workspace path to the downloaded .zip/.dat/.usd.
        destination: workspace .dat path. Defaults to ``out/background.dat``.
        menu_type: which screen to prefer when the pack contains both, 'css' or 'sss'.

    Returns:
        dict: ``{'path': str, 'menu_type': 'css'|'sss', 'source_file': str}``.

    Example:
        >>> menus.extract_background('out/halo-css.zip', 'out/background.dat')
        {'path': 'C:/.../out/background.dat', 'menu_type': 'css', 'source_file': 'MnSlChr.usd'}
    """
    from vault.menus.files import (find_mnslchr_dat as _find_mnslchr_dat,
                                   find_mnslmap_dat as _find_mnslmap_dat,
                                   find_menu_dat_by_roots as _find_menu_dat_by_roots)
    if menu_type not in MENU_FILES:
        raise ValueError("menu_type must be 'css' or 'sss'.")
    source = in_path(pack_path)
    target = out_path(destination, default_name='background.dat')
    with tempfile.TemporaryDirectory(prefix='nucleus-api-menu-') as scratch:
        work = Path(scratch)
        if source.suffix.lower() == '.zip':
            extracted = work / 'extracted'
            extracted.mkdir()
            with zipfile.ZipFile(source) as archive:
                for entry in archive.infolist():
                    if entry.is_dir():
                        continue
                    name = Path(entry.filename.replace('\\', '/')).name
                    (extracted / name).write_bytes(archive.read(entry))
            finders = ((_find_mnslmap_dat, 'sss'), (_find_mnslchr_dat, 'css')) if menu_type == 'sss' \
                else ((_find_mnslchr_dat, 'css'), (_find_mnslmap_dat, 'sss'))
            found, screen = None, menu_type
            for finder, kind in finders:
                hit = finder(extracted)
                if hit is not None:
                    found, screen = hit, kind
                    break
            if found is None:
                path, command = _find_menu_dat_by_roots(extracted, menu_type)
                found, screen = path, ('css' if command == '--css-bg' else 'sss')
            if found is None:
                raise ValueError('No MnSlChr or MnSlMap .dat/.usd found in this archive.')
        else:
            found = source
            screen = 'sss' if 'mnslmap' in source.name.lower() else 'css'
        export = work / 'bg'
        export.mkdir()
        try:
            _hsdraw([f'--{screen}-bg', 'export', found, export])
        except ValueError:
            screen = 'sss' if screen == 'css' else 'css'
            _hsdraw([f'--{screen}-bg', 'export', found, export])
        produced = export / 'background.dat'
        if not produced.is_file():
            raise ValueError('HSDRaw produced no background.dat for this menu file.')
        shutil.copyfile(produced, target)
    return {'path': str(target), 'menu_type': screen, 'source_file': Path(found).name}


def list_menu_files():
    """List the menu screen files available on this machine to edit a copy of.

    These are the game's own ``MnSlChr.usd`` (character select) and
    ``MnSlMap.usd`` (stage select), taken from the currently loaded project when
    there is one, otherwise from the extracted builds under the Nucleus storage
    folder. They are read-only sources; :func:`install_background` writes its
    result into the workspace.

    Returns:
        list[dict]: ``{'id': str, 'menu_type': 'css'|'sss', 'name': str,
        'path': str, 'source': str}``, current project first, then storage
        builds in lexical order. ``id`` is what :func:`install_background`
        takes: the menu file is chosen from this set, never named as a free
        host path.

    Example:
        >>> menus.list_menu_files()
        [{'id': 'menu_6f1c...', 'menu_type': 'css', 'name': 'MnSlChr.usd', ...}]
    """
    from core import config
    roots = []
    try:
        from core.state import get_project_files_dir
        directory = get_project_files_dir()
        if directory:
            roots.append((Path(directory), 'current project'))
    except Exception:       # noqa: BLE001 - no project loaded is normal offline
        pass
    storage = config.STORAGE_PATH.resolve()
    for stem in MENU_FILES.values():
        for path in sorted(storage.glob(f'*/files/{stem}.*')):
            if path.suffix.lower() in {'.dat', '.usd'}:
                roots.append((path.parent, f'storage/{path.parent.parent.name}'))
    rows, seen = [], set()
    for directory, label in roots:
        for menu_type, stem in MENU_FILES.items():
            for path in sorted(Path(directory).glob(f'{stem}.*')):
                if path.suffix.lower() not in {'.dat', '.usd'} or str(path) in seen:
                    continue
                seen.add(str(path))
                rows.append({'id': f'menu_{hashlib.sha256(str(path).lower().encode()).hexdigest()[:12]}',
                             'menu_type': menu_type, 'name': path.name,
                             'path': str(path), 'source': label})
    return rows


def install_background(background_path, destination=None, menu_type='css',
                       menu_file=None, include_scene=False):
    """Write a NEW menu file with this background bundle swapped in.

    This is the app's own CSS/SSS background install, pointed at a workspace
    copy instead of a project. The source menu file is not modified.

    Args:
        background_path: workspace path to a ``background.dat`` from
            :func:`export_background_mod` or :func:`extract_background`.
        destination: workspace path for the resulting menu file. Defaults to
            ``out/MnSlChr.usd`` (or ``MnSlMap.usd`` for sss).
        menu_type: 'css' for the character select screen, 'sss' for stage select.
        menu_file: the ``id`` (or the exact ``path``) of an entry from
            :func:`list_menu_files`. Required when this machine has more than
            one candidate for that screen - which build is being changed is the
            caller's decision, not a guess. An arbitrary host path is refused:
            this argument selects from the set the library located, it does not
            name a file.
        include_scene: also carry over the mod's camera/lighting scene.

    Returns:
        dict: ``{'path': str, 'menu_type': str, 'source_menu_file': str,
        'gecko_code': str}``. ``gecko_code`` is the code the game also needs so
        the hardcoded CSS backdrop animation stops covering the new one.

    Example:
        >>> menus.install_background('out/background.dat', 'out/MnSlChr.usd')
        {'path': 'C:/.../out/MnSlChr.usd', 'menu_type': 'css', ...}
    """
    if menu_type not in MENU_FILES:
        raise ValueError("menu_type must be 'css' or 'sss'.")
    background = in_path(background_path)
    candidates = [m for m in list_menu_files() if m['menu_type'] == menu_type]
    if menu_file is None:
        if not candidates:
            raise ValueError(f'No {MENU_FILES[menu_type]} file is available on this machine.')
        if len(candidates) > 1:
            listed = ', '.join(f"{c['id']} -> {c['path']} ({c['source']})" for c in candidates)
            raise ValueError('This machine has more than one ' + MENU_FILES[menu_type] +
                             ' file, and which build you mean to change is not a guess. '
                             'Pass menu_file explicitly: ' + listed)
        chosen = candidates[0]
    else:
        # A menu file is picked from the set THIS LIBRARY located, by id or by
        # its exact path. It is not a free host path: accepting one here would
        # let any file on the machine be read through a public argument, which
        # is the boundary the workspace rules exist to draw.
        wanted = str(menu_file)
        chosen = next((c for c in candidates
                       if wanted == c['id'] or wanted == c['path']), None)
        if chosen is None:
            listed = ', '.join(f"{c['id']} -> {c['path']}" for c in candidates) or 'none'
            raise ValueError(
                f'{wanted!r} is not one of the {MENU_FILES[menu_type]} files on this machine. '
                f'Pass an id or path from menus.list_menu_files(): {listed}')
    source = Path(chosen['path'])
    if not source.is_file():
        raise ValueError(f'No such menu file: {source}')
    target = out_path(destination, default_name=f'{MENU_FILES[menu_type]}.usd')
    with tempfile.TemporaryDirectory(prefix='nucleus-api-menu-') as scratch:
        produced = Path(scratch) / source.name
        args = [f'--{menu_type}-bg', 'import', source, background, produced]
        if include_scene:
            args.append('--include-scene')
        _hsdraw(args)
        if not produced.is_file() or not produced.stat().st_size:
            raise ValueError('HSDRaw produced no menu file.')
        shutil.copyfile(produced, target)
    return {'path': str(target), 'menu_type': menu_type, 'source_menu_file': str(source),
            'gecko_code': '04263384 48000010' if menu_type == 'css' else '',
            'note': ('The CSS also needs the Gecko code above ("Disable Hardcoded CSS BG Anim") '
                     'in the build, or the stock animation hides the new backdrop.'
                     if menu_type == 'css' else 'Rebuild the ISO to see this in game.')}


def identify(path):
    """Say what kind of Melee asset a downloaded file is.

    Runs the app's own import detection, so the answer is the one the app
    would act on. Useful right after :func:`nucleus_api.website.download`,
    when the website only said 'other'.

    Args:
        path: workspace path to a .dat/.usd/.zip you downloaded or built.

    Returns:
        dict: ``{'type': str, 'confidence': str, 'detail': {...},
        'menu_type': 'css'|'sss'|None, 'roots': [str, ...]}``. A character
        select screen comes back as ``type='css_background'`` with
        ``menu_type='css'``; a costume as ``'character'``; a stage as
        ``'stage'``.

    Example:
        >>> menus.identify('out/Halo3CSS.dat')
        {'type': 'css_background', 'confidence': 'high', 'menu_type': 'css',
         'roots': ['MnSelectChrDataTable', ...], ...}
    """
    from vault.importing.unified.detection import detect_content_type, dat_root_symbols
    source = in_path(path)
    roots = []
    if source.suffix.lower() in {'.dat', '.usd'}:
        try:
            roots = list(dat_root_symbols(source.read_bytes()))
        except (OSError, ValueError):
            roots = []
    with tempfile.TemporaryDirectory(prefix='nucleus-api-detect-') as scratch:
        probe = Path(scratch) / source.name
        if source.suffix.lower() == '.zip':
            shutil.copyfile(source, probe)
        else:
            # The app's route wraps a raw DAT in a temp ZIP before detection;
            # do the same so a bare Halo3CSS.dat is classified, not rejected.
            probe = probe.with_suffix('.zip')
            with zipfile.ZipFile(probe, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(source, source.name)
        result = detect_content_type(probe, source.name)
    menu_type = None
    if 'MnSelectChrDataTable' in roots:
        menu_type = 'css'
    elif 'MnSelectMapDataTable' in roots:
        menu_type = 'sss'
    elif (result.get('detail') or {}).get('source') in ('css', 'sss'):
        menu_type = result['detail']['source']
    return {'type': result.get('type'), 'confidence': result.get('confidence'),
            'detail': result.get('detail') or {}, 'menu_type': menu_type, 'roots': roots}


# ---------------------------------------------------------------------------
# Compatibility, structural validity, and the preview that does not exist yet
# ---------------------------------------------------------------------------

#: The root symbol each screen's data table is named by. The stage-select
#: table is ``MnSelectStageDataTable`` -- ``MnSelectMapDataTable`` was wrong,
#: and the app's own detector also accepts it, so both are recognised here and
#: the layout is chosen by the root that is actually present.
MENU_ROOTS = {'css': 'MnSelectChrDataTable', 'sss': 'MnSelectStageDataTable'}
MENU_ROOT_ALIASES = {'css': ('MnSelectChrDataTable',),
                     'sss': ('MnSelectStageDataTable', 'MnSelectMapDataTable')}

#: Root symbols a loose background bundle carries instead.
BUNDLE_ROOTS = ('bg_model', 'bg_camera', 'bg_anim')

#: Where each table keeps its BackgroundModel, and how big the table has to be.
#: These are the field offsets HSDRaw declares: SBM_SelectChrDataTable puts the
#: background at 0x10, and SBM_MnSelectStageDataTable puts it at 0xB0 -- 0x10 is
#: that table's LARGE ICON model. Checking the stage-select file at 0x10 read a
#: real pointer to the wrong thing and called it a background.
BACKGROUND_MODEL_SLOTS = {
    'MnSelectChrDataTable': 0x10,
    'MnSelectStageDataTable': 0xB0,
    'MnSelectMapDataTable': 0xB0,
}
#: HSDRaw's TrimmedSize for each table: a table shorter than this is not that
#: table, whatever its root is called.
MENU_TABLE_SIZES = {
    'MnSelectChrDataTable': 0x14,
    'MnSelectStageDataTable': 0xD0,
    'MnSelectMapDataTable': 0xD0,
}
#: The CSS offset, kept as a name because it is what the app's own installer
#: and the decomp both refer to (mncharsel.c:4324).
BACKGROUND_MODEL_SLOT = 0x10

#: Budgets. A DAT is a graph a stranger authored, walked while this process
#: holds the build's lock, so it gets a ceiling on every dimension: a file
#: claiming a million relocations, or a graph that is a very long list, must not
#: turn a compatibility check into a hang.
MAX_RELOCATIONS = 200_000
MAX_GRAPH_NODES = 20_000
MAX_GRAPH_DEPTH = 256
#: A JOBJ's own size and the pointers it carries (HSD_JOBJ: child 0x08,
#: next 0x0C, object 0x10, inverse world transform 0x38, robj 0x3C).
JOBJ_SIZE = 0x40
JOBJ_CHILD, JOBJ_NEXT = 0x08, 0x0C


def compatibility_manifest():
    """The versioned list of menu packages this install knows anything about.

    Shipped beside the backend (``data/menus/compatibility_manifest.json``) and
    seeded from the menu fixtures of the 2026-09-22 harness experiment. A
    package that is not listed can still be inspected and installed - it simply
    inherits nothing from a package that looks similar.

    Returns:
        dict: ``{'manifest_version', 'policy', 'menu_roots', 'packages': [...]}``.
        ``{'manifest_version': 0, 'packages': []}`` when the file is missing
        from this installation, which makes every judgement ``unknown`` rather
        than optimistic.

    Example:
        >>> from nucleus_api import menus
        >>> [p['package_id'] for p in menus.compatibility_manifest()['packages']][:1]
        ['halo3-matchmaking-lobby']
    """
    from core import config
    path = Path(config.BACKEND_DATA_DIR) / 'menus' / 'compatibility_manifest.json'
    if not path.is_file():
        return {'manifest_version': 0, 'policy': {}, 'menu_roots': dict(MENU_ROOTS),
                'packages': [], 'unavailable': f'No compatibility manifest at {path}'}
    return json.loads(path.read_text(encoding='utf-8'))


def _sha256(path):
    """Digest the bytes through the SAME handle the guard verified."""
    from ._workspace import open_input
    if isinstance(path, TrustedPath):
        return sha256_file(Path(path.path))
    with open_input(path) as source:
        return sha256_stream(source.handle)


def dat_integrity(path):
    """Walk a HAL DAT's header, relocation table and roots, and say if it holds.

    Reading a root's NAME proves nothing: the app's own detection parser
    discards the root's data pointer, so a file whose root points past the end
    of its data section still answers "MnSelectChrDataTable". This resolves the
    pointers instead:

    * the header's file size is the file's real size;
    * the data, relocation, root and string tables fit inside the file;
    * every relocation entry points into the data section, AND the pointer
      stored at that offset points into the data section too;
    * every root's data offset is inside the data section, and its name lies
      inside the string table.

    Args:
        path: the .dat/.usd to inspect.

    Returns:
        dict: ``{'status': 'pass'|'fail', 'reason', 'roots': [{'name',
        'offset'}], 'root_offsets': {name: offset}, 'data_size', 'relocations',
        'bad_relocations'}``.

    Example:
        >>> menus.dat_integrity('out/MnSlChr.usd')['status']
        'pass'
    """
    return dat_integrity_of(_input_bytes(path))


def dat_integrity_of(data):
    """The same walk, over bytes that are already in hand.

    Args:
        data: the DAT's bytes.

    Returns:
        dict: as :func:`dat_integrity`.

    Example:
        >>> menus.dat_integrity_of(blob)['status']
        'pass'
    """
    if len(data) < 0x20:
        return {'status': 'fail', 'reason': 'shorter than a DAT header', 'roots': [],
                'root_offsets': {}, 'data_size': 0, 'relocations': 0, 'bad_relocations': []}
    file_size, data_size, reloc_count, root_count, ref_count = struct.unpack('>5I', data[:0x14])
    fail = lambda reason: {'status': 'fail', 'reason': reason, 'roots': [],          # noqa: E731
                           'root_offsets': {}, 'data_size': data_size,
                           'relocations': reloc_count, 'bad_relocations': []}
    if file_size != len(data):
        return fail(f'the header says {file_size} bytes and the file is {len(data)}')
    reloc_table = 0x20 + data_size
    root_table = reloc_table + reloc_count * 4
    string_table = root_table + (root_count + ref_count) * 8
    if data_size + 0x20 > len(data) or string_table > len(data):
        return fail('the data, relocation or root table runs past the end of the file')
    if root_count == 0 or root_count > 64:
        return fail(f'{root_count} root symbols is not a menu or bundle DAT')
    if reloc_count > MAX_RELOCATIONS:
        return fail(f'{reloc_count} relocation entries is past the {MAX_RELOCATIONS} this '
                    'will walk; a file that large is not checked, it is refused')

    bad = []
    relocated = set()
    for index in range(reloc_count):
        offset = struct.unpack('>I', data[reloc_table + index * 4:reloc_table + index * 4 + 4])[0]
        if offset + 4 > data_size:
            bad.append({'entry': index, 'offset': offset, 'why': 'outside the data section'})
            continue
        pointer = struct.unpack('>I', data[0x20 + offset:0x24 + offset])[0]
        if pointer >= data_size:
            bad.append({'entry': index, 'offset': offset, 'pointer': pointer,
                        'why': 'points past the end of the data section'})
        relocated.add(offset)
    if bad:
        return {**fail(f'{len(bad)} relocation entries do not resolve inside the data '
                       f'section (first: {bad[0]})'), 'bad_relocations': bad[:5]}

    roots, offsets = [], {}
    for index in range(root_count):
        data_offset, string_offset = struct.unpack(
            '>II', data[root_table + index * 8:root_table + index * 8 + 8])
        if data_offset >= data_size:
            return fail(f'root {index} points to {data_offset}, past the {data_size}-byte '
                        'data section')
        end = data.find(b'\0', string_table + string_offset)
        if end < 0 or string_table + string_offset >= len(data):
            return fail(f'root {index} has no readable name')
        name = data[string_table + string_offset:end].decode('ascii', 'replace')
        roots.append({'name': name, 'offset': data_offset})
        offsets[name] = data_offset
    return {'status': 'pass', 'reason': None, 'roots': roots, 'root_offsets': offsets,
            'data_size': data_size, 'relocations': reloc_count, 'bad_relocations': [],
            # A sorted list, not the set it was built as: every result here has
            # to survive json.dumps, and a set does not.
            'relocated_offsets': sorted(relocated)}


def menu_graph_check(path, menu_type):
    """Beyond integrity: does this file's menu table actually carry a background?

    The character-select table's background model sits at
    ``MnSelectChrDataTable+0x10``. This checks that the slot is a RELOCATED
    pointer - i.e. a real reference the loader will follow - into the file's own
    data section, rather than a zero or a number that merely looks like one.

    Args:
        path: the menu file.
        menu_type: ``'css'`` or ``'sss'``.

    Returns:
        dict: ``{'status': 'pass'|'fail'|'unknown', 'reason',
        'background_pointer', 'integrity'}``.

    Example:
        >>> menus.menu_graph_check('out/MnSlChr.usd', 'css')['status']
        'pass'
    """
    data = _input_bytes(path)
    integrity = dat_integrity_of(data)
    if integrity['status'] != 'pass':
        return {'status': 'fail', 'reason': integrity['reason'], 'background_pointer': None,
                'integrity': integrity, 'graph': None}

    present = [name for name in MENU_ROOT_ALIASES[menu_type]
               if name in integrity['root_offsets']]
    if not present:
        wanted = ' or '.join(MENU_ROOT_ALIASES[menu_type])
        return {'status': 'fail',
                'reason': f'no {wanted} root; this is not a {menu_type} menu file',
                'background_pointer': None, 'integrity': integrity, 'graph': None}
    root = present[0]
    base = integrity['root_offsets'][root]
    minimum = MENU_TABLE_SIZES[root]
    if base + minimum > integrity['data_size']:
        return {'status': 'fail',
                'reason': f'{root} needs {minimum} bytes and only '
                          f'{integrity["data_size"] - base} remain; a table that short is '
                          'not that table, whatever its root is called',
                'background_pointer': None, 'integrity': integrity, 'graph': None}

    offset = BACKGROUND_MODEL_SLOTS[root]
    slot = base + offset
    relocated = set(integrity.get('relocated_offsets') or ())
    if slot not in relocated:
        return {'status': 'fail',
                'reason': f'{root}+0x{offset:02X} is not a relocated pointer, so this file '
                          'has no background model the loader would follow',
                'background_pointer': None, 'integrity': integrity, 'graph': None}
    pointer = struct.unpack('>I', data[0x20 + slot:0x24 + slot])[0]
    graph = walk_joint_graph(data, pointer, integrity)
    if graph['status'] != 'pass':
        return {'status': 'fail', 'reason': graph['reason'],
                'background_pointer': pointer, 'integrity': integrity, 'graph': graph}
    return {'status': 'pass', 'reason': None, 'background_pointer': pointer,
            'integrity': integrity, 'graph': graph, 'root': root,
            'background_slot': offset}


def walk_joint_graph(data, start, integrity):
    """Walk the joint tree a menu's background hangs off, with a ceiling.

    Bounds-checking the pointer says the number is inside the file. It does not
    say the loader can follow it: a background whose model is a single joint
    with one byte of room after it, or one whose child chain points back at
    itself, passed that check and is not a model. This follows the JOBJ child
    and next pointers the game follows, with a visited set (so a cycle is
    reported, not recursed), a node ceiling and a depth ceiling.

    Args:
        data: the whole DAT.
        start: the background model's offset inside the data section.
        integrity: the report from :func:`dat_integrity`.

    Returns:
        dict: ``{'status': 'pass'|'fail', 'reason', 'nodes', 'depth',
        'cycle'}``.

    Example:
        >>> menus.walk_joint_graph(blob, pointer, report)['nodes']
        41
    """
    data_size = integrity['data_size']
    relocated = set(integrity.get('relocated_offsets') or ())
    seen, depth_seen, nodes = set(), 0, 0
    stack = [(start, 0)]
    while stack:
        node, depth = stack.pop()
        if node in seen:
            return {'status': 'fail', 'nodes': nodes, 'depth': depth_seen, 'cycle': node,
                    'reason': f'the joint at {node} is reached twice; this graph has a '
                              'cycle, and the loader would follow it forever'}
        if node + JOBJ_SIZE > data_size:
            return {'status': 'fail', 'nodes': nodes, 'depth': depth_seen, 'cycle': None,
                    'reason': f'the joint at {node} needs {JOBJ_SIZE} bytes and the data '
                              f'section ends at {data_size}'}
        seen.add(node)
        nodes += 1
        depth_seen = max(depth_seen, depth)
        if nodes > MAX_GRAPH_NODES:
            return {'status': 'fail', 'nodes': nodes, 'depth': depth_seen, 'cycle': None,
                    'reason': f'more than {MAX_GRAPH_NODES} joints; this is not checked, '
                              'it is refused'}
        if depth > MAX_GRAPH_DEPTH:
            return {'status': 'fail', 'nodes': nodes, 'depth': depth_seen, 'cycle': None,
                    'reason': f'deeper than {MAX_GRAPH_DEPTH} joints'}
        for field, step in ((JOBJ_CHILD, 1), (JOBJ_NEXT, 0)):
            at = node + field
            if at not in relocated:
                continue                       # an absent pointer, not a broken one
            target = struct.unpack('>I', data[0x20 + at:0x24 + at])[0]
            stack.append((target, depth + step))
    return {'status': 'pass', 'reason': None, 'nodes': nodes, 'depth': depth_seen,
            'cycle': None}


def native_menu_report(path, menu_type):
    """Reopen a menu file through HSDRaw and export the background it carries.

    This is the strongest structural statement available: the native reader
    walks the graph the game walks, and the exported bundle is what can be
    compared semantically against the bundle that was meant to be installed.

    Args:
        path: the menu file.
        menu_type: ``'css'`` or ``'sss'``.

    Returns:
        dict: ``{'status': 'pass'|'fail'|'unknown', 'background_sha256',
        'background_bytes', 'reason'}``. ``unknown`` when HSDRaw is not part of
        this installation - a missing tool is not a passed check.

    Example:
        >>> menus.native_menu_report('out/MnSlChr.usd', 'css')['status']
        'pass'
    """
    from core.config import HSDRAW_EXE
    path = _resolve_input(path)
    if not Path(HSDRAW_EXE).is_file():
        return {'status': 'unknown', 'background_sha256': None, 'background_bytes': None,
                'reason': f'HSDRaw is not installed here ({HSDRAW_EXE}), so the menu graph '
                          'was not reopened natively.'}
    with tempfile.TemporaryDirectory(prefix='nucleus-menu-verify-') as scratch:
        export = Path(scratch) / 'bg'
        export.mkdir()
        try:
            _hsdraw([f'--{menu_type}-bg', 'export', Path(path), export])
        except ValueError as exc:
            return {'status': 'fail', 'background_sha256': None, 'background_bytes': None,
                    'reason': f'HSDRaw could not read this as a {menu_type} menu: {exc}'}
        produced = export / 'background.dat'
        if not produced.is_file() or not produced.stat().st_size:
            return {'status': 'fail', 'background_sha256': None, 'background_bytes': None,
                    'reason': 'HSDRaw read the file but found no background bundle in it.'}
        return {'status': 'pass',
                'background_sha256': _sha256(library_path(
                    produced, why='HSDRaw export in this temporary directory')),
                'background_bytes': produced.stat().st_size, 'reason': None}


#: The native reader used to reopen a produced menu file. HSDRaw in the app;
#: replaced in tests, which cannot hand HSDRaw a 4 MB retail menu file. A test
#: pins that the shipped default is the real reader.
NATIVE_MENU_READER = native_menu_report


def _roots(path):
    report = dat_integrity_of(_input_bytes(path))
    return sorted(entry['name'] for entry in report['roots'])


def _resolve_input(path):
    """A caller-named workspace path, or a path this LIBRARY located.

    The previous version accepted any absolute path that happened to exist,
    which is not a rule about where a file is - it is a rule about how the
    caller spelled it, and every caller can spell a path absolutely. A file
    outside the workspace now has to arrive as a :class:`TrustedPath`, which a
    string cannot become.
    """
    if isinstance(path, TrustedPath):
        resolved = path.path
        if not resolved.is_file():
            raise ValueError(f'No such file: {resolved}')
        return resolved
    return in_path(path)


def _input_bytes(path):
    """The bytes of an input, read through the verified handle."""
    if isinstance(path, TrustedPath):
        return _resolve_input(path).read_bytes()
    return read_input(path)


def identify_package(path):
    """Match a file against the compatibility manifest by its bytes.

    Args:
        path: workspace path to a menu file or background bundle.

    Returns:
        dict: ``{'package_id', 'name', 'matched_by', 'sha256', 'package'}``, or
        ``{'package_id': None, 'sha256': ..., 'package': None}`` when nothing in
        the manifest has those bytes. A filename never matches: only the digest.

    Example:
        >>> menus.identify_package('out/background.dat')['package_id']
        'halo3-matchmaking-lobby'
    """
    digest = _sha256(library_path(_resolve_input(path),
                                 why='already resolved by this call'))
    fields = ('published_file_sha256', 'installed_menu_file_sha256',
              'background_bundle_sha256', 'published_archive_sha256')
    for package in compatibility_manifest().get('packages', []):
        for field in fields:
            if (package.get('digests') or {}).get(field) == digest:
                return {'package_id': package['package_id'], 'name': package.get('name'),
                        'matched_by': field, 'sha256': digest, 'package': package}
    return {'package_id': None, 'name': None, 'matched_by': None, 'sha256': digest,
            'package': None}


def check_compatibility(path, menu_type='css', target=None, existing_codes=None,
                        extra_codes=None, enable_disabled=False, native=True):
    """Judge a menu artifact against a build, in the three dimensions that matter.

    ``structure`` (does the file's graph resolve, does it carry a background the
    loader would follow, does the native reader agree), ``target`` (was this
    package observed to work on a build like this one, by an observation that
    records what it observed) and ``codes`` (does the COMPLETE final code set
    merge without a name clash, without two codes writing one address different
    values, and without silently flipping a disabled code on).

    "It looks like a vanilla menu file" is never evidence: an unlisted package,
    or a listed one whose observation does not cover this build, is ``unknown``.

    Args:
        path: workspace path to the artifact that would be installed. Pass the
            SEALED copy if one exists - a mutable source can change afterwards.
        menu_type: ``'css'`` or ``'sss'``.
        target: the build's signature from
            :func:`nucleus_api.builds.target_signature`, or None to leave the
            target dimension ``unknown``.
        existing_codes: the build's current codes, so the ``codes`` dimension
            reports a real merge instead of a wish list.
        extra_codes: codes the caller is adding on top of the package's own
            requirement. They are part of the set that gets judged.
        enable_disabled: the proposal explicitly asks to enable a required code
            the build carries disabled.
        native: also reopen the file through :data:`NATIVE_MENU_READER`.

    Returns:
        dict: ``{'status', 'structure', 'target', 'codes', 'package',
        'manifest_version', 'required_codes', 'limitations'}``. ``status`` is
        the worst of the three dimensions (``fail`` beats ``unknown`` beats
        ``pass``).

    Example:
        >>> menus.check_compatibility('out/MnSlChr.usd', 'css')['structure']['status']
        'pass'
    """
    if menu_type not in MENU_FILES:
        raise ValueError("menu_type must be 'css' or 'sss'.")
    source = _resolve_input(path)
    manifest = compatibility_manifest()
    found = identify_package(library_path(source, why='already resolved by this call'))
    package = found['package']
    limitations = []
    if not manifest.get('packages'):
        limitations.append('This installation has no compatibility manifest, so nothing '
                           'can be recognised: every dimension is unknown.')

    trusted = library_path(source, why='already resolved by this call')
    structure = _structure_dimension(trusted, menu_type, package, native)
    target_result = _target_dimension(package, target, found)
    codes_result, required_codes = _codes_dimension(package, existing_codes, extra_codes,
                                                    enable_disabled)

    order = {'fail': 0, 'unknown': 1, 'pass': 2}
    status = min((structure['status'], target_result['status'], codes_result['status']),
                 key=lambda value: order[value])
    return {'status': status, 'structure': structure, 'target': target_result,
            'codes': codes_result, 'package': {k: found[k] for k in
                                               ('package_id', 'name', 'matched_by', 'sha256')},
            'manifest_version': manifest.get('manifest_version', 0),
            'required_codes': required_codes, 'limitations': limitations}


def _structure_dimension(source, menu_type, package, native):
    integrity = dat_integrity(source)
    roots = sorted(entry['name'] for entry in integrity['roots'])
    if integrity['status'] != 'pass':
        return {'status': 'fail', 'kind': None, 'roots': roots,
                'evidence': f'This file does not hold together as a DAT: {integrity["reason"]}.',
                'integrity': integrity['reason'], 'native': None}

    wanted_root = MENU_ROOTS[menu_type]
    if any(name in roots for name in MENU_ROOT_ALIASES[menu_type]):
        graph = menu_graph_check(source, menu_type)
        if graph['status'] != 'pass':
            return {'status': 'fail', 'kind': 'menu_file', 'roots': roots,
                    'evidence': f'The {wanted_root} table is not usable: {graph["reason"]}.',
                    'integrity': None, 'native': None}
        walked = graph.get('graph') or {}
        result = {'status': 'pass', 'kind': 'menu_file', 'roots': roots,
                  'background_pointer': graph['background_pointer'],
                  'evidence': (f'Every relocation and root pointer in this file resolves '
                               f'inside its own {integrity["data_size"]}-byte data section; '
                               f'{graph.get("root", wanted_root)}'
                               f'+0x{graph.get("background_slot", 0):02X} is a relocated '
                               f'pointer to a background model; and its joint tree walks to '
                               f'{walked.get("nodes")} joints, {walked.get("depth")} deep, '
                               'with no cycle.'),
                  'integrity': 'pass', 'native': None}
    elif any(root in roots for root in BUNDLE_ROOTS):
        result = {'status': 'pass', 'kind': 'background_bundle', 'roots': roots,
                  'evidence': ('The file carries the bg_model/bg_camera roots of a background '
                               f'bundle and its {integrity["relocations"]} relocations all '
                               'resolve; install_background writes it into a menu file.'),
                  'integrity': 'pass', 'native': None}
    else:
        return {'status': 'fail', 'kind': None, 'roots': roots,
                'evidence': f'This file carries {roots} and none of them is {wanted_root} or '
                            'a background bundle root.',
                'integrity': 'pass', 'native': None}

    if package:
        required = (package.get('structure') or {}).get('required_roots') or []
        missing = [root for root in required if root not in roots]
        if missing:
            return {**result, 'status': 'fail',
                    'evidence': f'{package["name"]} requires {required}; {missing} are '
                                'absent from this file.'}

    if native and result['kind'] == 'menu_file':
        report = NATIVE_MENU_READER(source, menu_type)
        result['native'] = report
        if report['status'] == 'fail':
            return {**result, 'status': 'fail',
                    'evidence': f'The native menu reader refused this file: {report["reason"]}'}
        if report['status'] == 'unknown':
            return {**result, 'status': 'unknown',
                    'evidence': result['evidence'] + ' The native reader could not be run '
                                f'({report["reason"]}), so the graph the game walks was not '
                                'checked.'}
        result['evidence'] += (' The native reader reopened it and exported its background '
                               f'bundle ({report["background_bytes"]} bytes, '
                               f'{report["background_sha256"][:12]}).')
    return result


def _target_dimension(package, target, found):
    if package is None:
        return {'status': 'unknown', 'signature': target,
                'evidence': 'These bytes match no package in the compatibility manifest, so '
                            'there is no record of any build this menu was observed to work '
                            'on. Looking like a vanilla menu file proves nothing.'}
    if not target:
        return {'status': 'unknown', 'signature': None,
                'evidence': f'{package["name"]} is known, but no build target was supplied '
                            'to compare it against.'}
    known = package.get('targets') or []
    if not known:
        return {'status': 'unknown', 'signature': target,
                'evidence': package.get('targets_note')
                or f'{package["name"]} has no recorded target: it was prepared but never '
                   'installed and booted anywhere.'}
    misses, unreported = [], []
    for entry in known:
        fields = entry.get('required_signature_fields') or sorted(
            k for k in ('game_code', 'disc_revision', 'menu_variant') if k in entry)
        absent = [field for field in fields if target.get(field) in (None, '')]
        if absent:
            # Not a mismatch: nobody measured it. An unmeasured field is the
            # definition of unknown, and calling it `fail` says this package is
            # known NOT to work here, which nothing established.
            unreported.append(
                f'this build does not report {absent}, which '
                f'{entry.get("label") or "the recorded observation"} is only valid for')
            continue
        different = [field for field in fields if entry.get(field) != target.get(field)]
        if different:
            misses.append(f'{different} differ (recorded '
                          f'{ {f: entry.get(f) for f in different} }, build has '
                          f'{ {f: target.get(f) for f in different} })')
            continue
        bases = entry.get('observed_base_menu_sha256')
        if bases is not None and not bases:
            return {'status': 'unknown', 'signature': target, 'candidate_target': entry,
                    'evidence': (f'{package["name"]} was observed working on this game and '
                                 'revision, but the observation did not record WHICH menu '
                                 'file it replaced. One m-ex build behaving does not certify '
                                 'every customized menu, so this stays unknown. Evidence: '
                                 f'{entry.get("evidence")}')}
        if bases and target.get('current_menu_sha256') not in bases:
            misses.append('the build\'s current menu file is not one the observation covers')
            continue
        return {'status': 'pass', 'signature': target, 'matched_target': entry,
                'evidence': entry.get('evidence')}
    if unreported and not misses:
        return {'status': 'unknown', 'signature': target, 'known_targets': known,
                'evidence': (f'{package["name"]} cannot be compared with this build: '
                             + '; '.join(unreported))}
    return {'status': 'fail', 'signature': target, 'known_targets': known,
            'evidence': f'{package["name"]} does not cover this build: '
                        + '; '.join(misses + unreported)}


def _codes_dimension(package, existing_codes, extra_codes=None, enable_disabled=False):
    from . import codes as codes_module
    required = list((package or {}).get('required_codes') or [])
    for entry in required:
        entry.setdefault('content_hash', codes_module.content_hash(entry.get('source', '')))
    required = required + list(extra_codes or [])
    if package is None and not required:
        return ({'status': 'unknown',
                 'evidence': 'No manifest entry, so the codes this menu needs are not known. '
                             'A code found in a published description may be supplied, but '
                             'nothing establishes that it is the complete requirement.'},
                [])
    if existing_codes is None:
        return ({'status': 'unknown',
                 'evidence': 'The build\'s current code list was not supplied, so no merge '
                             'was actually tried and no interaction could be analysed.'},
                required)
    merged = codes_module.merge(existing_codes, required, enable_disabled=enable_disabled)
    detail = {'merge': merged, 'interactions': merged['interactions']}
    if merged['conflicts']:
        return ({'status': 'fail', **detail,
                 'evidence': f'{merged["conflicts"]!r}'}, required)
    if merged['enable_required']:
        return ({'status': 'fail', **detail,
                 'evidence': f'{[e["identity"] for e in merged["enable_required"]]} are in '
                             'this build but switched off. Turning a code on changes what the '
                             'game does, so it has to be part of what the user approves.'},
                required)
    if merged['unknown']:
        return ({'status': 'unknown', **detail,
                 'evidence': f'{[u["identity"] for u in merged["unknown"]]} use opcodes the '
                             'code analyzer does not model, so their interaction with the '
                             'rest of the build cannot be established.'}, required)
    if package is None:
        return ({'status': 'unknown', **detail,
                 'evidence': 'The supplied codes merge cleanly, but no manifest entry says '
                             'what this menu actually requires, so the set may be incomplete.'},
                required)
    resolved = [row['identity'] for row in merged['added'] + merged['duplicates']]
    # The build's codes.ini is not everything that gets compiled: m-ex's own
    # MainCode is assembled into the same GCT and is not in this set. An
    # interaction with it cannot be ruled out here, so the honest verdict for a
    # complete-set question is unknown, not pass.
    return ({'status': 'unknown', **detail,
             'evidence': f'{resolved} resolved and valid; no two enabled codes overlap with '
                         f'different values across the final '
                         f'{merged["interactions"]["analyzed"]} write ranges; '
                         f'{len(merged["preserved"])} existing codes preserved unchanged. '
                         'The verdict stays unknown because the build also compiles m-ex\'s '
                         'own MainCode into the same GCT, and this analysis only sees '
                         'codes.ini.',
             'complete_set': False,
             'unexamined': ['m-ex MainCode (compiled from the project, not codes.ini)']},
            required)


def preview(menu_file_path=None, reference_image=None, task_id='', task_revision=1,
            workflow='menu_background_replace', required=False, chat_id=''):
    """Say what a produced menu file will look like in game - which nothing can.

    There is no offline renderer for a menu screen in this application:
    HSDRaw cannot navigate a ``bg_model`` root as a JOBJ, and no in-game menu
    capture path is verified. So this never returns an image. If one was
    published with the mod it returns the author's screenshot tagged
    ``role='reference'``, so it can never be mistaken for a picture of this
    build.

    The gap is recorded ONLY when a preview was actually required. Every
    prepared build calls this; filing a feature request each time would
    manufacture demand out of a routine status line. The verdict comes from
    ``assistant.tasks.wishes.classify_blocker`` on typed evidence, not from this
    module asserting a capability gap on its own.

    Args:
        menu_file_path: the produced menu file. Kept in the local result; it
            never becomes wish evidence, because evidence is a typed code and a
            workspace path must not ride out with a submitted request.
        reference_image: workspace path to an author screenshot, if any.
        task_id: the task this gap was hit in, so occurrences can be counted.
        task_revision: that task's revision.
        workflow: the workflow that hit it.
        required: the user asked to SEE the result, or completion genuinely
            depends on it. Only then is anything recorded.
        chat_id: the conversation, which is the unit demand is counted in.

    Returns:
        dict: ``{'status': 'unavailable', 'previewed': False, 'reason',
        'artifacts', 'wish', 'wish_recorded'}``. ``wish`` is the chat-free
        public projection or None; ``wish_recorded['stored']`` is the database
        write's own result, and nothing may claim a saved request without it.

    Example:
        >>> menus.preview('out/MnSlChr.usd')['status']
        'unavailable'
    """
    artifacts = []
    if reference_image:
        artifacts.append({'path': str(in_path(reference_image)), 'role': 'reference',
                          'attribution': 'published by the mod author',
                          'note': 'Not a render of the produced menu file.'})
    wish, recorded = _record_preview_wish(required, task_id, task_revision, workflow, chat_id)
    return {
        'status': 'unavailable',
        'previewed': False,
        'reason': ('This library cannot render a Melee menu screen offline, and no verified '
                   'in-game menu capture exists. The menu file can be produced and installed; '
                   'what it looks like cannot be shown.'),
        'artifacts': artifacts,
        'wish': wish,
        'wish_recorded': recorded,
    }


def _record_preview_wish(required, task_id, task_revision, workflow, chat_id=''):
    """Classify the gap and, only if it actually blocked the user, record it.

    Three rules, all of them about not lying:

    * **The classifier decides.** The verdict comes from typed evidence through
      ``wishes.classify_blocker``; this module no longer asserts a capability
      gap on its own. An incidental unavailable preview classifies as
      ``not_a_blocker`` and records nothing.
    * **No paths in the evidence.** The produced file path would have to be
      stripped again by the public projection and the outgoing report. Evidence
      is a typed CODE; the path stays local, in the task trace where it belongs.
    * **The grouping key is the authoritative one** (capability + blocked
      operation + implementation version + variant), not a versionless facade
      string, so shipping a renderer opens a new backlog row instead of
      silently closing the old one.

    Best-effort: a failure to record is REPORTED, never raised and never
    claimed as success.
    """
    try:
        from randall.reports import wishes as wishlib
    except Exception as exc:                                    # noqa: BLE001
        return None, {'stored': False, 'error': str(exc),
                      'delivery': 'not recorded; the gap is reported in this result only'}
    verdict = wishlib.classify_blocker(
        wishlib.Observation(evidence='operation_unavailable',
                            operation='render_menu_artifact',
                            variant='character_select'),
        wishlib.Requirement(operation='render_menu_artifact',
                            required_for_outcome=bool(required), workflow=workflow))
    if not verdict.creates_wish:
        return None, {'stored': False, 'classification': verdict.outcome,
                      'why': 'no preview was required, so nothing was recorded'}
    try:
        record = wishlib.record(verdict, task_id=task_id, task_revision=int(task_revision),
                                conversation_id=chat_id or task_id, workflow=workflow)
    except Exception as exc:                                    # noqa: BLE001
        return None, {'stored': False, 'error': str(exc),
                      'delivery': 'not recorded; the gap is reported in this result only'}
    summary = wishlib.public_summary(record.wish, classification=verdict)
    return summary, {'stored': record.persisted,
                     'wish_id': record.wish.wish_id if record.persisted else '',
                     'already_recorded': record.already_recorded,
                     'requesting_conversations': record.requesting_conversations,
                     'error': record.error,
                     'delivery': ('offered for the consent-aware feature request; nothing is '
                                  'sent until the user reviews and submits it')}
