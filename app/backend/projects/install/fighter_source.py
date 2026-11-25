"""Where a Vault fighter's C came from, and whether a person has said it may be compiled.

The Melee Unlocked export (projects/install/melee_unlocked.py) compiles a custom fighter's C (``code/`` in its Vault
folder) into a native plugin that the game loads: whatever that C does, the game then does on the player's
computer. The C reaches the Vault in one of two ways:

  attached   the user picked a folder with the attach action in the Nucleus window
             (POST /api/mex/melee-unlocked/source/<slug>, which only the window may call);
  imported   it came inside a fighter package: a website download, a ``nucleus://import`` link, a zip from disk.

Imported source is UNTRUSTED. The export does not compile it until the user confirms that fighter in the window
(POST /api/mex/melee-unlocked/source/<slug>/confirm, window only), and the confirmation names the fighter and
where its package came from. Source with no record at all (in the Vault before this existed) is untrusted too:
nothing can prove it was attached.

The records live outside the Vault folders (``fighter_source_trust.json`` beside ``custom_characters/``), where
nothing a package carries can write, and each is bound to the sha256 of the source it describes: a confirmation
covers those bytes, not whatever replaces them later.
"""
import contextlib
import contextvars
import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

STORE_NAME = 'fighter_source_trust.json'
ATTACHED, CONFIRMED, UNTRUSTED = 'attached', 'confirmed', 'untrusted'
TRUSTED_STATES = (ATTACHED, CONFIRMED)
UNKNOWN_ORIGIN = 'an imported fighter package (where it came from was not recorded)'
BEFORE_RECORDS = ('the Vault, from before Nucleus recorded where fighter source came from '
                  '(it may have come inside a downloaded package)')
CHANGED_SINCE = 'an unknown place (it changed after Nucleus recorded where this fighter\'s source came from)'
MAX_ORIGIN = 400

_lock = threading.Lock()
_origin = contextvars.ContextVar('fighter_source_origin', default=None)


# ---- where an import came from ----

def describe_origin(text):
    """``text`` made safe to store and show: one line, no control characters, bounded."""
    flat = ' '.join(''.join(c if c.isprintable() else ' ' for c in str(text or '')).split())
    return flat[:MAX_ORIGIN] or UNKNOWN_ORIGIN


@contextlib.contextmanager
def import_origin(text):
    """While this is open, fighter source an import keeps is recorded as coming from ``text`` (the import
    entry points say where the package came from: vault/importing/unified/protocol.py import_handoff)."""
    token = _origin.set(describe_origin(text))
    try:
        yield
    finally:
        _origin.reset(token)


def current_origin():
    return _origin.get() or UNKNOWN_ORIGIN


# ---- the records ----

def store_path(custom_characters_dir):
    return Path(custom_characters_dir).parent / STORE_NAME


def _load(store):
    try:
        data = json.loads(Path(store).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    fighters = data.get('fighters') if isinstance(data, dict) else None
    return fighters if isinstance(fighters, dict) else {}


def _save(store, fighters):
    store = Path(store)
    store.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.fighter_source_', suffix='.json', dir=str(store.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'version': 1, 'fighters': fighters}, f, indent=2, sort_keys=True)
        os.replace(tmp, store)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def record(custom_characters_dir, slug, state, *, digest, origin):
    """Write what is known about ``slug``'s source now: its ``state`` (attached / untrusted), the sha256 of the
    source it describes and where it came from. Replaces whatever was recorded before."""
    if state not in (ATTACHED, UNTRUSTED):
        raise ValueError(f'unknown fighter source state {state!r}')
    now = datetime.now().isoformat(timespec='seconds')
    with _lock:
        store = store_path(custom_characters_dir)
        fighters = _load(store)
        fighters[slug] = {'state': state, 'sha256': digest, 'origin': describe_origin(origin), 'recordedAt': now}
        _save(store, fighters)


def confirm(custom_characters_dir, slug, *, digest, shown_digest):
    """Record that the user confirmed ``slug``'s source in the window. ``shown_digest`` is the sha256 the window
    showed when it asked; when the source changed since (``digest`` differs), nothing is confirmed. The origin
    kept is the one the window showed (:func:`status`). Returns the record."""
    if not shown_digest or shown_digest != digest:
        raise ValueError('This fighter\'s source changed after it was shown to you. Nothing was confirmed: '
                         'look at it again.')
    now = datetime.now().isoformat(timespec='seconds')
    with _lock:
        store = store_path(custom_characters_dir)
        fighters = _load(store)
        shown = _verdict(fighters.get(slug), digest)
        fighters[slug] = {'state': CONFIRMED, 'sha256': digest, 'origin': shown['origin'],
                          'recordedAt': shown['recordedAt'] or now, 'confirmedAt': now}
        _save(store, fighters)
        return dict(fighters[slug])


def forget(custom_characters_dir, slug):
    with _lock:
        store = store_path(custom_characters_dir)
        fighters = _load(store)
        if fighters.pop(slug, None) is not None:
            _save(store, fighters)


def status(custom_characters_dir, slug, digest):
    """What the export may do with ``slug``'s source, whose sha256 is ``digest`` now:
    {trusted, state, origin, recordedAt, sha256, reason}. Untrusted unless a record says this very source was
    attached in the window or confirmed there."""
    verdict = _verdict(_load(store_path(custom_characters_dir)).get(slug), digest)
    trusted = verdict['state'] in TRUSTED_STATES
    return {'trusted': trusted, **verdict, 'sha256': digest,
            'reason': None if trusted else f'its C source came from {verdict["origin"]} and has not been confirmed'}


def _verdict(entry, digest):
    """{state, origin, recordedAt} for source whose sha256 is ``digest``, given its record (or None)."""
    if not isinstance(entry, dict) or not entry:
        return {'state': UNTRUSTED, 'origin': BEFORE_RECORDS, 'recordedAt': None}
    if entry.get('sha256') != digest:
        # The record is about other bytes: the code was changed or replaced after it was recorded.
        return {'state': UNTRUSTED, 'origin': CHANGED_SINCE, 'recordedAt': None}
    state = entry.get('state') if entry.get('state') in (ATTACHED, CONFIRMED, UNTRUSTED) else UNTRUSTED
    return {'state': state, 'origin': describe_origin(entry.get('origin') or BEFORE_RECORDS),
            'recordedAt': entry.get('recordedAt')}


def confirmation_text(name, origin):
    """What the window asks before an imported fighter's C may be built: it names the fighter and the origin."""
    return (f'Build {name} from C source that came from {origin}? Melee Unlocked runs a fighter plugin as native '
            'code on this computer, so only confirm source you trust. Nucleus has not checked what it does.')
