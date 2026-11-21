"""Copy-only stage workspaces shared by the human editor and Randall."""
import base64
import io
import json
import re
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from PIL import Image
import file_retry
from core import config
from core.stages import ALL_STAGES
from core.metadata import metadata_transaction
from shared import mod_files

_lock = threading.RLock()
# How long an update in place waits out a scanner holding the variant's archive or picture (file_retry).
REPLACE_TIMEOUT = 10.0


def _root():
    base = config.STORAGE_PATH.resolve()
    root = base / 'stage_editor'
    if not root.resolve().is_relative_to(base):
        raise ValueError('Invalid stage workspace location')
    root.mkdir(exist_ok=True)
    return root


# A workspace is a full copy of the stage (and of a variant's whole archive), one per
# open by either editor. A human editor session lasts as long as the editor is open;
# a Randall Stage Lab session that closed (15 idle minutes) is reopened from its
# workspace's resume record on its next call (randall/recolor/stage_lab.py). Kept: the
# newest KEEP_WORKSPACES, and any younger than WORKSPACE_DAYS, so an editor left open
# overnight can still save.
KEEP_WORKSPACES = 10
WORKSPACE_DAYS = 3


def prune_workspaces(keep=KEEP_WORKSPACES, days=WORKSPACE_DAYS, protect=(), root=None):
    """Delete old stage workspaces (best effort, like core/run_retention). -> names removed.

    `root` prunes another folder of session workspaces by the same rule (the Skin
    Lab's resume records, randall/recolor/skin_lab.py)."""
    root, removed, rows = root or _root(), [], []
    protected = set(protect)
    for entry in root.iterdir():
        if not entry.is_dir() or entry.name in protected or not re.fullmatch(r'[a-f0-9]{32}', entry.name):
            continue
        try:
            rows.append((entry.stat().st_mtime, entry))
        except OSError:
            continue
    rows.sort(reverse=True)
    cutoff = time.time() - days * 86400
    for mtime, entry in rows[max(keep, 0):]:
        if mtime >= cutoff:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            removed.append(entry.name)
    return removed


def resolve(workspace_id):
    if not isinstance(workspace_id, str) or not re.fullmatch(r'[a-f0-9]{32}', workspace_id):
        raise ValueError('Invalid stage workspace')
    directory = _root() / workspace_id
    if not directory.resolve().is_relative_to(_root()):
        raise ValueError('Invalid stage workspace location')
    info = json.loads((directory / 'workspace.json').read_text(encoding='utf-8'))
    source = directory / 'source.dat'
    if mod_files.digest(source) != info['sha256']:
        raise ValueError('Stage source changed; open it again')
    return directory, info


def open_stage(stage_code, variant_id=None):
    stage = ALL_STAGES.get(stage_code)
    if not stage:
        raise ValueError('Choose a supported stage code')
    source_zip = None
    if variant_id:
        if not isinstance(variant_id, str) or not re.fullmatch(r'[\w .()-]{1,180}', variant_id) or variant_id in ('.', '..'):
            raise ValueError('Invalid stage variant')
        source_zip = config.STORAGE_PATH / 'das' / stage['folder'] / (variant_id + '.zip')
        if not source_zip.resolve().is_relative_to(config.STORAGE_PATH.resolve()):
            raise ValueError('Invalid stage archive location')
        with zipfile.ZipFile(source_zip) as archive:
            members = mod_files.archive_entries(source_zip)
            candidates = [item.filename for item in members if re.match(r'^' + re.escape(stage_code) + r'(?:$|[-_. ])', Path(item.filename).stem, re.I) and Path(item.filename).suffix.lower() in ('.dat', '.usd')]
            if not candidates:
                raise ValueError('No matching stage DAT in this variant')
            # Prefer the localized base when both are included; retain every other file.
            candidates.sort(key=lambda name: (Path(name).suffix.lower() != '.usd', name))
            if len([name for name in candidates if Path(name).suffix.lower() == Path(candidates[0]).suffix.lower()]) != 1:
                raise ValueError('This archive has multiple base stage files; separate its variants first')
            member = candidates[0]
            data = archive.read(member)
    else:
        from shared.rendering.stage_ops import STAGE_DATS_DIR, stage_file_name
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        member = stage_file_name(stage_code)
        source = STAGE_DATS_DIR / member
        if not source.is_file():
            source = ensure_vanilla_ref(member)
        if not source:
            raise ValueError('Vanilla stage is unavailable; complete game-file setup first')
        data = Path(source).read_bytes()
    if not data or len(data) > mod_files.MAX_FILE:
        raise ValueError('Stage exceeds the 128 MB editor limit')
    workspace_id = uuid.uuid4().hex
    directory = _root() / workspace_id
    directory.mkdir()
    source = directory / 'source.dat'
    source.write_bytes(data)
    roots = mod_files.dat_roots(source)
    if not any('map_head' in name.lower() for name in roots):
        raise ValueError('This file does not contain a stage map_head')
    if source_zip:
        shutil.copyfile(source_zip, directory / 'source.zip')
    info = {'id': workspace_id, 'stage_code': stage_code, 'folder': stage['folder'], 'member': member,
            'name': variant_id or stage['name'], 'sha256': mod_files.digest(source)}
    (directory / 'workspace.json').write_text(json.dumps(info), encoding='utf-8')
    prune_workspaces(protect=(workspace_id,))
    return {**info, 'datFile': str(source), 'datName': Path(member).name, 'textures': []}


def _checked_export(directory, data):
    if not data or len(data) > mod_files.MAX_FILE:
        raise ValueError('Invalid stage data size')
    check = directory / (uuid.uuid4().hex + '.dat')
    check.write_bytes(data)
    try:
        if not any('map_head' in root.lower() for root in mod_files.dat_roots(check)):
            raise ValueError('Export is not a stage DAT')
    finally:
        check.unlink(missing_ok=True)


def _destination(info):
    folder = config.STORAGE_PATH / 'das' / info['folder']
    if not folder.resolve().is_relative_to(config.STORAGE_PATH.resolve()):
        raise ValueError('Invalid destination')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_archive(handle, directory, info, data):
    """The variant's archive: every other member of the source archive kept, the stage file replaced."""
    with zipfile.ZipFile(handle, 'w', zipfile.ZIP_DEFLATED) as output:
        if (directory / 'source.zip').exists():
            with zipfile.ZipFile(directory / 'source.zip') as original:
                for entry in original.infolist():
                    if entry.filename != info['member']:
                        output.writestr(entry, original.read(entry))
        output.writestr(info['member'], data)


def _write_screenshot(handle, screenshot):
    with Image.open(io.BytesIO(screenshot)) as image:
        if image.width * image.height > 16000000:
            raise ValueError('Preview is too large')
        image.convert('RGB').save(handle, format='PNG')


def save_copy(workspace_id, data, name, screenshot=None, chat_id=None):
    """A NEW vault variant from the workspace's stage. `chat_id` (Randall's chat, never the model's words) is kept
    on it as `randall_chat`: the retexture auto-save updates only a variant its own chat made (`update_copy`)."""
    name = str(name).strip()
    if not name or len(name) > 120:
        raise ValueError('Enter a stage name of up to 120 characters')
    if not data or len(data) > mod_files.MAX_FILE:
        raise ValueError('Invalid stage data size')
    with _lock:
        directory, info = resolve(workspace_id)
        _checked_export(directory, data)
        folder = _destination(info)
        slug = (re.sub(r'[^\w-]+', '-', name.lower()).strip('-') or 'stage') + '-' + uuid.uuid4().hex[:12]
        archive_path = folder / (slug + '.zip')
        image_path = folder / (slug + '_screenshot.png')
        created = []
        try:
            with archive_path.open('xb') as handle:
                created.append(archive_path)
                _write_archive(handle, directory, info, data)
            if screenshot:
                with image_path.open('xb') as handle:
                    created.append(image_path)
                    _write_screenshot(handle, screenshot)
            with metadata_transaction(default={}) as metadata:
                variants = metadata.setdefault('stages', {}).setdefault(info['folder'], {}).setdefault('variants', [])
                # The same fields an imported stage variant carries (vault/importing/unified/stages.py):
                # without them the Vault sorted a saved copy as undated and never showed its picture.
                variants.append({'id': slug, 'name': name, 'filename': archive_path.name,
                                 'has_screenshot': bool(screenshot),
                                 'screenshot_filename': image_path.name if screenshot else None,
                                 'date_added': datetime.now().isoformat(),
                                 'slippi_tested': False, 'slippi_safe': None,
                                 **({'randall_chat': chat_id} if chat_id else {})})
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return {'success': True, 'variantId': slug, 'folder': info['folder'], 'vault_changed': True,
                'name': name, 'stageCode': info['stage_code'], 'slippi_tested': False}


def update_copy(workspace_id, data, variant_id, screenshot=None, chat_id=None):
    """Replace the vault variant `variant_id` (in the workspace's stage folder) with the workspace's stage, in place:
    same id and name, the archive and screenshot each replaced atomically, the in-game check reset. Only a variant
    this chat made (`randall_chat`, `save_copy`) is ever updated; anything else is refused and left alone."""
    with _lock:
        directory, info = resolve(workspace_id)
        _checked_export(directory, data)
        folder = _destination(info)
        with metadata_transaction(default={}) as metadata:
            variants = metadata.get('stages', {}).get(info['folder'], {}).get('variants', [])
            variant = next((v for v in variants if v.get('id') == variant_id), None)
            if variant is None:
                raise ValueError('That stage variant is no longer in the vault')
            if not chat_id or variant.get('randall_chat') != chat_id:
                raise ValueError('That stage variant was not made in this chat, so it is not changed')
            archive_path = folder / (variant.get('filename') or f'{variant_id}.zip')
            image_path = folder / (variant.get('screenshot_filename') or f'{variant_id}_screenshot.png')
            for path in (archive_path, image_path):
                if Path(path.name).name != path.name or not path.resolve().is_relative_to(folder.resolve()):
                    raise ValueError('Invalid destination')
            partial = []
            try:
                archive_part = folder / f'{variant_id}.{uuid.uuid4().hex}.part'
                partial.append(archive_part)
                with archive_part.open('xb') as handle:
                    _write_archive(handle, directory, info, data)
                image_part = None
                if screenshot:
                    image_part = folder / f'{variant_id}.{uuid.uuid4().hex}.png.part'
                    partial.append(image_part)
                    with image_part.open('xb') as handle:
                        _write_screenshot(handle, screenshot)
                # A scanner holding the archive the vault just wrote (Defender reads a new zip whole) is waited out.
                file_retry.replace(archive_part, archive_path, timeout=REPLACE_TIMEOUT)
                if image_part is not None:
                    file_retry.replace(image_part, image_path, timeout=REPLACE_TIMEOUT)
            finally:
                for path in partial:
                    file_retry.retry_locked(path.unlink, missing_ok=True)
            variant.update(has_screenshot=bool(screenshot) or bool(variant.get('has_screenshot')),
                           date_modified=datetime.now().isoformat(), slippi_tested=False, slippi_safe=None)
            if screenshot:
                variant['screenshot_filename'] = image_path.name
        return {'success': True, 'variantId': variant_id, 'folder': info['folder'], 'vault_changed': True,
                'name': variant.get('name') or variant_id, 'stageCode': info['stage_code'], 'slippi_tested': False}
