"""
A menu mod's files: safe zip extraction, the zipped export download, finding the
preview picture, and finding the CSS/SSS menu file (MnSlChr / MnSlMap) in a pack.
"""

import io
import re
import zipfile
from pathlib import Path
from flask import send_file
from vault.menus.store import SCREENSHOT_CANDIDATES


# ─────────────────────────────────────────────────────────────────────────────
# Zip handling
# ─────────────────────────────────────────────────────────────────────────────

def _safe_extract_zip(zip_path, dest_dir, budget=None):
    """Extract zip through the shared extractor (core.safe_extract).

    The old predicate here was `str(target).startswith(str(dest_dir))`, a
    string prefix rather than path ancestry, so `../extracted-extra/payload.exe`
    escaped the extraction directory (2026-09-22 security review, finding 1).
    The shared extractor validates each member's components, refuses links and
    reserved names, completes its preflight before the first write, and charges
    the operation's cumulative budget.
    """
    from core.safe_extract import extract_zip, new_budget
    with zipfile.ZipFile(zip_path, 'r') as zf:
        extract_zip(zf, Path(dest_dir), budget=budget or new_budget())


def send_mod_zip(mod_dir, name):
    """Zip every file in a mod's folder in-memory and return it as a download
    attachment named after the mod. Shared by the menu mods' Export action."""
    mod_dir = Path(mod_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        if mod_dir.exists():
            for p in sorted(mod_dir.rglob('*')):
                if p.is_file() and p.name != 'mod.json':
                    zf.write(str(p), str(p.relative_to(mod_dir)))
    buf.seek(0)
    safe = re.sub(r'[^\w\-. ]+', '_', str(name)).strip() or 'mod'
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name=f'{safe}.zip', max_age=0)


def _find_screenshot(directory):
    """Find a preview image in the extracted directory."""
    directory = Path(directory)
    for candidate in SCREENSHOT_CANDIDATES:
        # Search anywhere in the tree (zips sometimes nest in a folder)
        matches = list(directory.rglob(candidate))
        if matches:
            return matches[0]
    for path in sorted(directory.rglob('*')):
        if path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
            return path
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Menu file discovery (background packs; also the Nucleus API's extract_background)
# ─────────────────────────────────────────────────────────────────────────────

def find_mnslchr_dat(directory):
    """Find a MnSlChr dat/usd file in an extracted directory."""
    directory = Path(directory)
    for p in sorted(directory.rglob('*')):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if name_lower.startswith('mnslchr') and name_lower.endswith(('.dat', '.usd')):
            return p
    return None


def find_menu_dat_by_roots(directory, menu_type=None):
    """(path, hsd command) for the first .dat/.usd whose ROOT SYMBOL is a
    character-select or stage-select table, preferring the screen asked for;
    (None, '--css-bg') when none qualifies."""
    from vault.importing.unified.detection import dat_root_symbols
    wanted = {'MnSelectChrDataTable': '--css-bg', 'MnSelectMapDataTable': '--sss-bg'}
    preferred = '--sss-bg' if menu_type == 'sss' else '--css-bg'
    found = []
    for p in sorted(Path(directory).rglob('*')):
        if not p.is_file() or not p.name.lower().endswith(('.dat', '.usd')):
            continue
        try:
            head = p.read_bytes()
        except OSError:
            continue
        for sym in dat_root_symbols(head):
            if sym in wanted:
                found.append((p, wanted[sym]))
                break
    for p, cmd in found:
        if cmd == preferred:
            return p, cmd
    return (found[0] if found else (None, '--css-bg'))


def find_mnslmap_dat(directory):
    """Find a MnSlMap dat/usd file in an extracted directory."""
    directory = Path(directory)
    for p in sorted(directory.rglob('*')):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if name_lower.startswith('mnslmap') and name_lower.endswith(('.dat', '.usd')):
            return p
    return None
