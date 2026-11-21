"""
vanilla_stage_import.py - wrap a raw vanilla-stage mod dat (a lone GrXx.dat /
.usd for a NON-tournament stage, e.g. GrGr Green Greens or GrCs Peach's
Castle) into a modern MexManager custom-stage package (stage.json + dat +
SSS icon/banner) that MexCLI add-stage understands.

The modded dat becomes an ADDED m-ex stage with its own SSS entry; the
vanilla stage slot is never touched. The 6 tournament-legal codes are NOT
handled here -- they keep routing to the DAS stage-skin path.

Design notes:
  - The synthesized stage.json reuses the VANILLA stage's own code tables
    (map GOBJ function pointer, OnStageInit/Load/Go..., collision materials,
    moving collision pointer/count). Those are vanilla main.dol addresses
    that stay valid in every m-ex build, so the reskinned dat runs the real
    stage logic (Whispy, Banzai Bills, F-Zero cars...) at its new internal
    id. Ground truth: MexStage.FromDOL, serialized via an import-iso scan
    (see vanilla_stage_specs.py).
  - MexStage.FromPackage resets soundBank (to 55 = none) and the playlist
    (to music 0) on install, so stage.json also carries a
    `nucleusVanillaStage` sidecar block (ignored by MexJsonSerializer) that
    the vault keeps and the install flow re-applies to the project's stage
    json after add-stage (custom_stages._apply_vanilla_stage_fixups).
  - fileName stays the canonical code ('GrGr.dat'); FromPackage's
    GetUniqueFilePath renames the packaged file (GrGr_001.dat) so the
    vanilla file in the build is never overwritten.
"""

import io
import json
import re
import zipfile
from pathlib import Path

from shared.vanilla_extract.menu_refs import stage_art_path
from vault.importing.vanilla_stage_specs import VANILLA_STAGE_SPECS

# Matches a known non-tournament stage code as a standalone token anywhere in
# the filename ('GrBb.dat', 'Legal Big Blue GrBb.dat'), but NOT as a prefix of
# a longer word ('GrGreatPlateau.dat' must not match GrGr) and not followed by
# digits ('GrPs1.dat' is a Stadium transformation file, not a stage).
_CODE_RE = re.compile(
    r'(?<![a-z0-9])(' + '|'.join(re.escape(c) for c in VANILLA_STAGE_SPECS) + r')(?![a-z0-9])',
    re.IGNORECASE)

_DAT_EXTS = ('.dat', '.usd')


def find_vanilla_stage_code(filename):
    """Return the spec key ('grgr', 'grcs', ...) for a stage dat filename,
    or None if it doesn't name a supported non-tournament vanilla stage."""
    name = Path(filename).name
    if not name.lower().endswith(_DAT_EXTS):
        return None
    m = _CODE_RE.search(Path(name).stem.lower())
    return m.group(1) if m else None


def detect_vanilla_stage_dats(names):
    """Scan archive member names for raw vanilla-stage mod dats.
    Returns [{'member', 'code', 'spec'}] (one per matching dat)."""
    found = []
    for n in names:
        if n.endswith('/') or n.startswith('__MACOSX'):
            continue
        key = find_vanilla_stage_code(n)
        if key:
            found.append({'member': n, 'code': key,
                          'spec': VANILLA_STAGE_SPECS[key]})
    return found


def default_stage_mod_name(spec, source_stem=None, custom_title=None):
    """Pick a display name for the imported stage: the website/user title if
    given, else the source filename when it says more than the bare code,
    else '<Vanilla Name> (Mod)'."""
    if custom_title and custom_title.strip():
        return custom_title.strip()
    if source_stem:
        stem = re.sub(r'[_\-]+', ' ', source_stem)
        # drop the bare code token ('Legal Big Blue GrBb' -> 'Legal Big Blue')
        stem = _CODE_RE.sub('', stem).strip()
        if stem:
            return stem
    return f"{spec['name']} (Mod)"


def build_vanilla_stage_package(dat_bytes, code_key, name, dat_ext='.dat'):
    """Build a custom-stage package zip (stage.json + dat + icon/banner)
    around a raw vanilla-stage mod dat. Returns (zip_bytes, spec).
    Raises KeyError for an unknown code."""
    spec = VANILLA_STAGE_SPECS[code_key]
    if dat_ext.lower() not in _DAT_EXTS:
        dat_ext = '.dat'
    file_name = spec['code'] + dat_ext.lower()

    stage_json = {
        'name': name,
        'location': spec.get('location', ''),
        'seriesID': spec.get('seriesID', 0),
        'fileName': file_name,
        'additionalFiles': [],
        # informational only -- FromPackage resets this to 55; the install
        # flow re-applies it from nucleusVanillaStage below.
        'soundBank': spec['soundBank'],
        'reverbValue1': spec['reverbValue1'],
        'reverbValue2': spec['reverbValue2'],
        'collisionMaterials': spec['collisionMaterials'],
        'mapDescPointer': spec['mapDescPointer'],
        'onStageInit': spec['onStageInit'],
        'onStageLoad': spec['onStageLoad'],
        'onStageGo': spec['onStageGo'],
        'onGo': spec['onGo'],
        'onUnknown2': spec['onUnknown2'],
        'onTouchLine': spec['onTouchLine'],
        'onUnknown4': spec['onUnknown4'],
        'unknownValue': spec['unknownValue'],
        'movingCollisionPointer': spec['movingCollisionPointer'],
        'movingCollisionCount': spec['movingCollisionCount'],
        'items': [],
        'mapGOBJs': [],
        'movingCollisions': [],
        'playlist': {'entries': list(spec['playlist'])},
        'alternateStages': [],
        # Nucleus sidecar (unknown to MexJsonSerializer, which ignores it):
        # what the install flow must re-apply after MexStage.FromPackage's
        # resets, plus provenance for the vault/website.
        'nucleusVanillaStage': {
            'code': spec['code'],
            'vanillaInternalID': spec['vanillaInternalID'],
            'soundBank': spec['soundBank'],
            'playlist': list(spec['playlist']),
        },
    }

    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('stage.json', json.dumps(stage_json, indent=2))
        zf.writestr(file_name, dat_bytes)
        # the vanilla SSS icon/banner (it IS that stage, reskinned -- same
        # convention as DAS variants showing the vanilla emblem), copied out of
        # the user's own game (menu_refs). Without it the package simply has
        # no icon, as any icon-less custom stage.
        for kind in ('icon', 'banner'):
            asset = stage_art_path(spec['code'], kind)
            if asset is not None:
                zf.writestr(f'{kind}.png', asset.read_bytes())
    return out.getvalue(), spec


def import_vanilla_stage_dats(zip_path, fallback_stem, custom_title=None):
    """Import every raw vanilla-stage mod dat in an uploaded archive as an
    ADDED custom stage in the vault. Returns a list of vault entries
    (empty when the archive contains none)."""
    from vault.importing.custom_stage_package import import_custom_stage_zip_bytes

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            found = detect_vanilla_stage_dats(names)
            payloads = [(f, zf.read(f['member'])) for f in found]
    except zipfile.BadZipFile:
        # .7z uploads also reach this phase; they are handled elsewhere
        return []

    entries = []
    multiple = len(payloads) > 1
    for f, dat_bytes in payloads:
        spec = f['spec']
        source_stem = Path(f['member']).stem
        # a single-dat upload usually carries its title on the archive/upload
        # name; multi-dat archives fall back to each member's own name
        stem = source_stem if multiple else (fallback_stem or source_stem)
        name = default_stage_mod_name(
            spec, source_stem=stem,
            custom_title=None if multiple else custom_title)
        pkg, _ = build_vanilla_stage_package(
            dat_bytes, f['code'], name,
            dat_ext=Path(f['member']).suffix.lower())
        entry = import_custom_stage_zip_bytes(pkg, name)
        entries.append(entry)
    return entries
