"""SHA-256 of a file, a stream or a bytes value: the one definition.

``sha256_file`` raises whatever ``open`` raises; ``sha256_file_or_none`` answers
None for a path that is not an existing regular file. Both stream the bytes, so
the chunk size changes memory use, never the digest. Callers that add something
on top (a ``sha256:`` prefix, a cache, a progress callback, a guarded handle)
keep that part and hash through these.
"""

import hashlib
from pathlib import Path

CHUNK = 1 << 20


def sha256_stream(stream, chunk=CHUNK):
    """Hex SHA-256 of everything left to read in a binary stream."""
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(chunk), b''):
        digest.update(block)
    return digest.hexdigest()


def sha256_file(path, chunk=CHUNK):
    """Hex SHA-256 of a file's bytes."""
    with open(path, 'rb') as stream:
        return sha256_stream(stream, chunk)


def sha256_file_or_none(path, chunk=CHUNK):
    """Hex SHA-256 of a file's bytes, or None when it is not a regular file."""
    path = Path(path)
    if not path.is_file():
        return None
    return sha256_file(path, chunk)


def sha256_bytes(data):
    """Hex SHA-256 of a bytes-like value."""
    return hashlib.sha256(data).hexdigest()
