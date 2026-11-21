"""
A custom character package into the vault: a fighter ZIP (MexManager export)
or a Nucleus full-vault export (the fighter plus its stored skins and assets)
becomes a storage/custom_characters/<slug>/ entry and an index row. Audio in
the package is normalized through MexCLI on the way in.

No routes. Used by the Custom Characters routes (vault/routes/custom_characters/),
the unified import (vault/importing/unified/archive.py), Echo clones and the Ice
Climbers pair builder. The full-vault export markers are shared with the export
route.
"""

import json
import tempfile
import zipfile
import logging
import mexcli.commands
from pathlib import Path
from datetime import datetime
from core.config import CUSTOM_CHARACTERS_PATH
from core.metadata import metadata_transaction
from vault.importing.custom_character_package import (DEFAULT_META as _DEFAULT_META,
    make_slug as _make_slug)
from vault.catalog.custom_characters import _dedupe_slug

logger = logging.getLogger(__name__)


def _append_custom_character(entry):
    """Thread-safe append of one entry to the vault's custom_characters list.
    The transaction makes the read-modify-write atomic across concurrent imports
    (a multi-file drag fires many /import/file at once); without it entries were
    lost — this is what dropped the seeded Giga Bowser."""
    with metadata_transaction(default=dict(_DEFAULT_META)) as metadata:
        metadata.setdefault('custom_characters', []).append(entry)


def _normalize_character_zip_audio(zf, audio_members):
    """Validate and normalize portable fighter audio before vault writes.

    ``audio_members`` maps ZIP member names to ``victory`` or ``announcer``.
    Victory HPS is always re-encoded by audio-to-hps (including native HPS),
    which also normalizes stereo/loop state. Announcer WAV takes the same
    validation path and is decoded back to a canonical WAV. A bad member raises
    ValueError before the caller creates a vault directory or metadata entry.
    """
    if not audio_members:
        return {}

    normalized = {}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for ordinal, (member, kind) in enumerate(audio_members.items()):
            source = td / f'{ordinal}_source{Path(member).suffix.lower()}'
            hps = td / f'{ordinal}_normalized.hps'
            source.write_bytes(zf.read(member))
            out = mexcli.commands.run_json(['audio-to-hps', source, hps])
            label = 'victory_theme.hps' if kind == 'victory' else 'announcer.wav'
            if not out.get('success') or not hps.exists():
                detail = out.get('error', 'Audio conversion failed')
                raise ValueError(f"Invalid {label}: {detail}")

            if kind == 'victory':
                normalized[member] = hps.read_bytes()
                continue

            wav = td / f'{ordinal}_normalized.wav'
            decoded = mexcli.commands.run_json(['hps-to-wav', hps, wav])
            if not decoded.get('success') or not wav.exists():
                detail = decoded.get('error', 'WAV normalization failed')
                raise ValueError(f"Invalid {label}: {detail}")
            normalized[member] = wav.read_bytes()

    return normalized


# Everything _build_full_vault_export_bytes can legitimately put in the zip.
# The restore used to accept arbitrary members, so an approved package could
# carry anything the host OS would later open (see the 2026-09-22 review).
_RESTORE_ALLOWED_SUFFIXES = frozenset({
    '.json', '.zip', '.png', '.jpg', '.jpeg', '.webp', '.gif',
    '.dat', '.usd', '.hps', '.wav', '.txt', '.sem', '.ssm', '.spk', '.md',
})


def _restore_full_vault_export(zf, payload, fallback_name, budget=None):
    """Restore a full-vault custom-character export (see export_custom_character).

    Every member is validated by the shared extractor first (components, not a
    string prefix), the payload is written into a FRESH staging folder, and
    only a completely validated tree is committed into the vault. Members
    outside the export's own file types are refused rather than skipped: a
    package that carries them is not one of ours.
    """
    from core.safe_extract import (
        UnsafeArchiveMember, extract_zip_to_new_directory, member_parts, new_budget)

    budget = budget or new_budget()
    entry = dict(payload.get('entry') or {})
    name = entry.get('name') or fallback_name
    slug = _dedupe_slug(_make_slug(name))
    char_dir = CUSTOM_CHARACTERS_PATH / slug

    wanted, audio_members = [], {}
    for member in zf.namelist():
        if member == NUCLEUS_EXPORT_MARKER or member.endswith('/'):
            continue
        parts = member_parts(member)  # raises UnsafeArchiveMember
        suffix = Path(parts[-1]).suffix.lower()
        if suffix not in _RESTORE_ALLOWED_SUFFIXES:
            raise UnsafeArchiveMember(
                f"this export carries a file type Nucleus never writes: {parts[-1]}")
        wanted.append(member)
        basename = parts[-1].lower()
        if basename == 'victory_theme.hps':
            audio_members[member] = 'victory'
        elif basename == 'announcer.wav':
            audio_members[member] = 'announcer'
    if not wanted:
        raise ValueError('This export contains no files to restore.')
    normalized_audio = _normalize_character_zip_audio(zf, audio_members)

    # charge=False: import_custom_character_zip_bytes already preflighted this
    # exact archive against this exact budget. Charging the same expansion
    # twice would fail a legitimately large export.
    extract_zip_to_new_directory(zf, char_dir, budget=budget, members=wanted,
                                 contents=normalized_audio, charge=False)

    entry['slug'] = slug
    entry['name'] = name
    entry.setdefault('source', 'zip')
    entry['date_added'] = datetime.now().isoformat()
    # has_css_icon may have been stale; recompute from what was restored
    entry['has_css_icon'] = (char_dir / 'css_icon.png').exists()

    _append_custom_character(entry)
    logger.info(f"[OK] Restored full-vault custom character '{name}' as {slug}")
    return entry


def import_custom_character_zip_bytes(zip_data, fallback_name, budget=None):
    """Import a custom character fighter package (zip bytes) into the vault.
    Returns the metadata entry. Raises ValueError on an invalid package.
    Shared by the dedicated route and the unified /import/file dispatcher.

    ``budget`` is the caller's cumulative extraction budget (see
    core.safe_extract); a package reached through a chat download shares the
    allowance the outer archive already spent instead of getting a fresh one.
    """
    import io
    from core.safe_extract import new_budget, preflight_zip
    budget = budget or new_budget()
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        # Charge the whole package against the operation's budget and refuse
        # hostile member names before any member is read into memory.
        preflight_zip(zf, budget=budget)
        names = zf.namelist()

        # Full-vault export (from export_custom_character): restore the whole
        # storage/custom_characters/<slug>/ folder verbatim so CSPs, stocks,
        # costumes, banners, series and audio all survive the round-trip.
        if NUCLEUS_EXPORT_MARKER in names:
            try:
                payload = json.loads(zf.read(NUCLEUS_EXPORT_MARKER))
            except (json.JSONDecodeError, KeyError):
                payload = {}
            if payload.get('nucleus_export') == NUCLEUS_EXPORT_KIND:
                return _restore_full_vault_export(zf, payload, fallback_name, budget)

        fighter_json_path = None
        icon_path = None
        fsm_path = None
        announcer_path = None
        victory_path = None
        vault_meta_path = None

        for name in names:
            basename = name.split('/')[-1].lower()
            if basename == 'fighter.json':
                fighter_json_path = name
            elif basename == 'icon.png':
                icon_path = name
            elif basename == 'fsm.txt':
                fsm_path = name
            elif basename == 'announcer.wav':
                announcer_path = name
            elif basename == 'victory_theme.hps':
                victory_path = name
            elif basename == 'vault_meta.json':
                vault_meta_path = name

        if not fighter_json_path:
            raise ValueError('ZIP must contain a fighter.json file')

        fighter_meta = json.loads(zf.read(fighter_json_path))
        fighter_name = fighter_meta.get('name', fallback_name)

        audio_members = {}
        if announcer_path:
            audio_members[announcer_path] = 'announcer'
        if victory_path:
            audio_members[victory_path] = 'victory'
        normalized_audio = _normalize_character_zip_audio(zf, audio_members)

        slug = _dedupe_slug(_make_slug(fighter_name))
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        char_dir.mkdir(parents=True, exist_ok=True)

        (char_dir / 'fighter.zip').write_bytes(zip_data)

        with open(char_dir / 'fighter.json', 'w', encoding='utf-8') as f:
            json.dump(fighter_meta, f, indent=2)

        has_css_icon = False
        if icon_path:
            (char_dir / 'css_icon.png').write_bytes(zf.read(icon_path))
            has_css_icon = True

        # Frame Speed Modifier data (Crazy Hand fsm.txt format) — extracted
        # to the vault folder so the export pipeline can bake it into the DOL.
        if fsm_path:
            (char_dir / 'fsm.txt').write_bytes(zf.read(fsm_path))

        # Announcer name-call and victory theme: the install path re-applies
        # these from the vault folder (add-fighter resets both), same as
        # ISO-scanned characters get via _extract_audio_meta.
        has_announcer = False
        if announcer_path:
            (char_dir / 'announcer.wav').write_bytes(normalized_audio[announcer_path])
            has_announcer = True

        victory_theme = None
        if victory_path:
            (char_dir / 'victory_theme.hps').write_bytes(normalized_audio[victory_path])
            victory_name = Path(victory_path).stem
            if vault_meta_path:
                try:
                    vm = json.loads(zf.read(vault_meta_path))
                    victory_name = vm.get('victory_theme_name') or victory_name
                except (json.JSONDecodeError, KeyError):
                    pass
            victory_theme = {'name': victory_name}

        costume_count = len(fighter_meta.get('costumes', []))

    entry = {
        'slug': slug,
        'name': fighter_name,
        'source': 'zip',
        'date_added': datetime.now().isoformat(),
        'series_id': fighter_meta.get('seriesID', 0),
        'costume_count': costume_count,
        'has_css_icon': has_css_icon
    }
    if has_announcer:
        entry['has_announcer'] = True
    if victory_theme:
        entry['victory_theme'] = victory_theme

    _append_custom_character(entry)

    logger.info(f"[OK] Imported custom character '{fighter_name}' as {slug}")
    return entry


# Marker file that flags a zip as a full-vault custom-character export (vs a
# bare MexManager fighter.zip). Carries the metadata entry so source/series/
# audio/CSP state survive a round-trip between installs.
NUCLEUS_EXPORT_MARKER = 'nucleus_export.json'
NUCLEUS_EXPORT_KIND = 'custom_character'
