"""
Adding a game to the shelf: the shelf_add job.

    start(artifact_id, name=..., description=..., cover=..., replace=...)              a finished export
    start_from_vault(kind, item_id, name=..., description=..., cover=..., replace=...)  a Vault patch or bundle

The cover: a picture the user chose (`cover`, already decoded and re-encoded as PNG by
shelf.encode_cover: the request sends bytes, never a path), else the source's own picture
(the Vault item's), else the disc's banner (an export's banner is its project's, set in
Disc Banner & Info), else none (the card's plain placeholder). It is written only into the
entry's own folder (shelf.write_cover, shelf.confined).

The same game twice: a new game whose name an added entry already has (shelf.same_game) is
refused with code ``already_on_shelf`` and that entry, so the window can ask "replace it?".
`replace` is the answer: that entry's id. The build is then made exactly as a new game's,
in a reserved folder of its own, and swapped in by shelf.replace (same id, saves, place on
the shelf; its cover unless a new one was chosen). A failed or cancelled replace leaves the
old entry as it was; one whose game is running is refused, when it starts and again at the
swap.

The export page runs a normal ISO export first (projects/install/export_job.py); the ISO
that export finished is the only disc this takes. The request names the export job's id,
and the ISO's path comes from that job's record (``_resolve_completed_artifact``, which
also checks the file is in output/artifacts), never from the request.

The job reserves an entry folder, hard-links the ISO into it as disc.iso (a copy when the
two folders are on different drives), hashes it, takes the disc's banner as the cover and
stores the entry. Until the entry is stored the job owns the reserved folder, so a failure,
a Cancel or Nucleus closing mid-way removes it (``shelf.discard``), at once or at the next
start. Adding the same export again makes a second entry with saves of its own.

A Vault patch or bundle (start_from_vault) is looked up in the Vault's own index by id;
its file's path is made from the indexed id, never from the request. The job checks the
user's Melee disc, decodes the patch onto it straight into the reserved folder (the same
decode as Play in Dolphin, projects/install/xdelta.decode_patch), and keeps the Vault
item's name, description and picture. A bundle goes through the Vault's own checks
(vault/catalog/bundles.check_bundle: every member's name and size before any is read);
its patch.xdelta is decoded and its textures/*.png are kept in the entry's textures folder
for the Dolphin target (play/launch.py loads them into Slippi's ssbm-nucleus pack). The
entry is the shelf's own afterwards: nothing points back at the Vault, so changing or
deleting the Vault item leaves it as it is.

Nothing here builds fighter code: a fighter package's C is never compiled as a side effect
of adding a game.
"""

import hashlib
import logging
import re
import secrets
import struct
import zipfile
from pathlib import Path

import file_retry
from core import jobs
from play import routing, shelf

logger = logging.getLogger(__name__)

ADD_KIND = 'shelf_add'

MELEE_ID = b'GALE01'
BANNER_FILE = 'opening.bnr'
BANNER_WIDTH, BANNER_HEIGHT, BANNER_PIXELS = 96, 32, 0x20     # RGB5A3 picture after the magic
BANNER_SCALE = 6                                                # 96x32 -> 576x192, nearest
_HASH_CHUNK = 8 * 1024 * 1024

VAULT_KINDS = ('patch', 'bundle')
_VAULT_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
DISC_PART = 'disc.part.iso'          # the disc while xdelta3 writes it (in the reserved folder)
PATCH_PART = 'patch.part.xdelta'     # a bundle's patch.xdelta while it is decoded


def _clean_add(name, value):
    """What an add still owned when it ended or Nucleus died: its reserved entry folder, and for
    a replace the folder the entry used before. shelf.discard removes either only while no
    entry uses it, so before the swap the old folder stays and after it the new one does."""
    if name in ('reserved', 'retired'):
        shelf.discard(value)
    return None


jobs.register_kind(ADD_KIND, label='Add to shelf', cleanup=_clean_add)


def finished_export(artifact_id):
    """The ISO of a finished export job, checked to be a Melee disc. Raises ShelfError."""
    from projects.install.export_job import _resolve_completed_artifact, export_job
    if not isinstance(artifact_id, str) or not artifact_id:
        raise shelf.ShelfError('Say which export to add.')
    path = _resolve_completed_artifact(artifact_id)
    if path is None:
        raise shelf.ShelfError('That export is not finished, or Nucleus has restarted since. Export it again.', 404)
    record = export_job(artifact_id) or {}
    if (record.get('params') or {}).get('texturePackMode'):
        raise shelf.ShelfError('A texture-pack build cannot go on the shelf. Use a normal ISO export.')
    with open(path, 'rb') as stream:
        if stream.read(6) != MELEE_ID:
            raise shelf.ShelfError('That export is not a Melee disc (GALE01).')
    return path, record


def sha256_file(path: Path, *, progress=None, should_stop=None):
    digest = hashlib.sha256()
    total = path.stat().st_size or 1
    done = 0
    with open(path, 'rb') as stream:
        while True:
            if should_stop is not None and should_stop():
                raise jobs.Cancelled()
            chunk = stream.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done / total)
    return digest.hexdigest()


def banner_picture(raw: bytes):
    """The 96x32 picture of an opening.bnr as RGBA pixels, or None for something else."""
    if len(raw) < BANNER_PIXELS + BANNER_WIDTH * BANNER_HEIGHT * 2 or raw[:3] != b'BNR':
        return None
    from shared.rendering.gx_texels import rgb5a3, tile_iter
    pixels = [(0, 0, 0, 0)] * (BANNER_WIDTH * BANNER_HEIGHT)
    for x, y, index in tile_iter(BANNER_WIDTH, BANNER_HEIGHT, 4, 4):
        value = struct.unpack_from('>H', raw, BANNER_PIXELS + index * 2)[0]
        pixels[y * BANNER_WIDTH + x] = rgb5a3(value)
    return pixels


def banner_cover(disc: Path, scratch: Path, scale=BANNER_SCALE):
    """The disc's banner as a cover PNG (scaled up `scale` times, nearest), or None when it has
    none. `scratch` is a file name the banner may be extracted to; it is removed afterwards."""
    from PIL import Image
    from shared.vanilla_extract.vanilla_refs import extract_file_from_iso
    try:
        if not extract_file_from_iso(disc, BANNER_FILE, scratch):
            return None
        pixels = banner_picture(scratch.read_bytes())
    except (OSError, ValueError, struct.error) as e:
        logger.info('Play: no banner read from %s: %s', disc.name, e)
        return None
    finally:
        try:
            scratch.unlink()
        except OSError:
            pass
    if pixels is None:
        return None
    image = Image.new('RGBA', (BANNER_WIDTH, BANNER_HEIGHT))
    image.putdata(pixels)
    if scale != 1:
        image = image.resize((BANNER_WIDTH * scale, BANNER_HEIGHT * scale), Image.NEAREST)
    import io
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


DISC_BANNER_GLOB = 'disc-banner-*.png'


def disc_banner():
    """The banner of the user's own Melee disc (launch.retail_iso) as a PNG in the Play folder, or
    None while Nucleus has no disc or the disc has no banner. It is the built-in Vanilla game's
    picture: the same 96x32 banner the Projects page shows for a project made from that disc, kept
    at its own size so the page can scale it by whole pixels (ShelfCard BannerArt). Made once per
    disc (the file name carries the disc's path, size and time, so choosing another disc makes it
    again) and read from the disc, never shipped."""
    from play import launch
    disc = launch.retail_iso()
    if not disc:
        return None
    disc = Path(disc)
    try:
        stat = disc.stat()
    except OSError:
        return None
    stamp = hashlib.sha1(f'{disc}|{stat.st_size}|{stat.st_mtime_ns}'.encode('utf-8')).hexdigest()[:12]
    folder = shelf.play_root()
    path = folder / DISC_BANNER_GLOB.replace('*', stamp)
    if path.is_file():
        return path
    folder.mkdir(parents=True, exist_ok=True)
    unique = secrets.token_hex(4)
    png = banner_cover(disc, folder / f'{path.name}.{unique}.bnr', scale=1)
    if png is None:
        return None
    temporary = folder / f'{path.name}.{unique}.tmp'
    try:
        temporary.write_bytes(png)
        file_retry.replace(temporary, path)
    except OSError as e:
        logger.info('Play: the disc banner was not kept: %s', e)
        try:
            temporary.unlink()
        except OSError:
            pass
        return None
    for old in folder.glob(DISC_BANNER_GLOB):
        if old != path:
            try:
                old.unlink()
            except OSError:
                pass
    return path


def _default_cover(entry_id, disc: Path, folder: Path, picture=None):
    """The cover a game gets when none was chosen: the source's own picture, else the disc's
    banner, else None."""
    if picture is not None:
        try:
            return shelf.encode_cover(Path(picture).read_bytes())
        except (OSError, shelf.ShelfError) as e:
            logger.info('Play: the picture of %s was not used as its cover: %s', entry_id, e)
    return banner_cover(disc, folder / (BANNER_FILE + '.tmp'))


def _finish(job, *, entry_id, folder: Path, how, start, name, description, origin, picture=None, extra=None,
            cover=None, replace=None, replace_description=None):
    """The end every add shares: hash the disc now in the entry's folder, read its fighters,
    take a cover (the one chosen, else the source's own picture, else the disc's banner) and
    store the entry, or swap it in for the entry `replace`."""
    disc = folder / shelf.DISC_FILE
    sha = sha256_file(disc, should_stop=job.should_stop,
                      progress=lambda f: job.progress(start + (0.9 - start) * f, 'Checking the disc...'))

    job.progress(0.92, 'Looking at the fighters...')
    entry = {'id': entry_id, 'name': name, 'description': description, 'origin': origin,
             'disc': {'kind': 'owned', 'size': disc.stat().st_size, 'sha256': sha, 'how': how}}
    entry.update(routing.decide(disc))
    entry.update(extra or {})

    job.progress(0.96, 'Making a cover...')
    png = cover if cover is not None else _default_cover(entry_id, disc, folder, picture)
    if png is not None:
        shelf.write_cover({'id': entry_id}, png)
        entry['cover'] = True

    if replace is None:
        stored = shelf.add(entry)
        job.release('reserved')
        logger.info('Play: added %s to the shelf (%s, disc %s)', entry_id, stored.get('engine'), how)
        job.progress(1.0, 'On the shelf')
        return {'entryId': entry_id, 'how': how, 'name': stored['name']}

    from play import launch
    job.progress(0.98, 'Replacing the game on the shelf...')
    retiring = shelf.folder_of(replace)
    if retiring is not None:
        job.own('retired', retiring)      # removed only once no entry uses it (after the swap)
    stored, retired = shelf.replace(replace, entry, files=entry_id, description=replace_description,
                                    keep_cover=cover is None,
                                    busy=lambda: launch.running_entry() == replace)
    job.release('reserved')
    shelf.discard(retired)
    job.release('retired')
    logger.info('Play: replaced the files of %s (now in %s, disc %s)', replace, entry_id, how)
    job.progress(1.0, 'Replaced on the shelf')
    return {'entryId': stored['id'], 'how': how, 'name': stored['name'], 'replaced': True}


def run_add(job, *, source: Path, name, description, origin, cover=None, replace=None, replace_description=None):
    """The shelf_add job for a finished export (module docstring). Returns {entryId, how, name}."""
    job.progress(0.0, 'Making room on the shelf...')
    entry_id, folder = shelf.reserve()
    job.own('reserved', entry_id)
    disc = folder / shelf.DISC_FILE

    def stop():
        return job.should_stop()

    job.progress(0.02, 'Adding the disc...', entryId=entry_id)
    try:
        how = shelf.link_or_copy(source, disc, should_stop=stop,
                                 progress=lambda f: job.progress(0.02 + 0.6 * f, 'Copying the disc...'))
    except shelf.ShelfError as e:
        if e.status == 409 and stop():
            raise jobs.Cancelled()
        raise
    return _finish(job, entry_id=entry_id, folder=folder, how=how, start=0.02 if how == 'linked' else 0.62,
                   name=name, description=description, origin=origin, cover=cover, replace=replace,
                   replace_description=replace_description)


# --------------------------------------------------------------------------- from the Vault

def vault_item(kind, item_id):
    """The Vault patch or bundle `item_id` names, from the Vault's own index:
    {kind, id, name, description, file, picture}. `file` and `picture` are made from the
    indexed id in the Vault's own folder. Raises ShelfError."""
    if kind not in VAULT_KINDS:
        raise shelf.ShelfError('Say whether it is a patch or a bundle.')
    if not isinstance(item_id, str) or not _VAULT_ID.match(item_id):
        raise shelf.ShelfError('That is not in your Vault.', 404)
    if kind == 'patch':
        from projects.install import xdelta
        rows, folder, suffix = xdelta.load_xdelta_metadata(), xdelta.XDELTA_PATH, '.xdelta'
    else:
        from vault.catalog import bundles
        rows, folder, suffix = bundles.load_bundle_metadata(), bundles.BUNDLE_PATH, '.ssbm'
    row = next((r for r in rows or [] if isinstance(r, dict) and r.get('id') == item_id), None)
    if row is None or not _VAULT_ID.match(str(row.get('id'))):
        raise shelf.ShelfError('That is not in your Vault.', 404)
    stored_id = str(row['id'])
    file = Path(folder) / f'{stored_id}{suffix}'
    if not file.is_file():
        raise shelf.ShelfError(f"That {kind}'s file is missing from your Vault.", 404)
    picture = Path(folder) / f'{stored_id}.png'
    return {'kind': kind, 'id': stored_id, 'file': file,
            'name': row.get('name') if isinstance(row.get('name'), str) else '',
            'description': row.get('description') if isinstance(row.get('description'), str) else '',
            'picture': picture if picture.is_file() else None}


def _open_bundle(zf):
    """(checked member names, build name) of an open bundle. Raises ShelfError."""
    from vault.catalog.bundles import _bundle_build_name, check_bundle, read_manifest
    try:
        names = check_bundle(zf)
        if 'manifest.json' not in names:
            raise ValueError('manifest.json missing')
        build_name = _bundle_build_name(read_manifest(zf))
    except (ValueError, KeyError, zipfile.BadZipFile) as e:
        raise shelf.ShelfError(f'That bundle cannot be used: {e}')
    if 'patch.xdelta' not in names:
        raise shelf.ShelfError('That bundle cannot be used: it has no patch.xdelta.')
    return names, build_name


def _copy_member(zf, name, target: Path, should_stop):
    with zf.open(name) as source, open(target, 'wb') as out:
        while True:
            if should_stop():
                raise jobs.Cancelled()
            chunk = source.read(_HASH_CHUNK)
            if not chunk:
                break
            out.write(chunk)


def run_add_vault(job, *, item, retail: Path, name, description, cover=None, replace=None,
                  replace_description=None):
    """The shelf_add job for a Vault patch or bundle (module docstring). Returns {entryId, how, name}."""
    from play import launch
    from projects.install.xdelta import building_progress, decode_patch

    job.progress(0.0, 'Checking your Melee disc...')
    try:
        launch.check_retail_iso(retail)
    except launch.PlayError as e:
        raise shelf.ShelfError(str(e))
    entry_id, folder = shelf.reserve()
    job.own('reserved', entry_id)
    stop = job.should_stop
    job.progress(0.02, 'Reading the patch...', entryId=entry_id)

    extra = {}
    patch = item['file']
    if item['kind'] == 'bundle':
        try:
            with zipfile.ZipFile(item['file'], 'r') as zf:
                names, build_name = _open_bundle(zf)
                patch = folder / PATCH_PART
                _copy_member(zf, 'patch.xdelta', patch, stop)
                from vault.catalog.bundles import texture_members
                textures = texture_members(names)
                if textures:
                    target = shelf.textures_dir({'id': entry_id})
                    target.mkdir(parents=True, exist_ok=True)
                    for member, file_name in textures.items():
                        _copy_member(zf, member, target / file_name, stop)
                    extra['texturePack'] = {'buildName': build_name, 'count': len(textures)}
        except zipfile.BadZipFile as e:
            raise shelf.ShelfError(f'That bundle cannot be used: {e}')

    staging = folder / DISC_PART
    try:
        decode_patch(retail, patch, staging, should_stop=stop,
                     progress=building_progress(job.progress, start=5, span=70))
    except RuntimeError as e:
        raise shelf.ShelfError(f'The {item["kind"]} could not be built onto your Melee disc. {e}')
    if patch != item['file']:
        patch.unlink(missing_ok=True)
    with open(staging, 'rb') as stream:
        if stream.read(6) != MELEE_ID:
            raise shelf.ShelfError(f'The {item["kind"]} did not build a Melee disc (GALE01).')
    file_retry.replace(staging, folder / shelf.DISC_FILE)
    origin = {'kind': item['kind'], 'name': shelf.clean_text(item['name'], shelf.MAX_NAME, field='name')}
    return _finish(job, entry_id=entry_id, folder=folder, how='built', start=0.75, name=name,
                   description=description, origin=origin, picture=item['picture'], extra=extra,
                   cover=cover, replace=replace, replace_description=replace_description)


def replacing(name, replace):
    """The id of the entry this add replaces, or None for a new game. Without `replace`, a game
    whose name an added entry already has is refused (409, code ``already_on_shelf``, with
    ``existing: {id, name}``). With it, that entry must be an added one and not running."""
    from play import launch
    if replace is None:
        existing = shelf.same_game(name)
        if existing is not None:
            raise shelf.ShelfError(f'"{existing["name"]}" is already on your Unlocked shelf.', 409,
                                   code=shelf.SAME_GAME, existing=existing)
        return None
    if replace in shelf.BUILTIN_IDS:
        raise shelf.ShelfError('The built-in games cannot be replaced.')
    entry = shelf.get(replace)
    if launch.running_entry() == entry['id']:
        raise shelf.ShelfError('That game is running. Close it first.', 409)
    return entry['id']


def _job_params(params, replace):
    return {**params, 'replace': replace} if replace is not None else params


def _label(name, replace):
    return f'Replace {name} on the shelf' if replace is not None else f'Add {name} to the shelf'


def start_from_vault(kind, item_id, *, name=None, description=None, cover=None, replace=None):
    """Start a shelf_add job for a Vault patch or bundle. `cover` is a chosen picture as
    shelf.encode_cover made it; `replace` the id of the entry it replaces. Returns the job id.
    Raises ShelfError, JobBusy."""
    from play import launch
    item = vault_item(kind, item_id)
    retail = launch.retail_iso()
    if retail is None:
        raise shelf.ShelfError('Nucleus needs your Melee ISO to build this. Choose it in Settings, Setup.')
    if kind == 'bundle':
        try:
            with zipfile.ZipFile(item['file'], 'r') as zf:
                _open_bundle(zf)
        except (OSError, zipfile.BadZipFile) as e:
            raise shelf.ShelfError(f'That bundle cannot be used: {e}')
    clean_name = shelf.clean_text(name, shelf.MAX_NAME, field='name') or \
        shelf.clean_text(item['name'], shelf.MAX_NAME, field='name') or 'Untitled game'
    clean_description = shelf.clean_text(item['description'] if description is None else description,
                                         shelf.MAX_DESCRIPTION, field='description')
    replace = replacing(clean_name, replace)
    # A replace keeps the entry's own description unless the request gave one (not the Vault item's).
    own_description = shelf.clean_text(description, shelf.MAX_DESCRIPTION, field='description')
    return jobs.start(ADD_KIND, lambda job: run_add_vault(job, item=item, retail=Path(retail), name=clean_name,
                                                          description=clean_description, cover=cover,
                                                          replace=replace, replace_description=own_description),
                      label=_label(clean_name, replace), single=True,
                      params=_job_params({'name': clean_name, 'from': kind}, replace))


def start(artifact_id, *, name=None, description=None, cover=None, replace=None):
    """Start a shelf_add job for a finished export. `cover` is a chosen picture as
    shelf.encode_cover made it; `replace` the id of the entry it replaces. Returns the job id.
    Raises ShelfError, JobBusy."""
    source, record = finished_export(artifact_id)
    params = record.get('params') or {}
    filename = params.get('filename') if isinstance(params.get('filename'), str) else ''
    stem = filename[:-4] if filename.lower().endswith('.iso') else filename
    clean_name = shelf.clean_text(name, shelf.MAX_NAME, field='name') or \
        shelf.clean_text(stem, shelf.MAX_NAME, field='name') or 'Untitled game'
    clean_description = shelf.clean_text(description, shelf.MAX_DESCRIPTION, field='description')
    replace = replacing(clean_name, replace)
    origin = {'kind': 'export', 'filename': shelf.clean_text(filename, 200, field='name')}
    return jobs.start(ADD_KIND, lambda job: run_add(job, source=source, name=clean_name,
                                                    description=clean_description, origin=origin, cover=cover,
                                                    replace=replace, replace_description=clean_description),
                      label=_label(clean_name, replace), single=True,
                      params=_job_params({'name': clean_name, 'artifactId': artifact_id}, replace))
