"""Which published files chat may download: the three export types, the any-mod gate and its
refusal, and the one export a family of color-slot variants offers by default."""

import re
from pathlib import Path


# The website's /export-nucleus route serves only these three. Asking it for
# anything else answers "Unsupported file type for Nucleus export" (HTTP 400),
# so the rest is fetched from the published media file instead -- the same host
# the whole-mod ZIP already comes from.
EXPORT_TYPES = ('character_dat', 'stage_dat', 'effects_dat')
# Every file type the site publishes. A download hands the bytes to the app's
# own unified import, which decides what the file is and where it goes: a
# costume to the vault, a menu file (MnSlChr/MnSlMap/GmPause) to the Menus
# section, a container ZIP to its per-archive import. Advertising a narrower
# list here was the only thing stopping Randall from fetching the rest -- a
# character-select screen is published as 'other', so its card said
# can_download=false and the mod could not be downloaded at all.
DOWNLOADABLE_TYPES = (*EXPORT_TYPES, 'other')


ANY_MOD_REFUSAL = (
    'Downloading this kind of file from chat is turned off in this build. '
    'Nucleus can still add costumes, stages and effects published as their own '
    'export. For anything else, use the Download button on the mod\'s page at '
    'ssbmnucleus.net and import the file with Add mod.')


def any_mod_download_enabled():
    """Whether chat may download published files beyond the three export types.

    The release gate (`core.gates`, `NUCLEUS_ANY_MOD_DOWNLOAD`, forced off in
    packaged builds) exists so the preview can ship with the rest of the
    assistant while the archive containment, nested-budget and
    destination-binding work from the 2026-09-22 security review is reviewed.
    """
    from core import gates
    return gates.enabled('any_mod_download')


def downloadable_types():
    """The published file types chat may fetch right now."""
    return DOWNLOADABLE_TYPES if any_mod_download_enabled() else EXPORT_TYPES


def assert_download_allowed(selected, *, whole_archive=False):
    """The gate, checked on what will ACTUALLY be fetched. Raises if refused.

    Checking it where the model picks a file was not enough: a whole-post
    request whose only `other` file carried a supported effect tag was
    converted into an effect SELECTION after that check, and fetched the media
    URL with the gate closed (2026-09-22 review JJ, 3). Every path that is
    about to fetch bytes calls this on the final resolved selection, so there
    is one place the answer comes from.
    """
    if any_mod_download_enabled():
        return
    if whole_archive or not selected:
        raise ValueError(ANY_MOD_REFUSAL)
    if selected.get('file_type') not in EXPORT_TYPES:
        raise ValueError(ANY_MOD_REFUSAL)


def _downloadable(file):
    """True when this published file has a Nucleus import route we may use.

    A published type of `other` is a catch-all: a character-select DAT belongs
    to the Menus section, but a Gecko code list published beside it has no
    validated import route at all. Advertising it as downloadable produced a
    "could not detect mod type" failure after an approval -- the capability was
    never real (2026-09-22 security review, finding 5). With the any-mod gate
    closed, only the three published export types are offered at all.
    """
    from vault.importing.unified.normalize import GECKO_TEXT_SUFFIXES
    if file.get('file_type') not in downloadable_types():
        return False
    name = str(file.get('filename') or '')
    return Path(name.replace(chr(92), '/')).suffix.lower() not in GECKO_TEXT_SUFFIXES


def published_exports(post):
    """The post's own per-file exports, in published order."""
    return [f for f in post.get('files') or []
            if f.get('file_type') in EXPORT_TYPES and _downloadable(f)]


def _default_variant(files):
    """Offer a single export only for an unambiguous family of color-slot variants."""
    from vault.importing.character_detector import _extract_character_color_from_filename
    if len(files) < 2 or any(f.get('type') != 'character_dat' for f in files):
        return None
    families, colors, defaults = set(), set(), []
    for file in files:
        name = file['name']
        character, color = _extract_character_color_from_filename(name)
        if not character or not color or not re.search(r'pl[a-z0-9]{4}', name, re.I):
            return None
        families.add((character, re.sub(r'pl[a-z0-9]{4}', 'costume', name.lower())))
        if color in colors:
            return None
        colors.add(color)
        if color == 'Default':
            defaults.append(file)
    return defaults[0] if len(families) == 1 and len(defaults) == 1 else None
