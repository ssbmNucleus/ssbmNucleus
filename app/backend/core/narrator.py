"""Announcer name-calls for imported custom characters, matched by content.

How m-ex wires a name-call (measured on ACE 2.0 and a vanilla m-ex project,
2026-09-21):

- A fighter's ``announcerCall`` is a SEM script id, ``bank * 10000 + script``.
  Bank 51 is the narrator name bank (``nr_name.ssm``); the script's first
  "play sound" command holds an ABSOLUTE sound id (bank start + index). The
  same call is what the character-select screen plays on pick and what the
  result screen announces.
- A vanilla m-ex project's narrator bank has 52 clips (the vanilla names plus
  "break the targets"/"com player"). MexManager rewrites these identically in
  every build, so a clip's decoded PCM hashes the same in any m-ex project.
- A build can point many fighters at one clip. ACE 2.0 points 29 fighters at
  its added clip 52 ("nr_bonuschar", "Bonus Character").

Raw call ids only mean something inside the build they came from (script 59
in ACE is "Bonus Character"; in a vanilla project it's whatever the sixth
ported name-call happened to be). So calls are carried by CONTENT: the vault
keeps the decoded clip, and install resolves it against the target project:

1. the target already has a narrator clip with the same PCM (a vanilla name,
   or a clip an earlier install ported) -> point at a script that plays it;
2. otherwise port the clip once (MexCLI appends a sound + script), and every
   later character with the same clip reuses it.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

from core.build_transaction import project_file

NARRATOR_SSM = 'nr_name.ssm'
DEFAULT_CALL = 540000        # m-ex's "no name-call" placeholder
SEM_PLAY_SOUND = 1           # SEM opcode carrying the absolute sound id


def pcm_hash(wav_path) -> str | None:
    """sha1 of a WAV's sample frames (header-independent), or None."""
    try:
        with wave.open(str(wav_path), 'rb') as w:
            frames = w.readframes(w.getnframes())
            meta = f"{w.getnchannels()}:{w.getframerate()}:{w.getsampwidth()}".encode()
    except (OSError, EOFError, wave.Error):
        return None
    if not frames:
        return None
    return hashlib.sha1(meta + b'|' + frames).hexdigest()


def parse_sem(data: bytes) -> list[list[list[tuple[int, int]]]]:
    """SEM file -> banks -> scripts -> [(opcode, value)]."""
    count = struct.unpack('>I', data[8:12])[0]
    starts = struct.unpack(f'>{count + 1}I', data[12:12 + 4 * (count + 1)])
    table = 12 + 4 * (count + 1)
    total = starts[-1]
    offsets = struct.unpack(f'>{total + 1}I', data[table:table + 4 * (total + 1)])
    banks = []
    for b in range(count):
        scripts = []
        for k in range(starts[b], starts[b + 1]):
            o0, o1 = offsets[k], offsets[k + 1]
            if o1 == 0 or o1 < o0:
                o1 = len(data)
            body = data[o0:o1]
            scripts.append([(body[i], int.from_bytes(body[i + 1:i + 4], 'big'))
                            for i in range(0, len(body) - 3, 4)])
        banks.append(scripts)
    return banks


def first_sound(script) -> int | None:
    for op, value in script:
        if op == SEM_PLAY_SOUND:
            return value
    return None


def _sound_groups(project_dir: Path) -> list[dict]:
    proj = json.loads(project_file(project_dir).read_text(encoding='utf-8'))
    paths = (proj.get('soundSaveMap') or {}).get('filePaths') or []
    sounds_dir = project_dir / 'data' / 'sounds'
    if not paths:
        paths = sorted(p.name for p in sounds_dir.glob('*.json'))
    return [json.loads((sounds_dir / p).read_text(encoding='utf-8')) for p in paths]


def narrator_bank(project_dir) -> tuple[int, int, Path] | None:
    """(bank index, absolute id of its first sound, ssm path) of the
    project's narrator name bank, or None."""
    project_dir = Path(project_dir)
    start = 0
    for i, group in enumerate(_sound_groups(project_dir)):
        if (group.get('fileName') or '').lower() == NARRATOR_SSM:
            return i, start, project_dir / 'files' / 'audio' / 'us' / NARRATOR_SSM
        start += len(group.get('sounds') or [])
    return None


def narrator_scripts(project_dir) -> dict[int, int]:
    """{script index: narrator sound index} for the project's narrator bank."""
    project_dir = Path(project_dir)
    nb = narrator_bank(project_dir)
    sem = project_dir / 'files' / 'audio' / 'us' / 'smash2.sem'
    if nb is None or not sem.exists():
        return {}
    bank, start, _ = nb
    banks = parse_sem(sem.read_bytes())
    if bank >= len(banks):
        return {}
    out = {}
    for i, script in enumerate(banks[bank]):
        sid = first_sound(script)
        if sid is not None and sid >= start:
            out[i] = sid - start
    return out


def _decode(mexcli, ssm: Path, index: int, dest: Path, run=None) -> bool:
    run = run or (lambda *a: subprocess.run([str(x) for x in a], capture_output=True, text=True))
    result = run(mexcli, 'ssm-to-wav', ssm, index, dest)
    return getattr(result, 'returncode', 1) == 0 and dest.exists()


def narrator_clip_hashes(project_dir, mexcli, run=None) -> dict[int, str]:
    """{narrator sound index: pcm hash}, cached next to the ssm by its size+mtime."""
    nb = narrator_bank(project_dir)
    if nb is None or not nb[2].exists():
        return {}
    ssm = nb[2]
    stat = ssm.stat()
    key = f"{stat.st_size}:{stat.st_mtime_ns}"
    cache_path = Path(project_dir) / 'data' / 'nucleus_narrator_hashes.json'
    try:
        cached = json.loads(cache_path.read_text(encoding='utf-8'))
        if cached.get('key') == key:
            return {int(k): v for k, v in cached['hashes'].items()}
    except (OSError, ValueError, KeyError):
        pass
    count = len((_sound_groups(Path(project_dir))[nb[0]].get('sounds') or []))
    hashes = {}
    with tempfile.TemporaryDirectory(prefix='nucleus_nr_') as tmp:
        for i in range(count):
            dest = Path(tmp) / f'{i}.wav'
            if _decode(mexcli, ssm, i, dest, run):
                h = pcm_hash(dest)
                if h:
                    hashes[i] = h
    try:
        cache_path.write_text(json.dumps({'key': key, 'hashes': hashes}), encoding='utf-8')
    except OSError:
        pass
    return hashes


def find_call_for_clip(project_dir, clip_hash, mexcli, run=None) -> int | None:
    """An announcerCall in the TARGET project that plays a clip with this PCM
    hash (a vanilla name, or one an earlier install ported), or None."""
    if not clip_hash:
        return None
    nb = narrator_bank(project_dir)
    if nb is None:
        return None
    by_hash = {}
    for idx, h in narrator_clip_hashes(project_dir, mexcli, run).items():
        by_hash.setdefault(h, idx)
    sound = by_hash.get(clip_hash)
    if sound is None:
        return None
    for script, snd in sorted(narrator_scripts(project_dir).items()):
        if snd == sound:
            return nb[0] * 10000 + script
    return None


# --- ported clips -----------------------------------------------------------
#
# A ported clip is re-encoded (WAV -> DSP ADPCM) on the way in, so its decoded
# PCM no longer equals the vault clip's. Each port is therefore recorded per
# project: {source clip hash: {call, ported_hash}}. A record is trusted only
# while the call still plays a clip with that ported hash, so a project edited
# elsewhere can't send a character to the wrong line.
PORTS_FILE = 'nucleus_narrator_ports.json'


def _ports_path(project_dir) -> Path:
    return Path(project_dir) / 'data' / PORTS_FILE


def _load_ports(project_dir) -> dict:
    try:
        return json.loads(_ports_path(project_dir).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def call_clip_hash(project_dir, call, mexcli, run=None) -> str | None:
    """PCM hash of the narrator clip a call plays in this project, or None."""
    nb = narrator_bank(project_dir)
    if nb is None or not isinstance(call, int):
        return None
    bank, script = divmod(call, 10000)
    if bank != nb[0]:
        return None
    sound = narrator_scripts(project_dir).get(script)
    if sound is None:
        return None
    return narrator_clip_hashes(project_dir, mexcli, run).get(sound)


def resolve_call(project_dir, clip_hash, mexcli, run=None) -> tuple[int | None, str]:
    """(call, how) for a vault clip in the target project without porting:
    'match' when the project already has the identical clip (a vanilla name),
    'ported' when an earlier install ported the same clip, or (None, 'port')."""
    if not clip_hash:
        return None, 'none'
    call = find_call_for_clip(project_dir, clip_hash, mexcli, run)
    if call is not None:
        return call, 'match'
    rec = _load_ports(project_dir).get(clip_hash)
    if isinstance(rec, dict) and isinstance(rec.get('call'), int):
        if call_clip_hash(project_dir, rec['call'], mexcli, run) == rec.get('ported_hash'):
            return rec['call'], 'ported'
    return None, 'port'


def record_port(project_dir, clip_hash, call, mexcli, run=None) -> bool:
    """Remember that `clip_hash` now lives at `call` in this project."""
    ported = call_clip_hash(project_dir, call, mexcli, run)
    if not clip_hash or not ported:
        return False
    ports = _load_ports(project_dir)
    ports[clip_hash] = {'call': call, 'ported_hash': ported}
    try:
        _ports_path(project_dir).write_text(json.dumps(ports, indent=1), encoding='utf-8')
    except OSError:
        return False
    return True


# --- the default "Bonus Character" line ---------------------------------------
#
# A custom character without a call of its own is announced "Bonus Character",
# the line builds like ACE splice from two vanilla narrator clips. Nintendo
# audio never ships with the app: only this RECIPE does, and the clip is built
# from the project's own narrator banks (which come from the user's ISO).
# Measured against ACE 2.0's clip 52: "Bonus" is the head of nr_1p.ssm #7 and
# "Character" the tail of nr_select.ssm #4; ACE cut at sample 7322 of the first
# and resumed 1236 samples later in the second (correlation 0.9993 with ACE's
# re-encoded clip). ACE's cut is a hard jump (-1541 -> -11352), so ours
# crossfades a few milliseconds across it.
BONUS_RECIPE = {
    'version': 1,
    'head': {'ssm': 'nr_1p.ssm', 'index': 7, 'frames': 16250},
    'tail': {'ssm': 'nr_select.ssm', 'index': 4, 'frames': 17368},
    'cut': 7322,          # last head sample + 1
    'lag': 1236,          # tail sample = output sample + lag
    'rate': 12000,
    'crossfade': 48,      # samples each side of the cut (4 ms)
}
BONUS_KEY = f"bonus-character:v{BONUS_RECIPE['version']}"


def _read_mono(path):
    with wave.open(str(path), 'rb') as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            return None, None
        frames = w.readframes(w.getnframes())
        return list(struct.unpack(f'<{len(frames) // 2}h', frames)), w.getframerate()


def splice_bonus(head, tail, recipe=BONUS_RECIPE):
    """The spliced sample list from the two decoded source clips."""
    cut, lag, fade = recipe['cut'], recipe['lag'], recipe['crossfade']
    out = list(head[:cut - fade])
    for i in range(2 * fade):
        w = (i + 0.5) / (2 * fade)
        k = cut - fade + i
        out.append(int(round(head[k] * (1 - w) + tail[k + lag] * w)))
    out.extend(tail[cut + fade + lag:])
    return [max(-32768, min(32767, s)) for s in out]


def build_bonus_clip(project_dir, mexcli, dest, run=None) -> Path | None:
    """Write the "Bonus Character" clip for this project to `dest`, from its own
    narrator banks. None when the banks aren't the vanilla clips the recipe
    was measured on (a build that replaced them)."""
    r = BONUS_RECIPE
    base = Path(project_dir) / 'files' / 'audio' / 'us'
    parts = []
    with tempfile.TemporaryDirectory(prefix='nucleus_bonus_') as tmp:
        for part in ('head', 'tail'):
            spec = r[part]
            wav_path = Path(tmp) / f'{part}.wav'
            if not (base / spec['ssm']).exists() or \
                    not _decode(mexcli, base / spec['ssm'], spec['index'], wav_path, run):
                return None
            samples, rate = _read_mono(wav_path)
            if samples is None or rate != r['rate'] or len(samples) != spec['frames']:
                return None
            parts.append(samples)
    out = splice_bonus(*parts)
    dest = Path(dest)
    with wave.open(str(dest), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(r['rate'])
        w.writeframes(struct.pack(f'<{len(out)}h', *out))
    return dest


def bonus_call(project_dir, mexcli, run=None) -> int | None:
    """The call of this project's "Bonus Character" line if it has been added."""
    rec = _load_ports(project_dir).get(BONUS_KEY)
    if isinstance(rec, dict) and isinstance(rec.get('call'), int):
        if call_clip_hash(project_dir, rec['call'], mexcli, run) == rec.get('ported_hash'):
            return rec['call']
    return None
