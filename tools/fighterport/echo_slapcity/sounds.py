"""A Slap City fighter's sounds, written as WAVs under Ultimate's sound words.

The fighter's `SmashSFXBank` lists its sounds by a short id (`jump`, `smallwhiff`, `fireball`); each id is a
`SmashSFX` holding one or more AudioClips (the game picks one at random) and a volume. The moveset plays them by
that id (`SAPSFX`). Unity keeps the clips as FMOD sound banks; UnityPy decodes them with the FMOD library it carries.

What the port's sound stage reads (fighter_port.voice) are Ultimate's words: `se_<fighter>_<what>` for a sound,
`vc_<fighter>_<what>` for a voice line. Each id is written as `se_<fighter>_<id>` (the game data names the moves'
sounds the same way), and ALSO gives the Ultimate word the donor table looks for, where one id plainly is that.

    <root>/gamedata/fighter/<fighter>/sound/<name>.wav     the first clip of each id, mono, at the clip's rate
    <root>/gamedata/fighter/<fighter>/sound/sounds.json    {name: {'file', 'id', 'also', 'clips', 'volume'}}

(fighter_port.source_game.sounds reads them back as the sound stage reads a bank.)
"""
from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import numpy as np

from .unity import audio

VOICE = {'holler'}                      # ids that are the fighter's voice (her one scream, as she flies off the top)
# the Ultimate words the donor tables look for, for ids that are that thing ({f}: the fighter)
ALSO = {'smallwhiff': ['se_{f}_swing_s'], 'mediumwhiff': ['se_{f}_swing_m'], 'strongwhiff': ['se_{f}_swing_l'],
        'swordswing': ['se_{f}_smash_s01'], 'strongwhoof': ['se_{f}_smash_h01'], 'mediumwhoosh': ['se_{f}_smash_l01'],
        'jump': ['se_{f}_jump01'], 'holler': ['vc_{f}_knockout'],
        'fireball': ['se_{f}_special_n01'], 'bomb': ['se_{f}_special_s01'], 'upbstart': ['se_{f}_special_h01'],
        'downb': ['se_{f}_special_l01']}


def name_of(fighter, sfx_id):
    """The Ultimate-shaped name an id is written under."""
    return f"{'vc' if sfx_id in VOICE else 'se'}_{fighter}_{sfx_id}".lower()


def mono(wav_bytes):
    """{'pcm': int16 mono, 'rate'} of a 16-bit PCM WAV (channels averaged)."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        n, ch, rate, width = w.getnframes(), w.getnchannels(), w.getframerate(), w.getsampwidth()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError(f'a {8 * width}-bit WAV')
    pcm = np.frombuffer(raw, '<i2').astype(np.float64).reshape(-1, ch).mean(axis=1)
    return {'pcm': np.round(pcm).astype(np.int16), 'rate': rate}


def write(f, out, log=print):
    """Every id of the fighter's bank (`f`: echo_slapcity.fighter.Fighter) as a WAV. -> the index written."""
    folder = Path(out) / 'sound'
    folder.mkdir(parents=True, exist_ok=True)
    index = {}
    for e in f.sound_bank()['entries']:
        obj = f.ref(e['sfx'])
        if obj is None:
            continue
        sfx = f.game.mono(obj)
        clips = [c for c in sfx.get('sfx') or [] if f.ref(c['clip']) is not None]
        if not clips:
            continue
        clip = f.ref(clips[0]['clip']).read()
        try:
            decoded = audio(clip)                       # WAV bytes, through FMOD
        except Exception as error:                      # noqa: BLE001 (FMOD's own errors: say which, go on)
            decoded, why = None, f'{type(error).__name__} {error}'
        else:
            why = 'nothing decoded'
        if not decoded:
            log(f'  {e["id"]}: {clip.m_Name} would not decode ({why})')
            continue
        sound = mono(decoded)
        name = name_of(f.name, e['id'])
        path = folder / f'{name}.wav'
        with wave.open(str(path), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sound['rate'])
            w.writeframes(sound['pcm'].astype('<i2').tobytes())
        index[name] = {'file': path.name, 'id': e['id'], 'clip': clip.m_Name, 'clips': len(clips),
                       'volume': float(clips[0].get('volume', 1.0)),
                       'also': [a.format(f=f.name).lower() for a in ALSO.get(e['id'], [])]}
    (folder / 'sounds.json').write_text(json.dumps(index, indent=1), 'utf-8')
    log(f'sounds: {len(index)} of the bank\'s ids written to {folder}')
    return index

