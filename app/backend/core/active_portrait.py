"""
The portrait a vault costume should INSTALL with.

A skin's `alternate_csps` list + `active_csp_id` decide which portrait the
vault SHOWS, but the costume ZIP's `csp.png` is only ever the ORIGINAL (or
missing). MexCLI's import-costume reads csp.png straight out of the zip, so
without this step every install shipped the original portrait -- or, when the
zip had no csp.png at all, the vanilla slot portrait -- no matter what the
user picked in Portraits ("Manage CSPs").

`prepare_install_zip` returns a TEMP copy of the zip with the right csp.png
(caller unlinks it after install), or None when the vault zip is fine as-is.
The vault zip itself is never touched (same contract as falcon_neutralize).

Custom-character skins have their own bake-in path (projects/routes/custom_characters.py
`_zip_bytes_with_active_csp`); `active_alt_csp_path` is shared with it.

`next_alt_csp_number` numbers every NEW alternate portrait file (pose renders,
CSP-manager uploads, HD regens, retakes) so none lands on a surviving one.

`resolve_active_portrait` reads which alternate (and pose) is active, for the
portrait retakes and Randall's portrait preview.

`put_pose_portrait` files a render of a pose (one portrait per pose), and
`show_pose_portrait` makes it the one the skin shows: the pose menu and a
retake that names a pose both end with the pose's picture on screen.
"""
import logging
import re
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_CSP_MEMBER_NAMES = ('csp.png', 'csp')

# <skin>_csp_alt_<N>[_hd].<ext>
_ALT_CSP_NUMBER = re.compile(r'_csp_alt_(\d+)(?:_hd)?\.[^.]+$')


def next_alt_csp_number(alt_csps):
    """N for a new `<skin>_csp_alt_<N>[_hd]` file: one past the highest N in use.

    Not len(alt_csps)+1 -- once an alternate is removed in the CSP manager that
    count lands on a surviving alternate's number and the new file overwrites
    its portrait."""
    used = [0]
    for alt in alt_csps or []:
        match = _ALT_CSP_NUMBER.search(alt.get('filename') or '')
        if match:
            used.append(int(match.group(1)))
    return max(used) + 1


def put_pose_portrait(skin, skin_id, pose_name, is_hd, write):
    """Record a render of `pose_name` on the skin and return its alternate entry.

    A skin holds ONE portrait per pose and size. Portraits, the swap and the
    vault card all take the first entry carrying a pose's name, so a second
    pair for the same pose is a picture nobody is ever shown: rendering a pose
    again replaces its picture in the same file.

    `write(filename)` puts the picture into the skin's folder. The entry is
    recorded only after it returns, so a failed write leaves no entry behind.
    A new SD and HD of one pose share their number.
    """
    alts = skin.setdefault('alternate_csps', [])
    is_hd = bool(is_hd)
    held = next((a for a in alts if a.get('pose_name') == pose_name
                 and bool(a.get('is_hd')) == is_hd), None)
    if held is not None:
        write(held['filename'])
        held['timestamp'] = datetime.now().isoformat()
        return held

    suffix = '_hd' if is_hd else ''
    sibling = next((a for a in alts if a.get('pose_name') == pose_name), None)
    match = _ALT_CSP_NUMBER.search((sibling or {}).get('filename') or '')
    number = int(match.group(1)) if match else next_alt_csp_number(alts)
    if any(a.get('filename') == f"{skin_id}_csp_alt_{number}{suffix}.png" for a in alts):
        number = next_alt_csp_number(alts)
    filename = f"{skin_id}_csp_alt_{number}{suffix}.png"
    write(filename)
    entry = {
        'id': f"alt_{int(time.time())}_{number}{suffix}",
        'filename': filename,
        'pose_name': pose_name,
        'is_hd': is_hd,
        'timestamp': datetime.now().isoformat(),
    }
    alts.append(entry)
    return entry


def show_pose_portrait(skin, pose_name):
    """Make the skin's portrait of `pose_name` the one it shows; returns the
    entry now active (None when the skin has no portrait of that pose). The SD
    member is the pointer, as the Portraits swap stores it."""
    alts = skin.get('alternate_csps') or []
    of_pose = [a for a in alts if a.get('pose_name') == pose_name]
    shown = next((a for a in of_pose if not a.get('is_hd')), None) or next(iter(of_pose), None)
    if shown is not None:
        skin['active_csp_id'] = shown.get('id')
    return shown


def resolve_active_portrait(skin_meta):
    """Resolve the costume's currently active portrait from metadata.

    Returns (active_alt, pose_name): the active alternate dict (None when the
    original/default CSP is active) and its pose name (None = default pose). A
    swap stores active_csp_id pointing at the SD member of a pose group, but we
    fold an HD pointer back to its SD sibling just in case.
    """
    skin_meta = skin_meta or {}
    alt_csps = skin_meta.get('alternate_csps', [])
    active_csp_id = skin_meta.get('active_csp_id')
    if not active_csp_id:
        return None, None
    active_alt = next((a for a in alt_csps if a.get('id') == active_csp_id), None)
    if active_alt and active_alt.get('is_hd'):
        active_alt = next((a for a in alt_csps
                           if a.get('pose_name') == active_alt.get('pose_name')
                           and not a.get('is_hd')), active_alt)
    pose_name = active_alt.get('pose_name') if active_alt else None
    return active_alt, pose_name


def active_alt_csp_path(skin_dir, skin):
    """Path of the skin's active SD alternate portrait, or None (original active).

    `active_csp_id` may (legacy) point at the HD member of a pose group; the game
    slot wants the SD render, so fold it to the SD sibling with the same pose."""
    if not skin:
        return None
    active_id = skin.get('active_csp_id')
    if not active_id:
        return None
    alts = skin.get('alternate_csps') or []
    active = next((a for a in alts if a.get('id') == active_id), None)
    if not active:
        return None
    if active.get('is_hd'):
        pose_name = active.get('pose_name')
        sd = next((a for a in alts
                   if a.get('pose_name') == pose_name and not a.get('is_hd')), None)
        if sd is None:
            return None
        active = sd
    filename = active.get('filename')
    if not filename:
        return None
    path = Path(skin_dir) / filename
    return path if path.exists() else None


def _zip_has_csp(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        return any(Path(i.filename).name.lower() in _CSP_MEMBER_NAMES
                   for i in zf.infolist() if not i.is_dir())


def install_csp_bytes(zip_path, skin):
    """csp.png bytes the install should carry, or None to install the zip as-is.

    1. an active alternate -> its SD file (the user's pick in Portraits)
    2. the zip has no csp.png but the standalone <id>_csp.png exists -> that
       (otherwise MexCLI keeps the vanilla portrait for the slot)
    3. None -> the zip's own csp.png (the original) is right."""
    zip_path = Path(zip_path)
    alt = active_alt_csp_path(zip_path.parent, skin)
    if alt is not None:
        return alt.read_bytes()
    if skin and not _zip_has_csp(zip_path):
        standalone = zip_path.parent / (skin.get('csp_filename') or f"{zip_path.stem}_csp.png")
        if standalone.exists():
            return standalone.read_bytes()
    return None


def zip_with_csp(zip_path, csp_bytes, temp_dir=None):
    """Write a temp copy of `zip_path` whose csp.png is `csp_bytes`; return its path."""
    zip_path = Path(zip_path)
    fd, tmp_name = tempfile.mkstemp(prefix=f'{zip_path.stem}_portrait_', suffix='.zip', dir=temp_dir)
    import os
    os.close(fd)
    tmp = Path(tmp_name)
    with zipfile.ZipFile(zip_path, 'r') as src, \
            zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if not item.is_dir() and Path(item.filename).name.lower() in _CSP_MEMBER_NAMES:
                continue
            dst.writestr(item, src.read(item.filename))
        dst.writestr('csp.png', csp_bytes)
    return tmp


def find_vault_skin(metadata, zip_path):
    """The metadata skin entry for a vault costume zip (storage/<Character>/<id>.zip)."""
    if not metadata:
        return None
    zip_path = Path(zip_path)
    char_data = (metadata.get('characters') or {}).get(zip_path.parent.name)
    if not char_data:
        return None
    return next((s for s in char_data.get('skins', [])
                 if s.get('id') == zip_path.stem and s.get('type') != 'folder'), None)


def prepare_install_zip(vault_zip, metadata, source_zip=None, temp_dir=None):
    """Temp zip carrying the skin's active portrait, or None to install as-is.

    `vault_zip` locates the skin (storage/<Character>/<id>.zip) and its portrait
    files; `source_zip` is the archive to copy everything else from -- pass the
    Falcon-neutralized temp when there is one, else it defaults to `vault_zip`."""
    vault_zip = Path(vault_zip)
    source_zip = Path(source_zip) if source_zip else vault_zip
    try:
        skin = find_vault_skin(metadata, vault_zip)
        csp = install_csp_bytes(vault_zip, skin)
        if csp is None:
            return None
        tmp = zip_with_csp(source_zip, csp, temp_dir=temp_dir)
        logger.info(f"Install portrait: {vault_zip.name} -> active portrait baked into {tmp.name}")
        return tmp
    except Exception as e:  # noqa: BLE001 - fail open: install the vault zip as-is
        logger.warning(f"Install portrait: could not prepare {vault_zip.name}: {e}")
        return None
