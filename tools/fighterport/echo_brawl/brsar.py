"""Brawl's sound archive (smashbros_sound.brsar): every sound the game plays, by number and by name.

The file is big-endian, in three sections. SYMB holds the names. INFO holds the tables: the sounds (a name, the
file it is in, its kind), the files (which groups hold each), and the groups (a group is a run of files loaded
together; it says where each of its files sits in the archive). FILE holds the groups' data: each file's header
part, then the group's sample data.

A table is a count, then 8-byte references: a kind byte, three unused, an offset from the section's data start
(8 bytes past its tag).

A 'wave' sound is one entry of an RWSD file. The entry leads (first track, first note event, its note) to one
of the waves of the file's WAVE section; in Brawl's archive every entry has one track, one event and one note.
A wave's header gives the samples' format, rate and length, where they are in the file's sample data, and for
each channel its ADPCM numbers. The samples are the GameCube's 4-bit
ADPCM: 8-byte frames, a byte that picks one of the wave's eight coefficient pairs (high half) and a shift (low
half), then fourteen samples. (The format also allows plain 8-bit and 16-bit samples. They are read here, but
no wave in Brawl's archive uses them, so that reading has never met real data.)

Every RWSD in Brawl's archive is version 1.2, the layout above. Later versions keep the waves as whole RWAV
files in an RWAR; that is not read here.

The number a fighter's sound script gives (`sound`, `stop_sound` ...) is the sound's index in INFO: the 'id'.

    python -m echo_brawl.brsar <brsar> <fighter> [<out dir>]
"""
from __future__ import annotations

import re
import struct
import sys
import wave as wavfile
from pathlib import Path

import numpy as np

KINDS = {1: 'seq', 2: 'strm', 3: 'wave'}
PCM8, PCM16, ADPCM = 0, 1, 2

# INFO starts with a reference to each of its tables; the offsets are at:
SOUNDS, FILES, GROUPS = 0x04, 0x1C, 0x24


def _u32(data, at):
    return struct.unpack_from('>I', data, at)[0]


def _refs(data, base, table):
    """The table at `table` (a count, then references) -> where each reference points."""
    return [base + _u32(data, table + 8 + i * 8) for i in range(_u32(data, table))]


# ---- the archive's tables
def _open(f):
    """-> (the archive up to its FILE section, {'SYMB' | 'INFO' | 'FILE': where that section's data starts})"""
    start = f.read(0x10)
    if start[:6] != b'RSAR\xfe\xff':
        raise ValueError('not a big-endian RSAR sound archive')
    size, count = struct.unpack_from('>HH', start, 0x0C)
    start += f.read(size - 0x10)
    at = {}
    for i in range(count):
        off = _u32(start, 0x10 + i * 8)
        f.seek(off)
        at[f.read(4).decode('ascii')] = off + 8
    f.seek(0)
    return f.read(at['FILE'] - 8), at


def _names(head, symb):
    """SYMB starts with the offset of its list of names: a count, then each name's offset."""
    table = symb + _u32(head, symb)
    out = []
    for i in range(_u32(head, table)):
        at = symb + _u32(head, table + 4 + i * 4)
        out.append(head[at:head.index(b'\x00', at)].decode('ascii', 'replace'))
    return out


def _sounds(head, at):
    """A sound's entry: name, file, player, a reference to its 3D numbers, volume, priority, kind (at 0x16),
    remote filter, then a reference (at 0x18) to what its kind needs: for a wave, its entry in the RWSD."""
    names, info = _names(head, at['SYMB']), at['INFO']
    out = []
    for i, e in enumerate(_refs(head, info, info + _u32(head, info + SOUNDS))):
        name, file = struct.unpack_from('>iI', head, e)
        kind = KINDS.get(head[e + 0x16], head[e + 0x16])
        out.append({'id': i, 'name': names[name] if name >= 0 else '', 'file': file, 'kind': kind,
                    'wave': _u32(head, info + _u32(head, e + 0x1C)) if kind == 'wave' else None})
    return out


def sounds(path):
    """Every sound in the archive, in INFO's order -> [{'id', 'name', 'file', 'kind', 'wave'}]; 'kind' is 'seq',
    'strm' or 'wave', 'wave' the sound's entry in its RWSD file (None for the other kinds)."""
    with open(path, 'rb') as f:
        return _sounds(*_open(f))


def _place(head, info, file):
    """Where a file is in the archive -> (its header part's offset, size, its sample data's offset, size).
    A file may be in several groups (each holds a copy); the first is read."""
    entry = _refs(head, info, info + _u32(head, info + FILES))[file]
    places = _refs(head, info, info + _u32(head, entry + 0x18))
    if not places:
        raise ValueError(f'file {file} is not in the archive (it is a stream on the disc)')
    group, index = struct.unpack_from('>II', head, places[0])
    group = _refs(head, info, info + _u32(head, info + GROUPS))[group]
    start, _size, samples, _samples_size = struct.unpack_from('>4I', head, group + 0x10)
    item = _refs(head, info, info + _u32(head, group + 0x24))[index]
    _file, off, size, wave_off, wave_size = struct.unpack_from('>5I', head, item)
    return start + off, size, samples + wave_off, wave_size


# ---- an RWSD file
def rwsd(data):
    """An RWSD file's header part -> (for each entry the wave it plays first, or None; each wave's header).

    An entry is three references: its numbers, its tracks, its notes. A track is a list of note events (when,
    how long, which note); a note starts with its wave's index."""
    if data[:4] != b'RWSD':
        raise ValueError('not an RWSD file')
    at = {}
    for i in range(struct.unpack_from('>H', data, 0x0E)[0]):
        off = _u32(data, 0x10 + i * 8)
        at[data[off:off + 4]] = off
    if b'WAVE' not in at:
        raise ValueError('an RWSD with no WAVE section (its waves are in an RWAR): not read here')
    base = at[b'DATA'] + 8
    plays = []
    for e in _refs(data, base, base):
        tracks = _refs(data, base, base + _u32(data, e + 0x0C))
        notes = _refs(data, base, base + _u32(data, e + 0x14))
        events = _refs(data, base, base + _u32(data, tracks[0] + 4)) if tracks else []
        note = _u32(data, events[0] + 8) if events else 0
        plays.append(_u32(data, notes[note]) if note < len(notes) else None)
    start = at[b'WAVE']
    return plays, [wave_header(data, start + _u32(data, start + 12 + i * 4)) for i in range(_u32(data, start + 8))]


def wave_header(data, at):
    """A wave's header -> {'format', 'loop', 'rate', 'loop_start', 'end', 'data', 'channels': [{'data', 'coefs',
    'h1', 'h2'}]}. 'data' is where the samples start in the file's sample data, a channel's 'data' is from
    there. In ADPCM 'loop_start' and 'end' count half-bytes, frame headers included, and 'end' is the last
    sample's own half-byte; otherwise they count samples."""
    kind, loop, count, rate_hi, rate, _where, _pad, loop_start, end, table, start = struct.unpack_from('>BBBBHBBIIII', data, at)
    channels = []
    for i in range(count):
        info = at + _u32(data, at + table + i * 4)
        off, adpcm = struct.unpack_from('>II', data, info)
        channel = {'data': off, 'coefs': None, 'h1': 0, 'h2': 0}
        if kind == ADPCM:
            # sixteen coefficients, gain, the first frame's header, the two samples before the first
            channel['coefs'] = struct.unpack_from('>16h', data, at + adpcm)
            channel['h1'], channel['h2'] = struct.unpack_from('>hh', data, at + adpcm + 0x24)
        channels.append(channel)
    return {'format': kind, 'loop': bool(loop), 'rate': rate_hi << 16 | rate, 'loop_start': loop_start, 'end': end,
            'data': start, 'channels': channels}


def wave_size(header):
    """-> (how many samples the wave has, how many bytes one channel's samples take)"""
    if header['format'] == ADPCM:
        frames, last = divmod(header['end'], 16)
        return frames * 14 + max(last - 1, 0), (frames + 1) * 8
    return header['end'], header['end'] * (2 if header['format'] == PCM16 else 1)


# ---- samples
def adpcm(data, count, coefs, h1=0, h2=0):
    """GameCube ADPCM -> `count` samples (int16). `h1` and `h2` are the two samples before the first."""
    frames = np.frombuffer(data, np.uint8, len(data) // 8 * 8).reshape(-1, 8)[:-(-count // 14)]
    heads = frames[:, 0].astype(np.int64)
    steps = np.stack([frames[:, 1:] >> 4, frames[:, 1:] & 15], axis=2).reshape(-1, 14).astype(np.int64)
    steps[steps > 7] -= 16
    steps = (steps << (heads & 15)[:, None] << 11) + 1024           # the frame's shift, and the rounding
    pair = (heads >> 4 & 7) * 2
    out = []
    for row, a, b in zip(steps.tolist(), np.take(coefs, pair).tolist(), np.take(coefs, pair + 1).tolist()):
        for step in row:
            s = (step + a * h1 + b * h2) >> 11
            s = 32767 if s > 32767 else -32768 if s < -32768 else s
            out.append(s)
            h2, h1 = h1, s
    return np.array(out[:count], np.int16)


def decode(header, read):
    """A wave's samples as mono int16 (channels averaged). `read(offset, size)` gives bytes of the file's
    sample data."""
    count, size = wave_size(header)
    channels = []
    for c in header['channels']:
        raw = read(header['data'] + c['data'], size)
        if header['format'] == ADPCM:
            channels.append(adpcm(raw, count, c['coefs'], c['h1'], c['h2']))
        elif header['format'] == PCM16:
            channels.append(np.frombuffer(raw, '>i2', count).astype(np.int16))
        elif header['format'] == PCM8:
            channels.append(np.frombuffer(raw, np.int8, count).astype(np.int16) << 8)
        else:
            raise ValueError(f"unknown sample format {header['format']}")
    if len(channels) == 1:
        return channels[0]
    return np.round(np.mean(channels, axis=0)).astype(np.int16)


def fighter_sounds(path, fighter):
    """A fighter's wave sounds, decoded -> {lower-case name: {'id', 'name', 'pcm' (int16, mono), 'rate'}}.

    A sound is the fighter's when its name has the fighter's name as a word ('ike': snd_vc_Ike_Attack01,
    snd_se_narration_characall_Ike; not Excitebike). Of a sound that plays several waves, the first is taken."""
    word = re.compile(rf'(?<![a-z]){re.escape(fighter)}(?![a-z])', re.I)
    out, files = {}, {}
    with open(path, 'rb') as f:
        head, at = _open(f)

        def read(off, size):
            f.seek(off)
            return f.read(size)

        for s in _sounds(head, at):
            if s['kind'] != 'wave' or not word.search(s['name']):
                continue
            if s['file'] not in files:
                off, size, samples, _samples_size = _place(head, at['INFO'], s['file'])
                files[s['file']] = rwsd(read(off, size)) + (samples,)
            plays, waves, samples = files[s['file']]
            if s['wave'] >= len(plays) or plays[s['wave']] is None:
                continue
            header = waves[plays[s['wave']]]
            pcm = decode(header, lambda off, size: read(samples + off, size))
            out[s['name'].lower()] = {'id': s['id'], 'name': s['name'], 'pcm': pcm, 'rate': header['rate'],
                                      'loop': bool(header.get('loop'))}
    return out


def to_wav(sound, out_path, rate, longest=None):
    """Write a sound (a `fighter_sounds` value) as a 16-bit mono WAV at `rate`, cut to `longest` seconds."""
    pcm = np.asarray(sound['pcm'], np.float64)
    if rate != sound['rate'] and len(pcm):
        count = max(1, round(len(pcm) * rate / sound['rate']))
        pcm = np.interp(np.arange(count) * (sound['rate'] / rate), np.arange(len(pcm)), pcm)
    if longest is not None:
        pcm = pcm[:int(longest * rate)]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wavfile.open(str(out_path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(np.round(pcm), -32768, 32767).astype('<i2').tobytes())
    return out_path


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    found = fighter_sounds(argv[0], argv[1])
    for s in sorted(found.values(), key=lambda s: s['id']):
        print(s['id'], s['name'], f"{len(s['pcm']) / s['rate']:.3f}", s['rate'])
        if len(argv) == 3:
            to_wav(s, Path(argv[2]) / (s['name'] + '.wav'), s['rate'])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
