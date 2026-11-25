"""Shared import handoff for nucleus:// links and approved Randall downloads.

The OS handler transports these fields to /import/file. Randall consumes the
same link in-process so its approval and receipt remain attached to its chat.
"""
from urllib.parse import parse_qs, urlsplit


def parse_import_link(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'nucleus' or parsed.netloc != 'import' or parsed.path not in ('', '/') or parsed.fragment:
        raise ValueError('Invalid Nucleus import link.')
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) - {'url', 'name', 'title', 'type', 'effect_type'} or any(len(values) != 1 for values in query.values()):
        raise ValueError('Invalid Nucleus import parameters.')
    values = {key: items[0] for key, items in query.items()}
    source = urlsplit(values.get('url', ''))
    if source.scheme != 'https' or source.username or source.password or not source.netloc:
        raise ValueError('Nucleus download must use HTTPS.')
    name = values.get('name') or 'mod'
    if len(name) > 200 or any(char in name for char in '/\\\0:') or name in ('.', '..'):
        raise ValueError('Invalid Nucleus import name.')
    return {'url': values['url'], 'filename': name + '.zip',
            'custom_title': values.get('title'), 'mod_type': values.get('type'),
            'effect_type': values.get('effect_type')}


def describe_import(*, origin=None, protocol_url=None, filename=None):
    """Where an import came from, as the Melee Unlocked export's confirmation shows it for fighter C that came
    in the package (projects/install/fighter_source.py). Only informational: such C is untrusted wherever it
    came from."""
    if origin:
        return origin
    if protocol_url:
        try:
            return f"a nucleus://import link to {parse_import_link(protocol_url)['url']}"
        except ValueError:
            return 'a nucleus://import link'
    return f'the file {filename}' if filename else None


def import_handoff(path, filename, *, protocol_url=None, expected_url=None,
                   slippi_action=None, duplicate_action=None, custom_title=None,
                   mod_type=None, effect_type=None, character=None, budget=None,
                   source_filename=None, mod_type_override=None, origin=None):
    """Normalize the downloaded/uploaded object, then run the import cascade.

    `origin` says where the object came from (the route: the download URL the window fetched, or a file
    from this computer; Randall: the mod website post). Fighter C in a package is recorded with it, as
    untrusted (projects/install/fighter_source.py).

    This used to call `_import_single_archive` directly, which meant an
    approved chat download of a real raw `Halo3CSS.dat`, an image, or a
    top-level 7z/RAR never got the raw-file wrapping and archive conversion
    the HTTP route performs, and failed before reaching any importer
    (2026-09-22 security review, finding 3). Both routes share
    `normalized_upload` now.

    `source_filename` is the publisher's own filename, which is what a wrapped
    raw file is named inside the temp ZIP -- detection reads that name, so
    `Halo3CSS.dat` has to survive as a `.dat`.
    """
    if protocol_url:
        handoff = parse_import_link(protocol_url)
        if handoff['url'] != expected_url:
            raise ValueError('Nucleus import source changed after approval.')
        filename, custom_title, mod_type, effect_type = (
            handoff['filename'], handoff['custom_title'], handoff['mod_type'], handoff['effect_type'])
    if mod_type_override:
        # The user answered the importer's own question on the approval card.
        # That answer is more specific than anything the link carried.
        mod_type, effect_type = mod_type_override, None
    from .normalize import normalized_upload
    from vault.importing.unified.archive import _import_single_archive
    hints = {}
    if mod_type:
        hints['mod_type'] = mod_type
    if effect_type:
        hints['effect_type'] = effect_type
    if character:
        hints['character'] = character
    from projects.install.fighter_source import import_origin
    where = describe_import(origin=origin, protocol_url=protocol_url, filename=source_filename or filename)
    with normalized_upload(path, filename, source_filename=source_filename,
                           budget=budget) as upload, import_origin(where):
        return _import_single_archive(upload.path, upload.filename,
                                      slippi_action=slippi_action,
                                      duplicate_action=duplicate_action,
                                      custom_title=custom_title,
                                      budget=budget, **hints)
