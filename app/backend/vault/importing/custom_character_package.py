"""
Custom characters in the vault: the helpers shared by every path that adds
or edits a storage/custom_characters/<slug>/ entry.

  make_slug / dedupe_slug   folder naming (Windows-safe, unique in the vault)
  sync_costume_meta         mirror fighter.zip's bundled costumes into
                            entry['costume_meta'] + per-costume zips
  DEFAULT_META              the vault shape a missing/empty metadata file reads as

No routes. Used by the Custom Characters routes (vault/routes/custom_characters/,
which holds the package importer) and Randall's clone adapter
(randall/assistant/clone_character.py).
"""
import re
import shutil
import zipfile
from pathlib import Path

from core.config import CUSTOM_CHARACTERS_PATH
from core.path_safety import validate_path_segment

# Default vault shape a custom-character write expects from a missing/empty
# metadata file.
DEFAULT_META = {'characters': {}, 'stages': {}, 'custom_stages': [], 'custom_characters': []}


def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def make_slug(name):
    slug = sanitize_filename(name).lower().replace(' ', '-')
    # Windows drops a trailing dot or space from a folder name, so a slug
    # ending in one names a folder that path checks can never match.
    slug = re.sub(r'[-. ]+$', '', re.sub(r'-+', '-', slug).strip('-'))
    try:
        validate_path_segment(slug, field='slug')
    except ValueError:  # empty, a reserved device name (con, nul, ...) or a control char
        slug = 'custom-character'
    return slug


def dedupe_slug(slug, root=None):
    """`slug`, or `slug-N` for the first N not taken under `root` (default:
    the vault's custom_characters folder)."""
    root = CUSTOM_CHARACTERS_PATH if root is None else root
    if not (root / slug).exists():
        return slug
    counter = 2
    while (root / f"{slug}-{counter}").exists():
        counter += 1
    return f"{slug}-{counter}"


def sync_costume_meta(entry, char_dir, fighter_data):
    """Mirror the bundled costumes into entry['costume_meta'] + materialized
    per-costume zips under char_dir/costumes/, keyed by DAT stem.

    This is what lets the shared skin-edit stack (EditModal, CSP manager,
    3D viewer) open a bundled costume directly via the pseudo-character
    'custom_characters/<slug>/costumes'. Edits land in the materialized
    zips/meta and are folded back into fighter.zip at install time.
    Returns True if anything changed.
    """
    fighter_zip = char_dir / 'fighter.zip'
    if not fighter_zip.exists():
        return False

    costumes_dir = char_dir / 'costumes'
    meta_list = entry.setdefault('costume_meta', [])
    by_id = {m['id']: m for m in meta_list}
    changed = False
    current_ids = []

    with zipfile.ZipFile(fighter_zip) as zf:
        inner_names = {n.split('/')[-1].lower(): n for n in zf.namelist()}
        for i, costume in enumerate(fighter_data.get('costumes', [])):
            dat = (costume.get('file') or {}).get('fileName') or ''
            stem = Path(dat).stem
            if not stem:
                continue
            current_ids.append(stem)
            costumes_dir.mkdir(exist_ok=True)

            zip_dest = costumes_dir / f'{stem}.zip'
            if not zip_dest.exists():
                inner = inner_names.get(f'{stem}.zip'.lower())
                if inner is None:
                    continue
                zip_dest.write_bytes(zf.read(inner))
                changed = True

            if not (costumes_dir / f'{stem}_csp.png').exists() and (char_dir / f'csp_{i}.png').exists():
                shutil.copy2(char_dir / f'csp_{i}.png', costumes_dir / f'{stem}_csp.png')
                changed = True
            if not (costumes_dir / f'{stem}_stc.png').exists() and (char_dir / f'stock_{i}.png').exists():
                shutil.copy2(char_dir / f'stock_{i}.png', costumes_dir / f'{stem}_stc.png')
                changed = True

            # Belt-and-suspenders: a bare fighter.zip (no csp_{i}.png alongside)
            # still carries previews INSIDE each costume zip — pull them out so
            # even a minimal import materializes CSPs instead of placeholders.
            need_csp = not (costumes_dir / f'{stem}_csp.png').exists()
            need_stc = not (costumes_dir / f'{stem}_stc.png').exists()
            if (need_csp or need_stc) and zip_dest.exists():
                with zipfile.ZipFile(zip_dest) as cz:
                    # This runs AFTER import, on a costume archive taken out of
                    # fighter.zip, and it reads members whole. Without a
                    # preflight it was the one place a package's declared 1 GiB
                    # preview could still be expanded (2026-09-22 re-review, 1).
                    from core.safe_extract import new_budget, preflight_zip
                    preflight_zip(cz, budget=new_budget(max_bytes=64 * 1024 * 1024,
                                                        max_members=2000))
                    for n in cz.namelist():
                        base = n.split('/')[-1].lower()
                        if need_csp and base in ('csp.png', 'portrait.png', 'select.png'):
                            (costumes_dir / f'{stem}_csp.png').write_bytes(cz.read(n))
                            need_csp = False
                            changed = True
                        elif need_stc and base in ('stc.png', 'stock.png', 'icon.png'):
                            (costumes_dir / f'{stem}_stc.png').write_bytes(cz.read(n))
                            need_stc = False
                            changed = True

            m = by_id.get(stem)
            if m is None:
                m = {
                    'id': stem,
                    'color': costume.get('name') or stem,
                    'filename': f'{stem}.zip',
                    'dat_name': dat,
                }
                meta_list.append(m)
                by_id[stem] = m
                changed = True
            has_csp = (costumes_dir / f'{stem}_csp.png').exists()
            has_stock = (costumes_dir / f'{stem}_stc.png').exists()
            if m.get('has_csp') != has_csp or m.get('has_stock') != has_stock:
                m['has_csp'] = has_csp
                m['has_stock'] = has_stock
                changed = True

    stale = [m for m in meta_list if m['id'] not in current_ids]
    for m in stale:
        meta_list.remove(m)
        changed = True
        if costumes_dir.exists():
            for p in costumes_dir.glob(f"{m['id']}*"):
                p.unlink()

    return changed
