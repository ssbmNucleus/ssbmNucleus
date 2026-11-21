"""Gecko codes - the little patches a build needs beside its files.

Some menu mods only work with a code (a custom character-select backdrop needs
"Disable Hardcoded CSS Animations", or Melee's own animation draws over it).
Mod descriptions publish those codes as text; this module turns that text into
the code list a build uses, and writes it into the workspace.

    text  = '$Disable Hardcoded CSS Animations\\n04263384 48000010'
    found = codes.parse(text)
    codes.write_code_list(found['codes'], 'out/codes.ini')
"""
import json

from ._workspace import in_path, out_path
from core.gecko_codes import (  # noqa: F401  (re-exported, documented here: see gendocs)
    address_conflicts, check, content_hash, identity,
    merge, normalized_body, write_targets,
)

# gendocs documents these as nucleus_api.codes functions although they live in core.
_DOCUMENTED_FROM = ('core.gecko_codes',)


def list_vault_codes():
    """List the Gecko codes this Nucleus install already keeps.

    Read-only. These are the codes the app's Codes section offers when building
    an ISO.

    Returns:
        list[dict]: ``{'id', 'name', 'creator', 'category', 'description',
        'source'}``. ``source`` is the code's hex lines - :func:`write_code_list`
        needs it, so it is included here.

    Example:
        >>> from nucleus_api import codes
        >>> [c['name'] for c in codes.list_vault_codes()][:3]
        ['Disable Hardcoded CSS Animations', 'UCF 0.84', ...]
    """
    from core import config
    path = config.STORAGE_PATH.resolve() / 'codes' / 'metadata.json'
    if not path.is_file():
        return []
    entries = json.loads(path.read_text(encoding='utf-8'))
    return [{key: entry.get(key) for key in
             ('id', 'name', 'creator', 'category', 'description', 'source')}
            for entry in entries if isinstance(entry, dict)]


def parse(text):
    """Turn pasted code text into normalized Gecko codes.

    Handles a full INI block (``$Name [Creator]`` plus hex lines), bare hex
    lines, and the loose "title, blurb, hex" shape mod descriptions use. It
    validates the hex; nothing is saved anywhere.

    Args:
        text: the pasted text, e.g. a mod description's code section.

    Returns:
        dict: ``{'codes': [{'name', 'creator', 'description', 'source',
        'enabled', 'valid', 'error'?}], 'warnings': [str, ...]}``. Check
        ``valid`` before using a code.

    Example:
        >>> codes.parse('$Disable Hardcoded CSS Animations\\n04263384 48000010')
        {'codes': [{'name': 'Disable Hardcoded CSS Animations', 'valid': True, ...}], 'warnings': []}
    """
    from core.gecko import smart_parse
    return smart_parse(text or '')


def write_code_list(entries, destination=None):
    """Write codes to a ``codes.ini`` in the workspace, the format a build reads.

    Args:
        entries: list of code dicts from :func:`parse` or :func:`list_vault_codes`
            (each needs at least ``name`` and ``source``).
        destination: workspace path. Defaults to ``out/codes.ini``.

    Returns:
        str: absolute path of the file written.

    Example:
        >>> codes.write_code_list(codes.parse(text)['codes'], 'out/codes.ini')
        'C:/.../workspace/out/codes.ini'
    """
    from core.gecko import serialize_ini, validate_source
    rows = []
    for entry in entries or []:
        if not isinstance(entry, dict) or not entry.get('source'):
            raise ValueError('Each code needs a name and a source (its hex lines).')
        check = validate_source(entry['source'])
        if not check['ok']:
            raise ValueError(f"{entry.get('name') or 'A code'} has invalid hex: {check['error']}")
        rows.append({'name': entry.get('name'), 'creator': entry.get('creator', ''),
                     'description': entry.get('description', ''), 'source': entry['source'],
                     'enabled': entry.get('enabled', True)})
    if not rows:
        raise ValueError('No codes to write.')
    target = out_path(destination, default_name='codes.ini')
    target.write_text(serialize_ini(rows), encoding='utf-8')
    return str(target)


def read_code_list(path):
    """Read a ``codes.ini`` back into code dicts.

    Args:
        path: workspace path to a codes.ini.

    Returns:
        list[dict]: same shape as :func:`parse`'s ``codes``.

    Example:
        >>> codes.read_code_list('out/codes.ini')[0]['name']
        'Disable Hardcoded CSS Animations'
    """
    from core.gecko import parse_ini
    return parse_ini(in_path(path).read_text(encoding='utf-8', errors='replace'))


def from_published_description(text, source_ref):
    """Read code data out of a mod's published description.

    A description may SUPPLY a code. It never authorizes installing one: the
    return carries ``authorizes_install=False`` and every code is tagged with
    where it came from, so a build change records a provenance instead of a
    claim.

    A candidate whose body had lines the parser could not read comes back
    ``status='invalid'`` with those lines listed. The parser drops them
    silently; a two-line code that arrives as a one-line code is not the code
    that was published, and installing it would patch half of something.

    Args:
        text: the description text as published.
        source_ref: where the text came from, e.g.
            ``'ssbmnucleus.net post 14063'``. Required - an untraceable code is
            not a usable one.

    Returns:
        dict: ``{'codes': [...], 'warnings': [...], 'source_ref': str,
        'authorizes_install': False}``. Each code gains ``origin``,
        ``content_hash``, ``status``, ``writes`` and ``dropped_lines``.

    Example:
        >>> found = codes.from_published_description(text, 'ssbmnucleus.net post 14063')
        >>> found['authorizes_install']
        False
    """
    from core.gecko import trim_hex_line
    if not (source_ref or '').strip():
        raise ValueError('Say where the description came from (source_ref), e.g. '
                         "'ssbmnucleus.net post 14063'.")
    found = parse(text)
    warnings = list(found.get('warnings', []))
    rows = []
    for entry in found.get('codes', []):
        verdict = check(entry)
        dropped = _dropped_lines(text, entry, trim_hex_line)
        row = {**entry, 'origin': source_ref, 'content_hash': verdict['content_hash'],
               'status': verdict['status'], 'error': verdict['error'],
               'writes': verdict['writes'], 'dropped_lines': dropped}
        if dropped:
            # Quoted with ascii() so a line full of control characters or
            # non-ASCII cannot reshape the message it is reported in.
            quoted = ', '.join(ascii(line[:120]) for line in dropped[:5])
            row['status'] = 'invalid'
            row['error'] = (f'{len(dropped)} line(s) of this code could not be read as hex '
                            f'and were dropped by the parser: {quoted}')
            row['valid'] = False
            warnings.append(f'{identity(entry)}: {row["error"]}')
        rows.append(row)
    return {'codes': rows, 'warnings': warnings, 'source_ref': source_ref,
            'authorizes_install': False}


def _dropped_lines(text, entry, trim_hex_line):
    """Lines that belonged to this code's body and did not survive parsing.

    The first version only looked inside ``$Name`` sections, so it saw nothing
    in the two shapes that actually lose lines: a description with a BOM in
    front of its header (the header stops being a header) and a loose
    SmashBoards paste with no header at all. Both returned a shortened code
    reported as valid.

    A body is contiguous: this takes the candidate's surviving lines, walks
    from the first of them to the next header or a blank line, and reports every
    non-comment line in between that the parser threw away. Prose after a blank
    line is prose, not a lost write.
    """
    text = (text or '').lstrip('\ufeff')\
        .replace('\r\n', '\n').replace('\r', '\n')
    kept = {line.strip() for line in (entry.get('source') or '').split('\n')
            if line.strip()}
    if not kept:
        return []
    lines = [line.strip() for line in text.split('\n')]
    try:
        start = next(index for index, line in enumerate(lines) if line and line in kept)
    except StopIteration:
        return []
    dropped = []
    for line in lines[start:]:
        if not line:
            break                       # the block ended; what follows is prose
        if line.startswith('$'):
            break                       # the next code's header
        if line.startswith('*') or line.startswith('#') or line.startswith('//'):
            continue
        if line in kept or trim_hex_line(line) is not None:
            continue
        dropped.append(line)
    return dropped
