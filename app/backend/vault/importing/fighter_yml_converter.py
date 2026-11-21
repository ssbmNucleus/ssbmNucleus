"""
fighter_yml_converter.py - convert classic mexTool fighter packages
(fighter.yml — the format community custom fighters ship in) into modern
MexManager packages (fighter.json) that the vault importer and MexCLI
add-fighter understand. The fighter analog of stage_yml_converter.py.

Field mapping notes:
  - fighter.yml is mexTool's YAML serialization of essentially the same model
    mexLib's MexFighter serializes to fighter.json (camelCase). Most keys map
    1:1; the renames are: nameText->name, insigniaID->seriesID,
    sSMBitfield1/2->ssmBitfield1/2, functions.onItemRelease->onItemDrop,
    items[].onUnknown1/2/3->onClank/onUnk2/onUnk3, items[].itemStates->states,
    costumes[].modelSymbol->file.jointSymbol, boneTable->boneDefinitions.lookup.
  - Install-time resets (MexFighter.FromPackage): victoryTheme, announcerCall,
    fighterMusic1/2, targetTestStage and the trophy ids are hardcoded over on
    install, and soundBank/ssmBitfields are recomputed from sound.zip — so we
    emit defaults and instead ship victory_theme.hps / announcer.wav, which
    the vault's install path re-applies via add-music / set-fighter-announcer.
  - sound.spk (classic sound pack) IS converted here: the SPK container
    (little-endian header, raw SEM script sections, embedded big-endian .ssm)
    becomes the modern sound.zip (group.json + scripts.sem + scripts.json +
    the .ssm) that MexSoundGroup.FromPackage reads. Stage conversion drops
    .spk; fighters need their voices, so we don't.
  - functions.* are absolute code pointers from the SOURCE build's m-ex core.
    Packages authored on extended cores (Ace build) only work on that base —
    same caveat as the docs' m-ex/Ace-build gotcha. Bundled codes.ini /
    patches/*.dat are passed through; add-fighter merges them.
"""

import io
import json
import logging
import re
import struct
import zipfile
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _u32(v):
    return int(v) & 0xFFFFFFFF if v is not None else 0


# ── fighter.yml -> fighter.json ─────────────────────────────────────────────

_SUB_BEHAVIOR = {'SpawnSimultaneously': 0, 'SpawnSeparately': 1, 'SpawnNormally': 0xFF}

# mexLib MexFighterFunctions property names (camelCase). yml name differences
# are handled via _FUNC_RENAMES; anything else maps verbatim.
_FUNC_KEYS = [
    'version', 'onLoad', 'onRespawn', 'onDestroy', 'moveLogicPointer',
    'demoMoveLogicPointer', 'specialN', 'specialNAir', 'specialHi',
    'specialHiAir', 'specialLw', 'specialLwAir', 'specialS', 'specialSAir',
    'onSmashHi', 'onSmashLw', 'onSmashF', 'onAbsorb', 'onItemPickup',
    'onMakeItemInvisible', 'onMakeItemVisible', 'onItemDrop', 'onItemCatch',
    'onUnknownItemRelated', 'onApplyHeadItem', 'onRemoveHeadItem',
    'eyeTextureDamaged', 'eyeTextureNormal', 'onFrame', 'onActionStateChange',
    'resetAttribute', 'onModelRender', 'onShadowRender', 'onUnknownMultijump',
    'onActionStateChangeWhileEyeTextureIsChanged1',
    'onActionStateChangeWhileEyeTextureIsChanged2',
    'onTwoEntryTable1', 'onTwoEntryTable2', 'onLanding', 'onExtRstAnim',
    'onIndexExtRstAnim', 'enterFloat', 'enterDoubleJump', 'enterTether',
    'onIntroL', 'onIntroR', 'onCatch', 'onAppeal', 'getSwordTrail',
    'kirbySpecialN', 'kirbySpecialNAir', 'kirbyOnSwallow',
    'kirbyOnLoseAbility', 'kirbyOnHit', 'kirbyOnDeath', 'kirbyOnItemInit',
    'kirbyOnFrame',
]
_FUNC_RENAMES = {'onItemDrop': 'onItemRelease'}

# SBM_BoneLookupTable property names (camelCase); yml boneTable keys match.
_BONE_KEYS = [
    'boneCount', 'top', 'trans', 'xRot', 'yRot', 'hip', 'waist', 'lLegA',
    'lLeg', 'lKnee', 'lFootA', 'lFoot', 'rLegA', 'rLeg', 'rKnee', 'rFootA',
    'rFoot', 'waistB', 'bust', 'lClavicle', 'lShoulderA', 'lShoulder', 'lArm',
    'lHand', 'lIndex1', 'lIndex2', 'lMiddle1', 'lMiddle2', 'lRing1', 'lRing2',
    'lPinky1', 'lPinky2', 'lHave', 'lThumb1', 'lThumb2', 'neckN', 'headN',
    'rClavicle', 'rShoulderA', 'rShoulder', 'rArm', 'rHand', 'rIndex1',
    'rIndex2', 'rMiddle1', 'rMiddle2', 'rRing1', 'rRing2', 'rPinky1',
    'rPinky2', 'rHave', 'rThumb1', 'rThumb2', 'throw', 'extra',
]

_FILES_KEYS = [
    'fighterDataPath', 'fighterDataSymbol', 'animFile', 'animCount',
    'demoFile', 'demoWait', 'demoResult', 'demoIntro', 'demoEnding',
    'rstAnimFile', 'rstAnimCount', 'effectFile', 'effectSymbol',
    'kirbyCapFileName', 'kirbyCapSymbol', 'kirbyEffectFile',
    'kirbyEffectSymbol',
]
_MEDIA_KEYS = ['endClassicFile', 'endAdventureFile', 'endAllStarFile', 'endMovieFile']

_ITEM_CB_KEYS = [
    'onSpawn', 'onDestroy', 'onPickup', 'onDrop', 'onThrow', 'onGiveDamage',
    'onTakeDamage', 'onEnterAir', 'onReflect', 'onClank', 'onUnk2',
    'onHitShieldBounce', 'onHitShieldDetermineDestroy', 'onUnk3',
]
_ITEM_CB_RENAMES = {'onClank': 'onUnknown1', 'onUnk2': 'onUnknown2', 'onUnk3': 'onUnknown3'}


def convert_fighter_yml(yml_text, fallback_name):
    """Convert a fighter.yml document to a fighter.json dict (camelCase keys
    matching MexJsonSerializer). Raises ValueError on unusable input."""
    doc = yaml.safe_load(yml_text)
    if not isinstance(doc, dict):
        raise ValueError('fighter.yml did not parse to a mapping')

    files = {}
    for k in _FILES_KEYS:
        v = doc.get(k)
        if k in ('animCount', 'rstAnimCount'):
            files[k] = int(v or 0)
        else:
            files[k] = (v or '').strip() if isinstance(v, str) else (v or '')
    if not files['fighterDataPath'] or not files['animFile']:
        raise ValueError('fighter.yml has no fighterDataPath/animFile')

    yfun = doc.get('functions') or {}
    functions = {k: _u32(yfun.get(_FUNC_RENAMES.get(k, k)))
                 for k in _FUNC_KEYS}
    functions['version'] = int(yfun.get('version', 0) or 0)

    ybones = doc.get('boneTable') or {}
    lookup = {k: int(ybones.get(k, 255) or 0) if k == 'boneCount'
              else int(ybones.get(k, 255) if ybones.get(k) is not None else 255)
              for k in _BONE_KEYS}
    lookup['boneCount'] = int(ybones.get('boneCount', 0) or 0)

    items = []
    for it in (doc.get('items') or []):
        if not isinstance(it, dict):
            continue
        entry = {'name': it.get('name') or 'New Item',
                 'states': [{
                     'animID': int(s.get('animID', 0) or 0),
                     'animationCallback': _u32(s.get('animationCallback')),
                     'physicsCallback': _u32(s.get('physicsCallback')),
                     'collisionCallback': _u32(s.get('collisionCallback')),
                 } for s in (it.get('itemStates') or []) if isinstance(s, dict)]}
        for k in _ITEM_CB_KEYS:
            entry[k] = _u32(it.get(_ITEM_CB_RENAMES.get(k, k)))
        items.append(entry)

    def costume_entry(c):
        return {
            'name': Path(c.get('fileName') or '').stem or 'New Costume',
            'colorSmashGroup': -1,
            'file': {
                'visibilityIndex': int(c.get('visibilityIndex', 0) or 0),
                'fileName': c.get('fileName') or '',
                'jointSymbol': c.get('modelSymbol') or '',
                'materialSymbol': c.get('materialSymbol') or '',
            },
            'icon': '', 'csp': '',
        }

    costumes = [costume_entry(c) for c in (doc.get('costumes') or [])
                if isinstance(c, dict) and c.get('fileName')]
    if not costumes:
        raise ValueError('fighter.yml has no costumes')

    kirby_costumes = [{
        'fileName': c.get('fileName') or '',
        'jointSymbol': c.get('modelSymbol') or c.get('jointSymbol') or '',
        'materialSymbol': c.get('materialSymbol') or '',
    } for c in (doc.get('kirbyCostumes') or []) if isinstance(c, dict) and c.get('fileName')]

    # Classic packages usually EMBED the move-logic table (custom action
    # states) with moveLogicPointer 0 — the fighter analog of stage mapGOBJs.
    # mexLib's MexFighter.MoveLogic carries the entries and MexCLI packs them
    # into MxDt.dat as a relocated array reference at export.
    move_logic = []
    for m in (yfun.get('moveLogic') or []):
        if isinstance(m, dict):
            move_logic.append({
                'animationID': int(m.get('animationID', -1) if m.get('animationID') is not None else -1),
                'stateFlags': _u32(m.get('stateFlags')),
                'attackID': int(m.get('attackID', 0) or 0),
                'bitFlags': int(m.get('bitFlags', 0) or 0),
                'animationCallBack': _u32(m.get('animationCallBack')),
                'iASACallBack': _u32(m.get('iASACallBack')),
                'physicsCallback': _u32(m.get('physicsCallback')),
                'collisionCallback': _u32(m.get('collisionCallback')),
                'cameraCallback': _u32(m.get('cameraCallback')),
            })

    fighter_json = {
        'name': (doc.get('nameText') or fallback_name).strip(),
        'seriesID': int(doc.get('insigniaID', 0) or 0),
        'canWallJump': bool(doc.get('canWallJump', False)),
        'subCharacter': -1,
        'subCharacterBehavior': _SUB_BEHAVIOR.get(str(doc.get('subCharacterBehavior', '')).strip(), 0),
        # soundBank/ssmBitfields are recomputed from sound.zip on install;
        # victory/announcer/music/trophies are hardcoded over by FromPackage.
        'soundBank': 55,
        'ssmBitfield1': _u32(doc.get('sSMBitfield1')),
        'ssmBitfield2': _u32(doc.get('sSMBitfield2')),
        'announcerCall': 540000,
        'victoryTheme': 10,
        'fighterMusic1': 0,
        'fighterMusic2': 0,
        'targetTestStage': 0,
        'classicTrophyId': int(doc.get('classicTrophyId', 0) or 0),
        'adventureTrophyId': int(doc.get('adventureTrophyId', 1) or 1),
        'allStarTrophyId': int(doc.get('allStarTrophyId', 2) or 2),
        'racetoTheFinishTime': int(doc.get('racetoTheFinishTime', 60) or 60),
        'resultScreenScale': float(doc.get('resultScreenScale', 1) or 1),
        'endingScreenScale': float(doc.get('endingScreenScale', 1) or 1),
        'items': items,
        'boneDefinitions': {'lookup': lookup, 'ext': []},
        'assets': {'cssIcon': '', 'resultBannerBig': '', 'resultSmallBig': ''},
        'redCostumeIndex': int(doc.get('redCostumeIndex', 0) or 0),
        'blueCostumeIndex': int(doc.get('blueCostumeIndex', 0) or 0),
        'greenCostumeIndex': int(doc.get('greenCostumeIndex', 0) or 0),
        'costumes': costumes,
        'kirbyCostumes': kirby_costumes,
        'hasKirbyCostumes': bool(kirby_costumes),
        'gaWData': None,
        'files': files,
        'functions': functions,
        'media': {k: (doc.get(k) or '') for k in _MEDIA_KEYS},
        'moveLogic': move_logic,
    }
    return fighter_json


# ── sound.spk -> sound.zip ──────────────────────────────────────────────────

def _read_pascal(data, pos):
    n = data[pos]
    return data[pos + 1:pos + 1 + n].decode('ascii', errors='replace'), pos + 1 + n


def parse_spk(spk):
    """Parse a classic mexTool SPK sound pack (little-endian header, raw SEM
    script sections, embedded .ssm). Returns dict or raises ValueError."""
    if len(spk) < 0x14 or spk[0:3] != b'SPK':
        raise ValueError('not an SPK file')
    version = 2 if spk[3:4] == b'2' else 1
    group_flags, flags, ssm_size, script_count = struct.unpack_from('<IIiI', spk, 4)
    pos = 20
    scripts = []
    for _ in range(script_count):
        start, size = struct.unpack_from('<Ii', spk, pos)
        pos += 8
        name = 'New Script'
        if version > 1:
            name_ptr, = struct.unpack_from('<I', spk, pos)
            pos += 4
            name, _ = _read_pascal(spk, name_ptr)
        scripts.append({'name': name, 'data': spk[start:start + size]})
    file_name, pos = _read_pascal(spk, pos)
    ssm = spk[pos:pos + ssm_size]
    if len(ssm) != ssm_size:
        raise ValueError('SPK truncated: embedded ssm short')
    return {'group_flags': group_flags, 'flags': flags,
            'file_name': file_name, 'scripts': scripts, 'ssm': ssm}


def _compile_sem(script_blobs):
    """SemFile.Compile for a single group (big-endian): header [0,0,1,0,N],
    N data offsets, trailing 0, then the script data. The last script's end
    is implied by EOF (Decompile treats offset 0 as stream length)."""
    n = len(script_blobs)
    out = io.BytesIO()
    out.write(struct.pack('>iiiii', 0, 0, 1, 0, n))
    data_start = 20 + 4 * (n + 1)
    offsets = []
    for blob in script_blobs:
        offsets.append(data_start)
        data_start += len(blob)
    for off in offsets:
        out.write(struct.pack('>I', off))
    out.write(struct.pack('>i', 0))
    for blob in script_blobs:
        out.write(blob)
    return out.getvalue()


def spk_to_sound_zip(spk_bytes, bank_name):
    """Convert sound.spk bytes to the modern sound.zip (group.json +
    scripts.sem + scripts.json + <name>.ssm) MexSoundGroup.FromPackage reads."""
    info = parse_spk(spk_bytes)
    file_name = (info['file_name'] or f'{bank_name}.ssm').strip()
    if not file_name.lower().endswith('.ssm'):
        file_name += '.ssm'
    file_name = Path(file_name).name.lower()

    group_json = {
        'name': Path(file_name).stem.capitalize(),
        'fileName': file_name,
        'groupFlags': info['group_flags'],
        'flags': info['flags'],
        'sounds': [],  # names re-derived from the ssm on load
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('group.json', json.dumps(group_json, indent=2))
        if info['scripts']:
            zf.writestr('scripts.sem', _compile_sem([s['data'] for s in info['scripts']]))
            zf.writestr('scripts.json', json.dumps([s['name'] for s in info['scripts']]))
        zf.writestr(file_name, info['ssm'])
    return buf.getvalue()


# ── whole-package conversion ────────────────────────────────────────────────

def _norm(name):
    return name.replace('\\', '/')


_NESTED_ZIP_SCAN_LIMIT = 8
_NESTED_ZIP_MAX_BYTES = 200 * 1024 * 1024


def find_fighter_package(zf, names, budget=None):
    """Locate the fighter.yml package inside an archive: either loose, or one
    level down inside a nested zip (community posts wrap the package and keep
    UI art next to it). Returns (package_zf, package_names, aux_zf, aux_names)
    where aux is the OUTER archive when the package was nested (for icon/csp
    harvesting), else None. Raises ValueError when no package exists.

    `budget` is the operation's cumulative extraction budget. A nested package
    is preflighted against it the moment it is opened, so a small outer archive
    can no longer carry a multi-gigabyte fighter payload (2026-09-22 security
    review, finding 2).
    """
    loose = next((n for n in names
                  if _norm(n).rsplit('/', 1)[-1].lower() == 'fighter.yml'), None)
    if loose is not None:
        return zf, names, None, None

    # Multiple nested packages (e.g. "Slippy.zip" + "Slippy (OLD).zip"):
    # prefer the largest — updated packages carry more (media, costumes).
    matches = []
    scanned = 0
    for n in names:
        if not n.lower().endswith('.zip') or scanned >= _NESTED_ZIP_SCAN_LIMIT:
            continue
        try:
            info = zf.getinfo(n)
        except KeyError:
            continue
        if info.file_size > _NESTED_ZIP_MAX_BYTES:
            continue
        scanned += 1
        try:
            inner = zipfile.ZipFile(io.BytesIO(zf.read(n)))
        except (zipfile.BadZipFile, OSError):
            continue
        if budget is not None:
            from core.safe_extract import preflight_zip
            # Descending into a nested package is a nesting level like any
            # other: `max_depth=0` used to accept one anyway. The occurrence is
            # the shared logical ancestry, so the safety pass that already
            # looked at this package does not pay for it twice.
            with budget.nested():
                preflight_zip(inner, budget=budget, occurrence=f'!{n}')
        inner_names = [m for m in inner.namelist()
                       if not m.startswith('__MACOSX') and not m.endswith('/')]
        if any(_norm(m).rsplit('/', 1)[-1].lower() == 'fighter.yml' for m in inner_names):
            matches.append((info.file_size, inner, inner_names))
    if matches:
        _, inner, inner_names = max(matches, key=lambda m: m[0])
        return inner, inner_names, zf, names
    raise ValueError('no fighter.yml in archive')


def _score_icon_candidate(name):
    """Rank CSS-icon candidates: explicit css-icon names beat plain icon.png
    beat *_icon.png beat anything mentioning icon; shallower paths win ties.
    Stock icons are excluded by the caller."""
    b = _norm(name).rsplit('/', 1)[-1].lower()
    depth = _norm(name).count('/')
    if 'css' in b and 'icon' in b:
        rank = 0
    elif b == 'icon.png':
        rank = 1
    elif b.endswith('_icon.png') or b.endswith(' icon.png'):
        rank = 2
    else:
        rank = 3
    return (rank, depth, len(b))


def _harvest_icon(sources):
    """Find the best CSS-icon png across (zf, names) source pairs, searched in
    order. Returns bytes or None."""
    for zf, names in sources:
        if zf is None:
            continue
        candidates = []
        for n in names:
            b = _norm(n).rsplit('/', 1)[-1].lower()
            if not b.endswith('.png') or 'icon' not in b:
                continue
            if 'stock' in b or 'stc' in b:
                continue
            candidates.append(n)
        if candidates:
            best = min(candidates, key=_score_icon_candidate)
            return zf.read(best)
    return None


def _fallback_icon_from_csp(csp_bytes):
    """Synthesize a CSS icon from a costume CSP: crop the head/torso region
    and scale to the 64x56 icon frame. Returns png bytes or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(csp_bytes)).convert('RGBA')
        w, h = img.size
        crop_h = int(w * 56 / 64)
        top = max(0, int(h * 0.06))
        img = img.crop((0, top, w, min(h, top + crop_h)))
        img = img.resize((64, 56), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, 'PNG')
        return out.getvalue()
    except Exception:
        return None


def _find_member(names_map, base_dir, ref):
    """Resolve a yml-referenced file: exact path relative to the yml's folder
    first, then unique basename match anywhere in the archive."""
    if not ref:
        return None
    ref = _norm(ref).lstrip('/')
    candidate = f'{base_dir}{ref}' if base_dir else ref
    if candidate.lower() in names_map:
        return names_map[candidate.lower()]
    base = ref.rsplit('/', 1)[-1].lower()
    matches = [v for k, v in names_map.items() if k.rsplit('/', 1)[-1] == base]
    return matches[0] if matches else None


def convert_fighter_yml_zip(zip_bytes, fallback_name, budget=None):
    """Convert a classic mexTool fighter package zip (fighter.yml + files,
    possibly nested in folders OR one level down inside a nested zip, with
    UI art kept beside it) into a modern fighter.json package zip.
    Returns (new_zip_bytes, info dict). Raises ValueError.

    Every archive layer is preflighted against the caller's cumulative
    `budget` before any of its members are read into memory.
    """
    from core.safe_extract import new_budget, preflight_zip
    budget = budget or new_budget()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as outer:
        preflight_zip(outer, budget=budget)
        outer_names = [n for n in outer.namelist()
                       if not n.startswith('__MACOSX') and not n.endswith('/')]

        zf, names, aux_zf, aux_names = find_fighter_package(outer, outer_names, budget=budget)
        names_map = {_norm(n).lower(): n for n in names}

        yml_member = next(n for n in names
                          if _norm(n).rsplit('/', 1)[-1].lower() == 'fighter.yml')
        base_dir = _norm(yml_member).rsplit('/', 1)[0] + '/' if '/' in _norm(yml_member) else ''

        fighter_json = convert_fighter_yml(
            zf.read(yml_member).decode('utf-8', errors='replace'), fallback_name)
        files = fighter_json['files']
        warnings = []

        out = io.BytesIO()
        added = set()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as oz:

            def add(member, arcname):
                key = arcname.lower()
                if key in added:
                    return True
                oz.writestr(arcname, zf.read(member))
                added.add(key)
                return True

            def add_ref(ref, required=False, label=None):
                if not ref:
                    return False
                member = _find_member(names_map, base_dir, ref)
                if member is None:
                    msg = f'referenced file missing from package: {ref}'
                    if required:
                        raise ValueError(msg)
                    warnings.append(f'{label or ref}: missing, skipped')
                    return False
                return add(member, Path(_norm(ref)).name)

            # fighter data files
            add_ref(files['fighterDataPath'], required=True)
            add_ref(files['animFile'], required=True)
            for key in ('demoFile', 'rstAnimFile', 'effectFile',
                        'kirbyEffectFile', 'kirbyCapFileName'):
                add_ref(files.get(key), label=key)

            # media (thp/mth are optional)
            for key, ref in fighter_json['media'].items():
                add_ref(ref, label=key)

            # costumes: each needs an inner <stem>.zip. Classic packages ship
            # either the ready-made costume zip or a loose dat (+csp/stc).
            kept = []
            first_csp = None
            for costume in fighter_json['costumes']:
                fname = costume['file']['fileName']
                stem = Path(fname).stem
                inner = _find_member(names_map, base_dir, f'{stem}.zip')
                if inner:
                    # EVERY carried costume archive is validated, not only the
                    # one that happens to answer the CSP search: the rest are
                    # copied into the package verbatim and read later, so
                    # checking them opportunistically checked nothing
                    # (2026-09-22 re-review, 1).
                    try:
                        costume_zip = zipfile.ZipFile(io.BytesIO(zf.read(inner)))
                    except (zipfile.BadZipFile, OSError) as exc:
                        raise ValueError(
                            f'costume archive {Path(_norm(inner)).name} could not be '
                            f'opened, so this package cannot be imported') from exc
                    with costume_zip:
                        with budget.nested():
                            preflight_zip(costume_zip, budget=budget,
                                          occurrence=f'!{_norm(inner)}')
                        if first_csp is None:
                            m = next((x for x in costume_zip.namelist()
                                      if x.rsplit('/', 1)[-1].lower()
                                      in ('csp.png', 'portrait.png', 'select.png')), None)
                            if m:
                                first_csp = costume_zip.read(m)
                    add(inner, f'{stem}.zip')
                    kept.append(costume)
                    continue
                loose = _find_member(names_map, base_dir, fname)
                if loose:
                    cbuf = io.BytesIO()
                    with zipfile.ZipFile(cbuf, 'w', zipfile.ZIP_DEFLATED) as cz:
                        cz.writestr(fname, zf.read(loose))
                        for img, arc in ((f'{stem}_csp.png', 'csp.png'), ('csp.png', 'csp.png'),
                                         (f'{stem}_stc.png', 'stc.png'), ('stc.png', 'stc.png')):
                            m = _find_member(names_map, base_dir, img)
                            if m and arc not in {i.lower() for i in cz.namelist()}:
                                cz.writestr(arc, zf.read(m))
                                if arc == 'csp.png' and first_csp is None:
                                    first_csp = zf.read(m)
                    oz.writestr(f'{stem}.zip', cbuf.getvalue())
                    added.add(f'{stem}.zip'.lower())
                    kept.append(costume)
                else:
                    warnings.append(f'costume {fname}: file missing, dropped')
            if not kept:
                raise ValueError('no costume files found in package')
            fighter_json['costumes'] = kept

            # Team-color costume indexes can point past the shipped costume
            # list (authors trim release packages below their dev build's
            # costume count — Shadow ships 1 costume with blue=3/green=4).
            # An out-of-range slot would break team battles; clamp to 0.
            for key in ('redCostumeIndex', 'blueCostumeIndex', 'greenCostumeIndex'):
                if fighter_json[key] >= len(kept):
                    fighter_json[key] = 0

            # kirby costumes: keep only entries whose files ship in the
            # package — dangling references would install broken cap slots.
            kept_kirby = []
            for kc in fighter_json['kirbyCostumes']:
                if add_ref(kc.get('fileName'), label='kirbyCostume'):
                    kept_kirby.append(kc)
            if len(kept_kirby) != len(fighter_json['kirbyCostumes']):
                dropped = len(fighter_json['kirbyCostumes']) - len(kept_kirby)
                warnings.append(f'{dropped} kirby costume(s) not in package, dropped')
            fighter_json['kirbyCostumes'] = kept_kirby
            fighter_json['hasKirbyCostumes'] = bool(kept_kirby)

            # sound.spk -> sound.zip
            spk_member = _find_member(names_map, base_dir, 'sound.spk')
            has_sound = False
            if spk_member:
                try:
                    sound_zip = spk_to_sound_zip(zf.read(spk_member), fighter_json['name'])
                    oz.writestr('sound.zip', sound_zip)
                    has_sound = True
                except ValueError as e:
                    warnings.append(f'sound.spk: {e} — fighter will be silent')
            else:
                warnings.append('no sound.spk — fighter will be silent')

            # announcer name-call and victory theme, re-applied post-install
            # by the vault (see install path in projects/routes/custom_characters.py)
            has_announcer = False
            m = _find_member(names_map, base_dir, 'namecall.wav') \
                or _find_member(names_map, base_dir, 'announcer.wav')
            if m:
                oz.writestr('announcer.wav', zf.read(m))
                has_announcer = True

            victory_name = None
            doc = yaml.safe_load(zf.read(yml_member).decode('utf-8', errors='replace'))
            vt = (doc.get('victoryTheme') or {}) if isinstance(doc, dict) else {}
            for source in (vt, (doc.get('fighterSongID1') or {}) if isinstance(doc, dict) else {}):
                ref = source.get('fileName') if isinstance(source, dict) else None
                if not ref:
                    continue
                m = _find_member(names_map, base_dir, ref)
                if m:
                    oz.writestr('victory_theme.hps', zf.read(m))
                    victory_name = (source.get('label') or Path(ref).stem)
                    break

            # pass-throughs add-fighter knows how to merge
            for n in names:
                nn = _norm(n).lower()
                bn = nn.rsplit('/', 1)[-1]
                if bn in ('codes.ini', 'fighter_codes.ini', 'fsm.txt'):
                    add(n, _norm(n).rsplit('/', 1)[-1])
                elif '/patches/' in nn or nn.startswith('patches/'):
                    if nn.endswith('.dat'):
                        add(n, f"patches/{nn.rsplit('/', 1)[-1]}")

            # CSS icon: community posts keep the UI art NEXT TO the package
            # (UI/CSS icon.png, <name>_icon.png, ...), so search the outer
            # archive first, then the package itself; failing both, synthesize
            # one from the first costume's CSP so the roster grid never shows
            # a blank slot.
            has_icon = False
            icon_bytes = _harvest_icon([(aux_zf, aux_names or []), (zf, names)])
            icon_source = 'package'
            if icon_bytes is None and first_csp is not None:
                icon_bytes = _fallback_icon_from_csp(first_csp)
                icon_source = 'generated from CSP'
            if icon_bytes:
                oz.writestr('icon.png', icon_bytes)
                added.add('icon.png')
                has_icon = True
                if icon_source != 'package':
                    warnings.append(f'CSS icon {icon_source}')

            if victory_name:
                oz.writestr('vault_meta.json', json.dumps({'victory_theme_name': victory_name}))
            oz.writestr('fighter.json', json.dumps(fighter_json, indent=2))

        info = {
            'name': fighter_json['name'],
            'costumes': len(fighter_json['costumes']),
            'has_sound': has_sound,
            'has_announcer': has_announcer,
            'has_icon': has_icon,
            'victory_theme': victory_name,
            'warnings': warnings,
        }
        return out.getvalue(), info
