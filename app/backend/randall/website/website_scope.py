"""Where an approved download may land: the destinations an approval declares or leaves unpromised,
the importer's pending question, and whether identified bytes stay inside what was approved."""


# A whole character-select DAT carries the icons AND the backdrop, so the
# importer legitimately has a question. Asked at APPROVAL time it is one
# radio button on the card; asked afterwards it cost a second download and a
# reply that said "download it again" (2026-09-22 re-review, 5).
_MENU_CHOICE_OPTIONS = {
    'css_icon_grid': ('Icon grid', 'The character icons from this screen.'),
    'css_background': ('CSS background', "The screen's backdrop model and animation."),
}


def _pending_choice(content):
    """The import question these bytes will raise, or None if there is none."""
    candidates = [c for c in (content.get('candidates') or []) if c in _MENU_CHOICE_OPTIONS]
    if len(candidates) < 2:
        return None
    from vault.importing.unified.normalize import destination_for
    return {'question': 'This file is a whole character select screen. Import it as:',
            'default': candidates[0],
            'options': [{'key': key, 'label': _MENU_CHOICE_OPTIONS[key][0],
                         'description': _MENU_CHOICE_OPTIONS[key][1],
                         'destination': destination_for(key)} for key in candidates]}


_DECLARED_DESTINATIONS = {
    'character_dat': 'Vault > Characters (costumes)',
    'stage_dat': 'Vault > Stages (stage skins)',
    'effects_dat': 'Vault > Characters > Extras',
}

# What an UNPROMISED download (a published `other` file, or a whole-mod
# archive) is allowed to turn out to be. The publisher's type says nothing
# here, so the approval names this whole list and anything outside it is a
# change of scope the user never agreed to (2026-09-22 re-review, 3).
UNPROMISED_DESTINATIONS = (
    'Vault > Characters (costumes)',
    'Vault > Characters > Extras',
    'Vault > Stages (stage skins)',
    'Vault > Stages (custom stages)',
    'Vault > Custom Characters',
    'Vault > Custom Characters (skins)',
    'Vault > Bundles',
    'Vault > Music',
    'Menus',
)


def _is_allowed_destination(label):
    """True when `label` is one of the places an unpromised download may go."""
    if not label:
        return False
    return any(label.startswith(allowed) for allowed in UNPROMISED_DESTINATIONS)


def _declared_destinations(plan):
    """Where this download may land, as the approval card states it."""
    seen = []
    for kind in plan['declared_types']:
        label = _DECLARED_DESTINATIONS.get(kind)
        if label is None:
            # Unpromised: name every place it could go, rather than "the vault".
            for allowed in UNPROMISED_DESTINATIONS:
                if allowed not in seen:
                    seen.append(allowed)
            continue
        if label not in seen:
            seen.append(label)
    return seen


# Detected types the approval's published type is allowed to turn into. A
# selected costume/stage/effect export has one honest answer each; a whole-mod
# archive is a grab bag, so the check there is about what must NOT be in it.
_EXPECTED_FROM_DECLARED = {
    'character_dat': {'character', 'character_renamed', 'ic_half', 'custom_fighter_costume'},
    'stage_dat': {'stage', 'custom_stage', 'mex_stage_yml'},
    'effects_dat': {'effect', 'effect_image', 'effect_unsupported'},
}


def _scope_refusal(plan, content):
    """A sentence when these bytes are outside what the approval covered, else ''.

    Reads the RECURSIVE plan: an executable or a patch three archives down is
    exactly as much of a scope change as one at the top, and an archive this
    pass could not open is refused rather than approved unseen.
    """
    from vault.importing.unified.normalize import PATCH_TYPES
    detected = content['type']
    where = content.get('destination') or 'an undetermined place'
    if content.get('executable_members'):
        return ('This download contains program files ('
                + ', '.join(content['executable_members'][:3])
                + '). Nucleus never installs those, so nothing was imported.')
    if content.get('uninspected'):
        return ('Part of this download could not be checked before importing it ('
                + ', '.join(content['uninspected'][:3]) + '). Nothing was imported. '
                'Download it from the website and import the files inside it.')
    declared = set(plan.get('declared_types') or [])
    filed_as_patch = 'Patch' in (plan['mod'].get('tags') or [])
    if (detected in PATCH_TYPES or content.get('patch_members')) and not filed_as_patch:
        return (f'This download is an ISO patch, which rewrites a whole build rather than '
                f'adding an item to {where}. The post is not filed as a patch, so nothing '
                f'was imported. Download it from the website if that is what you want.')
    expected = set()
    if plan.get('file_id') is not None:
        # Only a SELECTED file carries a published promise. A whole-mod archive
        # lists every file type the post has; holding the archive to one of
        # them would refuse an ordinary mod zip that happens to be a package.
        for kind in declared:
            expected |= _EXPECTED_FROM_DECLARED.get(kind, set())
    if expected:
        # A SELECTED published export type is a promise about one object, so a
        # confident disagreement with it is a change of scope. An unrecognised
        # type is not a disagreement: the importer's own cascade reports that
        # in its own words.
        if content.get('destination') and detected not in expected:
            return (f'The post publishes this as {", ".join(sorted(declared))}, but the downloaded '
                    f'file is {detected} and would land in {where}. Nothing was imported - '
                    f'inspect the mod and download it again if that is really what you want.')
        return ''
    # Unpromised: a published `other` file or a whole-mod archive. The approval
    # named the places it may land; every destination in the plan has to be one
    # of them, and a selected file the importer cannot even classify is a
    # refusal rather than an attempt (2026-09-22 re-review, 3).
    outside = [label for label in (content.get('destinations') or [])
               if not _is_allowed_destination(label)]
    if outside:
        return (f'This download would land in {outside[0]}, which is not one of the places '
                f'the approval covered. Nothing was imported.')
    if plan.get('file_id') is not None and not content.get('destination'):
        return ('Nucleus could not tell what this published file is, so it has no place to '
                'put it. Nothing was imported. Download it from the website and import it '
                'with Add mod, which can ask you what it is.')
    return ''


def _choice_destination(option):
    """Where one importer-dialog option would put the file."""
    from vault.importing.unified.normalize import destination_for
    hint = (option.get('hints') or {}).get('mod_type') or option.get('key')
    return destination_for(hint)
