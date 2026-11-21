"""
Pure content-type detection for the unified import endpoint.

Classifies an uploaded archive WITHOUT importing anything — no storage writes,
no metadata mutation. The /import/file route dispatches on the result.

Types, in dispatch priority order:
    custom_character        zip containing fighter.json (full fighter package)
    custom_stage            zip containing stage.json (Nucleus stage package)
    mex_stage_yml           zip containing stage.yml (classic m-ex stage
                            package; recognized but needs yml→json conversion)
    bundle                  .ssbm extension, or manifest.json + textures/*.png
    character               costume DAT(s) detected by character_detector
    stage                   stage DAT(s) detected by stage_detector -- any
                            versus stage code in core/stages.py (the 6 DAS
                            stages and the 23 replace-slot stages alike);
                            all land in the vault as stage skins
    xdelta                  .xdelta extension or .xdelta member(s)
    css_icon_grid           '='-prefixed icon PNGs, or MnSlChr/MexSelectChr dat
    pause_screen            GmPause*.dat/.usd member
    percent_font            IfAll*.dat/.usd member (HUD percent typeface), or
                            a loose pack of digit / word-banner images
                            (detail.pack = 'glyphs' | 'words')
    css_background          MnSlMap (SSS) dat; MnSlChr ambiguous w/ icon grid
    css_doors               image(s) named 'door' or sized like the 128x200
                            CSS door texture
    pause_picture           a picture for the pause screen's central graphic
                            ('pause' in the name, or a wide lone image)
    effect_image            a lone image whose name or exact size matches an
                            image-capable extra (256x256 shine picture,
                            128x128 shield texture) -- detail names the
                            character + extra_type
    effect                  Ef*Data.dat / Pl*.dat effect files whose editable
                            layers were read by the extras offset system;
                            detail.dats[].candidates say which extra types
                            differ from vanilla (see effect_detect.py)
    music                   .hps extension or .hps member(s)
    character_renamed       costume DAT(s) whose filenames don't start with
                            'Pl' but whose contents parse to a known character
                            (e.g. lucinablack.dat → Marth). Not yet importable:
                            character_detector's filename filter skips them.
    custom_fighter_costume  DAT(s) with Ply joint symbols but no vanilla
                            character match (Akaneia Sonic/Knuckles etc.) —
                            belongs in a custom character's skin list
    ic_half                 only unpaired Popo-only / Nana-only costumes
                            (importable once the matching half is provided)
    effect_unsupported      a character's data / effect file (PlPe.dat,
                            EfPeData.dat) that no extra type reads yet --
                            informational, names the character
    dolphin_textures        Dolphin texture pack (tex1_*.png hash names)
    sound_bank              .spk / .ssm sound files
    unsupported_audio       mp3/wav/ogg (not .hps — can't go into an ISO)
    nested_archive          nothing recognized directly, but contains inner
                            archives worth recursing into
    unknown                 nothing recognized

Lone images and effect DATs are the two genuinely ambiguous inputs. Their
results carry confidence 'medium'/'low' with every plausible type in
`candidates` so the route can ask the user instead of guessing; a filename
keyword ('door', 'pause', 'shield', 'shine') or an exact texture size makes
them 'high'. The website's nucleus:// links still pass explicit
mod_type / effect_type hints, which bypass detection entirely.

Returned dict:
    {
        'type': <one of the above>,
        'confidence': 'high' | 'medium' | 'low',
        'candidates': [types...],   # every plausible type, best first
        'detail': {...},            # payload for the chosen type
        'all_details': {...},       # payloads for every candidate
    }
"""

import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path

from vault.importing.character_detector import detect_character_from_zip, DATParser, read_7z_member
from vault.importing.stage_detector import detect_stage_from_zip

# py7zr is imported LAZILY, only when a .7z is actually handled. Importing it
# pulls in multiprocessing, and in a PyInstaller build that machinery can
# re-execute the app (see the freeze_support() note in app.py). find_spec
# answers "is 7z support available?" without paying that cost.
import importlib.util as _importlib_util

HAS_7Z = _importlib_util.find_spec("py7zr") is not None


def _py7zr():
    """Import py7zr on demand. Callers must check HAS_7Z first."""
    import py7zr
    return py7zr

logger = logging.getLogger(__name__)

ARCHIVE_EXTS = {'.zip', '.7z', '.rar'}
AUDIO_EXTS = {'.mp3', '.wav', '.ogg', '.m4a', '.flac'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
# Members that never decide a type (readmes, OS droppings) -- an archive of
# images plus a readme is still "an archive of images".
JUNK_EXTS = {'.txt', '.md', '.ini', '.url', '.ds_store', '.nfo', ''}
MAX_FALLBACK_DAT_PARSES = 8
DOOR_SIZE = (128, 200)

# Container recursion: a zip of skin zips recurses one level, and an inner
# zip may itself wrap one more archive (site downloads often double-wrap).
# These container boundaries are shared by the importer (archive.py) and the
# chat download preflight (randall/website/website_safety.py), so both
# walk an archive the same way.
MAX_CONTAINER_DEPTH = 2

# Shallow-detected package types that legitimately contain nested archives
# (fighter packages ship sound.zip etc.) — never treat these as containers.
_PACKAGE_TYPES = {'custom_character', 'custom_stage', 'bundle',
                  'mex_stage_yml', 'mex_fighter_yml'}

_INNER_ARCHIVE_EXTS = {'.zip', '.7z', '.rar'}


def _archive_names(archive_path):
    """List member names of a zip/7z archive, excluding macOS junk.
    Returns None if the file can't be read as an archive."""
    path = Path(archive_path)
    try:
        if path.suffix.lower() == '.7z':
            if not HAS_7Z:
                return None
            with _py7zr().SevenZipFile(path, 'r') as sz:
                names = sz.getnames()
        else:
            with zipfile.ZipFile(path, 'r') as zf:
                names = zf.namelist()
    except Exception:
        return None
    return [n for n in names
            if not n.startswith('__MACOSX') and not Path(n).name.startswith('._')]


def _list_inner_archives(temp_zip_path):
    """First-level archive members (.zip/.7z/.rar) of a zip/7z, macOS junk
    and directory entries excluded. Empty list if none or unreadable."""
    names = _archive_names(temp_zip_path)
    if not names:
        return []
    return [n for n in names
            if not n.endswith('/')
            and Path(n).suffix.lower() in _INNER_ARCHIVE_EXTS]


def _read_member(archive_path, member):
    """Read one member's bytes from a zip/7z archive; None on failure."""
    path = Path(archive_path)
    try:
        if path.suffix.lower() == '.7z':
            if not HAS_7Z:
                return None
            with _py7zr().SevenZipFile(path, 'r') as sz:
                return read_7z_member(sz, member)
        with zipfile.ZipFile(path, 'r') as zf:
            return zf.read(member)
    except Exception:
        return None


def _find_member(names, basename_lower):
    """First member whose basename matches (case-insensitive), else None."""
    for n in names:
        if Path(n).name.lower() == basename_lower:
            return n
    return None


def _nested_zip_has_member(archive_path, names, basename_lower,
                           scan_limit=8, max_bytes=200 * 1024 * 1024, budget=None,
                           occurrence=''):
    """True if a first-level nested .zip contains a member with this basename.

    Reads at most `scan_limit` nested zips' central directories. This decides
    that an archive is a *package*, which used to exempt everything inside it
    from the download resource limits, so the nested archive is charged against
    the operation's cumulative budget here -- before the classification that
    grants it package status.
    """
    import io
    from core.safe_extract import ArchiveBudgetExceeded, preflight_zip
    scanned = 0
    try:
        with zipfile.ZipFile(archive_path) as zf:
            for n in names:
                if not n.lower().endswith('.zip') or scanned >= scan_limit:
                    continue
                try:
                    if zf.getinfo(n).file_size > max_bytes:
                        continue
                    scanned += 1
                    with zipfile.ZipFile(io.BytesIO(zf.read(n))) as inner:
                        if budget is not None:
                            # Raises before the caller can classify this as a
                            # package: a declared bomb never becomes exempt.
                            # The occurrence name is the one every pass uses
                            # (`<archive path>!<member>`), so inspecting this
                            # child twice costs the allowance once.
                            preflight_zip(inner, budget=budget,
                                          occurrence=f'{occurrence}!{n}')
                        if any(Path(m).name.lower() == basename_lower
                               for m in inner.namelist()):
                            return True
                except ArchiveBudgetExceeded:
                    raise
                except (KeyError, zipfile.BadZipFile, OSError):
                    continue
    except (zipfile.BadZipFile, OSError):
        return False
    return False


import struct as _struct

# Root symbol -> which menu file a DAT really is, whatever it was named.
_MENU_ROOT_SYMBOLS = {
    'MnSelectChrDataTable': 'mnslchr',     # character select scene
    'MnSelectMapDataTable': 'mnslmap',     # stage select scene
    'ScGamPause_scene_data': 'gmpause',    # pause overlay
    'DmgNum_scene_models': 'ifall',        # HUD percent digits ...
    'ScInfDmg_scene_data': 'ifall',        # ... and the rest of IfAll
    'ScInfStc_scene_models': 'ifall',
    'ScInfTim_scene_models': 'ifall',
}


def dat_root_symbols(data):
    """Root symbol names of a HAL DAT (header + root table), [] if malformed."""
    try:
        if len(data) < 0x20:
            return []
        file_size, data_size, reloc_count, root_count, ref_count = _struct.unpack('>5I', data[:0x14])
        if file_size > len(data) or data_size + 0x20 > len(data):
            return []
        root_off = 0x20 + data_size + reloc_count * 4
        str_off = root_off + (root_count + ref_count) * 8
        if root_count > 64 or str_off > len(data):
            return []
        out = []
        for i in range(root_count):
            _, s = _struct.unpack('>II', data[root_off + i * 8: root_off + i * 8 + 8])
            end = data.find(b'\0', str_off + s)
            if end < 0:
                return []
            out.append(data[str_off + s:end].decode('ascii', 'replace'))
        return out
    except Exception:
        return []


def _menu_kind_from_dat_roots(archive_path, names, limit=8):
    """'mnslchr' / 'mnslmap' / 'gmpause' / 'ifall' when one of the archive's
    .dat/.usd members carries that menu file's root symbol, else None. Only
    the first few DATs are read (the header is enough; nothing decodes)."""
    dats = [n for n in names if n.lower().endswith(('.dat', '.usd'))
            and not n.endswith('/')][:limit]
    for member in dats:
        try:
            data = _read_member(archive_path, member)
        except Exception:
            continue
        if not data:
            continue
        for sym in dat_root_symbols(data):
            kind = _MENU_ROOT_SYMBOLS.get(sym)
            if kind:
                return kind
    return None


def detect_content_type(archive_path, filename=None, deep=True, budget=None,
                        occurrence=''):
    """Classify an archive for import. Pure — never writes anything.

    archive_path: path to the file on disk (zip/7z/raw file)
    filename: original upload filename (extension fast-paths); defaults to
              archive_path's own name
    deep: run the DAT-parsing character/stage detectors and the content
          fallback. With deep=False only cheap name heuristics run.
    budget: the operation's cumulative extraction budget (core.safe_extract).
          Classification can look inside nested archives, and a nested
          `fighter.yml` is what makes the OUTER archive a package, so those
          reads are charged here instead of being free.
    """
    filename = filename or Path(archive_path).name
    ext = Path(filename).suffix.lower()

    # ── extension fast-paths (no archive open needed) ────────────────────────
    if ext == '.xdelta':
        return _result('xdelta', 'high', detail={'patch_count': 1})
    if ext == '.ssbm':
        return _detect_bundle(archive_path, from_extension=True)
    if ext == '.hps':
        return _result('music', 'high', detail={'track_count': 1})

    names = _archive_names(archive_path)
    if names is None:
        # Raw .dat/.usd files are wrapped in a temp zip by the route before
        # detection, so an unreadable archive here is a hard unknown.
        return _result('unknown', 'low', detail={'error': 'unreadable archive'})

    basenames = [Path(n).name.lower() for n in names if not n.endswith('/')]
    candidates = []
    details = {}

    def add(type_, detail=None):
        candidates.append(type_)
        details[type_] = detail or {}

    # ── package markers (must beat raw dat detection: a fighter package is ──
    # ── full of Pl*.dat files that would misclassify as costumes) ───────────
    fighter_json = _find_member(names, 'fighter.json')
    if fighter_json is not None:
        add('custom_character',
            _package_detail(archive_path, fighter_json))

    stage_json = _find_member(names, 'stage.json')
    if stage_json is not None:
        add('custom_stage', _package_detail(archive_path, stage_json))

    stage_yml = _find_member(names, 'stage.yml')
    dat_basenames = [b for b in basenames if b.endswith(('.dat', '.usd'))]
    if stage_yml is not None and dat_basenames:
        add('mex_stage_yml', {'dats': dat_basenames})

    # classic mexTool fighter package (fighter.yml). Must be a marker: these
    # zips are full of Pl*.dat + .hps files that would otherwise misclassify
    # as costumes or hit the music refusal. Community posts often wrap the
    # package one level down in a nested zip with the UI art beside it, so a
    # nested fighter.yml counts too (the converter recurses the same way).
    fighter_yml = _find_member(names, 'fighter.yml')
    if fighter_yml is None and fighter_json is None:
        if _nested_zip_has_member(archive_path, names, 'fighter.yml', budget=budget,
                                  occurrence=occurrence):
            fighter_yml = 'nested'
    if fighter_yml is not None and fighter_json is None and (dat_basenames or fighter_yml == 'nested'):
        add('mex_fighter_yml', {'dats': dat_basenames, 'nested': fighter_yml == 'nested'})

    has_manifest = 'manifest.json' in names or 'manifest.json' in basenames
    texture_pngs = [n for n in names
                    if n.startswith('textures/') and n.lower().endswith('.png')]
    if has_manifest and texture_pngs:
        add('bundle', {'texture_count': len(texture_pngs)})

    is_package = bool(candidates)

    # ── costume / stage DAT detection (the expensive, accurate pass) ────────
    char_infos = []
    if deep and not is_package:
        try:
            char_infos = detect_character_from_zip(str(archive_path))
        except Exception as e:
            logger.warning(f'character detection failed: {e}')
        if char_infos:
            add('character', {
                'costumes': [{'character': c['character'], 'color': c['color']}
                             for c in char_infos],
                'char_infos': char_infos,
            })

        try:
            stage_infos = detect_stage_from_zip(str(archive_path))
        except Exception as e:
            logger.warning(f'stage detection failed: {e}')
            stage_infos = []
        if stage_infos:
            add('stage', {
                'stages': [s['stage_name'] for s in stage_infos],
                'stage_infos': stage_infos,
            })
    elif not deep:
        # cheap name-based approximation for harness fast mode
        pl_dats = [b for b in dat_basenames if b.startswith('pl')]
        gr_dats = [b for b in dat_basenames if b.startswith('gr')]
        if pl_dats and not is_package:
            add('character', {'dat_names': pl_dats})
        if gr_dats and not is_package:
            add('stage', {'dat_names': gr_dats})

    # (Raw GrXx.dat mods for the non-tournament versus stages are ordinary
    # 'stage' hits now -- stage_detector covers every stage in core/stages.py
    # and they land in the vault as stage skins like the DAS six.)

    # ── patches ──────────────────────────────────────────────────────────────
    xdeltas = [b for b in basenames if b.endswith('.xdelta')]
    if xdeltas:
        add('xdelta', {'patch_count': len(xdeltas)})

    # ── menu mods ────────────────────────────────────────────────────────────
    equals_pngs = [b for b in basenames if b.startswith('=') and b.endswith('.png')]
    has_mnslchr = any(('mnslchr' in b or b == 'mexselectchr.dat')
                      and b.endswith(('.dat', '.usd')) for b in basenames)
    has_mnslmap = any('mnslmap' in b and b.endswith(('.dat', '.usd'))
                      for b in basenames)
    has_gmpause = any('gmpause' in b and b.endswith(('.dat', '.usd'))
                      for b in basenames)
    has_ifall = any(b.startswith('ifall') and b.endswith(('.dat', '.usd'))
                    for b in basenames)
    # Menu files travel under any name ("Halo3CSS.dat" was a MnSlChr): when
    # the filename says nothing, the DAT's own root symbols do. Reported as
    # "can't be imported (unsupported file type)" for a CSS background that
    # the Menus page's own picker would have accepted.
    if not (has_mnslchr or has_mnslmap or has_gmpause or has_ifall):
        menu_kind = _menu_kind_from_dat_roots(archive_path, names)
        has_mnslchr = has_mnslchr or menu_kind == 'mnslchr'
        has_mnslmap = has_mnslmap or menu_kind == 'mnslmap'
        has_gmpause = has_gmpause or menu_kind == 'gmpause'
        has_ifall = has_ifall or menu_kind == 'ifall'

    if len(equals_pngs) >= 2 or has_mnslchr:
        add('css_icon_grid', {'icon_pngs': len(equals_pngs),
                              'has_mnslchr': has_mnslchr})
    if has_gmpause:
        add('pause_screen')
    if has_ifall:
        add('percent_font')
    if has_mnslmap or has_mnslchr:
        # MnSlMap is unambiguously a background source; MnSlChr could be either
        # an icon-grid source or a CSS background source.
        add('css_background', {'source': 'sss' if has_mnslmap else 'css'})

    # ── loose images: glyph / word packs, door textures, pause pictures, ────
    # ── effect pictures (shine images, shield textures) ─────────────────────
    file_members = [n for n in names if not n.endswith('/')
                    and Path(n).suffix.lower() not in JUNK_EXTS]
    image_members = [n for n in file_members
                     if Path(n).suffix.lower() in IMAGE_EXTS
                     and not Path(n).name.startswith('.')]
    if image_members and not candidates and len(image_members) == len(file_members):
        for type_, detail in _classify_images(archive_path, image_members):
            add(type_, detail)

    # ── music ────────────────────────────────────────────────────────────────
    hps = [b for b in basenames if b.endswith('.hps')]
    if hps:
        add('music', {'track_count': len(hps)})

    # ── unpaired Ice Climbers halves: pl-named IC dats that deep detection ──
    # ── dropped because no Popo/Nana partner exists in this zip. Must run ───
    # ── before the content fallback, which would claim them as 'renamed'. ───
    if deep and not candidates and dat_basenames and not char_infos:
        ic_dats = [b for b in dat_basenames
                   if b.startswith(('plpp', 'plnn'))]
        if ic_dats and len(ic_dats) == len([b for b in dat_basenames
                                            if b.startswith('pl')]) == len(dat_basenames):
            half = 'popo' if ic_dats[0].startswith('plpp') else 'nana'
            add('ic_half', {'half': half, 'dats': ic_dats})

    # ── content fallback: dats that defeated the name-based detectors. ──────
    # ── Also covers the old website's renamed-extension convention for ──────
    # ── alternate variants (.rat/.lat/.0at… are plain dats renamed). ────────
    if deep and not candidates:
        fb_type, fb_detail = _classify_dats_by_content(archive_path, names)
        if fb_type:
            add(fb_type, fb_detail)

    # ── effect files (EfFxData.dat, EfCoData.dat, PlFx.dat...): which of the ─
    # ── extras that target this file actually differ from vanilla ──────────
    if deep and not candidates:
        eff = _classify_effect_dats(archive_path, names)
        if eff:
            add('effect', eff)

    # ── informational last resorts ───────────────────────────────────────────
    if not candidates:
        # A character's own data file (PlPe.dat) or effect file for which no
        # extra type exists yet: say so instead of "could not detect".
        unsupported = _unsupported_effect_dats(dat_basenames)
        if unsupported:
            add('effect_unsupported', unsupported)

        tex_pngs = [b for b in basenames
                    if b.startswith('tex1_') and b.endswith('.png')]
        if tex_pngs:
            add('dolphin_textures', {'texture_count': len(tex_pngs)})

        sound_files = [b for b in basenames if b.endswith(('.spk', '.ssm'))]
        if not candidates and sound_files:
            add('sound_bank', {'files': sound_files})

        audio = [b for b in basenames if Path(b).suffix in AUDIO_EXTS]
        if not candidates and audio:
            add('unsupported_audio', {'count': len(audio),
                                      'extensions': sorted({Path(b).suffix for b in audio})})

        inner = [b for b in basenames if Path(b).suffix in ARCHIVE_EXTS]
        if not candidates and inner:
            add('nested_archive', {'archives': inner})

    if not candidates:
        return _result('unknown', 'low',
                       detail={'member_count': len(basenames),
                               'sample': basenames[:10]})

    chosen = candidates[0]
    # MnSlChr-only zips are genuinely ambiguous (icon grid vs background);
    # default to icon grid to match the historical cascade order.
    ambiguous = (chosen == 'css_icon_grid' and not equals_pngs
                 and 'css_background' in candidates)
    confidence = 'medium' if (ambiguous or len(candidates) > 1) else 'high'
    # Image and effect classification grade themselves (a 'door' in the
    # filename is certain even when a second candidate was listed).
    graded = details.get(chosen, {}).get('confidence')
    if graded:
        confidence = graded

    return _result(chosen, confidence, candidates=candidates,
                   detail=details.get(chosen, {}), all_details=details)


# ── images ───────────────────────────────────────────────────────────────────

def _image_dims(archive_path, member):
    """(width, height) of an image member, or None when it can't be decoded."""
    data = _read_member(archive_path, member)
    if not data:
        return None
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


def _image_extra_targets():
    """Extras that accept a picture: [(owner, cfg, (w, h), keywords)].
    Keywords come from the extra's id/name ('shine', 'shield')."""
    from core.extra_types import EXTRA_TYPES
    out = []
    for owner, extras in EXTRA_TYPES.items():
        for cfg in extras:
            spec = cfg.get('image_model') or cfg.get('texture_region')
            if not spec:
                continue
            try:
                size = (int(str(spec['width']), 0), int(str(spec['height']), 0))
            except (KeyError, ValueError):
                continue
            words = set(cfg['id'].split('_')) | set(cfg.get('name', '').lower().split())
            words -= {'common', 'color', 'colors', 'texture', ''}
            out.append((owner, cfg, size, sorted(words)))
    return out


def _classify_single_image(archive_path, member):
    """Candidates for ONE loose picture, best first. Filename keywords are
    certain; exact texture sizes are strong; otherwise the shape decides
    with low confidence and the route asks."""
    name = Path(member).name
    lower = name.lower()
    dims = _image_dims(archive_path, member)
    w, h = dims or (0, 0)
    out = []

    def door(conf):
        out.append(('css_doors', {'images': [name], 'width': w, 'height': h, 'confidence': conf}))

    def pause(conf):
        out.append(('pause_picture', {'images': [name], 'width': w, 'height': h, 'confidence': conf}))

    def effect(conf, owner, cfg):
        out.append(('effect_image', {'image': name, 'character': owner,
                                     'extra_type': cfg['id'], 'name': cfg.get('name', cfg['id']),
                                     'width': w, 'height': h, 'confidence': conf}))

    targets = _image_extra_targets()

    # 1. the filename says what it is
    if 'door' in lower:
        door('high')
        return out
    if 'pause' in lower:
        pause('high')
        return out
    for owner, cfg, _size, keywords in targets:
        if any(k in lower for k in keywords):
            effect('high', owner, cfg)
            return out

    # 2. an exact texture size
    if (w, h) == DOOR_SIZE:
        door('high')
        return out
    exact = [(o, c) for o, c, size, _ in targets if size == (w, h)]
    if exact:
        effect('medium', *exact[0])
        pause('medium')
        return out

    # 3. shape only -- never certain
    if w and h:
        if abs(w / h - DOOR_SIZE[0] / DOOR_SIZE[1]) <= 0.06:
            door('medium')
            pause('medium')
        elif w > h:
            pause('medium')
            door('medium')
        else:
            door('low')
            pause('low')
        return out
    pause('low')
    door('low')
    return out


def _classify_images(archive_path, members):
    """Candidates for an archive that holds nothing but pictures."""
    from core.hud_words import word_key_for_name, digit_key_for_name
    basenames = [Path(m).name.lower() for m in members]
    digits = {k for k in (digit_key_for_name(b) for b in basenames) if k}
    words = {k for k in (word_key_for_name(b) for b in basenames) if k}
    if len(digits) == 10:
        return [('percent_font', {'pack': 'glyphs', 'images': len(members), 'confidence': 'high'})]
    if len(words) >= 3:
        return [('percent_font', {'pack': 'words', 'category': 'readygo',
                                  'images': len(members), 'confidence': 'high'})]
    if len(members) == 1:
        return _classify_single_image(archive_path, members[0])

    names = [Path(m).name for m in members]
    if all('door' in b for b in basenames):
        return [('css_doors', {'images': names, 'confidence': 'high'})]
    if all('pause' in b for b in basenames):
        return [('pause_picture', {'images': names, 'confidence': 'high'})]
    # several unrelated pictures: a batch of doors or of pause pictures
    return [('css_doors', {'images': names, 'confidence': 'low'}),
            ('pause_picture', {'images': names, 'confidence': 'low'})]


# ── effects ──────────────────────────────────────────────────────────────────

def _unsupported_effect_dats(dat_basenames):
    """Character data / effect files that look like effect mods but have no
    extra type reading them: {'dats': [...], 'characters': [...]} or None."""
    import re
    from core.extra_types import CHAR_DAT_PREFIX
    from .effect_detect import match_target
    by_prefix = {v.lower(): k for k, v in CHAR_DAT_PREFIX.items()}
    dats, characters = [], []
    for b in dat_basenames:
        stem = Path(b).stem.lower()
        if match_target(b)[0]:
            continue  # a supported effect file (handled earlier)
        m = re.match(r'^(pl[a-z]{2})(?![a-z])', stem) or re.match(r'^ef([a-z]{2})data', stem)
        if not m:
            continue
        code = m.group(1) if stem.startswith('pl') else 'pl' + m.group(1)
        char = by_prefix.get(code)
        if not char:
            continue
        dats.append(b)
        if char not in characters:
            characters.append(char)
    if not dats:
        return None
    return {'dats': dats, 'characters': characters}


def _classify_effect_dats(archive_path, names):
    """For every member that is a known effect file, which extra types can
    read it and whether they differ from vanilla. None when no member is an
    effect file at all."""
    from .effect_detect import match_target, candidate_effects
    found = []
    dat_members = [n for n in names
                   if _looks_like_dat_extension(Path(n).suffix.lower())
                   and not n.endswith('/')][:MAX_FALLBACK_DAT_PARSES]
    for member in dat_members:
        target, entries = match_target(Path(member).name)
        if not target:
            continue
        data = _read_member(archive_path, member)
        if not data:
            continue
        try:
            cands = candidate_effects(data, Path(member).name)
        except Exception as e:
            logger.warning(f'effect detection failed for {member}: {e}')
            cands = []
        found.append({'dat': Path(member).name, 'member': member,
                      'target_file': target, 'candidates': cands})
    if not found:
        return None
    differing = [c for f in found for c in f['candidates'] if c['differs']]
    undecided = [c for f in found for c in f['candidates'] if c['differs'] is None]
    if differing:
        confidence = 'high' if (len(differing) == 1 and len(found) == 1) else 'medium'
    elif undecided:
        confidence = 'low'
    else:
        confidence = 'low'
    return {'dats': found, 'confidence': confidence}


def _looks_like_dat_extension(suffix):
    """.dat/.usd, plus the old website's alternate-variant renames
    (.rat, .lat, .0at–.9at, .aat… — all plain dats with a letter swapped)."""
    if suffix in ('.dat', '.usd'):
        return True
    return len(suffix) == 4 and suffix.endswith('at') and suffix[1].isalnum()


def _classify_dats_by_content(archive_path, names):
    """Parse up to MAX_FALLBACK_DAT_PARSES dats by content. Catches costume
    dats with arbitrary filenames (lucinablack.dat → Marth) and costumes for
    non-vanilla fighters (Ply symbols, no character match)."""
    if DATParser is None:
        return None, None

    dat_members = [n for n in names
                   if _looks_like_dat_extension(Path(n).suffix.lower())
                   and not n.endswith('/')][:MAX_FALLBACK_DAT_PARSES]
    renamed = []
    custom_fighter = []
    for member in dat_members:
        data = _read_member(archive_path, member)
        if not data:
            continue
        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            parser = DATParser(tmp_path)
            parser.read_dat()
            character, _symbol = parser.detect_character()
            has_ply = any('Ply' in node['symbol'] for node in parser.root_nodes)
            if not has_ply:
                continue
            if character:
                renamed.append({'dat': Path(member).name,
                                'character': character,
                                'costume_code': parser.get_character_filename()})
            else:
                custom_fighter.append({'dat': Path(member).name})
        except Exception:
            continue
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if renamed:
        return 'character_renamed', {'costumes': renamed}
    if custom_fighter:
        return 'custom_fighter_costume', {'dats': [d['dat'] for d in custom_fighter]}
    return None, None


def _result(type_, confidence, candidates=None, detail=None, all_details=None):
    return {
        'type': type_,
        'confidence': confidence,
        'candidates': candidates or [type_],
        'detail': detail or {},
        'all_details': all_details or {},
    }


def _package_detail(archive_path, member, name_key='name'):
    """Pull the display name out of a fighter.json / stage.json marker."""
    data = _read_member(archive_path, member)
    if not data:
        return {}
    try:
        meta = json.loads(data)
        return {'name': meta.get(name_key)}
    except (ValueError, UnicodeDecodeError):
        return {}


def _detect_bundle(archive_path, from_extension=False):
    names = _archive_names(archive_path) or []
    if 'manifest.json' not in names:
        if from_extension:
            return _result('bundle', 'medium',
                           detail={'warning': 'no manifest.json'})
        return _result('unknown', 'low', detail={'error': 'no manifest.json'})
    name = None
    data = _read_member(archive_path, 'manifest.json')
    if data:
        try:
            name = json.loads(data).get('name')
        except (ValueError, UnicodeDecodeError):
            pass
    textures = [n for n in names
                if n.startswith('textures/') and n.lower().endswith('.png')]
    return _result('bundle', 'high',
                   detail={'name': name, 'texture_count': len(textures)})
