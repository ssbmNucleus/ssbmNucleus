"""Ultimate's sound banks: the sounds of a .nus3audio file, by name, as plain audio.

A .nus3audio file is a list of named sounds. A fighter's are stored the way the GameCube stored sound
(4-bit ADPCM with sixteen coefficients, eight bytes for fourteen samples: the format Melee's own banks
use), under a short header of the game's own.

  sounds(path)             -> {name: bytes of one sound as the game stores it}
  pcm(sound)               -> (sample rate, mono samples as int16)
  to_wav(sound, out, rate) -> one mono 16-bit WAV at `rate`
"""
from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np


def sounds(path) -> dict:
    """{name: the sound's bytes} of a .nus3audio file (little-endian sections: ids, name offsets, data
    offsets and sizes, the names, the data)."""
    data = Path(path).read_bytes()
    if data[:4] != b'NUS3' or data[8:16] != b'AUDIINDX':
        raise ValueError(f'{path}: not a nus3audio file')
    count = struct.unpack_from('<I', data, 20)[0]
    at, sections = 24, {}
    while at + 8 <= len(data):
        tag, size = data[at:at + 4], struct.unpack_from('<I', data, at + 4)[0]
        sections[tag] = (at + 8, size)
        if tag == b'PACK':
            break
        at += 8 + size
    names_at, where = sections[b'NMOF'][0], sections[b'ADOF'][0]
    out = {}
    for i in range(count):
        n = struct.unpack_from('<I', data, names_at + 4 * i)[0]
        name = data[n:data.index(b'\0', n)].decode('ascii', 'replace')
        offset, size = struct.unpack_from('<II', data, where + 8 * i)
        out.setdefault(name, data[offset:offset + size])
    return out


def _decode(data: bytes, coefs, count: int) -> np.ndarray:
    """`count` samples of GameCube ADPCM: each eight bytes are a header (which pair of coefficients,
    how far to scale) and fourteen 4-bit steps from the two samples before."""
    out = np.zeros(count, np.int16)
    h1 = h2 = 0
    n = 0
    for frame in range(0, len(data) - 7, 8):
        head = data[frame]
        scale, pair = 1 << (head & 0xF), (head >> 4) & 7
        c1, c2 = coefs[2 * pair], coefs[2 * pair + 1]
        for k in range(14):
            if n >= count:
                return out
            byte = data[frame + 1 + (k >> 1)]
            nib = (byte >> 4) if k % 2 == 0 else (byte & 0xF)
            if nib >= 8:
                nib -= 16
            s = ((nib * scale) << 11) + c1 * h1 + c2 * h2 + 1024 >> 11
            s = 32767 if s > 32767 else -32768 if s < -32768 else s
            out[n] = s
            n += 1
            h2, h1 = h1, s
    return out


def pcm(sound: bytes):
    """(sample rate, mono int16 samples) of one sound; several channels are averaged."""
    if sound[:4] != b'IDSP':
        raise ValueError(f'not a sound in the GameCube format ({sound[:4]!r})')
    channels, rate, count, _, _, interleave, heads, spacing, start = struct.unpack_from('>9I', sound, 8)
    body = sound[start:]
    parts = []
    for c in range(channels):
        at = heads + spacing * c
        coefs = struct.unpack_from('>16h', sound, at + 0x1C)
        if channels == 1:
            mine = body
        else:                                           # the channels take turns, `interleave` bytes each
            mine = b''.join(body[i:i + interleave] for i in range(c * interleave, len(body), channels * interleave))
        parts.append(_decode(mine, coefs, count).astype(np.int32))
    mono = sum(parts) // len(parts)
    return int(rate), mono.astype(np.int16)


def resample(samples: np.ndarray, rate: int, to: int) -> np.ndarray:
    import math
    from scipy.signal import resample_poly
    if rate == to:
        return samples
    g = math.gcd(rate, to)
    out = resample_poly(samples.astype(np.float64), to // g, rate // g)
    return np.clip(np.rint(out), -32768, 32767).astype(np.int16)


def to_wav(sound: bytes, out, rate: int, seconds=None) -> Path:
    """One mono 16-bit WAV at `rate`, cut to `seconds` when given (with a short fade so the cut does not click)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    source_rate, samples = pcm(sound)
    samples = resample(samples, source_rate, int(rate))
    if seconds and len(samples) > int(seconds * rate):
        samples = samples[:int(seconds * rate)].copy()
        fade = min(len(samples), int(0.03 * rate))
        samples[-fade:] = (samples[-fade:] * np.linspace(1.0, 0.0, fade)).astype(np.int16)
    with wave.open(str(out), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(samples.tobytes())
    return out
