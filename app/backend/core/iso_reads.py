"""Admit Melee's 32-byte rounded DVD reads, including the last FST file.

Padding the whole image to 32 bytes is insufficient when an FST file starts
at a non-32-byte boundary. Only missing read padding can be repaired here;
truncated file payloads or malformed FSTs are refused.
"""
import hashlib
import os
import struct
from pathlib import Path


def _inspect(stream):
    size = os.fstat(stream.fileno()).st_size
    stream.seek(0)
    header = stream.read(0x430)
    if len(header) != 0x430 or header[0x1C:0x20] != bytes.fromhex('c2339f3d'):
        raise ValueError('Expected a complete GameCube disc header')
    offset, length = struct.unpack_from('>II', header, 0x424)
    if not 12 <= length <= 16 * 1024 * 1024 or offset < 0x430 or offset + length > size:
        raise ValueError('Invalid or truncated FST region')
    stream.seek(offset)
    fst = stream.read(length)
    count = struct.unpack_from('>I', fst, 8)[0]
    if fst[0] != 1 or count < 1 or count * 12 > length:
        raise ValueError('Invalid FST root/count')
    strings = fst[count * 12:]
    files, required_end, issues = 0, size, []
    for index in range(1, count):
        entry = fst[index * 12:(index + 1) * 12]
        name_offset = int.from_bytes(entry[1:4], 'big')
        end = strings.find(b'\0', name_offset)
        if name_offset >= len(strings) or end < 0 or entry[0] not in (0, 1):
            raise ValueError(f'Invalid FST entry {index}')
        name = strings[name_offset:end].decode('ascii', errors='replace')
        start, payload_size = struct.unpack_from('>II', entry, 4)
        if entry[0]:
            if not index < payload_size <= count:
                raise ValueError(f'Invalid FST directory extent: {name}')
            continue
        files += 1
        if start + payload_size > size:
            raise ValueError(f'Truncated ISO payload, cannot repair by padding: {name}')
        if payload_size and start % 4:
            raise ValueError(f'Unaligned DVD file offset: {name}')
        read_end = start + ((payload_size + 31) & ~31)
        if read_end > size:
            issues.append(dict(fst_index=index, name=name, offset=start,
                               bytes=payload_size, read_end=read_end,
                               missing_padding=read_end - size))
            required_end = max(required_end, read_end)
    return dict(schema='gamecube-rounded-read-admission-v1', bytes=size,
                fst_sha256=hashlib.sha256(fst).hexdigest(), files=files,
                required_end=required_end, issues=issues,
                status='FAIL_MISSING_READ_PADDING' if issues else 'PASS_ROUNDED_DVD_READS')


def inspect(path):
    with Path(path).open('rb') as stream:
        return _inspect(stream)


def ensure_padding(path):
    """Append zeros only when a valid payload's rounded read exceeds EOF.

    All existing bytes, FST offsets, filenames and lengths remain unchanged.
    A repair ends at a 2048-byte sector boundary and is idempotent. Caller
    owns this export and must prevent concurrent writers or active readers.
    """
    with Path(path).open('r+b') as stream:
        before = _inspect(stream)
        target = (before['required_end'] + 2047) & ~2047 if before['issues'] else before['bytes']
        stream.seek(0, 2)
        if stream.tell() != before['bytes']:
            raise ValueError('ISO changed while admitting rounded reads')
        added = target - before['bytes']
        # A valid payload can lack at most 31 bytes, plus sector rounding.
        if not 0 <= added <= 2078:
            raise ValueError('Unexpected ISO padding extent')
        if added:
            stream.write(bytes(added))
            stream.flush()
            os.fsync(stream.fileno())
        after = _inspect(stream)
        if after['issues'] or after['fst_sha256'] != before['fst_sha256']:
            raise ValueError('Rounded DVD read admission failed after padding')
    return dict(schema='gamecube-read-padding-v1', before=before, after=after,
                added_bytes=added, status='PASS_ROUNDED_DVD_READS',
                scope='Disc read bounds only; does not establish gameplay acceptance')


def fst_entries(path):
    """Every FILE in a GameCube image's FST, with its validated extent.

    Returns ``{name: {'offset': int, 'bytes': int}}``.

    Melee's disc is flat, so a costume DAT appears here under exactly the name
    the project's fighter table gave it. That makes this the check that can tell
    "the build was rebuilt with this costume in it" from "the project directory
    mentions it": the bytes the user would boot either carry the file or they do
    not.

    Names alone are not enough, so each entry is validated the way `_inspect`
    validates them -- the extent must lie inside the image and start on a
    4-byte boundary. An FST naming a file whose payload is outside the image is
    a malformed disc, not a disc containing that file, and this raises rather
    than reporting the name.
    """
    with Path(path).open('rb') as stream:
        size = os.fstat(stream.fileno()).st_size
        stream.seek(0)
        header = stream.read(0x430)
        if len(header) != 0x430 or header[0x1C:0x20] != bytes.fromhex('c2339f3d'):
            raise ValueError('Expected a complete GameCube disc header')
        offset, length = struct.unpack_from('>II', header, 0x424)
        if not 12 <= length <= 16 * 1024 * 1024 or offset < 0x430 or offset + length > size:
            raise ValueError('Invalid or truncated FST region')
        stream.seek(offset)
        fst = stream.read(length)
    count = struct.unpack_from('>I', fst, 8)[0]
    if fst[0] != 1 or count < 1 or count * 12 > length:
        raise ValueError('Invalid FST root/count')
    strings = fst[count * 12:]
    entries = {}
    for index in range(1, count):
        entry = fst[index * 12:(index + 1) * 12]
        name_offset = int.from_bytes(entry[1:4], 'big')
        end = strings.find(b'\0', name_offset)
        if name_offset >= len(strings) or end < 0 or entry[0] not in (0, 1):
            raise ValueError(f'Invalid FST entry {index}')
        if entry[0]:
            continue
        name = strings[name_offset:end].decode('ascii', errors='replace')
        start, payload = struct.unpack_from('>II', entry, 4)
        if start + payload > size:
            raise ValueError(f'Truncated ISO payload: {name}')
        if payload and start % 4:
            raise ValueError(f'Unaligned DVD file offset: {name}')
        entries[name] = {'offset': start, 'bytes': payload}
    return entries


def file_names(path):
    """The set of file names in a GameCube image's FST, each with a valid extent."""
    return set(fst_entries(path))


def file_digest(path, name, entries=None):
    """SHA-256 of one FST file's payload, or None when the image has no such file.

    This is what makes "the costume is in the disc image" a statement about
    BYTES rather than about a name: the digest is compared against the same
    file inside the project the build came from.
    """
    entries = entries if entries is not None else fst_entries(path)
    entry = entries.get(name)
    if entry is None:
        return None
    digest = hashlib.sha256()
    remaining = entry['bytes']
    with Path(path).open('rb') as stream:
        stream.seek(entry['offset'])
        while remaining > 0:
            chunk = stream.read(min(1 << 20, remaining))
            if not chunk:
                raise ValueError(f'Truncated ISO payload while reading {name}')
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()
