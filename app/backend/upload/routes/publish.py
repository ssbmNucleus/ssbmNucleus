"""Publish a vault package to ssbmnucleus.net (the Upload page's Publish
button).

Mirrors the website's browser-side intake (meleeWebsite frontend
services/clientUpload.js) server-side, because the app already has every vault
file on disk and server-to-server calls avoid CORS entirely:

  1. resolve the selected vault items to files, build the storage plan
     (nested archives reconstructed exactly like the site's uploader:
     costume/stage zips stay downloadable as themselves inside files.zip)
  2. api_create_pending_post RPC   (Supabase, the user's access token — the
     ssbmnucleus.net login's, or the backend's Discord session's when there
     is no site login: both are Supabase Auth users of the same project)
  3. POST https://ssbmnucleus.net/api/intake/presign  (Pages Function)
  4. PUT every object straight to R2
  5. api_finalize_pending_post RPC (file rows / screenshots / manifest)

All new posts land in the website's approval queue (status=pending).
`dryRun: true` stops after step 1 and returns the plan for inspection.
"""

import io
import json
import logging
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

from core.config import STORAGE_PATH, SUPABASE_URL, SUPABASE_ANON_KEY
from core.metadata import load_metadata

logger = logging.getLogger(__name__)

publish_bp = Blueprint('publish', __name__)

# SUPABASE_URL / SUPABASE_ANON_KEY (core.config) are the same public project the
# viewer's account service signs into (the anon key ships in the
# ssbmnucleus.net bundle; RLS protects the data).
WEBSITE_URL = 'https://ssbmnucleus.net'

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
CONTENT_TYPES = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.zip': 'application/zip',
}

# The website's file rows carry a COLOR WORD (rendered as a colored badge —
# PostPage getColorForBadge), not a display name. Map the vault costume_code
# slot suffix to the site's vocabulary; anything unknown renders as a dark
# unnamed badge, so fall back to Default.
SLOT_COLOR_WORDS = {
    'nr': 'Default', 're': 'Red', 'bu': 'Blue', 'gr': 'Green',
    'ye': 'Yellow', 'bk': 'Black', 'wh': 'White', 'pi': 'Pink',
    'or': 'Orange', 'la': 'Lavender', 'aq': 'Aqua/Light Blue', 'gy': 'Grey',
}


def _slot_color(costume_code):
    m = re.match(r'^pl\w{2}(\w{2})$', str(costume_code or ''), re.IGNORECASE)
    return SLOT_COLOR_WORDS.get(m.group(1).lower(), 'Default') if m else 'Default'


def _ext(name):
    m = re.search(r'\.[^./\\]+$', name or '')
    return m.group(0).lower() if m else ''


def _content_type(name):
    return CONTENT_TYPES.get(_ext(name), 'application/octet-stream')


def _safe_name(value, fallback='mod'):
    """Filesystem/R2-safe display name: keep letters/digits/space/()-_ then
    collapse; the presign function rejects control chars, .., backslashes."""
    cleaned = re.sub(r'[^A-Za-z0-9 ()_\-.]+', '', str(value or '')).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip('. ')
    return cleaned or fallback


def _unique(name, used):
    base, ext = name, ''
    m = re.match(r'^(.*?)(\.[^.]*)?$', name)
    if m:
        base, ext = m.group(1), m.group(2) or ''
    out = name
    i = 2
    while out.lower() in used:
        out = f'{base}_{i}{ext}'
        i += 1
    used.add(out.lower())
    return out


def _dat_symbol(data):
    """First root symbol of a DAT (the site stores it on file rows)."""
    try:
        import struct
        file_size, data_size, reloc_count, root_count, ref_count = struct.unpack_from('>IIIII', data, 0)
        reloc_start = 0x20 + data_size
        roots_start = reloc_start + reloc_count * 4
        strings_start = roots_start + (root_count + ref_count) * 8
        if root_count < 1:
            return None
        _, str_off = struct.unpack_from('>II', data, roots_start)
        end = data.index(b'\0', strings_start + str_off)
        return data[strings_start + str_off:end].decode('ascii', 'replace')
    except Exception:
        return None


def _make_thumb(data):
    """640px-max webp q82 thumbnail (site convention <stem>__thumb.webp)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode not in ('RGB', 'RGBA'):
            im = im.convert('RGBA')
        scale = min(1.0, 640 / max(im.width, im.height))
        if scale < 1.0:
            im = im.resize((max(1, round(im.width * scale)),
                            max(1, round(im.height * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, 'WEBP', quality=82, method=6)
        return buf.getvalue()
    except Exception:
        return None


class PackageBuilder:
    """Accumulates the storage plan + file rows + zip_structure."""

    def __init__(self, folder_placeholder='__FOLDER__'):
        self.plan = []           # {relPath, data, contentType}
        self.file_rows = []
        self.nested = []         # zip_structure nested_archives
        self.raw_archives = {}   # archive_path -> original zip bytes
        self.used_names = set()
        self.used_prefixes = set()
        self.folder = folder_placeholder

    def add(self, rel_path, data):
        if any(p['relPath'] == rel_path for p in self.plan):
            return rel_path
        self.plan.append({'relPath': rel_path, 'data': data,
                          'contentType': _content_type(rel_path)})
        return rel_path

    def url(self, rel_path):
        return f'/uploads/{self.folder}/{rel_path}'

    def add_vault_zip(self, zip_path, display_name, *, row=None, preview=None, item_key=None):
        """A vault zip becomes a nested archive: its entries join the plan
        under a prefix, files.zip gets the ORIGINAL zip bytes back, and the
        DAT inside becomes a website file row (character/stage)."""
        prefix = _unique(_safe_name(display_name), self.used_prefixes)
        raw = Path(zip_path).read_bytes()
        inner_names = []
        dat_entry = None
        csp_entry = None
        stock_entry = None
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace('\\', '/').split('/')[-1]
                data = zf.read(info)
                rel = f'{prefix}/{name}'
                self.add(rel, data)
                inner_names.append(name)
                low = name.lower()
                if low.endswith(('.dat', '.usd')) and dat_entry is None:
                    dat_entry = (rel, data)
                elif low in ('csp.png', 'csp'):
                    csp_entry = (rel, data)
                elif low in ('stc.png', 'stock.png', 'stc', 'stock'):
                    stock_entry = (rel, data)

        self.nested.append({
            'archive_name': f'{prefix}.zip',
            'archive_path': f'{prefix}.zip',
            'prefix': prefix,
            'files': inner_names,
        })
        self.raw_archives[f'{prefix}.zip'] = raw

        if row is not None and dat_entry is not None:
            character = row.get('character')
            csp_url = None
            stock_url = None
            if csp_entry is not None:
                name = _unique(_safe_name(f'{character or prefix}_{prefix}_csp') + '.png', self.used_names)
                self.add(name, csp_entry[1])
                csp_url = self.url(name)
            if stock_entry is not None:
                name = _unique(_safe_name(f'{character or prefix}_{prefix}_stock') + '.png', self.used_names)
                self.add(name, stock_entry[1])
                stock_url = self.url(name)
            preview_url = None
            if preview is not None and Path(preview).exists():
                pname = _unique(_safe_name(f'{prefix}_preview') + _ext(str(preview)), self.used_names)
                self.add(pname, Path(preview).read_bytes())
                preview_url = self.url(pname)
            self.file_rows.append({
                'filename': dat_entry[0],
                'file_type': row['file_type'],
                'character': character,
                'color': row.get('color'),
                'symbol': _dat_symbol(dat_entry[1]),
                'slippi_safe': row.get('slippi_safe'),
                'csp_url': csp_url,
                'stock_url': stock_url,
                'file_url': None,
                'preview_url': preview_url,
                # dry-run only: lets the Upload page's post preview map rows
                # back to catalog items; stripped before the finalize RPC
                'item_key': item_key,
            })
        return prefix

    def add_plain_file(self, path, name=None):
        p = Path(path)
        rel = _unique(_safe_name(name or p.name, p.name), self.used_names)
        self.add(rel, p.read_bytes())
        return rel

    def build_files_zip(self):
        """files.zip: nested archives as their original bytes, everything
        else (not claimed by a prefix) as plain entries."""
        claimed = set()
        for arch in self.nested:
            for p in self.plan:
                if p['relPath'].startswith(arch['prefix'] + '/'):
                    claimed.add(p['relPath'])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for arch in self.nested:
                zf.writestr(arch['archive_path'], self.raw_archives[arch['archive_path']])
            for p in self.plan:
                if p['relPath'] not in claimed:
                    zf.writestr(p['relPath'], p['data'])
        return buf.getvalue()


def _resolve_items(builder, items, metadata):
    """Turn the Upload page's selected vault items into plan entries + rows."""
    chars = metadata.get('characters', {})
    for item in items:
        kind = item.get('kind')
        key = str(item.get('key') or '')
        parts = key.split(':')

        if kind == 'costume' and len(parts) >= 3:
            character, skin_id = parts[1], parts[2]
            skin = next((s for s in chars.get(character, {}).get('skins', [])
                         if s.get('id') == skin_id), None)
            if not skin:
                raise ValueError(f'Costume not found in vault: {key}')
            zip_path = STORAGE_PATH / character / (skin.get('filename') or f'{skin_id}.zip')
            if not zip_path.exists():
                raise ValueError(f'Costume archive missing: {zip_path.name}')
            display = skin.get('color') or skin.get('name') or skin_id
            builder.add_vault_zip(zip_path, display, row={
                'file_type': 'character_dat',
                'character': character,
                'color': _slot_color(skin.get('costume_code')),
                'slippi_safe': skin.get('slippi_safe'),
            }, item_key=key)

        elif kind == 'stage' and parts[0] == 'stage' and len(parts) >= 3:
            stage, variant_id = parts[1], parts[2]
            variants = metadata.get('stages', {}).get(stage, {}).get('variants', [])
            variant = next((v for v in variants if v.get('id') == variant_id), None)
            if not variant:
                raise ValueError(f'Stage skin not found in vault: {key}')
            zip_path = STORAGE_PATH / 'das' / stage / (variant.get('filename') or f'{variant_id}.zip')
            if not zip_path.exists():
                raise ValueError(f'Stage archive missing: {zip_path.name}')
            display = variant.get('name') or variant_id
            preview = None
            if variant.get('has_screenshot') and variant.get('screenshot_filename'):
                preview = STORAGE_PATH / 'das' / stage / variant['screenshot_filename']
            builder.add_vault_zip(zip_path, display, row={
                'file_type': 'stage_dat',
                'character': None,
                'color': None,
                'slippi_safe': variant.get('slippi_safe'),
            }, preview=preview, item_key=key)

        elif kind == 'effect' and len(parts) >= 4:
            character, effect_type, effect_id = parts[1], parts[2], parts[3]
            effects = chars.get(character, {}).get('extras', {}).get(effect_type, [])
            effect = next((e for e in effects if e.get('id') == effect_id), None)
            if not effect:
                raise ValueError(f'Effect not found in vault: {key}')
            extras_dir = STORAGE_PATH / character / 'extras'
            prefix = _unique(_safe_name(effect.get('name') or effect_id), builder.used_prefixes)
            added = False
            for field in ('model_file', 'screenshot'):
                fname = effect.get(field)
                if fname and (extras_dir / fname).exists():
                    builder.add(f'{prefix}/{fname}', (extras_dir / fname).read_bytes())
                    added = True
            if effect.get('modifications') is not None:
                builder.add(f'{prefix}/{prefix}.json', json.dumps(
                    {'character': character, 'effect_type': effect_type,
                     'modifications': effect.get('modifications')},
                    indent=2).encode('utf-8'))
                added = True
            if not added:
                raise ValueError(f'Effect has no files to publish: {key}')

        elif kind == 'character' and len(parts) >= 2:
            slug = parts[1]
            fighter = STORAGE_PATH / 'custom_characters' / slug / 'fighter.zip'
            if not fighter.exists():
                raise ValueError(f'Custom character archive missing: {slug}')
            builder.add_plain_file(fighter, f'{_safe_name(item.get("name") or slug)}.zip')

        elif kind == 'stage' and parts[0] == 'custom-stage' and len(parts) >= 2:
            slug = parts[1]
            stage_dir = STORAGE_PATH / 'custom_stages' / slug
            entry = next((s for s in metadata.get('custom_stages', [])
                          if s.get('slug') == slug), None) or {}
            prefix = _unique(_safe_name(item.get('name') or slug), builder.used_prefixes)
            added = False
            for fname in (entry.get('dat_files') or []):
                p = stage_dir / fname
                if p.exists():
                    builder.add(f'{prefix}/{fname}', p.read_bytes())
                    added = True
            banner = stage_dir / 'banner.png'
            if banner.exists():
                builder.add(f'{prefix}/banner.png', banner.read_bytes())
                added = True
            if not added:
                raise ValueError(f'Custom stage has no files to publish: {key}')

        elif kind == 'patch' and len(parts) >= 2:
            entry_id = parts[1]
            source = metadata.get('xdelta', []) if parts[0] == 'patch' else metadata.get('bundles', [])
            folder = 'xdelta' if parts[0] == 'patch' else 'bundles'
            entry = next((e for e in source if str(e.get('id')) == entry_id), None)
            if not entry or not entry.get('filename'):
                raise ValueError(f'Patch not found in vault: {key}')
            p = STORAGE_PATH / folder / entry['filename']
            if not p.exists():
                raise ValueError(f'Patch file missing: {entry["filename"]}')
            builder.add_plain_file(p)

        else:
            raise ValueError(f'Unsupported vault item: {key}')


def _rpc(name, token, payload):
    resp = requests.post(
        f'{SUPABASE_URL}/rest/v1/rpc/{name}',
        headers={
            'apikey': SUPABASE_ANON_KEY,
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        json=payload, timeout=60)
    if not resp.ok:
        detail = ''
        try:
            detail = resp.json().get('message') or resp.text[:300]
        except Exception:
            detail = resp.text[:300]
        raise RuntimeError(f'{name} failed ({resp.status_code}): {detail}')
    return resp.json()


def _discord_session_token():
    """The backend's Discord sign-in (shared/account), when someone is signed in."""
    try:
        from shared.account import discord
        return discord.session_token()
    except Exception:  # noqa: BLE001 — no sign-in, no fallback
        return None


@publish_bp.route('/api/mex/publish', methods=['POST'])
def publish_package():
    """Publish selected vault mods (+ local files + screenshots) as a pending
    post on ssbmnucleus.net. Multipart form:

      payload        JSON {accessToken, title, description, tags, items, dryRun}
      screenshot_<i> ordered screenshot blobs
      manual_<i>     local files added on the Upload page
    """
    try:
        payload = json.loads(request.form.get('payload') or '{}')
    except json.JSONDecodeError:
        return jsonify({'success': False, 'error': 'Invalid payload JSON'}), 400

    token = payload.get('accessToken') or _discord_session_token()
    title = (payload.get('title') or '').strip()
    description = (payload.get('description') or '').strip()
    tags = [str(t) for t in (payload.get('tags') or []) if str(t).strip()]
    items = payload.get('items') or []
    dry_run = bool(payload.get('dryRun'))

    if not title or not description:
        return jsonify({'success': False, 'error': 'Title and description are required'}), 400
    if not dry_run and not token:
        return jsonify({'success': False, 'error': 'Sign in to publish (Settings: ssbmnucleus.net account or Discord)'}), 401

    metadata = load_metadata() or {}
    builder = PackageBuilder()

    # 1) vault items + local files
    try:
        _resolve_items(builder, items, metadata)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    manual_files = sorted((k for k in request.files if k.startswith('manual_')),
                          key=lambda k: int(k.split('_')[1]))
    for k in manual_files:
        f = request.files[k]
        rel = _unique(_safe_name(f.filename, 'file'), builder.used_names)
        builder.add(rel, f.read())

    if not builder.plan:
        return jsonify({'success': False, 'error': 'Nothing selected to publish'}), 400

    # screenshots: screenshot_<i>.<ext>, first is the cover
    screenshot_rows = []
    shot_keys = sorted((k for k in request.files if k.startswith('screenshot_')),
                       key=lambda k: int(k.split('_')[1]))
    for i, k in enumerate(shot_keys):
        f = request.files[k]
        ext = _ext(f.filename or '') or '.png'
        name = f'screenshot_{i}{ext}'
        builder.add(name, f.read())
        screenshot_rows.append({'screenshot_url': builder.url(name), 'display_order': i})
    if not dry_run and not screenshot_rows:
        return jsonify({'success': False, 'error': 'At least one screenshot is required'}), 400

    # stage rows default their preview to the cover screenshot
    first_shot = screenshot_rows[0]['screenshot_url'] if screenshot_rows else None
    for row in builder.file_rows:
        if row['file_type'] == 'stage_dat' and not row['preview_url']:
            row['preview_url'] = first_shot

    # 2) files.zip + manifest + thumbnails
    files_zip = builder.build_files_zip()
    manifest = [{'filename': p['relPath'], 'size': len(p['data']),
                 'compressed_size': len(p['data'])} for p in builder.plan]
    thumbs = []
    for p in list(builder.plan):
        if _ext(p['relPath']) in IMAGE_EXTS:
            t = _make_thumb(p['data'])
            if t:
                thumbs.append({'relPath': re.sub(r'\.[^./]+$', '__thumb.webp', p['relPath']),
                               'data': t, 'contentType': 'image/webp'})

    full_plan = builder.plan + thumbs + [
        {'relPath': 'files.zip', 'data': files_zip, 'contentType': 'application/zip'}]

    if dry_run:
        return jsonify({
            'success': True, 'dryRun': True,
            'plan': [{'relPath': p['relPath'], 'size': len(p['data'])} for p in full_plan],
            'fileRows': builder.file_rows,
            'screenshots': screenshot_rows,
            'zipStructure': {'nested_archives': builder.nested} if builder.nested else None,
            'tags': tags,
        })

    # 3) pending post
    try:
        created = _rpc('api_create_pending_post', token, {
            'p_title': title,
            'p_description': description,
            'p_tags': tags,
            'p_zip_structure': {'nested_archives': builder.nested} if builder.nested else None,
        })
        post_id = created['post_id']
        folder = created['folder']
    except (RuntimeError, KeyError, TypeError) as e:
        logger.error(f'publish: create failed: {e}')
        return jsonify({'success': False, 'error': f'Could not create the post: {e}'}), 502

    # rewrite the folder placeholder now that we know the real folder
    for row in builder.file_rows:
        for field in ('csp_url', 'stock_url', 'file_url', 'preview_url'):
            if row.get(field):
                row[field] = row[field].replace(builder.folder, folder)
    for row in screenshot_rows:
        row['screenshot_url'] = row['screenshot_url'].replace(builder.folder, folder)

    # 4) presign + upload
    try:
        resp = requests.post(
            f'{WEBSITE_URL}/api/intake/presign',
            headers={'Authorization': f'Bearer {token}',
                     'Content-Type': 'application/json'},
            json={'post_id': post_id,
                  'files': [{'name': p['relPath'], 'content_type': p['contentType'],
                             'size': len(p['data'])} for p in full_plan]},
            timeout=60)
        if not resp.ok:
            err = {}
            try:
                err = resp.json()
            except Exception:
                pass
            raise RuntimeError(err.get('error') or f'HTTP {resp.status_code}')
        urls = resp.json()['urls']
    except (requests.RequestException, RuntimeError, KeyError) as e:
        logger.error(f'publish: presign failed: {e}')
        return jsonify({'success': False, 'error': f'Upload authorization failed: {e}'}), 502

    def _put(p):
        url = urls.get(p['relPath'])
        if not url:
            raise RuntimeError(f'No upload URL for {p["relPath"]}')
        r = requests.put(url, data=p['data'],
                         headers={'Content-Type': p['contentType']}, timeout=300)
        if not r.ok:
            raise RuntimeError(f'Upload failed for {p["relPath"]} (HTTP {r.status_code})')

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(_put, full_plan))
    except RuntimeError as e:
        logger.error(f'publish: upload failed: {e}')
        return jsonify({'success': False, 'error': str(e)}), 502

    # 5) finalize (item_key is preview-only metadata, not a website field)
    try:
        _rpc('api_finalize_pending_post', token, {
            'p_post_id': post_id,
            'p_files': [{k: v for k, v in row.items() if k != 'item_key'}
                        for row in builder.file_rows],
            'p_screenshots': screenshot_rows,
            'p_post_zip_url': f'/uploads/{folder}/files.zip',
            'p_files_manifest': manifest,
        })
    except RuntimeError as e:
        logger.error(f'publish: finalize failed: {e}')
        return jsonify({'success': False, 'error': f'Could not finalize the post: {e}'}), 502

    logger.info(f'[OK] published post {post_id}: "{title}" '
                f'({len(full_plan)} objects, {len(builder.file_rows)} file rows)')
    return jsonify({
        'success': True,
        'postId': post_id,
        'url': f'{WEBSITE_URL}/post/{post_id}',
        'status': 'pending',
    })
