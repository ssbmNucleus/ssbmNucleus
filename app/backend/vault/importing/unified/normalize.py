"""One normalization entry point in front of the unified import cascade.

Everything downstream of `_import_single_archive` opens the file with
`zipfile`, so something has to turn "whatever the user or the website handed
us" into a ZIP first. The HTTP route did that (wrap raw files, convert 7z/RAR)
but the Randall download handoff called `_import_single_archive` directly, so
a real raw `Halo3CSS.dat`, an INI, an image, or a top-level 7z/RAR downloaded
from the website failed before it reached any importer -- and the tests hid it
by mocking both the safety inspection and the importer (2026-09-22 security
review, finding 3).

This module is that one entry point. Both callers use it:

* `vault.routes.import_unified.routes.import_file` (the HTTP upload)
* `vault.importing.unified.protocol.import_handoff` (nucleus:// links and
  approved chat downloads)

It also removes an extension-trust bug worth its own mention: the format is
decided by MAGIC BYTES, not by the published filename. A file called
`costume.zip` that is really a 7z is converted as a 7z, and a `.dat` that is
really a ZIP is treated as the archive it is, so the published extension can no
longer steer the file down a different pipeline from its contents.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Leading magic for every container format the importer can open. Order
# matters only in that each signature is checked against the file's head.
_SIGNATURES = (
    (b'PK\x03\x04', 'zip'),
    (b'PK\x05\x06', 'zip'),   # empty archive
    (b'PK\x07\x08', 'zip'),   # spanned archive
    (b'7z\xbc\xaf\x27\x1c', '7z'),
    (b'Rar!\x1a\x07\x00', 'rar'),
    (b'Rar!\x1a\x07\x01\x00', 'rar'),
)

_MAX_SIGNATURE = max(len(signature) for signature, _ in _SIGNATURES)

# Text payloads the website publishes that no importer consumes. They are
# refused by name here instead of reaching the cascade's blank
# "could not detect mod type", which reads like a bug rather than a decision.
GECKO_TEXT_SUFFIXES = frozenset({'.ini', '.txt', '.gct', '.xml'})
GECKO_REFUSAL = (
    'Gecko codes are not imported from chat. Nucleus has no validated import '
    'route for a code list yet — open the Codes page and paste it there, where '
    'you can see and choose each code before it is installed.'
)


def sniff_format(path):
    """'zip' / '7z' / 'rar' / 'raw', decided by the file's leading bytes."""
    try:
        with open(path, 'rb') as handle:
            head = handle.read(_MAX_SIGNATURE)
    except OSError:
        return 'raw'
    for signature, kind in _SIGNATURES:
        if head.startswith(signature):
            return kind
    return 'raw'


def safe_member_name(filename, *, default='mod.dat'):
    """One portable filename, never a path, for a member of the wrapper ZIP.

    The published name is preserved as far as it safely can be, because the
    importer's detection reads it: `Halo3CSS.dat` has to stay a `.dat`.
    """
    name = str(filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', '_', name).strip().strip('.')
    from core.safe_extract import is_safe_member_name
    if not name or not is_safe_member_name(name):
        return default
    return name[:160]


@dataclass(frozen=True)
class NormalizedUpload:
    """A ZIP on disk the cascade can open, plus the name detection should see."""
    path: str
    filename: str
    source_format: str
    wrapped: bool


@contextmanager
def normalized_upload(path, filename, *, source_filename=None, budget=None,
                      raw_bytes=None):
    """Yield a :class:`NormalizedUpload` for `path`, cleaning up temp files.

    `filename` is the name the cascade should classify by. `source_filename`
    is the publisher's own filename when it differs (the nucleus:// handoff
    carries a generated `<character>_<color>.zip`, not `Halo3CSS.dat`); it wins
    for a raw file, because the wrapped member's name is what detection reads.
    """
    from core.safe_extract import new_budget
    from vault.importing.unified.archive import HAS_7Z, _convert_7z_to_temp_zip
    from core.rar_tools import rar_available, rar_to_temp_zip

    budget = budget or new_budget()
    kind = sniff_format(path)
    temporary = None
    try:
        if kind == 'zip':
            yield NormalizedUpload(str(path), filename, 'zip', False)
            return

        if kind == '7z':
            if not HAS_7Z:
                raise ValueError('This build cannot open .7z archives. '
                                 'Extract the archive and import its contents.')
            temporary = _convert_7z_to_temp_zip(str(path), limits=budget.archive_limits())
            if not temporary:
                raise ValueError('This .7z archive could not be opened — it may be '
                                 'corrupt, password-protected, or over the size limit.')
            yield NormalizedUpload(temporary, filename, '7z', False)
            return

        if kind == 'rar':
            if not rar_available():
                raise ValueError('This build cannot open .rar archives — the bundled '
                                 'UnRAR tool is missing. Extract the archive and import '
                                 'its contents.')
            temporary = rar_to_temp_zip(str(path), limits=budget.archive_limits())
            if not temporary:
                raise ValueError('This .rar archive could not be opened — it may be '
                                 'corrupt, password-protected, or over the size limit.')
            yield NormalizedUpload(temporary, filename, 'rar', False)
            return

        # A raw file: wrap it exactly the way the HTTP route always has, under
        # the sanitized PUBLISHED name so detection sees the real extension.
        member = safe_member_name(source_filename or filename)
        if Path(member).suffix.lower() in GECKO_TEXT_SUFFIXES:
            raise ValueError(GECKO_REFUSAL)
        from core.safe_extract import NESTED_ARCHIVE_SUFFIXES
        if Path(member).suffix.lower() in NESTED_ARCHIVE_SUFFIXES:
            # We sniffed this as a raw file, so the published `.zip` name is
            # wrong. Keeping it made the wrapper look like a container with an
            # unopenable child, which the plan then (correctly) refused.
            member = Path(member).stem + '.dat'
        payload = raw_bytes if raw_bytes is not None else Path(path).read_bytes()
        budget.charge_members(1)
        budget.charge_bytes(len(payload))
        handle, temporary = tempfile.mkstemp(suffix='.zip')
        os.close(handle)
        with zipfile.ZipFile(temporary, 'w') as zf:
            zf.writestr(member, payload)
        yield NormalizedUpload(temporary, member, 'raw', True)
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


# ── what the importer will actually do with it ─────────────────────────────

# Detected type -> the vault section it lands in. The approval used to show the
# PUBLISHER's file type (often just 'other') and the word "vault"; a post
# presented as a menu can carry a ZIP that dispatches as a custom fighter or a
# patch (2026-09-22 security review, finding 4). This is the map that lets the
# approval and the receipt name the real destination.
_TYPE_LOCATIONS = {
    'character': 'Vault > Characters (costumes)',
    'character_renamed': 'Vault > Characters (costumes)',
    'custom_fighter_costume': 'Vault > Custom Characters (skins)',
    'ic_half': 'Vault > Characters (Ice Climbers costume)',
    'stage': 'Vault > Stages (stage skins)',
    'custom_stage': 'Vault > Stages (custom stages)',
    'mex_stage_yml': 'Vault > Stages (custom stages)',
    'custom_character': 'Vault > Custom Characters',
    'mex_fighter_yml': 'Vault > Custom Characters',
    'effect': "Vault > Characters > Extras",
    'effect_image': "Vault > Characters > Extras",
    'bundle': 'Vault > Bundles',
    'xdelta': 'Vault > Patches',
    'music': 'Vault > Music',
    'dolphin_textures': 'Not imported (Dolphin texture pack)',
    'sound_bank': 'Not imported (sound bank)',
}

# Types whose arrival is a change of scope, not a detail: a patch rewrites an
# ISO rather than adding an item to the vault.
PATCH_TYPES = frozenset({'xdelta'})


def destination_for(detected_type):
    """The vault section a detected type lands in, or None when unknown."""
    from vault.importing.unified.menu_import import _MENU_LOCATIONS
    if detected_type in _MENU_LOCATIONS:
        return _MENU_LOCATIONS[detected_type]
    return _TYPE_LOCATIONS.get(detected_type)


def _walk_archives(path, budget, depth=0, max_depth=3, seen=None, occurrence=''):
    """Yield (label, ZipFile) for this archive and every archive inside it.

    Preflighted on the way in, so a nested archive is charged and its member
    names are validated before anything reads it. An archive that cannot be
    opened at the depth limit is REPORTED, not skipped: the caller refuses on
    it rather than approving content nobody looked at.
    """
    import zipfile
    from core.safe_extract import preflight_zip
    from .detection import _INNER_ARCHIVE_EXTS

    seen = seen if seen is not None else set()
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        # A child that cannot be opened is not absent: it is unchecked, and
        # the plan has to say so or a malformed archive is approved unseen
        # (2026-09-22 review JJ, 9). The top level is a raw file, not a child.
        if depth:
            yield '', None, True
        return
    with archive:
        if budget is not None:
            preflight_zip(archive, budget=budget, occurrence=occurrence)
        yield '', archive, False
        inner = [name for name in archive.namelist()
                 if not name.endswith('/')
                 and Path(name).suffix.lower() in _INNER_ARCHIVE_EXTS]
        if not inner:
            return
        if depth >= max_depth:
            yield '', None, True          # deeper than we will look
            return
        import io
        for name in inner:
            if Path(name).suffix.lower() != '.zip':
                # 7z/RAR inside an archive are converted by the importer, not
                # read here; report them as uninspected rather than ignored.
                yield name + ' / ', None, True
                continue
            try:
                data = archive.read(name)
            except (zipfile.BadZipFile, OSError, KeyError):
                yield name + ' / ', None, True
                continue
            for label, child, unchecked in _walk_archives(
                    io.BytesIO(data), budget, depth + 1, max_depth, seen,
                    occurrence=f'{occurrence}!{name}'):
                yield name + ' / ' + label, child, unchecked


def describe_import_target(archive_path, filename, *, budget=None, mod_type=None,
                           max_depth=3):
    """A RECURSIVE import plan for these exact bytes, for the approval card.

    Returns {'type', 'confidence', 'candidates', 'destination', 'destinations',
    'sha256', 'executable_members', 'patch_members', 'uninspected'}.

    The first version reported only the outer archive's detected type and only
    top-level names, and an explicit menu hint returned an empty executable
    list without scanning anything (2026-09-22 re-review, 3). Every level is
    walked now: destinations, executables and patch members come from the
    whole tree, and anything too deep or in a format this pass cannot open is
    listed in `uninspected` so the caller can refuse it.

    Reads only; imports nothing.
    """
    import hashlib
    from core.safe_extract import dangerous_members
    from vault.importing.unified.menu_import import _MENU_HINT_TYPES
    from .detection import detect_content_type

    path = Path(archive_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    executables, patches, uninspected = [], [], []
    for label, archive, unchecked in _walk_archives(path, budget, max_depth=max_depth):
        if unchecked:
            uninspected.append((label or '(this archive)')[:200])
            continue
        names = [n for n in archive.namelist() if not n.endswith('/')]
        executables.extend(label + n for n in dangerous_members(names))
        patches.extend(label + n for n in names if Path(n).suffix.lower() == '.xdelta')

    explicit = mod_type in _MENU_HINT_TYPES or mod_type in (
        'effect', 'effect_image', 'css_icon_grid')
    if explicit:
        # An explicit nucleus:// hint bypasses detection in the cascade, so the
        # card reports the hint rather than a guess the importer will not use
        # -- but the tree was still walked above, so the refusals still apply.
        verdict = {'type': mod_type, 'confidence': 'explicit', 'candidates': [mod_type]}
    else:
        verdict = detect_content_type(str(path), filename, deep=True, budget=budget,
                                      occurrence='')

    destination = destination_for(verdict['type'])
    destinations = [d for d in [destination] if d]
    for candidate in verdict.get('candidates') or []:
        label = destination_for(candidate)
        if label and label not in destinations:
            destinations.append(label)
    if patches and 'Vault > Patches' not in destinations:
        destinations.append('Vault > Patches')
    return {'type': verdict['type'], 'confidence': verdict.get('confidence'),
            'candidates': list(verdict.get('candidates') or [verdict['type']]),
            'destination': destination, 'destinations': destinations,
            'sha256': digest,
            'executable_members': executables[:20],
            'patch_members': patches[:20],
            'uninspected': uninspected[:20]}
