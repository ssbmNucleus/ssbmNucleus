"""Ultimate's music streams (a victory fanfare, a stage's music): Opus packets in the console's own wrapper.

A stream file (`stream:/sound/bgm/<name>.nus3audio`) holds one sound whose data starts `OPUS`: a short header of
the publisher's (how many samples, channels, rate, where the console's header starts), then the console's own
header (type 0x80000001: channels, rate, the samples to skip at the start), then a data chunk (type 0x80000004) of
packets, each a length, a number the decoder does not need, and the Opus packet itself.

Nothing here decodes Opus: `ogg` puts the same packets in an Ogg file, which any Opus decoder plays (ffmpeg does).
"""
from __future__ import annotations

import struct
import subprocess
from pathlib import Path

_TABLE = []
for _i in range(256):
    _c = _i << 24
    for _ in range(8):
        _c = ((_c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if _c & 0x80000000 else (_c << 1) & 0xFFFFFFFF
    _TABLE.append(_c)


def _crc(data: bytes) -> int:
    """An Ogg page's checksum."""
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _TABLE[((crc >> 24) ^ b) & 0xFF]
    return crc


def _page(kind: int, granule: int, serial: int, number: int, packets) -> bytes:
    lacing = b''.join(bytes([255] * (len(p) // 255) + [len(p) % 255]) for p in packets)
    head = b'OggS' + struct.pack('<BBqIII', 0, kind, granule, serial, number, 0) + bytes([len(lacing)]) + lacing
    page = head + b''.join(packets)
    return page[:22] + struct.pack('<I', _crc(page)) + page[26:]


def samples(packet: bytes) -> int:
    """How many samples (at 48,000 a second) an Opus packet holds, from its first byte."""
    toc = packet[0]
    config, code = toc >> 3, toc & 3
    if config < 12:
        one = (480, 960, 1920, 2880)[config % 4]
    elif config < 16:
        one = (480, 960)[config % 2]
    else:
        one = (120, 240, 480, 960)[config % 4]
    count = 1 if code == 0 else 2 if code in (1, 2) else packet[1] & 0x3F
    return one * count


def read(sound: bytes) -> dict:
    """A stream sound taken apart: dict(channels, rate, skip, samples, packets)."""
    if sound[:4] != b'OPUS':
        raise ValueError(f'not a music stream ({sound[:4]!r})')
    total, channels, rate = struct.unpack_from('>III', sound, 8)
    at = struct.unpack_from('>I', sound, 0x20)[0]
    kind, size = struct.unpack_from('<II', sound, at)
    if kind != 0x80000001:
        raise ValueError("the console's header is not where the stream says")
    skip = struct.unpack_from('<H', sound, at + 0x1C)[0]
    at += 8 + size
    kind, size = struct.unpack_from('<II', sound, at)
    if kind != 0x80000004:
        raise ValueError('no packets follow the header')
    at, end, packets = at + 8, at + 8 + size, []
    while at + 8 <= end:
        length = struct.unpack_from('>I', sound, at)[0]
        if not length or at + 8 + length > end:
            break
        packets.append(sound[at + 8:at + 8 + length])
        at += 8 + length
    return dict(channels=channels, rate=rate, skip=skip, samples=total, packets=packets)


def ogg(sound: bytes) -> bytes:
    """The stream as an Ogg Opus file."""
    got = read(sound)
    serial = 0x4E55434C
    head = b'OpusHead' + struct.pack('<BBHIhB', 1, got['channels'], got['skip'], got['rate'], 0, 0)
    tags = b'OpusTags' + struct.pack('<I', 5) + b'lopus' + struct.pack('<I', 0)
    out = [_page(2, 0, serial, 0, [head]), _page(0, 0, serial, 1, [tags])]
    granule, number, packets = 0, 2, got['packets']
    for i in range(0, len(packets), 20):
        part = packets[i:i + 20]
        granule += sum(samples(p) for p in part)
        last = i + 20 >= len(packets)
        if last:
            granule = min(granule, got['skip'] + got['samples']) if got['samples'] else granule
        out.append(_page(4 if last else 0, granule, serial, number, part))
        number += 1
    return b''.join(out)


def to_wav(sound: bytes, path, rate: int, ffmpeg='ffmpeg') -> Path:
    """Write the stream as a 16-bit WAV at `rate` (ffmpeg decodes it)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    source = path.with_suffix('.ogg')
    source.write_bytes(ogg(sound))
    r = subprocess.run([str(ffmpeg), '-y', '-loglevel', 'error', '-i', str(source), '-ar', str(rate), '-c:a', 'pcm_s16le', str(path)],
                       capture_output=True, text=True)
    if r.returncode or not path.exists():
        raise RuntimeError(f'the stream would not decode: {(r.stdout + r.stderr)[-300:]}')
    return path
