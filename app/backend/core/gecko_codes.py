"""Gecko code identity, normalization, what a code writes, and the merge rules.

Pure functions over code entries (``{'name', 'creator', 'source', ...}``), no I/O.
Shipped code (the CSS-background install in projects/routes/menus/backgrounds.py)
and the assistant's ``nucleus_api.codes`` facade both merge codes through here, so the
rules live in one place and a stable build, which carries no nucleus_api, still has
them. Moved out of nucleus_api/codes.py for 0.8.16; ``nucleus_api.codes`` re-exports
every public name and its API.md still documents them there.
"""

# ---------------------------------------------------------------------------
# Identity, normalization, what a code WRITES, and the merge rules
# ---------------------------------------------------------------------------

def identity(entry):
    """The identifier two codes are compared BY: ``'Name [Creator]'``.

    Args:
        entry: a code dict with ``name`` and optionally ``creator``.

    Returns:
        str: the canonical header, exactly as a ``codes.ini`` spells it.

    Example:
        >>> codes.identity({'name': 'UCF', 'creator': 'Dan'})
        'UCF [Dan]'
    """
    from core.gecko import header
    return header((entry or {}).get('name'), (entry or {}).get('creator', ''))


def normalized_body(source):
    """The comparable form of a code's hex: comments gone, upper case, one
    8-byte word per pair.

    Two codes with the same normalized body ARE the same patch however they
    were pasted, which is what deduplication may rely on. Anything that is not
    a valid hex line is kept verbatim (upper-cased) so a malformed code never
    silently normalizes into a valid-looking one.

    Args:
        source: the code's hex lines.

    Returns:
        str: the normalized body.

    Example:
        >>> codes.normalized_body('04263384 48000010  # label')
        '04263384 48000010'
    """
    from core.gecko import trim_hex_line
    lines = []
    for line in (source or '').split('\n'):
        if not line.strip():
            continue
        trimmed = trim_hex_line(line)
        if trimmed is None:
            lines.append(' '.join(line.split()).upper())
        else:
            lines.append(f'{trimmed[:8].upper()} {trimmed[8:].upper()}')
    return '\n'.join(lines)


def content_hash(source):
    """SHA-256 of :func:`normalized_body` - a code's content identity.

    Recorded for every code a change requires, so a receipt names the exact
    bytes that were installed rather than a title anyone could reuse.

    Args:
        source: the code's hex lines.

    Returns:
        str: 64 hex characters.

    Example:
        >>> codes.content_hash('04263384 48000010') == codes.content_hash('04263384 48000010 # x')
        True
    """
    import hashlib
    return hashlib.sha256(normalized_body(source).encode('utf-8')).hexdigest()


def write_targets(source):
    """What a code actually writes, so two codes can be compared by EFFECT.

    Comparing names catches a code being added twice under one title. It does
    not catch the real collision: two differently named codes patching the same
    instruction with different values, where whichever the loader applies last
    silently wins. This decodes the opcodes the m-ex loader supports and returns
    the address each one touches.

    Supported: ``00``/``02``/``04`` writes (8, 16 and 32 bit) and ``C2``
    branch injections. Anything else is reported as unsupported - it may write
    anywhere, and saying otherwise would be a guess.

    Args:
        source: the code's hex lines.

    Returns:
        dict: ``{'writes': [{'address', 'opcode', 'value', 'width', 'line'}],
        'unsupported': [{'opcode', 'line'}], 'analyzable': bool}``. Addresses
        are the full ``0x8...`` form the Gecko base implies.

    Example:
        >>> codes.write_targets('04263384 48000010')['writes'][0]['address']
        '0x80263384'
    """
    from core.gecko import _compiled_bytes
    data, error, _ = _compiled_bytes(source)
    if error or not data:
        return {'writes': [], 'unsupported': [], 'analyzable': False, 'error': error}
    writes, unsupported = [], []
    index = 0
    while index + 8 <= len(data):
        opcode = data[index]
        word0 = int.from_bytes(data[index:index + 4], 'big')
        word1 = int.from_bytes(data[index + 4:index + 8], 'big')
        line = index // 8
        address = f'0x{(word0 & 0x01FFFFFF) | 0x80000000:08X}'
        if opcode in (0x00, 0x02, 0x04):
            width = {0x00: 1, 0x02: 2, 0x04: 4}[opcode]
            writes.append({'address': address, 'opcode': f'{opcode:02X}',
                           'value': f'0x{word1:08X}', 'width': width,
                           'bytes': width, 'line': line})
            index += 8
        elif opcode == 0xC2:
            body = data[index + 8:index + 8 * (word1 + 1)]
            # The four bytes a C2 replaces with its branch are a write like any
            # other; what the injected BODY then does is machine code this
            # analyzer does not model, so it is carried as an unmodelled effect
            # rather than summarised as "branch+N", which made two different
            # bodies of the same length look identical.
            writes.append({'address': address, 'opcode': 'C2', 'width': 4, 'bytes': 4,
                           'value': 'branch to injected code',
                           'body_sha256': __import__('hashlib').sha256(body).hexdigest(),
                           'body_lines': word1, 'unmodelled_body': True, 'line': line})
            index += 8 * (word1 + 1)
        else:
            unsupported.append({'opcode': f'{opcode:02X}', 'line': line})
            index += 8
    return {'writes': writes, 'unsupported': unsupported,
            'analyzable': not unsupported and not any(w.get('unmodelled_body')
                                                      for w in writes),
            'error': None}


def check(entry):
    """Validate one code and say whether the analyzer can judge it at all.

    Args:
        entry: a code dict with ``source``.

    Returns:
        dict: ``{'status': 'valid'|'invalid'|'unknown', 'error': str|None,
        'content_hash': str, 'writes': [...]}``. ``'unknown'`` means the code
        uses an opcode this analyzer does not model - syntax checking is not a
        compatibility proof, so it is reported, not waved through.

    Example:
        >>> codes.check({'source': '04263384 48000010'})['status']
        'valid'
    """
    from core.gecko import validate_source
    source = (entry or {}).get('source') or ''
    digest = content_hash(source)
    targets = write_targets(source)
    result = validate_source(source)
    if result.get('ok'):
        return {'status': 'valid', 'error': None, 'content_hash': digest,
                'writes': targets['writes']}
    error = result.get('error') or 'invalid code'
    status = 'unknown' if 'opcode 0x' in error else 'invalid'
    return {'status': status, 'error': error, 'content_hash': digest,
            'writes': targets['writes']}


def address_conflicts(entries):
    """Find codes that patch the same address with different values.

    This is the interaction a name comparison cannot see. Two entries writing
    the same address with the same value are redundant, not conflicting; two
    writing it with different values are a conflict whichever order the loader
    applies them in. A code the analyzer cannot decode makes the whole set
    ``unresolved``, because an unmodelled opcode may write anywhere.

    Args:
        entries: the final code set, each with ``name``/``source``.

    Returns:
        dict: ``{'conflicts': [{'address', 'writers': [...]}], 'redundant':
        [...], 'unresolved': [{'identity', 'opcodes'}], 'analyzed': int}``.

    Example:
        >>> codes.address_conflicts([
        ...     {'name': 'A', 'source': '04263384 48000010'},
        ...     {'name': 'B', 'source': '04263384 60000000'}])['conflicts'][0]['address']
        '0x80263384'
    """
    ranges, unresolved = [], []
    for entry in entries or []:
        label = identity(entry)
        targets = write_targets(entry.get('source', ''))
        reasons = sorted({u['opcode'] for u in targets['unsupported']})
        if any(write.get('unmodelled_body') for write in targets['writes']):
            reasons.append('C2 injected body')
        if reasons or not targets['writes'] and targets.get('error'):
            unresolved.append({'identity': label, 'opcodes': reasons or ['undecodable']})
        for write in targets['writes']:
            start = int(write['address'], 16)
            ranges.append({'identity': label, 'start': start,
                           'end': start + int(write.get('bytes') or write['width']),
                           'value': write['value'], 'opcode': write['opcode'],
                           'width': write['width'], 'address': write['address'],
                           'body_sha256': write.get('body_sha256')})

    # Byte RANGES, not starting addresses: a 32-bit write at 0x80001000 and a
    # byte write at 0x80001001 land on the same word and used to be reported as
    # unrelated because their first addresses differ.
    conflicts, redundant = [], []
    for first in range(len(ranges)):
        for second in range(first + 1, len(ranges)):
            left, right = ranges[first], ranges[second]
            if left['end'] <= right['start'] or right['end'] <= left['start']:
                continue
            same = (left['address'] == right['address'] and left['width'] == right['width']
                    and left['value'] == right['value']
                    and left.get('body_sha256') == right.get('body_sha256'))
            record = {'address': left['address'], 'overlap': [max(left['start'],
                                                                 right['start']),
                                                              min(left['end'], right['end'])],
                      'writers': [left, right]}
            (redundant if same else conflicts).append(record)
    return {'conflicts': conflicts, 'redundant': redundant, 'unresolved': unresolved,
            'analyzed': len(ranges)}


def merge(existing, required, enable_disabled=False):
    """Merge required codes into a build's existing list, preserving it.

    The rules a build change has to follow, in one place:

    * every existing code survives, and its enabled flag is NEVER changed as a
      side effect. A required code the build already carries but has DISABLED
      is reported in ``enable_required``; turning it on is an explicit
      operation the proposal has to ask for (``enable_disabled=True``), because
      enabling a code changes what the game does;
    * a required code whose normalized body already appears is a duplicate - it
      is not added twice;
    * the same identifier carrying different bytes is a CONFLICT, never an
      overwrite;
    * two codes writing the same address with different values are a conflict
      too, however they are named (:func:`address_conflicts`);
    * a code the analyzer cannot judge is merged but reported as ``unknown``;
    * invalid hex is a conflict.

    Args:
        existing: the build's current codes (from :func:`read_code_list` or the
            app's project code list).
        required: the codes the change needs, each with ``name``/``source`` and
            ideally ``origin``.
        enable_disabled: the proposal explicitly asks to enable a required code
            the build carries disabled. Without it, that situation blocks.

    Returns:
        dict: ``{'merged', 'added', 'preserved', 'duplicates', 'conflicts',
        'unknown', 'enable_required', 'enabled', 'interactions', 'ok'}``.
        ``preserved`` reports each existing code's RESULTING enabled flag.
        ``ok`` is False when there is any conflict or an unrequested enable.

    Example:
        >>> codes.merge([{'name': 'UCF', 'source': '04001234 60000000', 'enabled': True}],
        ...             [{'name': 'Disable Hardcoded CSS Animations',
        ...               'source': '04263384 48000010'}])['added'][0]['identity']
        'Disable Hardcoded CSS Animations'
    """
    merged = []
    by_identity, by_body = {}, {}
    for entry in existing or []:
        row = {'name': entry.get('name'), 'creator': entry.get('creator', '') or '',
               'description': entry.get('description', '') or '',
               'source': entry.get('source', ''), 'enabled': bool(entry.get('enabled', True))}
        key = identity(row).lower()
        body = normalized_body(row['source'])
        if key in by_identity and normalized_body(by_identity[key]['source']) == body:
            continue            # the build already carried an exact duplicate
        merged.append(row)
        by_identity[key] = row
        by_body.setdefault(body, row)

    added, duplicates, conflicts, unknown = [], [], [], []
    enable_required, enabled_ops = [], []
    for entry in required or []:
        row = {'name': entry.get('name'), 'creator': entry.get('creator', '') or '',
               'description': entry.get('description', '') or '',
               'source': entry.get('source', ''), 'enabled': True}
        label = identity(row)
        body = normalized_body(row['source'])
        verdict = check(row)
        record = {'identity': label, 'content_hash': verdict['content_hash'],
                  'origin': entry.get('origin'), 'source': row['source'],
                  'status': verdict['status'], 'error': verdict['error']}
        if verdict['status'] == 'invalid':
            conflicts.append({**record, 'reason': 'invalid_syntax'})
            continue
        twin = by_identity.get(label.lower()) or (
            by_body.get(body) if normalized_body((by_body.get(body) or {}).get('source', ''))
            == body else None)
        if twin is not None:
            same_bytes = normalized_body(twin['source']) == body
            if not same_bytes:
                conflicts.append({**record, 'reason': 'same_identifier_different_bytes',
                                  'existing_content_hash': content_hash(twin['source'])})
                continue
            reason = ('already_present' if identity(twin).lower() == label.lower()
                      else 'same_bytes_under_another_name')
            hit = {**record, 'reason': reason, 'existing_identity': identity(twin)}
            if not twin['enabled']:
                if enable_disabled:
                    twin['enabled'] = True
                    enabled_ops.append({'identity': identity(twin), 'from': False, 'to': True,
                                        'because': f'{label} is required by this change'})
                    hit['enabled_by_this_change'] = True
                else:
                    enable_required.append({
                        **hit,
                        'reason': 'required_but_disabled',
                        'message': (f'{identity(twin)} is in this build but turned OFF. '
                                    'Enabling it changes what the game does, so it is an '
                                    'explicit part of the proposal, not a side effect.')})
            duplicates.append(hit)
            continue
        merged.append(row)
        by_identity[label.lower()] = row
        by_body[body] = row
        added.append(record)
        if verdict['status'] == 'unknown':
            unknown.append(record)

    preserved = [{'identity': identity(row), 'enabled': row['enabled'],
                  'content_hash': content_hash(row['source'])}
                 for row in merged
                 if identity(row).lower() in {identity(e).lower() for e in (existing or [])}]
    interactions = address_conflicts([row for row in merged if row['enabled']])
    for clash in interactions['conflicts']:
        conflicts.append({'identity': ' vs '.join(w['identity'] for w in clash['writers']),
                          'reason': 'same_address_different_value',
                          'address': clash['address'], 'writers': clash['writers'],
                          'content_hash': None, 'origin': None, 'source': None,
                          'status': 'invalid', 'error': None})
    for stuck in interactions['unresolved']:
        if stuck['identity'] not in {u['identity'] for u in unknown}:
            unknown.append({'identity': stuck['identity'], 'content_hash': None,
                            'origin': None, 'source': None, 'status': 'unknown',
                            'error': f'opcodes {stuck["opcodes"]} are not modelled, so what '
                                     'this code writes cannot be compared with the rest'})

    return {'merged': merged, 'added': added, 'preserved': preserved,
            'duplicates': duplicates, 'conflicts': conflicts, 'unknown': unknown,
            'enable_required': enable_required, 'enabled': enabled_ops,
            'interactions': interactions,
            'ok': not conflicts and not enable_required}
