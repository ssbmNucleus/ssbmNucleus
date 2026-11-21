"""
Custom characters, project side: install vault custom characters into the open
m-ex project (one at a time or as one `add-fighters` batch), install one of a
character's added skins, and remove a fighter from the project.

An install folds the vault-side edits into the fighter package first: costume
CSP/stock edits and renames, a custom franchise created or matched in the
target project, the clone item patch, and the victory theme and announcer
name-call, which add-fighter itself resets. Every workspace-mutating MexCLI
call holds mexcli_lock.

These routes register on `custom_characters_bp` from
vault/routes/custom_characters/ (the vault's custom character library), so URLs
and endpoint names are unchanged; the vault index and fighter.zip helpers both
use are vault/catalog/custom_characters.py.
"""

import json
import os
import subprocess
import tempfile
import zipfile
import logging
from pathlib import Path
from flask import request, jsonify

from core.config import CUSTOM_CHARACTERS_PATH, MEXCLI_PATH, PROJECT_ROOT, get_subprocess_args
import mexcli.commands
from core.state import get_current_project_path, reload_mex_manager, get_socketio, mexcli_lock
from vault.catalog.custom_characters import (
    SERIES_NAMES, _active_csp_path_for_skin, _find_entry, _read_metadata, _rewrite_zip_fighter_json,
)
from vault.routes.custom_characters import custom_characters_bp

logger = logging.getLogger(__name__)


CSP_SD_SIZE = (136, 188)


def _normalize_csp_png(raw):
    """Return in-game-sized PNG bytes for a CSP source image."""
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as src:
            img = src.convert('RGBA')
        if img.size != CSP_SD_SIZE:
            img.thumbnail(CSP_SD_SIZE, Image.LANCZOS)
            canvas = Image.new('RGBA', CSP_SD_SIZE, (0, 0, 0, 0))
            x = (CSP_SD_SIZE[0] - img.size[0]) // 2
            y = (CSP_SD_SIZE[1] - img.size[1]) // 2
            canvas.alpha_composite(img, (x, y))
            img = canvas
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()
    except Exception:
        return raw


def _zip_bytes_with_csp(zip_path, csp_bytes):
    """Return zip bytes with csp.png replaced or appended."""
    import io
    normalized = _normalize_csp_png(csp_bytes)
    buf = io.BytesIO()
    replaced = False
    with zipfile.ZipFile(zip_path, 'r') as src, \
            zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            basename = item.filename.split('/')[-1].lower()
            if basename in ('csp.png', 'csp'):
                dst.writestr(item, normalized)
                replaced = True
            else:
                dst.writestr(item, src.read(item.filename))
        if not replaced:
            dst.writestr('csp.png', normalized)
    return buf.getvalue()


def _zip_bytes_with_active_csp(storage_key, skin, zip_path):
    active_path = _active_csp_path_for_skin(storage_key, skin)
    if active_path:
        return _zip_bytes_with_csp(zip_path, active_path.read_bytes())
    return Path(zip_path).read_bytes()


def _clone_patch_entries(zip_path):
    """Install-time FALLBACK for vault entries scanned before the patch was
    baked into fighter.zip (_bake_clone_patch): {zip entry: bytes} adding the
    item-only clone patch to the install zip, so add-fighter merges it.
    Without it ACE's Metal Mario froze on side-B ("item not initialized") on
    any project not built from the ACE patch. Packages that already carry
    their own patches/*.dat are left alone."""
    from core.clone_patch import PATCH_ENTRY, fighter_needs_items_patch, items_patch_bytes
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if any(n.lower().startswith('patches/') for n in names):
                return {}
            fj = next((n for n in names if n.split('/')[-1].lower() == 'fighter.json'), None)
            if fj is None or not fighter_needs_items_patch(json.loads(zf.read(fj))):
                return {}
        return {PATCH_ENTRY: items_patch_bytes()}
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as e:
        logger.warning(f"clone item patch not added for {zip_path}: {e}")
        return {}


def _apply_announcer(project_path, fighter_ref, announcer_wav):
    """Point an installed fighter at its name-call, matched by CONTENT
    (core/narrator.py): an identical clip already in the project (a vanilla
    name, or one an earlier install ported) is reused; otherwise the clip is
    ported once and recorded so later characters with the same clip share it.
    Returns (announcerCall or None, how): how is 'match', 'ported' (reused an
    earlier port), 'new' (ported now), 'bonus' / 'bonus-new' (no clip of its
    own: the project's "Bonus Character" line), 'none' or 'failed'.

    The old fallback reused the SOURCE build's raw call id when no clip was
    extracted. Ids only mean something in their own build: ACE's 510059
    ("Bonus Character") is, in a vanilla project, whichever name-call happened
    to be ported sixth -- which is how every ACE import said one other
    character's name. No clip now means the default "Bonus Character" line."""
    from core import narrator
    announcer_wav = Path(announcer_wav)
    project_dir = Path(project_path).parent
    if not announcer_wav.exists():
        return _apply_bonus_call(project_path, fighter_ref)
    clip = narrator.pcm_hash(announcer_wav)
    call, how = narrator.resolve_call(project_dir, clip, MEXCLI_PATH)
    if call is not None:
        out = mexcli.commands.run_json(['set-fighter-announcer-id', project_path, fighter_ref, call])
        return (call, how) if out.get('success') else (None, 'failed')
    out = mexcli.commands.run_json(['set-fighter-announcer', project_path, fighter_ref, announcer_wav])
    call = out.get('announcerCall')
    if not out.get('success') or not isinstance(call, int):
        return None, 'failed'
    narrator.record_port(project_dir, clip, call, MEXCLI_PATH)
    return call, 'new'


def _apply_bonus_call(project_path, fighter_ref):
    """Point a fighter without a call of its own at the project's "Bonus
    Character" line, adding it once (core/narrator.py builds it from the
    project's own narrator banks; no audio ships with the app)."""
    from core import narrator
    project_dir = Path(project_path).parent
    call = narrator.bonus_call(project_dir, MEXCLI_PATH)
    if call is not None:
        out = mexcli.commands.run_json(['set-fighter-announcer-id', project_path, fighter_ref, call])
        return (call, 'bonus') if out.get('success') else (None, 'failed')
    with tempfile.TemporaryDirectory(prefix='nucleus_bonus_') as tmp:
        clip = narrator.build_bonus_clip(project_dir, MEXCLI_PATH, Path(tmp) / 'bonus.wav')
        if clip is None:
            return None, 'none'          # the build replaced the source clips
        clip_hash = narrator.pcm_hash(clip)
        out = mexcli.commands.run_json(['set-fighter-announcer', project_path, fighter_ref, clip])
    call = out.get('announcerCall')
    if not out.get('success') or not isinstance(call, int):
        return None, 'failed'
    narrator.record_port(project_dir, narrator.BONUS_KEY, call, MEXCLI_PATH)
    # a vault clip sample-identical to ours dedupes onto it
    narrator.record_port(project_dir, clip_hash, call, MEXCLI_PATH)
    return call, 'bonus-new'


def _plan_batch_announcers(prepared):
    """One port per distinct new clip in a batch: the first fighter carrying a
    clip keeps its announcerWav (add-fighters ports it); later fighters with
    the same clip lose theirs and are pointed at the first one's call after
    the batch. Returns ({clip hash: owner index}, [(index, owner index)])."""
    port_owner, dupes = {}, []
    for i, pre in enumerate(prepared):
        h, e = pre.get('announcer_hash'), pre['manifest']
        if not h or 'announcerWav' not in e:
            continue
        if h in port_owner:
            e.pop('announcerWav')
            dupes.append((i, port_owner[h]))
        else:
            port_owner[h] = i
    return port_owner, dupes


def _resolve_install_series(entry, char_dir, project_path, mexcli_path):
    """Work out what seriesID the fighter should use in the TARGET project.

    Returns (series_id_or_None, warnings). None means "leave fighter.json
    as-is". A custom series (extracted from the source build) is matched by
    name in the target project or created there via `mexcli add-series`.
    A dangling seriesID (points past the target's series list) falls back
    to Smash Bros. so the install never references a missing series.
    """
    warnings = []
    project_dir = Path(project_path).parent
    series_json = project_dir / 'data' / 'series.json'
    target_series = None
    if series_json.exists():
        try:
            with open(series_json, 'r', encoding='utf-8') as f:
                target_series = json.load(f)
        except (json.JSONDecodeError, OSError):
            target_series = None
    target_count = len(target_series) if target_series is not None else len(SERIES_NAMES)

    cs = entry.get('custom_series')
    icon = char_dir / 'series_icon.png'
    if cs and cs.get('active') and icon.exists():
        name = (cs.get('name') or '').strip() or f"Series {cs.get('source_id', '?')}"

        if target_series is not None:
            for i, s in enumerate(target_series):
                if (s.get('name') or '').strip().lower() == name.lower():
                    return i, warnings

        cmd = [mexcli_path, 'add-series', str(project_path), name, str(icon)]
        emblem = char_dir / 'series_emblem.obj'
        if emblem.exists():
            cmd.append(str(emblem))
        logger.info(f"Creating series '{name}' in project: {' '.join(cmd)}")
        with mexcli_lock:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(PROJECT_ROOT), **get_subprocess_args()
            )
        if result.returncode == 0:
            out = mexcli.commands.parse_json(result.stdout)
            if 'seriesId' in out:
                return out['seriesId'], warnings
        warnings.append(f"Could not create series '{name}' in project; franchise icon skipped")
        logger.warning(f"add-series failed: {result.stderr or result.stdout}")

    # No (usable) custom series — make sure the fighter's seriesID isn't dangling
    sid = entry.get('series_id', 0)
    if isinstance(sid, int) and sid >= target_count:
        warnings.append(f"Series {sid} does not exist in this project; defaulted to Smash Bros.")
        return 11, warnings
    return None, warnings


@custom_characters_bp.route('/api/mex/custom-characters/install', methods=['POST'])
def install_custom_character():
    """Install a custom character from the vault into the currently open project."""
    temp_zip = None
    try:
        data = request.json or {}
        slug = data.get('slug', '').strip()
        if not slug:
            return jsonify({'success': False, 'error': 'Missing slug parameter'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded. Open a project first.'}), 400

        char_dir = CUSTOM_CHARACTERS_PATH / slug
        zip_path = char_dir / 'fighter.zip'

        # An Any Climbers pair is stored as a recipe, not a baked package.
        built, pair_error = _materialize_pair(
            _find_entry(_read_metadata(), slug) or {}, char_dir, project_path)
        if pair_error:
            return jsonify({'success': False, 'error': pair_error}), 422
        if built:
            zip_path = built

        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Fighter ZIP not found for "{slug}". Re-scan the ISO to generate it.'}), 404

        mexcli_path = str(MEXCLI_PATH)
        if not Path(mexcli_path).exists():
            return jsonify({'success': False, 'error': 'MexCLI not found'}), 500

        metadata = _read_metadata()
        entry = _find_entry(metadata, slug) or {}
        # Custom franchise: re-create the series in the target project (or
        # match an existing one by name) and point the fighter at it
        series_id, series_warnings = _resolve_install_series(
            entry, char_dir, project_path, mexcli_path)

        # Fold costume edits back into the fighter zip: CSP/stock changes
        # live in the materialized per-costume zips (costumes/<stem>.zip),
        # renames in costume_meta — installs must carry both
        costumes_dir = char_dir / 'costumes'
        meta_by_id = {m['id']: m for m in entry.get('costume_meta', [])}
        replace_entries = {}
        if costumes_dir.exists():
            for f in costumes_dir.glob('*.zip'):
                meta = meta_by_id.get(Path(f.name).stem)
                if meta:
                    replace_entries[f.name] = _zip_bytes_with_active_csp(
                        f'custom_characters/{slug}/costumes', meta, f)
        replace_entries.update(_clone_patch_entries(zip_path))

        def _mutate_install_json(meta):
            if series_id is not None:
                meta['seriesID'] = series_id
            for costume in meta.get('costumes', []):
                stem = Path((costume.get('file') or {}).get('fileName') or '').stem
                m = meta_by_id.get(stem)
                if m and m.get('color'):
                    costume['name'] = m['color']
            return meta

        install_zip = zip_path
        if series_id is not None or replace_entries:
            temp_zip = Path(tempfile.mktemp(suffix='.zip', prefix='nucleus_fighter_'))
            _rewrite_zip_fighter_json(zip_path, temp_zip,
                                      mutate_json=_mutate_install_json,
                                      replace_entries=replace_entries)
            install_zip = temp_zip

        cmd = [mexcli_path, 'add-fighter', str(project_path), str(install_zip)]
        logger.info(f"Installing custom character '{slug}': {' '.join(cmd)}")

        with mexcli_lock:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(PROJECT_ROOT), **get_subprocess_args()
            )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or 'Unknown error'
            logger.error(f"add-fighter failed: {error_msg}")
            return jsonify({'success': False, 'error': f'Failed to add fighter: {error_msg}'}), 500

        cli_output = mexcli.commands.parse_json(result.stdout)
        fighter_name = cli_output.get('name', slug)
        fighter_internal_id = cli_output.get('internalId')
        if not isinstance(fighter_internal_id, int):
            fighter_internal_id = None

        # Custom skins are intentionally NOT force-installed here. They appear
        # in the costume "Available to Import" list (via /storage/costumes) so
        # the user chooses which to import per-skin, like a vanilla character's
        # vault skins. See install_custom_character_skin / the install-skin route.
        skins_installed = 0
        skin_warnings = []

        # Port the victory theme: add the track to the target project (or
        # reuse a same-named one) and point the fighter at it — add-fighter
        # itself resets victoryTheme to the default
        victory_ported = False
        vt_file = char_dir / 'victory_theme.hps'
        vt_meta = entry.get('victory_theme') or {}
        if vt_file.exists() and vt_meta.get('name'):
            music_out = mexcli.commands.run_json(['add-music', project_path, vt_file, vt_meta['name']])
            if music_out.get('success') and 'musicId' in music_out:
                set_out = mexcli.commands.run_json(['set-fighter-music', project_path,
                                           fighter_name, music_out['musicId']])
                victory_ported = bool(set_out.get('success'))
            if not victory_ported:
                skin_warnings.append(f"Victory theme '{vt_meta['name']}' could not be ported")
                logger.warning(f"Victory theme port failed for {slug}")
            else:
                logger.info(f"Ported victory theme '{vt_meta['name']}' "
                            f"(musicId {music_out['musicId']}) for {fighter_name}")

        # Announcer name-call, matched by content (see _apply_announcer).
        ann_call, ann_how = _apply_announcer(
            project_path,
            fighter_internal_id if fighter_internal_id is not None else fighter_name,
            char_dir / 'announcer.wav')
        announcer_ported = ann_call is not None
        announcer_reused = ann_how in ('match', 'ported')
        if ann_how == 'failed':
            skin_warnings.append("Announcer name-call could not be set")
        elif ann_call is not None:
            logger.info(f"Announcer for {fighter_name}: {ann_how} -> {ann_call}")

        import time
        time.sleep(0.15)
        reload_mex_manager()

        logger.info(f"[OK] Installed custom character '{slug}' into project "
                    f"(+{skins_installed} custom skin(s))")
        message = f"Added {fighter_name} to project"
        if skins_installed:
            message += f" with {skins_installed} custom skin(s)"
        if victory_ported:
            message += f", victory theme '{vt_meta['name']}'"
        return jsonify({
            'success': True,
            'message': message,
            'name': fighter_name,
            'costumeCount': cli_output.get('costumeCount', 0),
            'customSkinsInstalled': skins_installed,
            'seriesId': series_id,
            'victoryThemePorted': victory_ported,
            'announcerPorted': announcer_ported,
            'announcerReused': announcer_reused,
            'warnings': series_warnings + skin_warnings,
        })
    except Exception as e:
        logger.error(f"Install custom character error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if temp_zip is not None and temp_zip.exists():
            temp_zip.unlink()


def _materialize_pair(entry, char_dir, project_path):
    """Build an Any Climbers pair's fighter package, if this entry is one.

    A pair is stored in the vault as a recipe (two fighter names) rather than a
    baked package, so that creating one does not require a project. The package
    is built here, against the project being installed into. Returns
    (zip_path_or_None, error_or_None); a non-pair entry returns (None, None).
    """
    if not entry.get('climbers'):
        return None, None
    try:
        from vault.climbers.pairs import materialize
        return materialize(entry, char_dir, project_path), None
    except ValueError as e:
        return None, str(e)
    except Exception as e:
        logger.exception(f"pair materialize failed for {entry.get('slug')}")
        return None, f'Could not build pair: {e}'


def _prepare_fighter_for_batch(slug, project_path, mexcli_path):
    """Per-char preprocessing for a batch install, identical to the work
    install_custom_character does BEFORE add-fighter: resolve the series (may
    create it, baking seriesID into a temp zip), fold costume CSP/stock edits +
    renames into that zip, and collect the victory-theme / announcer manifest
    fields. The actual add-fighter + victory + announcer mutations are folded into
    the single `add-fighters` Save by the batch CLI command.

    Returns {ok, slug, manifest, temp_zip, warnings} or {ok: False, slug, error}.
    """
    char_dir = CUSTOM_CHARACTERS_PATH / slug
    zip_path = char_dir / 'fighter.zip'

    metadata = _read_metadata()
    entry = _find_entry(metadata, slug) or {}

    built, pair_error = _materialize_pair(entry, char_dir, project_path)
    if pair_error:
        return {'ok': False, 'slug': slug, 'error': pair_error}
    if built:
        zip_path = built

    if not zip_path.exists():
        return {'ok': False, 'slug': slug,
                'error': f'Fighter ZIP not found for "{slug}". Re-scan the ISO to generate it.'}

    warnings = []

    # Custom franchise: re-create/match the series in the target project. This is
    # the one piece that stays a separate (rare) save -- the zip carries the result.
    series_id, series_warnings = _resolve_install_series(entry, char_dir, project_path, mexcli_path)
    warnings += series_warnings

    # Fold costume CSP/stock edits + color renames back into the fighter zip.
    costumes_dir = char_dir / 'costumes'
    meta_by_id = {m['id']: m for m in entry.get('costume_meta', [])}
    replace_entries = {}
    if costumes_dir.exists():
        for f in costumes_dir.glob('*.zip'):
            meta = meta_by_id.get(Path(f.name).stem)
            if meta:
                replace_entries[f.name] = _zip_bytes_with_active_csp(
                    f'custom_characters/{slug}/costumes', meta, f)
    replace_entries.update(_clone_patch_entries(zip_path))

    def _mutate_install_json(meta):
        if series_id is not None:
            meta['seriesID'] = series_id
        for costume in meta.get('costumes', []):
            stem = Path((costume.get('file') or {}).get('fileName') or '').stem
            m = meta_by_id.get(stem)
            if m and m.get('color'):
                costume['name'] = m['color']
        return meta

    install_zip = zip_path
    temp_zip = None
    if series_id is not None or replace_entries:
        temp_zip = Path(tempfile.mktemp(suffix='.zip', prefix='nucleus_fighter_'))
        _rewrite_zip_fighter_json(zip_path, temp_zip,
                                  mutate_json=_mutate_install_json,
                                  replace_entries=replace_entries)
        install_zip = temp_zip

    e = {'zip': str(install_zip)}

    # Victory theme (add-fighter resets victoryTheme; the batch re-ports it).
    vt_file = char_dir / 'victory_theme.hps'
    vt_meta = entry.get('victory_theme') or {}
    if vt_file.exists() and vt_meta.get('name'):
        e['victoryHps'] = str(vt_file)
        e['victoryName'] = vt_meta['name']

    # Announcer name-call, matched by content (see _apply_announcer): a clip the
    # project already has is reused by id; a new one is ported by add-fighters.
    # The batch route dedupes identical new clips across the batch.
    announcer_wav = char_dir / 'announcer.wav'
    announcer_hash = None
    if announcer_wav.exists():
        from core import narrator
        announcer_hash = narrator.pcm_hash(announcer_wav)
        call, _how = narrator.resolve_call(Path(project_path).parent, announcer_hash, MEXCLI_PATH)
        if call is not None:
            e['announcerCallReuse'] = call
        else:
            e['announcerWav'] = str(announcer_wav)

    return {'ok': True, 'slug': slug, 'manifest': e, 'temp_zip': temp_zip, 'warnings': warnings,
            'announcer_hash': announcer_hash}


@custom_characters_bp.route('/api/mex/custom-characters/install-batch', methods=['POST'])
def install_custom_characters_batch():
    """Bulk-install several vault custom characters in ONE `add-fighters` call --
    one workspace Save instead of ~4 per character (add-fighter + add-music +
    set-fighter-music + set-fighter-announcer all re-Save today). Output is
    byte-identical to N sequential installs except the generated PlCo bone-lookup
    file (serialization layout only; every fighter validated loadable in-game).

    The frontend re-fits the CSS grid afterwards, exactly like the per-char path.

    Body: { "slugs": ["wario", "toad", ...] }
    """
    temp_zips = []
    try:
        data = request.json or {}
        slugs = [s.strip() for s in (data.get('slugs') or []) if s and s.strip()]
        if not slugs:
            return jsonify({'success': False, 'error': 'No slugs provided'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded. Open a project first.'}), 400
        mexcli_path = str(MEXCLI_PATH)
        if not Path(mexcli_path).exists():
            return jsonify({'success': False, 'error': 'MexCLI not found'}), 500

        # Stream progress: the per-fighter prepare loop is the slow part and the
        # UI otherwise sits at 0/N the whole time (looks frozen). Events go over
        # SocketIO as 'custom_char_install_progress'; the request still returns
        # the final result synchronously.
        socketio = get_socketio()
        total = len(slugs)

        def _emit(current, phase, name=None, message=None):
            try:
                socketio.emit('custom_char_install_progress', {
                    'current': current, 'total': total,
                    'phase': phase, 'name': name, 'message': message})
            except Exception:
                pass

        prepared, failed, warnings = [], [], []
        for i, slug in enumerate(slugs):
            _emit(i + 1, 'preparing', name=slug)
            pre = _prepare_fighter_for_batch(slug, project_path, mexcli_path)
            if not pre.get('ok'):
                failed.append({'slug': slug, 'error': pre.get('error')})
                continue
            if pre.get('temp_zip'):
                temp_zips.append(pre['temp_zip'])
            prepared.append(pre)
            warnings += [f"{slug}: {w}" for w in pre.get('warnings', [])]

        if not prepared:
            return jsonify({'success': False, 'error': 'No installable characters', 'failed': failed}), 400

        port_owner, dupes = _plan_batch_announcers(prepared)

        manifest = {'fighters': [p['manifest'] for p in prepared]}
        logger.info(f"=== BATCH CHARACTER INSTALL ({len(prepared)} fighters) ===")
        # The single add-fighters compile is one long step — tell the user so the
        # bar doesn't look stuck at N/N.
        _emit(total, 'compiling', message='Building project (this can take a minute)…')
        fd, manifest_path = tempfile.mkstemp(suffix='.json', prefix='nucleus_fighters_batch_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(manifest, f)
            with mexcli_lock:
                result = subprocess.run(
                    [mexcli_path, 'add-fighters', str(project_path), manifest_path],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT), **get_subprocess_args())
        finally:
            try:
                os.unlink(manifest_path)
            except OSError:
                pass

        if result.returncode != 0:
            err = result.stderr or result.stdout or 'Unknown error'
            logger.error(f"add-fighters batch failed: {err}")
            return jsonify({'success': False, 'error': f'Batch add failed: {err}'}), 500

        cli = mexcli.commands.parse_json(result.stdout)
        for fr in cli.get('fighters', []):
            for w in (fr.get('warnings') or []):
                warnings.append(f"{fr.get('name', '?')}: {w}")

        # Record the batch's new ports, then point same-clip fighters at them.
        from core import narrator
        results = cli.get('fighters', [])
        project_dir = Path(project_path).parent
        for h, i in port_owner.items():
            call = results[i].get('announcerCall') if i < len(results) else None
            if isinstance(call, int) and call >= 0:
                narrator.record_port(project_dir, h, call, MEXCLI_PATH)
        for i, owner in dupes:
            if i >= len(results) or owner >= len(results) or not results[i].get('success'):
                continue
            call = results[owner].get('announcerCall')
            if not isinstance(call, int) or call < 0:
                continue
            ref = results[i].get('internalId', results[i].get('name'))
            out = mexcli.commands.run_json(['set-fighter-announcer-id', project_path, ref, call])
            if out.get('success'):
                results[i]['announcerCall'] = call
            else:
                warnings.append(f"{results[i].get('name', '?')}: announcer name-call not set")

        for i, pre in enumerate(prepared):
            e = pre['manifest']
            if 'announcerWav' in e or 'announcerCallReuse' in e or pre.get('announcer_hash'):
                continue
            if i >= len(results) or not results[i].get('success'):
                continue
            call, how = _apply_bonus_call(project_path, results[i].get('internalId', results[i].get('name')))
            if call is not None:
                results[i]['announcerCall'] = call
            elif how == 'failed':
                warnings.append(f"{results[i].get('name', '?')}: announcer name-call not set")

        import time
        time.sleep(0.15)
        reload_mex_manager()

        added = cli.get('totalAdded', 0)
        logger.info(f"[OK] Batch-installed {added} custom character(s)")
        _emit(total, 'done')
        return jsonify({
            'success': True,
            'message': f"Added {added} character(s) to project",
            'totalAdded': added,
            'totalFailed': cli.get('totalFailed', 0) + len(failed),
            'fighters': cli.get('fighters', []),
            'failed': failed,
            'warnings': warnings,
        })
    except Exception as e:
        logger.error(f"Batch install error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        for tz in temp_zips:
            try:
                if tz and tz.exists():
                    tz.unlink()
            except OSError:
                pass


@custom_characters_bp.route('/api/mex/custom-characters/install-skin', methods=['POST'])
def install_custom_character_skin():
    """Install ONE of a custom character's added skins into the open project.

    Custom-char skins are no longer force-installed with the fighter; they
    surface in the costume "Available to Import" list and the user imports
    them per-skin through this endpoint (MexCLI import-costume), exactly like
    a vanilla character's vault skins.
    """
    temp_zip = None
    try:
        data = request.json or {}
        slug = (data.get('slug') or '').strip()
        skin_id = (data.get('skinId') or '').strip()
        fighter_name = (data.get('fighterName') or '').strip()
        if not slug or not skin_id or not fighter_name:
            return jsonify({'success': False, 'error': 'Missing slug, skinId, or fighterName'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded.'}), 400

        mexcli_path = str(MEXCLI_PATH)
        metadata = _read_metadata()
        entry = _find_entry(metadata, slug) or {}
        skin = next((s for s in entry.get('added_skins', []) if s.get('id') == skin_id), None)
        if not skin:
            return jsonify({'success': False, 'error': f'Skin "{skin_id}" not found for "{slug}"'}), 404

        skin_zip = CUSTOM_CHARACTERS_PATH / slug / 'skins' / skin['filename']
        if not skin_zip.exists():
            return jsonify({'success': False, 'error': 'Skin file missing'}), 404

        install_zip = skin_zip
        active_path = _active_csp_path_for_skin(f'custom_characters/{slug}/skins', skin)
        if active_path:
            temp_zip = Path(tempfile.mktemp(suffix='.zip', prefix='nucleus_skin_'))
            temp_zip.write_bytes(_zip_bytes_with_csp(skin_zip, active_path.read_bytes()))
            install_zip = temp_zip

        cmd = [mexcli_path, 'import-costume', str(project_path), fighter_name, str(install_zip)]
        with mexcli_lock:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(PROJECT_ROOT), **get_subprocess_args()
            )
        if result.returncode != 0:
            err = result.stderr or result.stdout or 'unknown error'
            logger.warning(f"import-costume failed for skin '{skin_id}' of '{slug}': {err}")
            return jsonify({'success': False, 'error': f'Failed to import skin: {err}'}), 500

        reload_mex_manager()
        return jsonify({
            'success': True,
            'message': f"Imported skin into {fighter_name}",
            'name': skin.get('color') or skin.get('name') or 'Custom Skin',
        })
    except Exception as e:
        logger.error(f"Install custom skin error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if temp_zip is not None and temp_zip.exists():
            temp_zip.unlink()


@custom_characters_bp.route('/api/mex/custom-characters/remove-from-project', methods=['POST'])
def remove_custom_character_from_project():
    """Remove a custom character from the currently open project."""
    try:
        data = request.json or {}
        fighter_name = data.get('name', '').strip()
        if not fighter_name:
            return jsonify({'success': False, 'error': 'Missing name parameter'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded.'}), 400

        mexcli_path = str(MEXCLI_PATH)
        cmd = [mexcli_path, 'remove-fighter', str(project_path), fighter_name]
        logger.info(f"Removing fighter '{fighter_name}': {' '.join(cmd)}")

        from projects.lload import export as lload_export
        with mexcli_lock:
            # remove-fighter can delete Captain Falcon's icon instead of the
            # removed fighter's (see lload_export.repair_after_remove), so the
            # icons are restored from this snapshot afterwards.
            try:
                before = lload_export.get_layout(project_path)
            except Exception as e:
                before = None
                logger.warning(f"CSS layout snapshot before removal failed: {e}")
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(PROJECT_ROOT), **get_subprocess_args()
            )
            if result.returncode == 0 and before is not None:
                try:
                    lload_export.repair_after_remove(project_path, before, fighter_name)
                except Exception as e:
                    logger.warning(f"CSS layout repair after removal failed: {e}")
            if result.returncode == 0:
                try:
                    from projects.lload import groups as lload_groups
                    lload_groups.forget_fighter(project_path, fighter_name)
                except Exception as e:
                    logger.warning(f"L-load groups not updated after removal: {e}")

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or 'Unknown error'
            return jsonify({'success': False, 'error': f'Failed to remove fighter: {error_msg}'}), 500

        import time
        time.sleep(0.15)
        reload_mex_manager()

        logger.info(f"[OK] Removed fighter '{fighter_name}' from project")
        return jsonify({'success': True, 'message': f'Removed {fighter_name}'})
    except Exception as e:
        logger.error(f"Remove fighter error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
