"""
.ssbm bundles, build side: export, install and play.

Exports the built ISO as a bundle (xdelta patch + texture pack) into the vault,
installs a stored bundle (builds the ISO, loads its textures into Slippi
Dolphin) and plays one in the user's real Slippi. Each runs as a job
(core/jobs.py: `bundle_export`, `bundle_install`, `bundle_play`) that owns its
temp folder and half-written output, so a failure or a death mid-run leaves
neither behind. These routes register on `bundles_bp` from
vault/routes/bundles.py (the vault's bundle list), so URLs and endpoint names
are unchanged; bundle storage and index are vault/catalog/bundles.py.
"""

import os
import re
import json
import time
import uuid
import shutil
import zipfile
import tempfile
import subprocess
import configparser
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from flask import request, jsonify

import file_retry
from core import jobs
from core.child_procs import own
from core.config import OUTPUT_PATH, get_subprocess_args
from core.safe_archive import safe_extract_zip
from shared.ingame.boot import parse_dolphin_ini_iso_path, slippi_user_dir
from projects.install.xdelta import clean_job_files, require_xdelta_exe
from vault.catalog.bundles import BUNDLE_PATH, _append_bundle, _bundle_build_name
from vault.routes.bundles import bundles_bp

logger = logging.getLogger(__name__)

EXPORT_KIND = 'bundle_export'
INSTALL_KIND = 'bundle_install'
PLAY_KIND = 'bundle_play'
jobs.register_kind(EXPORT_KIND, label='Bundle export', cleanup=clean_job_files)
jobs.register_kind(INSTALL_KIND, label='Bundle install', cleanup=clean_job_files)
jobs.register_kind(PLAY_KIND, label='Bundle play', cleanup=clean_job_files)


def _bundle_play_artifacts(bundle_id, bundle_path, iso_folder, mod_name):
    digest = hashlib.sha256(Path(bundle_path).read_bytes()).hexdigest()
    safe_name = re.sub(r'[^\w\-_]', '_', mod_name)
    stem = f'{safe_name}-{bundle_id}-{digest[:12]}'
    iso_path = Path(iso_folder) / f'{stem}.iso'
    marker_path = Path(iso_folder) / f'{stem}.complete.json'
    return digest, iso_path, marker_path


def _bundle_cache_is_complete(marker_path, iso_path, bundle_id, digest):
    if not iso_path.is_file() or iso_path.stat().st_size == 0 or not marker_path.is_file():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return marker == {'bundle_id': bundle_id, 'sha256': digest}


def _publish_bundle_artifact(staging_path, iso_path, marker_path, bundle_id, digest):
    if not staging_path.is_file() or staging_path.stat().st_size == 0:
        raise RuntimeError('Bundle build produced no ISO file')
    file_retry.replace(staging_path, iso_path)
    marker_tmp = marker_path.with_name(f'{marker_path.name}.{uuid.uuid4().hex}.part')
    marker_tmp.write_text(
        json.dumps({'bundle_id': bundle_id, 'sha256': digest}), encoding='utf-8')
    file_retry.replace(marker_tmp, marker_path)


def set_dolphin_texture_settings(slippi_path, dump_textures=False, hires_textures=True):
    """Set Dolphin texture settings in GFX.ini. Raises when it cannot be written,
    so a bundle is never reported ready (or launched) with its textures off."""
    gfx_ini = slippi_user_dir(slippi_path) / 'Config' / 'GFX.ini'
    try:
        config = configparser.ConfigParser()
        if gfx_ini.exists():
            config.read(gfx_ini, encoding='utf-8')

        if 'Settings' not in config:
            config['Settings'] = {}

        config['Settings']['DumpTextures'] = 'True' if dump_textures else 'False'
        config['Settings']['HiresTextures'] = 'True' if hires_textures else 'False'

        gfx_ini.parent.mkdir(parents=True, exist_ok=True)
        with open(gfx_ini, 'w') as f:
            config.write(f)
    except Exception as e:
        logger.error(f"Failed to update GFX.ini: {e}")
        raise RuntimeError(f"Could not turn on HD textures in Dolphin ({gfx_ini}): {e}") from e

    logger.info(f"Updated GFX.ini: DumpTextures={dump_textures}, HiresTextures={hires_textures}")


def run_bundle_export(job, name, description, build_name, vanilla_iso_path, exported_iso_path, texture_pack_path, image_path=None):
    """The `bundle_export` job: package the exported ISO's patch and texture pack
    as storage/bundles/<bundleId>.ssbm and index it. Its temp folder and the
    half-written bundle are the job's, so however it ends they are removed.
    Returns { bundle_id, filename (the download name), size, size_mb, texture_count }."""
    bundle_id = job.params['bundleId']
    job.progress(0, 'Creating xdelta patch...')

    # Create temp directory for bundle contents
    temp_dir = Path(tempfile.mkdtemp(prefix='bundle_'))
    job.own('temp', str(temp_dir))
    bundle_dir = temp_dir / 'bundle'
    bundle_dir.mkdir()

    # 1. Create xdelta patch
    patch_path = bundle_dir / 'patch.xdelta'

    xdelta_exe = require_xdelta_exe()

    cmd = [
        str(xdelta_exe),
        '-e',  # Encode (create patch)
        '-1',  # Fast compression
        '-s', str(vanilla_iso_path),
        str(exported_iso_path),
        str(patch_path)
    ]

    logger.info(f"Creating xdelta patch for bundle: {' '.join(cmd)}")

    process = own(subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **get_subprocess_args()
    ))

    # Monitor progress
    last_size_mb = 0
    while process.poll() is None:
        time.sleep(1)
        try:
            if patch_path.exists():
                current_size_mb = patch_path.stat().st_size / (1024 * 1024)
                if int(current_size_mb) != int(last_size_mb):
                    job.progress(0.3, f'Creating patch... ({current_size_mb:.1f} MB)')
                    last_size_mb = current_size_mb
        except Exception:
            pass

    stdout, stderr = process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode() if stderr else stdout.decode() if stdout else 'Unknown xdelta error'
        logger.error(f"xdelta3 failed: {error_msg}")
        raise RuntimeError(f'Failed to create patch: {error_msg}')

    job.progress(0.5, 'Copying textures...')

    # 2. Copy textures
    textures_dir = bundle_dir / 'textures'
    texture_count = 0

    if texture_pack_path and Path(texture_pack_path).exists():
        texture_src = Path(texture_pack_path)
        textures_dir.mkdir()

        # Copy all PNG files
        png_files = list(texture_src.glob('*.png'))
        total_textures = len(png_files)

        for i, png_file in enumerate(png_files):
            shutil.copy2(png_file, textures_dir / png_file.name)
            texture_count += 1

            if i % 20 == 0:
                job.progress(0.5 + (i / max(total_textures, 1)) * 0.3,
                             f'Copying textures... ({i}/{total_textures})')

    job.progress(0.85, 'Creating manifest...')

    # 3. Copy image if provided (include in bundle)
    has_image = bool(image_path and Path(image_path).exists())
    if has_image:
        shutil.copy(image_path, bundle_dir / 'image.png')

    # 4. Create manifest.json
    manifest = {
        'version': '1.0',
        'name': name,
        'description': description,
        'build_name': build_name,
        'created': datetime.now().isoformat(),
        'texture_count': texture_count,
        'has_image': has_image
    }

    with open(bundle_dir / 'manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)

    job.progress(0.9, 'Packaging bundle...')

    # 5. Write the .ssbm ZIP beside its final name, then move it into place
    bundle_filename = f"{bundle_id}.ssbm"
    bundle_path = BUNDLE_PATH / bundle_filename
    partial = BUNDLE_PATH / f"{bundle_filename}.part"
    job.own('partial', str(partial))

    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in bundle_dir.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(bundle_dir)
                zf.write(file_path, arcname)

    file_retry.replace(partial, bundle_path)
    job.release('partial')

    bundle_size = bundle_path.stat().st_size
    bundle_size_mb = bundle_size / (1024 * 1024)

    # 6. Also save image separately for display in UI (the temp upload is the job's)
    if has_image:
        shutil.copy(image_path, BUNDLE_PATH / f"{bundle_id}.png")

    # 7. Save to metadata (locked load-append-save; shared metadata.json)
    _append_bundle({
        'id': bundle_id,
        'name': name,
        'description': description,
        'build_name': build_name,
        'filename': bundle_filename,
        'size': bundle_size,
        'size_mb': round(bundle_size_mb, 2),
        'texture_count': texture_count,
        'created': datetime.now().isoformat()
    })

    # Create user-friendly filename for download
    safe_name = re.sub(r'[^\w\-_]', '_', name)
    download_filename = f"{safe_name}.ssbm"

    logger.info(f"[OK] Created bundle: {bundle_filename} ({bundle_size_mb:.2f} MB)")
    logger.info(f"  Bundle saved to: {bundle_path}")
    logger.info(f"  Bundle ID: {bundle_id}")

    return {
        'bundle_id': bundle_id,
        'filename': download_filename,
        'size': bundle_size,
        'size_mb': round(bundle_size_mb, 2),
        'texture_count': texture_count
    }


def run_bundle_install(job, bundle_path, slippi_path, vanilla_iso_path):
    """The `bundle_install` job: build the bundle's ISO into the user's Dolphin
    ISO folder, load its textures and turn HD textures on.

    The ISO is decoded into `<name>.<job id>.part.iso` beside the destination and
    replaces `<name>.iso` only after every step has worked, so a failed install
    leaves an earlier copy untouched. The partial ISO and the extraction folder
    are the job's, so however it ends they are removed.
    Returns { name, iso_path, texture_count }."""
    job.progress(0, 'Extracting bundle...')

    # 1. Extract ZIP to temp
    temp_dir = Path(tempfile.mkdtemp(prefix='bundle_import_'))
    job.own('temp', str(temp_dir))

    with zipfile.ZipFile(bundle_path, 'r') as zf:
        safe_extract_zip(zf, temp_dir)

    # 2. Validate manifest.json and patch.xdelta exist
    manifest_path = temp_dir / 'manifest.json'
    patch_path = temp_dir / 'patch.xdelta'

    if not manifest_path.exists():
        raise RuntimeError('Invalid bundle: manifest.json not found')

    if not patch_path.exists():
        raise RuntimeError('Invalid bundle: patch.xdelta not found')

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    build_name = _bundle_build_name(manifest)
    mod_name = manifest.get('name', 'Imported Mod')

    job.progress(0.1, 'Building ISO from patch...')

    # 3. Run xdelta3 to build ISO
    dolphin_ini = str(slippi_user_dir(slippi_path) / 'Config' / 'Dolphin.ini')
    iso_folder = parse_dolphin_ini_iso_path(dolphin_ini)

    if not iso_folder:
        # Fallback: use a default location
        iso_folder = str(slippi_user_dir(slippi_path) / 'Games')
        os.makedirs(iso_folder, exist_ok=True)

    # Output ISO path, and this install's own file beside it
    safe_name = re.sub(r'[^\w\-_]', '_', mod_name)
    output_iso_path = Path(iso_folder) / f"{safe_name}.iso"
    partial = Path(iso_folder) / f"{safe_name}.{job.id}.part.iso"
    job.own('partial', str(partial))

    xdelta_exe = require_xdelta_exe()

    cmd = [
        str(xdelta_exe),
        '-d',  # Decode/decompress
        '-s', str(vanilla_iso_path),
        str(patch_path),
        str(partial)
    ]

    logger.info(f"Building ISO from bundle: {' '.join(cmd)}")

    process = own(subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **get_subprocess_args()
    ))

    # Monitor progress by checking output file size
    expected_size = Path(vanilla_iso_path).stat().st_size
    last_progress = 0

    while process.poll() is None:
        time.sleep(0.3)
        try:
            if partial.exists():
                current_size = partial.stat().st_size
                progress = min(int((current_size / expected_size) * 60) + 10, 69)
                if progress != last_progress:
                    job.progress(progress / 100, f'Building ISO... {progress - 10}%')
                    last_progress = progress
        except Exception:
            pass

    stdout, stderr = process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode() if stderr else stdout.decode() if stdout else 'Unknown xdelta error'
        logger.error(f"xdelta3 failed: {error_msg}")
        raise RuntimeError(f'Failed to build ISO: {error_msg}')

    job.progress(0.7, 'Copying textures...')

    # 4. Copy textures to Load folder
    textures_src = temp_dir / 'textures'
    texture_count = 0

    if textures_src.exists():
        load_path = slippi_user_dir(slippi_path) / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus' / build_name
        load_path.mkdir(parents=True, exist_ok=True)

        png_files = list(textures_src.glob('*.png'))
        total_textures = len(png_files)

        for i, png_file in enumerate(png_files):
            shutil.copy2(png_file, load_path / png_file.name)
            texture_count += 1

            if i % 20 == 0:
                job.progress(0.7 + (i / max(total_textures, 1)) * 0.2,
                             f'Copying textures... ({i}/{total_textures})')

    job.progress(0.95, 'Enabling hi-res textures...')

    # 5. Enable HiresTextures=True in GFX.ini (raises if it can't)
    set_dolphin_texture_settings(slippi_path, dump_textures=False, hires_textures=True)

    # 6. Everything worked: the new ISO replaces any earlier copy
    file_retry.replace(partial, output_iso_path)
    job.release('partial')

    logger.info(f"[OK] Imported bundle: {mod_name}")
    logger.info(f"  ISO: {output_iso_path}")
    logger.info(f"  Textures: {texture_count}")

    return {
        'name': mod_name,
        'iso_path': str(output_iso_path),
        'texture_count': texture_count
    }


def run_bundle_play(job, bundle_id, slippi_path, vanilla_iso_path):
    """The `bundle_play` job: build the ISO into the user's Dolphin ISO folder if
    it's missing, (re)load this bundle's texture pack, and boot it in the user's
    REAL Slippi Dolphin. Returns { iso_path, texture_count }."""
    from shared.ingame.boot import launch_real, iso_dir_from_slippi

    bundle_path = BUNDLE_PATH / f"{bundle_id}.ssbm"
    if not bundle_path.exists():
        raise RuntimeError('Bundle file not found')

    job.progress(0.05, 'Reading bundle...')
    with zipfile.ZipFile(bundle_path, 'r') as zf:
        names = zf.namelist()
        if 'manifest.json' not in names:
            raise RuntimeError('Invalid bundle: manifest.json missing')
        manifest = json.loads(zf.read('manifest.json'))
        build_name = _bundle_build_name(manifest)
        mod_name = manifest.get('name', 'Imported Mod')

        iso_folder = iso_dir_from_slippi(slippi_path)
        digest, iso_path, marker_path = _bundle_play_artifacts(
            bundle_id, bundle_path, iso_folder, mod_name)

        # A cache hit belongs to this exact bundle generation, not merely
        # another file with the same display name.
        if _bundle_cache_is_complete(marker_path, iso_path, bundle_id, digest):
            job.progress(0.65, 'ISO already built - skipping build')
        else:
            if not vanilla_iso_path:
                raise RuntimeError('ISO not built yet and no vanilla ISO path is set (Settings).')
            if 'patch.xdelta' not in names:
                raise RuntimeError('Invalid bundle: patch.xdelta missing')
            job.progress(0.1, 'Building ISO from patch...')
            # Both are the job's: its cleanup removes them however it ends.
            temp_dir = Path(tempfile.mkdtemp(prefix='bundle_play_'))
            job.own('temp', str(temp_dir))
            zf.extract('patch.xdelta', temp_dir)
            staging_path = iso_path.with_name(
                f'{iso_path.stem}.{uuid.uuid4().hex}.part.iso')
            job.own('staging', str(staging_path))
            cmd = [str(require_xdelta_exe()), '-d', '-f', '-s', str(vanilla_iso_path),
                   str(temp_dir / 'patch.xdelta'), str(staging_path)]
            proc = own(subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **get_subprocess_args()))
            expected = Path(vanilla_iso_path).stat().st_size
            last = 0
            while proc.poll() is None:
                time.sleep(0.3)
                try:
                    if staging_path.exists():
                        p = min(int(staging_path.stat().st_size / expected * 55) + 10, 65)
                        if p != last:
                            job.progress(p / 100, f'Building ISO... {p - 10}%'); last = p
                except Exception:
                    pass
            out, errout = proc.communicate()
            if proc.returncode != 0:
                msg = (errout or out or b'').decode(errors='replace') or 'xdelta error'
                raise RuntimeError(f'Failed to build ISO: {msg}')
            _publish_bundle_artifact(
                staging_path, iso_path, marker_path, bundle_id, digest)
            job.release('staging')

        # 2. Texture pack: clear ours, then load THIS bundle's portraits.
        job.progress(0.75, 'Loading texture pack...')
        load_root = slippi_user_dir(slippi_path) / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus'
        if load_root.exists():
            for item in load_root.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    try:
                        item.unlink()
                    except OSError:
                        pass
        dest = load_root / build_name
        dest.mkdir(parents=True, exist_ok=True)
        tex_members = [n for n in names if n.startswith('textures/') and n.lower().endswith('.png')]
        for n in tex_members:
            with zf.open(n) as src, open(dest / Path(n).name, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        set_dolphin_texture_settings(slippi_path, dump_textures=False, hires_textures=True)

    # 3. Launch the user's real Slippi Dolphin on the ISO.
    job.progress(0.95, 'Launching Slippi...')
    launch_real(slippi_path, iso_path)
    logger.info(f"[PLAY] bundle '{mod_name}': launched {iso_path} ({len(tex_members)} textures)")
    return {'iso_path': str(iso_path), 'texture_count': len(tex_members)}


@bundles_bp.route('/api/mex/bundle/play/<bundle_id>', methods=['POST'])
def play_bundle(bundle_id):
    """Start a `bundle_play` job: build (if missing), load the texture pack and
    launch a bundle in the real Slippi.

    Body: { slippiPath, vanillaIsoPath }. Returns { success, job_id }.
    """
    try:
        data = request.json or {}
        slippi_path = data.get('slippiPath')
        vanilla_iso_path = data.get('vanillaIsoPath')
        if not slippi_path:
            return jsonify({'success': False, 'error': 'slippiPath is required'}), 400
        if not (BUNDLE_PATH / f"{bundle_id}.ssbm").exists():
            return jsonify({'success': False, 'error': 'Bundle not found'}), 404
        job_id = jobs.start(
            PLAY_KIND,
            lambda job: run_bundle_play(job, bundle_id, slippi_path, vanilla_iso_path),
            label='Bundle play', params={'bundleId': bundle_id})
        return jsonify({'success': True, 'job_id': job_id})
    except Exception as e:
        logger.error(f"Play bundle start error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@bundles_bp.route('/api/mex/bundle/export', methods=['POST'])
def export_bundle():
    """Start a `bundle_export` job that saves a .ssbm bundle (xdelta patch +
    texture pack) to the Vault. Returns { success, job_id, bundle_id }."""
    try:
        # Handle both JSON and FormData
        if request.content_type and 'multipart/form-data' in request.content_type:
            name = request.form.get('name', 'My Mod Pack')
            description = request.form.get('description', '')
            build_name = request.form.get('buildName', 'mod-pack')
            vanilla_iso_path = request.form.get('vanillaIsoPath')
            exported_iso_path = request.form.get('exportedIsoPath')
            texture_pack_path = request.form.get('texturePackPath') or None
            image_file = request.files.get('image')
        else:
            data = request.json or {}
            name = data.get('name', 'My Mod Pack')
            description = data.get('description', '')
            build_name = data.get('buildName', 'mod-pack')
            vanilla_iso_path = data.get('vanillaIsoPath')
            exported_iso_path = data.get('exportedIsoPath')
            texture_pack_path = data.get('texturePackPath') or None
            image_file = None

        if not vanilla_iso_path:
            return jsonify({
                'success': False,
                'error': 'No vanilla ISO path provided'
            }), 400

        if not exported_iso_path:
            return jsonify({
                'success': False,
                'error': 'No exported ISO path provided'
            }), 400

        vanilla_iso = Path(vanilla_iso_path)
        exported_iso = Path(exported_iso_path)

        if not vanilla_iso.exists():
            return jsonify({
                'success': False,
                'error': f'Vanilla ISO not found: {vanilla_iso_path}'
            }), 404

        if not exported_iso.exists():
            return jsonify({
                'success': False,
                'error': f'Exported ISO not found: {exported_iso_path}'
            }), 404

        # The new bundle's id in the Vault
        bundle_id = str(uuid.uuid4())[:8]

        # Save image to temp if provided; the job owns it from its first record
        image_path = None
        owned = {}
        if image_file and image_file.filename:
            image_path = OUTPUT_PATH / f"temp_bundle_image_{bundle_id}.png"
            image_file.save(str(image_path))
            owned['image'] = str(image_path)

        logger.info(f"Exporting bundle: {name}")
        logger.info(f"  Vanilla ISO: {vanilla_iso_path}")
        logger.info(f"  Exported ISO: {exported_iso_path}")
        logger.info(f"  Texture pack: {texture_pack_path}")
        logger.info(f"  Image: {image_path}")

        job_id = jobs.start(
            EXPORT_KIND,
            lambda job: run_bundle_export(job, name, description, build_name, vanilla_iso_path,
                                          exported_iso_path, texture_pack_path,
                                          str(image_path) if image_path else None),
            label='Bundle export', params={'bundleId': bundle_id, 'name': name}, owned=owned)

        return jsonify({
            'success': True,
            'job_id': job_id,
            'bundle_id': bundle_id
        })
    except Exception as e:
        logger.error(f"Export bundle error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bundles_bp.route('/api/mex/bundle/install/<bundle_id>', methods=['POST'])
def install_bundle_from_storage(bundle_id):
    """Start a `bundle_install` job for a stored bundle (builds the ISO + loads
    its textures). Returns { success, job_id }."""
    try:
        data = request.json or {}
        slippi_path = data.get('slippiPath')
        vanilla_iso_path = data.get('vanillaIsoPath')

        if not slippi_path:
            return jsonify({
                'success': False,
                'error': 'Slippi Dolphin path is required'
            }), 400

        if not vanilla_iso_path:
            return jsonify({
                'success': False,
                'error': 'Vanilla ISO path is required'
            }), 400

        if not Path(vanilla_iso_path).exists():
            return jsonify({
                'success': False,
                'error': f'Vanilla ISO not found: {vanilla_iso_path}'
            }), 404

        # Find bundle file
        bundle_path = BUNDLE_PATH / f"{bundle_id}.ssbm"

        if not bundle_path.exists():
            return jsonify({
                'success': False,
                'error': 'Bundle file not found'
            }), 404

        job_id = jobs.start(
            INSTALL_KIND,
            lambda job: run_bundle_install(job, bundle_path, slippi_path, vanilla_iso_path),
            label='Bundle install', params={'bundleId': bundle_id})
        logger.info(f"[BUNDLE INSTALL] Starting install from storage: {bundle_id}, job {job_id}")

        return jsonify({
            'success': True,
            'job_id': job_id
        })
    except Exception as e:
        logger.error(f"Install bundle error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
