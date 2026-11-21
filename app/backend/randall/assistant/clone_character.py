"""File-handle adapter: an imported costume becomes a separate editable Echo."""
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime

from shared import mod_files

_lock = threading.Lock()


def _source(file_id):
    from vault.echo.donors import UNSUPPORTED, donor_name
    from shared.rendering.hitbox_elements import CHAR_PREFIXES
    path, info = mod_files.resolve(file_id)
    origin = mod_files.origin_of(info)
    if info['extension'] not in ('.dat', '.usd') or not origin.get('character'):
        raise ValueError('Export the fitted model or open its costume first; use that DAT file ID.')
    try:
        donor = donor_name(origin['character'])
    except KeyError as exc:
        raise ValueError('The source has no supported vanilla donor.') from exc
    if donor in UNSUPPORTED or donor == 'G&W' or origin.get('paired'):
        raise ValueError('This donor needs special multi-fighter or engine-color handling; simple clones are unavailable.')
    prefix = CHAR_PREFIXES[donor]
    if not re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9]{2}', origin.get('costume_code', '')):
        raise ValueError('The source costume does not match its recorded donor.')
    roots = mod_files.dat_roots(path)
    joints = [r for r in roots if r.startswith('Ply') and r.endswith('_joint') and 'matanim' not in r]
    if len(joints) != 1:
        raise ValueError('A simple clone needs exactly one fighter model root.')
    symbols = {'joint': joints[0], 'material': next((r for r in roots if r.endswith('_matanim_joint')), '')}
    return path, info, donor, prefix, symbols


def _receipt(entry, directory, *, existing=False):
    fighter = json.loads((directory / 'fighter.json').read_text(encoding='utf-8'))
    costumes = [{'name': c.get('name', f'Costume {i + 1}'), 'index': i}
                for i, c in enumerate(fighter.get('costumes', []))]
    previews = [{**mod_files.register((directory / 'clone_preview.png').read_bytes(), entry['name'] + ' costumes.png'),
                 'preview_only': True}]
    previews.append(mod_files.register((directory / 'fighter.zip').read_bytes(), entry['name'] + '.zip'))
    return dict(summary=('Clone already in vault' if existing else 'Clone character created'),
        vault_changed=not existing, character={k: entry[k] for k in ('slug', 'name', 'based_on', 'costume_count')},
        files=previews, costumes=costumes,
        required_runtime='m-ex', gameplay_tested=False,
        note=('This clone already exists; its later edits have been preserved. ' if existing else
             'Separate custom character with five costumes, portraits, stock icons, CSS artwork and name banners. ') +
             'Moves, attributes, animations, effects and audio are inherited from the donor. '
             'The original donor is unchanged. In-game appearance and gameplay still need testing.')


def create_clone_character(file_id, name, short_name=None, recolor_mode='all', recolor_file_ids=None,
                           *, _progress=None, _cancelled=None):
    from .vault_items import _text
    from vault.echo.donors import export_donor_zip
    from vault.importing import custom_character_package as vault
    from core.metadata import load_metadata, metadata_transaction
    from vault.echo import clone, package

    name = _text(name, 'name', 64)
    short_name = _text(short_name if short_name is not None else name[:24], 'short_name', 24)
    if recolor_mode not in ('all', 'neutral'):
        raise ValueError('Use all or neutral for recolor_mode.')
    if recolor_file_ids is not None and (not isinstance(recolor_file_ids, list) or len(recolor_file_ids) != 4):
        raise ValueError('Supply exactly four recolor file IDs in red, blue, green, gold order.')
    inputs = [_source(fid) for fid in [file_id, *(recolor_file_ids or [])]]
    source, info, donor, prefix, symbols = inputs[0]
    if any(row[2] != donor for row in inputs):
        raise ValueError('Every costume must use the same donor skeleton.')
    if len(inputs) == 5 and len({row[1]['sha256'] for row in inputs}) != 5:
        raise ValueError('Provide five distinct costume files.')
    recipe = dict(name=name, short_name=short_name, donor=donor, recolor_mode=recolor_mode,
                  source_hashes=[row[1]['sha256'] for row in inputs], version=1)
    key = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()

    def progress(label):
        if _cancelled and _cancelled():
            raise ValueError('Clone creation cancelled before saving.')
        if _progress:
            _progress({'progress_label': label})

    if not _lock.acquire(blocking=False):
        raise ValueError('A clone is already being created. Wait for its result.')
    try:
        for item in load_metadata(default={}).get('custom_characters', []):
            if item.get('clone_recipe') == key:
                directory = vault.CUSTOM_CHARACTERS_PATH / item['slug']
                if all((directory / f).is_file() for f in ('fighter.zip', 'clone_preview.png')):
                    return _receipt(item, directory, existing=True)
        progress('Preparing donor gameplay and imported costume')
        donor_zip = export_donor_zip(donor)
        with zipfile.ZipFile(io.BytesIO(donor_zip)) as archive:
            donor_meta = json.loads(archive.read('fighter.json'))
        expected = donor_meta['costumes'][0]['file']['jointSymbol'].split('5K')[0]
        if not expected.startswith('Ply') or any(row[4]['joint'].split('5K')[0] != expected for row in inputs):
            raise ValueError('The DAT model belongs to a different donor skeleton.')
        echo = dict(donor=donor, donor_prefix=prefix, name=name, short_name=short_name,
                    ops=[], animations=[], version=package.VERSION, appearance=recipe)
        with tempfile.TemporaryDirectory(prefix='clone-', dir=mod_files.root()) as tmp:
            work = Path(tmp)
            base = work / (prefix + 'Nr.dat')
            base.write_bytes(source.read_bytes())
            if len(inputs) == 5:
                paths = [base]
                for row, (code, _, _) in zip(inputs[1:], clone.COSTUMES[1:]):
                    path = work / (prefix + code + '.dat')
                    path.write_bytes(row[0].read_bytes())
                    paths.append(path)
                all_symbols = [row[4] for row in inputs]
            else:
                paths = clone.recolor(base, work, prefix, recolor_mode, progress)
                all_symbols = [symbols] * 5
            artwork = []
            for path, (_, label, _) in zip(paths, clone.COSTUMES):
                progress(f'Rendering {label.lower()} portrait and stock icon')
                artwork.append(clone.render_assets(path, donor))
            fighter_zip, fighter, loose = clone.assemble(donor_zip, echo, paths, artwork, all_symbols)
            loose.update({'fighter.zip': fighter_zip, 'donor.zip': donor_zip,
                          'echo.json': json.dumps(echo, indent=2).encode(),
                          'fighter.json': json.dumps(fighter, indent=2).encode(),
                          'clone_preview.png': clone.contact_sheet(name, artwork)})
            progress('Saving the complete custom character')
            # Prepare all files before publishing metadata. The vault lock protects
            # slug selection; failed writes cannot expose a partial character.
            vault.CUSTOM_CHARACTERS_PATH.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.clone-', dir=vault.CUSTOM_CHARACTERS_PATH) as stage:
                staged = Path(stage) / 'character'
                staged.mkdir()
                for relative, data in loose.items():
                    dest = staged / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                entry = dict(name=name, source='clone', based_on=donor, costume_count=5,
                    has_css_icon=True, series_id=fighter.get('seriesID', 0),
                    date_added=datetime.now().isoformat(), clone_recipe=key,
                    randall_source_file=file_id, required_runtime='m-ex')
                vault.sync_costume_meta(entry, staged, fighter)
                final = None
                try:
                    with metadata_transaction(default=dict(vault.DEFAULT_META)) as metadata:
                        entry['slug'] = vault.dedupe_slug(vault.make_slug(name))
                        final = vault.CUSTOM_CHARACTERS_PATH / entry['slug']
                        staged.rename(final)
                        metadata.setdefault('custom_characters', []).append(entry)
                except Exception:
                    if final and final.resolve().parent == vault.CUSTOM_CHARACTERS_PATH.resolve() and final.is_dir() and not staged.exists():
                        shutil.rmtree(final)
                    raise
        return _receipt(entry, final)
    finally:
        _lock.release()
