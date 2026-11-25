"""Headless HSDRaw operations on immutable file handles; edits create copies."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import file_retry
from core import config
from core.child_env import child_environment
from shared import mod_files as files
from .stage_scene import SCENE_OPERATIONS, run_scene

OPERATIONS = {
    **SCENE_OPERATIONS,
    'meshes': 'List mesh indices, vertices, bones AND the texture indices each mesh draws with at node.',
    'export_texture': 'Export texture_index at node as PNG.',
    'texture_sheet': 'One labelled contact sheet of EVERY texture at node. Look at this before choosing a texture_index.',
    'replace_texture': 'Replace texture_index at node using a PNG replacement_file_id. Produces a new DAT.',
    'export_model': 'Export the model at node as SMD, with texture PNGs when present.',
    'remove_meshes': 'Remove exact mesh indices at node. Produces a new DAT.',
    'remove_triangles': 'Remove triangle indices from mesh_index at node. Produces a new DAT.',
    'animations': 'List animation symbols in an AJ file.',
    'export_animation': 'Export animation matching node to an .anim file.',
    'render_stage': 'Render a stage DAT to PNG.',
}


def hsdraw_capabilities():
    return {'operations': OPERATIONS, 'available': Path(config.HSDRAW_EXE).is_file(),
            'workflow': 'Open a vault mod or attach a file; inspect_mod_file lists DAT roots or ZIP members. unpack_mod_file opens an exact ZIP member. hsdraw operates on a file_id. Edits return a new file_id; save_mod_copy adds a new vault costume. For stage scenery, prefer two stage_lab_open sessions: inspect scene, preview_objects, copy_objects, transform_scenery/hide_objects, then save a new stage variant. stage_lab export returns a DAT file_id. Attached originals are never overwritten. No arbitrary CLI arguments, scripts or ISO export.'}


def _node(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_ /\[\].-]{0,299}', value) or '..' in value:
        raise ValueError('Use an exact HSD root/property path from inspection.')
    return value


def _contact_sheet(source_dir, output_path, cell=96, columns=8):
    """Tile every exported texture into one labelled image.

    A costume carries ~100 textures and the model only ever sees two images per
    tool result, so exporting them one at a time means choosing an index from a
    text dump -- which is how a face ends up on the wrong slot. One sheet puts
    the whole set in front of it with the indices written on.
    """
    from PIL import Image, ImageDraw
    tiles = sorted(source_dir.glob('tex_*.png'),
                   key=lambda p: int(re.search(r'(\d+)', p.stem).group(1)))
    if not tiles:
        raise ValueError('HSDRaw exported no textures for this node.')
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new('RGB', (columns * cell, rows * (cell + 14)), (18, 24, 34))
    draw = ImageDraw.Draw(sheet)
    for position, path in enumerate(tiles):
        index = int(re.search(r'(\d+)', path.stem).group(1))
        x, y = (position % columns) * cell, (position // columns) * (cell + 14)
        try:
            with Image.open(path) as tile:
                tile = tile.convert('RGB')
                tile.thumbnail((cell - 6, cell - 6))
                sheet.paste(tile, (x + 3, y + 3 + (cell - 6 - tile.height) // 2))
        except OSError:
            draw.text((x + 3, y + 3), '?', fill=(200, 120, 120))
        draw.text((x + 3, y + cell), str(index), fill=(140, 200, 255))
    sheet.save(output_path, format='PNG')
    return f'Contact sheet of {len(tiles)} textures; the number under each tile is its texture_index.'


def _index(value):
    if type(value) is not int or not 0 <= value <= 1000000:
        raise ValueError('Indices must be nonnegative integers up to 1000000.')
    return str(value)


def _indices(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 1000:
        raise ValueError('Choose between 1 and 1000 exact indices.')
    return ','.join(dict.fromkeys(_index(value) for value in values))


def _run(argv, directory):
    exe = Path(config.HSDRAW_EXE)
    if not exe.is_file():
        raise ValueError('HSDRaw is unavailable in this installation.')
    # Only this known child is owned here. subprocess.run's timeout closes that
    # exact Popen child; there are no process-name sweeps or app restarts.
    with tempfile.TemporaryFile() as log:
        try:
            result = subprocess.run([str(exe), *map(str, argv)], cwd=directory,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=120, env=child_environment(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('HSDRaw timed out. The original file was not changed.') from exc
        log.seek(0, os.SEEK_END)
        log.seek(max(0, log.tell() - 16000))
        output = log.read().decode('utf-8', errors='replace').replace(str(directory), '[working copy]')
    if result.returncode or re.search(r'(?im)^ERROR[: ]', output):
        raise ValueError(f'HSDRaw could not complete: {output[-1800:]}')
    return output


def hsdraw(operation, file_id, node=None, texture_index=None, replacement_file_id=None, indices=None, mesh_index=None, donor_file_id=None, object_ids=None, target_group=None, instance_id=None, transform=None, animation_index=None):
    if operation not in OPERATIONS:
        raise ValueError('Choose an operation from hsdraw_capabilities.')
    if operation in SCENE_OPERATIONS:
        if any(value is not None for value in (node,texture_index,replacement_file_id,indices,mesh_index)):
            raise ValueError('Use scene object IDs, not costume mesh arguments')
        return run_scene(operation,file_id,donor_file_id=donor_file_id,object_ids=object_ids,target_group=target_group,instance_id=instance_id,transform=transform,animation_index=animation_index)
    if any(value is not None for value in (donor_file_id,object_ids,target_group,instance_id,transform,animation_index)):
        raise ValueError('Scene arguments require a stage scene operation')
    required = {
        'meshes': {'node'}, 'export_texture': {'node', 'texture_index'},
        'texture_sheet': {'node'},
        'replace_texture': {'node', 'texture_index', 'replacement_file_id'},
        'export_model': {'node'}, 'remove_meshes': {'node', 'indices'},
        'remove_triangles': {'node', 'mesh_index', 'indices'},
        'animations': set(), 'export_animation': {'node'}, 'render_stage': set(),
    }[operation]
    supplied = {key for key, value in {'node': node, 'texture_index': texture_index,
        'replacement_file_id': replacement_file_id, 'indices': indices, 'mesh_index': mesh_index}.items() if value is not None}
    if supplied != required:
        raise ValueError(f'{operation} requires exactly: {", ".join(sorted(required)) or "file_id only"}.')
    source, info = files.resolve(file_id)
    files.dat_roots(source)
    if node is not None:
        node = _node(node)
    if operation == 'remove_meshes' and re.match(r'Ply\w*_Share_joint$', str(node)):
        # Melee's model tables (Pl<XX>.dat) address a costume's meshes by
        # position; deleting any shifts every later one, so the game hides the
        # wrong pieces and shows low-poly ones. A Goku import saved that way
        # looked right offline and would not in game.
        raise ValueError('Removing meshes from a fighter costume shifts the mesh indices the game uses to '
                         'choose which pieces to show, so the costume renders wrong in game. For an import, '
                         'delete the unwanted parts in the import itself instead (its clean-up stage).')
    edited = operation in {'replace_texture', 'remove_meshes', 'remove_triangles'}
    with tempfile.TemporaryDirectory(prefix='hsdraw-', dir=files.root()) as scratch:
        directory = Path(scratch)
        input_path = directory / 'input.dat'
        shutil.copyfile(source, input_path)
        output_dir = directory / 'output'
        output_dir.mkdir()
        suffix = '.dat' if edited else {'export_texture': '.png', 'render_stage': '.png',
                                     'texture_sheet': '.png',
                                     'export_model': '.smd', 'export_animation': '.anim'}.get(operation, '')
        output_path = output_dir / ('result' + suffix)
        if operation == 'meshes':
            argv = ['--dobj-info', input_path, node]
        elif operation == 'export_texture':
            argv = ['--texture', 'export', input_path, node, _index(texture_index), output_path]
        elif operation == 'replace_texture':
            replacement, replacement_info = files.resolve(replacement_file_id)
            if replacement_info['extension'] != '.png':
                raise ValueError('Texture replacement requires an attached or exported PNG.')
            replacement_path = directory / 'replacement.png'
            shutil.copyfile(replacement, replacement_path)
            argv = ['--texture', 'import', input_path, node, _index(texture_index), replacement_path, output_path]
        elif operation == 'texture_sheet':
            argv = ['--texture', 'export-all', input_path, node, directory / 'sheet']
        elif operation == 'export_model':
            argv = ['--model', 'export', input_path, node, output_path]
        elif operation == 'remove_meshes':
            argv = ['--remove-dobjs', input_path, node, _indices(indices), output_path]
        elif operation == 'remove_triangles':
            argv = ['--remove-tris-by-index', input_path, node, _index(mesh_index), _indices(indices), output_path]
        elif operation == 'animations':
            argv = ['--anim', 'list', input_path]
        elif operation == 'export_animation':
            argv = ['--anim', 'export', input_path, node, output_path]
        else:
            argv = ['--stage-render', input_path, output_path]
        log = _run(argv, directory)
        if operation == 'texture_sheet':
            log += os.linesep + _contact_sheet(directory / 'sheet', output_path)
        result = {'operation': operation, 'summary': OPERATIONS[operation], 'log': log, 'files': []}
        # Exports are working material the model looks at, not artifacts for the
        # thread: without this, pulling six textures posts six cards of
        # identically-named result.png between the user and the actual answer.
        # A stage render is a picture worth showing, and an edit returns a DAT
        # the user may act on, so neither folds away.
        if operation in {'export_texture', 'texture_sheet', 'export_model', 'export_animation'}:
            result['reading'] = True
        # Which texture it was: the collapsed row is otherwise six identical
        # 'Mod file' entries, and texture identity is the thing that goes wrong.
        if texture_index is not None:
            result['texture_index'] = texture_index
        if suffix:
            if not output_path.is_file() or not output_path.stat().st_size:
                raise ValueError('HSDRaw did not produce the expected file. The original was not changed.')
            if edited:
                files.dat_roots(output_path)
            outputs = [output_path] + [p for p in output_dir.rglob('*') if p.is_file() and p != output_path]
            if len(outputs) > 100 or sum(p.stat().st_size for p in outputs) > 512 * 1024 * 1024:
                raise ValueError('HSDRaw produced too many assets. Export individual textures instead.')
            for path in outputs:
                if path.suffix.lower() not in files.EXTENSIONS or not path.resolve().is_relative_to(output_dir):
                    continue
                name = (Path(info['name']).stem + '-edited.dat') if edited else path.name
                payload = path.read_bytes()
                result['files'].append(files.register(payload, name,
                    origin=info.get('origin') if edited else None, edited=edited))
            if edited:
                result['note'] = 'Edited working copy ready. The vault is unchanged. This is not a Slippi or gameplay validation.'
                origin = files.origin_of(info)     # a plain label (a model import's) is no vault costume
                result['can_save_to_vault'] = bool(origin.get('member') or origin.get('vanilla_color'))
        return result


def save_refusal(info):
    """Why an edited working copy cannot become a vault costume, or None when it can (`save_mod_copy`'s
    own checks, also asked by the retexture auto-save, randall/recolor/autosave.py, before it starts)."""
    origin = info.get('origin')
    if not info.get('edited') or not isinstance(origin, dict) or not (origin.get('member') or origin.get('vanilla_color')):
        return 'Save an edited vault or vanilla costume. For an unrecognized uploaded file, download it from its card instead.'
    character = origin.get('character')
    if not isinstance(character, str) or not character:
        return 'The source costume has no character. Download the edited DAT instead.'
    if not (config.STORAGE_PATH / character).resolve().is_relative_to(config.STORAGE_PATH.resolve()):
        return 'The destination is outside the vault.'
    if origin.get('paired') or character in {'Ice Climbers', 'Nana'}:
        return 'Save paired climber copies together in the Texture Lab. The edited DAT remains available to download.'
    if not isinstance(origin.get('costume_code'), str) or not re.fullmatch(r'Pl[A-Za-z0-9]{4}', origin['costume_code']):
        return 'The source costume has no valid costume code. Download the edited DAT instead.'
    if origin.get('vanilla_color'):
        from core.constants import CHAR_PREFIXES
        if origin['costume_code'] != f"Pl{CHAR_PREFIXES.get(character, '')}{origin['vanilla_color']}":
            return 'The vanilla source does not match its character and costume code.'
    return None


def _import_copy(path, origin, name):
    """Import the DAT at `path` as a NEW costume through the vault's own importer (fresh CSP and stock icon, the
    Slippi check). -> (skin id, required_runtime). The caller holds `metadata_lock`."""
    from core.metadata import load_metadata
    from vault.importing.unified.characters import import_character_costume
    import uuid
    import zipfile
    roots = files.dat_roots(path)
    required_runtime = 'm-ex' if 'mexCostume' in roots else None
    character = origin['character']
    # A unique import name prevents both metadata and orphan-file collisions.
    # This importer only creates a new skin, never updates the source costume.
    unique_name = f'{name} {uuid.uuid4().hex[:12]}'
    with tempfile.TemporaryDirectory(prefix='mod-copy-', dir=files.root()) as scratch:
        archive = Path(scratch) / 'copy.zip'
        member = Path(origin.get('member', origin['costume_code'] + '.dat').replace('\\', '/')).name
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
            output.writestr(member, path.read_bytes())
        char_info = {'character': character, 'dat_file': member,
                     'costume_code': origin['costume_code'], 'csp_file': None, 'stock_file': None}
        existing_ids = {skin['id'] for skin in load_metadata(default={}).get('characters', {}).get(character, {}).get('skins', [])}
        result = import_character_costume(str(archive), char_info, 'copy.zip',
                                          auto_fix=False, custom_name=unique_name)
    if not result.get('success'):
        raise ValueError(result.get('error') or 'The edited copy could not be added to the vault.')
    if result.get('skin_id') in existing_ids:
        raise ValueError('The importer did not create a new costume. No existing item was renamed.')
    return result['skin_id'], required_runtime


def save_mod_copy(file_id, name, chat_id=None):
    """A NEW vault costume from an edited working copy. `chat_id` (never the model's: the engine passes the
    chat's own) is recorded on it as `randall_chat`: the retexture auto-save updates only a costume its own
    chat made (randall/recolor/autosave.py)."""
    from .vault_items import _skin, _item, _text
    from core.metadata import load_metadata, metadata_lock, metadata_transaction
    path, info = files.resolve(file_id)
    refusal = save_refusal(info)
    if refusal:
        raise ValueError(refusal)
    origin = info['origin']
    name = _text(name, 'name', 80)
    character = origin['character']
    with metadata_lock:
        skin_id, required_runtime = _import_copy(path, origin, name)
        with metadata_transaction(default={}) as metadata:
            _, created = _skin(metadata, character, skin_id)
            created.update(name=name, color=name, randall_source_file=file_id)
            if chat_id:
                created['randall_chat'] = chat_id
            if required_runtime:
                created['required_runtime'] = required_runtime
    _, skin = _skin(load_metadata(default={}), character, skin_id)
    return {'summary': 'Edited copy added to vault', 'vault_changed': True,
            'items': [_item(character, skin)], 'files': [files.describe(info)],
            **({'required_runtime': required_runtime} if required_runtime else {}),
            'note': ('Added a new costume with fresh artwork and a Slippi check. The source costume was not changed.'
                     + (' Its costume extensions require m-ex; the Slippi check does not validate those visuals.' if required_runtime else ''))}


# How long an update in place waits out a scanner holding one of the costume's files (file_retry).
REPLACE_TIMEOUT = 10.0
# What an updated costume takes from the fresh import: the file's own facts (hash, artwork, Slippi check). Its
# id, name, folder and date added stay the costume's.
_UPDATED_FIELDS = ('dat_hash', 'has_csp', 'has_stock', 'csp_source', 'stock_source', 'slippi_safe', 'slippi_tested',
                   'slippi_test_date', 'slippi_manual_override', 'gaw_colors', 'required_runtime')


def update_mod_copy(file_id, character, skin_id, chat_id):
    """Replace the costume `skin_id` with an edited working copy, in place: same id, name and folder, the archive,
    portrait and stock icon replaced (each file atomically) and the Slippi check run again. Only a costume this
    chat made (`randall_chat`, `save_mod_copy`) is ever updated; anything else is refused and left alone.

    The new files come from the vault's own importer, exactly as a new save's do (`_import_copy`, under a
    throwaway name); they are then moved over the costume's and the throwaway entry is removed, in one metadata
    transaction."""
    from .vault_items import _skin, _item
    from core.metadata import load_metadata, metadata_lock, metadata_transaction
    from datetime import datetime
    path, info = files.resolve(file_id)
    refusal = save_refusal(info)
    if refusal:
        raise ValueError(refusal)
    origin = info['origin']
    if origin['character'] != character:
        raise ValueError('The edited copy is of another character than the costume it would update.')
    folder = config.STORAGE_PATH / character
    with metadata_lock:
        _, owned = _skin(load_metadata(default={}), character, skin_id)
        if not chat_id or owned.get('randall_chat') != chat_id:
            raise ValueError('That costume was not made in this chat, so it is not changed.')
        target = folder / (owned.get('filename') or f'{skin_id}.zip')
        if Path(target.name).name != target.name or not target.resolve().is_relative_to(folder.resolve()):
            raise ValueError('The costume archive is outside the vault.')
        made, required_runtime = _import_copy(path, origin, owned.get('name') or skin_id)
        try:
            with metadata_transaction(default={}) as metadata:
                skins = metadata.get('characters', {}).get(character, {}).get('skins', [])
                fresh = next((s for s in skins if s.get('id') == made), None)
                current = next((s for s in skins if s.get('id') == skin_id), None)
                if fresh is None or current is None:
                    raise ValueError('The costume changed in the vault while it was being updated; nothing was changed.')
                # A scanner holding a file the vault just wrote (Defender reads a new zip whole) is waited out.
                file_retry.replace(folder / (fresh.get('filename') or f'{made}.zip'), target, timeout=REPLACE_TIMEOUT)
                for suffix in ('_csp.png', '_stc.png'):
                    new, old = folder / f'{made}{suffix}', folder / f'{skin_id}{suffix}'
                    if new.is_file():
                        file_retry.replace(new, old, timeout=REPLACE_TIMEOUT)
                    else:
                        file_retry.retry_locked(old.unlink, missing_ok=True)
                # A high-resolution portrait rendered from the old file would show the old look.
                file_retry.retry_locked((folder / f'{skin_id}_csp_hd.png').unlink, missing_ok=True)
                for key in _UPDATED_FIELDS:
                    if key in fresh:
                        current[key] = fresh[key]
                    else:
                        current.pop(key, None)
                if required_runtime:
                    current['required_runtime'] = required_runtime
                current.update(randall_source_file=file_id, date_modified=datetime.now().isoformat())
                skins.remove(fresh)
        except Exception:
            # The throwaway costume never stays in the vault: its entry and whatever files were not moved go.
            with metadata_transaction(default={}) as metadata:
                skins = metadata.get('characters', {}).get(character, {}).get('skins', [])
                skins[:] = [s for s in skins if s.get('id') != made]
            for suffix in ('.zip', '_csp.png', '_stc.png'):
                (folder / f'{made}{suffix}').unlink(missing_ok=True)
            raise
    _, skin = _skin(load_metadata(default={}), character, skin_id)
    item = _item(character, skin)
    for key in ('image', 'stock_image'):
        if item.get(key) and skin.get('dat_hash'):
            item[key] += f"?v={str(skin['dat_hash'])[:12]}"      # the same URL now shows the new portrait
    return {'summary': 'Vault costume updated', 'vault_changed': True, 'items': [item], 'files': [files.describe(info)],
            **({'required_runtime': required_runtime} if required_runtime else {}),
            'note': ('Updated the costume in place with fresh artwork and a Slippi check. The source costume was '
                     'not changed.')}
