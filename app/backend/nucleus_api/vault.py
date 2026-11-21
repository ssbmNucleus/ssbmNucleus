"""Read-only view of the local Nucleus vault (fighters, costumes, archives).

Nothing here modifies the vault. Functions that produce a file copy it into the
workspace.

Worked example - take a costume out of the vault, look at it, edit it, look
again::

    skin = vault.find_costumes('goku fox')[0]
    skin['id']                       # 'DBZ Pack _ Goku Fox-plfxnr-goku-fox'
    skin['csp_path']                 # the portrait the vault already has

    dat  = vault.extract_member(skin['character'], skin['id'],
                                destination='out/PlFxNr.dat')
    node = modfile.inspect(dat)['roots'][0]          # 'PlyFox5K_Share_joint'
    modfile.texture_sheet(dat, node, 'out/sheet.png')          # LOOK at this
    png  = modfile.export_texture(dat, node, 12, 'out/hair.png')
    # ... recolour out/hair.png with PIL ...
    new  = modfile.replace_texture(dat, node, 12, 'out/hair.png', 'out/blue.dat')
    modfile.pack_costume(new, 'out/goku-blue.zip', 'PlFxNr.dat')
    render.costume_preview(new, 'Fox', 'PlFxNr')     # LOOK at the result
"""
import shutil
import zipfile
from pathlib import Path

from ._workspace import out_path


def _metadata():
    from core.metadata import load_metadata
    return load_metadata(default={'characters': {}})


def _storage():
    from core import config
    return config.STORAGE_PATH.resolve()


def list_fighters():
    """List the fighters that have costumes in the vault.

    Returns:
        list[dict]: one entry per fighter, sorted by name, each
        ``{'character': str, 'costume_count': int}``.

    Example:
        >>> from nucleus_api import vault
        >>> vault.list_fighters()[:1]
        [{'character': 'Bowser', 'costume_count': 12}]
    """
    data = _metadata()
    rows = []
    for character, info in data.get('characters', {}).items():
        skins = [s for s in info.get('skins', [])
                 if s.get('type') != 'folder' and s.get('visible') is not False and not s.get('is_nana')]
        rows.append({'character': character, 'costume_count': len(skins)})
    return sorted(rows, key=lambda row: row['character'])


def list_costumes(character):
    """List every costume the vault holds for one fighter.

    Args:
        character: exact fighter name from :func:`list_fighters`, e.g. 'Fox'.

    Returns:
        list[dict]: each entry has ``id`` (the skin id you pass to other calls),
        ``name``, ``variant`` (colour slot), ``costume_code`` (e.g. 'PlFxNr'),
        ``zip_path`` (the archive in the vault, read-only), ``csp_path`` and
        ``stock_path`` (PNGs, or None), and ``slippi_safe``.

    Example:
        >>> vault.list_costumes('Fox')[0]['id']
        'DBZ Pack _ Goku Fox-plfxnr-goku-fox'
    """
    from randall.assistant.vault_items import _character, _item
    data = _metadata()
    character, skins = _character(data, character)
    root = _storage()
    rows = []
    for skin in skins:
        if skin.get('type') == 'folder' or skin.get('visible') is False or skin.get('is_nana'):
            continue
        item = _item(character, skin)
        archive = root / character / skin.get('filename', f"{skin['id']}.zip")
        csp = root / character / (skin.get('csp_filename') or f"{skin['id']}_csp.png")
        stock = root / character / f"{skin['id']}_stc.png"
        rows.append({'id': skin['id'], 'name': item['name'], 'variant': item.get('variant', ''),
                     'character': character, 'costume_code': skin.get('costume_code'),
                     'slippi_safe': skin.get('slippi_safe'),
                     'zip_path': str(archive) if archive.is_file() else None,
                     'csp_path': str(csp) if skin.get('has_csp') and csp.is_file() else None,
                     'stock_path': str(stock) if skin.get('has_stock') and stock.is_file() else None})
    return rows


def find_costumes(words, character=''):
    """Find vault costumes whose name, colour, character or id contain all words.

    Args:
        words: search text, e.g. 'goku fox'. Every whitespace-separated word
            must appear somewhere in the item.
        character: optional fighter-name filter (substring, case-insensitive).

    Returns:
        list[dict]: same shape as :func:`list_costumes`, across all fighters.

    Example:
        >>> vault.find_costumes('goku')[0]['character']
        'Fox'
    """
    terms = str(words).casefold().split()
    rows = []
    for fighter in list_fighters():
        if character and character.casefold() not in fighter['character'].casefold():
            continue
        for row in list_costumes(fighter['character']):
            haystack = ' '.join(str(row.get(key, '')) for key in
                                ('id', 'name', 'variant', 'character', 'costume_code')).casefold()
            if all(term in haystack for term in terms):
                rows.append(row)
    return rows


def _archive(character, skin_id):
    from randall.assistant.vault_items import _skin
    character, skin = _skin(_metadata(), character, skin_id)
    root = _storage()
    path = (root / character / skin.get('filename', f'{skin_id}.zip')).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'No vault archive for {character} / {skin_id}.')
    return character, skin, path


def read_archive(character, skin_id):
    """List what is inside a vault costume ZIP without extracting anything.

    Args:
        character: fighter name.
        skin_id: the ``id`` from :func:`list_costumes`.

    Returns:
        dict: ``{'zip_path': str, 'members': [{'name': str, 'size': int}, ...]}``.

    Example:
        >>> vault.read_archive('Fox', 'DBZ Pack _ Goku Fox-plfxnr-goku-fox')['members']
        [{'name': 'PlFxNr.dat', 'size': 1234567}]
    """
    _, _, path = _archive(character, skin_id)
    with zipfile.ZipFile(path) as archive:
        members = [{'name': e.filename, 'size': e.file_size} for e in archive.infolist() if not e.is_dir()]
    return {'zip_path': str(path), 'members': members}


def copy_costume(character, skin_id, destination=None):
    """Copy a vault costume ZIP into the workspace so you can work on it.

    The vault copy is never touched.

    Args:
        character: fighter name.
        skin_id: the ``id`` from :func:`list_costumes`.
        destination: workspace path for the copy. Defaults to ``out/<skin_id>.zip``.

    Returns:
        str: absolute path of the copy in the workspace.

    Example:
        >>> vault.copy_costume('Fox', 'DBZ Pack _ Goku Fox-plfxnr-goku-fox', 'out/goku.zip')
        'C:/.../workspace/out/goku.zip'
    """
    _, _, path = _archive(character, skin_id)
    target = out_path(destination, default_name=f'{skin_id}.zip')
    shutil.copyfile(path, target)
    return str(target)


def extract_member(character, skin_id, member=None, destination=None):
    """Extract one file out of a vault costume ZIP into the workspace.

    Args:
        character: fighter name.
        skin_id: the ``id`` from :func:`list_costumes`.
        member: exact member name from :func:`read_archive`. When omitted, the
            archive's single .dat/.usd costume file is used, and an archive with
            several raises.
        destination: workspace path. Defaults to ``out/<member filename>``.

    Returns:
        str: absolute path of the extracted file.

    Example:
        >>> vault.extract_member('Fox', 'DBZ Pack _ Goku Fox-plfxnr-goku-fox')
        'C:/.../workspace/out/PlFxNr.dat'
    """
    _, _, path = _archive(character, skin_id)
    with zipfile.ZipFile(path) as archive:
        names = [e.filename for e in archive.infolist() if not e.is_dir()]
        if member is None:
            dats = [n for n in names if Path(n).suffix.lower() in {'.dat', '.usd'}]
            if len(dats) != 1:
                raise ValueError(f'Name the member to extract; this archive holds {names}.')
            member = dats[0]
        if member not in names:
            raise ValueError(f'No such member {member!r}; the archive holds {names}.')
        target = out_path(destination, default_name=Path(member).name)
        target.write_bytes(archive.read(member))
    return str(target)
