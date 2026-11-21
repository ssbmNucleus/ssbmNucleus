"""Downloaded bytes held between the preview and the import.

The approval a user gives describes a post. What arrives is an object nobody
has looked at yet, so the two have to be joined: the download happens into
quarantine while the preview is being built, the object is identified there,
and the approval card states what it actually IS and where it will land. The
grant is then bound to that object's hash (2026-09-22 review, 4).

Holding the bytes also removes the second download the importer's own
questions used to cost. A whole character-select DAT is legitimately both an
icon grid and a backdrop; the answer now arrives as the approval's choice and
is applied to the object already on disk, instead of a reply that says "ask me
again" (re-review, 5).

What the third review found wrong with the first version, and what this does
instead (review JJ, 9):

* **The name was derived from public post metadata**, so two preparations of
  the same post shared a pathname: two with different bytes collided, and
  checking the older hash deleted the newer object. A hold now mints a RANDOM
  identifier; nothing can predict or collide with it.
* **Publication was a plain copy**, so a reader could see a half-written file.
  The bytes land on a temporary name and are moved into place atomically, with
  a sidecar recording the owner and the hash.
* **Anything that knew the name could take the object.** A hold records the
  post, file and revision it belongs to, and a mismatched owner is refused
  rather than served.
* **The cap counted objects, not bytes**, and only ran opportunistically: 26
  sequential holds left 25 under a limit of 24. Capacity is bytes AND count,
  the incoming object is counted before it is admitted, and expiry runs at
  process start as well as on every hold.
"""
import hashlib
import json
import logging
import secrets
import shutil
import time
from pathlib import Path

import file_retry

logger = logging.getLogger(__name__)

TTL_SECONDS = 60 * 60            # an approval expires in 15 minutes; this is slack
MAX_HELD = 24                    # a bounded holding area, not a cache
MAX_HELD_BYTES = 1024 * 1024 * 1024
_STARTED = False


def _root():
    """The holding directory, swept once per process on first use."""
    global _STARTED
    from core.config import SCRATCH_PATH
    root = Path(SCRATCH_PATH) / 'website-quarantine'
    root.mkdir(parents=True, exist_ok=True)
    if not _STARTED:
        _STARTED = True
        # Anything still here belongs to a run that is over.
        for path in root.iterdir():
            try:
                path.unlink()
            except OSError:
                pass
    return root


def _paths(token):
    if not isinstance(token, str) or not 8 <= len(token) <= 64 or not token.isalnum():
        raise ValueError('Invalid quarantine token.')
    root = _root()
    return root / f'{token}.bin', root / f'{token}.json'


def _record(token):
    _, sidecar = _paths(token)
    try:
        entry = json.loads(sidecar.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


def _held_objects():
    """[(token, sidecar dict, size)] for everything currently held."""
    out = []
    for sidecar in _root().glob('*.json'):
        token = sidecar.stem
        try:
            entry = json.loads(sidecar.read_text(encoding='utf-8'))
            size = (_root() / f'{token}.bin').stat().st_size
        except (OSError, ValueError):
            release(token)
            continue
        out.append((token, entry, size))
    return out


def sweep(now=None, *, incoming=0):
    """Expire by age, then make room for `incoming` bytes, oldest first."""
    now = now if now is not None else time.time()
    held = []
    for token, entry, size in _held_objects():
        if now - float(entry.get('at') or 0) > TTL_SECONDS:
            release(token)
            continue
        held.append((float(entry.get('at') or 0), token, size))
    held.sort()
    total = sum(size for _, _, size in held) + max(0, int(incoming or 0))
    count = len(held) + (1 if incoming else 0)
    while held and (total > MAX_HELD_BYTES or count > MAX_HELD):
        _, token, size = held.pop(0)
        release(token)
        total -= size
        count -= 1
    return count <= MAX_HELD and total <= MAX_HELD_BYTES


def hold(source, *, owner):
    """Admit `source` under a fresh random token. Returns (token, sha256).

    Raises when the object cannot be admitted within the holding area's
    capacity -- refusing is the honest answer, and it keeps a download from
    quietly evicting an approval somebody is looking at right now.
    """
    source = Path(source)
    size = source.stat().st_size
    if size > MAX_HELD_BYTES:
        raise ValueError('This download is too large to hold for approval. '
                         'Download it from the website instead.')
    if not sweep(incoming=size):
        raise ValueError('Too many downloads are waiting for approval. Answer or '
                         'dismiss one, then try again.')
    token = secrets.token_hex(16)
    blob, sidecar = _paths(token)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    staging = blob.with_suffix('.partial')
    shutil.copyfile(source, staging)
    file_retry.replace(staging, blob)          # atomic publication: never half a file
    sidecar.write_text(json.dumps({
        'at': time.time(), 'sha256': digest, 'owner': str(owner), 'size': size,
    }), encoding='utf-8')
    return token, digest


def held(token, expected_sha256=None, *, owner=None):
    """The held object's path, or None when it is not the one asked for.

    A missing object, an expired one, a different owner or different bytes all
    answer None. The caller treats that as "this approval no longer refers to
    anything" -- it must not fetch a replacement and import that instead.
    """
    try:
        blob, _ = _paths(token)
    except ValueError:
        return None
    entry = _record(token)
    if entry is None or not blob.is_file():
        return None
    if time.time() - float(entry.get('at') or 0) > TTL_SECONDS:
        release(token)
        return None
    if owner is not None and entry.get('owner') != str(owner):
        return None                     # not ours: left alone, not deleted
    if expected_sha256 and entry.get('sha256') != expected_sha256:
        return None
    if expected_sha256 and hashlib.sha256(blob.read_bytes()).hexdigest() != expected_sha256:
        return None
    return blob


def release(token):
    """Drop a held object. Never raises: this is cleanup, not a step."""
    try:
        blob, sidecar = _paths(token)
    except ValueError:
        return
    for path in (blob, sidecar, blob.with_suffix('.partial')):
        try:
            path.unlink()
        except OSError:
            pass
