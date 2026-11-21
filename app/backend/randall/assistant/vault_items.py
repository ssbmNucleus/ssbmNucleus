"""Vault costumes as Randall's tools read and show them: checked text, a character's skins, one exact
skin, and the card item a costume becomes (its online-play label read with its provenance).

Shared by the tool registry (``tools.py``) and the feature tools that read vault rows (delivery, projects,
in-game tests, website downloads, HSDRaw saves), so none of them imports the registry. Moved out of
``tools.py`` on 2026-10-03.
"""
import hashlib
from pathlib import Path
from urllib.parse import quote

from core import config
from shared import mod_files


def _text(value, name, maximum=160):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{name} must be nonempty text, at most {maximum} characters.')
    return value.strip()


def _characters(data):
    return data.get('characters', {})


def _character(data, character):
    character = _text(character, 'character')
    names = _characters(data)
    match = next((n for n in names if n.casefold() == character.casefold()), None)
    if match is None:
        raise ValueError('Character not found. Search the vault first.')
    return match, names[match].get('skins', [])


def _skin(data, character, skin_id):
    character, skins = _character(data, character)
    skin = next((s for s in skins if s.get('id') == skin_id
                 and s.get('type') != 'folder' and s.get('visible') is not False), None)
    if skin is None:
        raise ValueError('Skin not found. Search the vault for its exact ID.')
    return character, skin


def _item(character, skin):
    # The online-play label travels with its PROVENANCE. `slippi_safe` alone
    # cannot tell a validator verdict from a value somebody set by hand or a
    # later retest, and a card that renders one as the other invents evidence.
    item = {k: skin[k] for k in ('id', 'name', 'color', 'costume_code', 'folder_id',
                                'slippi_safe', 'slippi_tested', 'slippi_test_date',
                                'slippi_manual_override', 'dat_hash', 'required_runtime',
                                'has_csp', 'has_stock') if k in skin}
    # One authoritative reading of that label, so a card never has to guess what
    # the booleans meant: `slippi_verdict` is safe/not safe/unknown and
    # `slippi_evidence` says what produced it. Same function the delivery
    # workflow reports from, so the card and the result cannot disagree.
    from randall.delivery.deliver_checks import _label_provenance
    provenance = _label_provenance(skin)
    item['slippi_verdict'] = provenance['verdict']
    item['slippi_evidence'] = provenance['source']
    item['character'] = character
    item['name'] = skin.get('name') or skin.get('color') or skin['id']
    from vault.importing.character_detector import _extract_character_color_from_filename
    _, variant = _extract_character_color_from_filename(skin.get('costume_code') or '')
    item['variant'] = variant or skin.get('color') or ''
    if skin.get('has_csp'):
        filename = skin.get('csp_filename') or f"{skin['id']}_csp.png"
        if Path(filename).name == filename and '/' not in character and '\\' not in character:
            item['image'] = f'/storage/{quote(character, safe="")}/{quote(filename, safe="")}'
    if skin.get('has_stock'):
        filename = f"{skin['id']}_stc.png"
        if Path(filename).name == filename and '/' not in character and '\\' not in character:
            item['stock_image'] = f'/storage/{quote(character, safe="")}/{quote(filename, safe="")}'
    return item

def open_vault_file(character, skin_id):
    from core.metadata import load_metadata
    character, skin = _skin(load_metadata(default={}), character, skin_id)
    vault_root = config.STORAGE_PATH.resolve()
    path = (vault_root / character / skin.get('filename', f'{skin_id}.zip')).resolve()
    if not path.is_relative_to(vault_root) or not path.is_file() or path.stat().st_size > mod_files.MAX_FILE:
        raise ValueError('This vault archive is unavailable or exceeds 128 MB.')
    data = path.read_bytes()
    origin = {'character': character, 'skin_id': skin_id, 'archive_sha256': hashlib.sha256(data).hexdigest(),
              'costume_code': skin.get('costume_code'),
              'paired': bool(skin.get('paired_nana_id') or skin.get('is_nana'))}
    file = mod_files.register(data, path.name, origin=origin)
    entries = mod_files.archive_entries(mod_files.resolve(file['file_id'])[0])
    result = {'reading': True, 'files': [file], 'vault_item': _item(character, skin)}
    dats = [entry for entry in entries if Path(entry.filename).suffix.lower() in {'.dat', '.usd'}]
    if len(dats) == 1:
        result['files'] += mod_files.unpack_file(file['file_id'], dats[0].filename)['files']
    else:
        result['members'] = [{'name': entry.filename, 'size': entry.file_size} for entry in entries[:200]]
    return result
