"""Games other than Ultimate whose fighter is carried on its own skeleton by being written out in Ultimate's shapes
first, by a reader of the game's own (`echo_<game>`, run once before the command: `python -m echo_<game> ...`):

    <root>/gamedata/fighter/<fighter>/model/body/c0N/   model.nusktb .numshb .numdlb .numatb, pictures .nutexb
    <root>/gamedata/fighter/<fighter>/motion/body/c00/  <stem>.nuanmb under the clip table's stems
    <root>/gamedata/fighter/<fighter>/game.json          the driver's `game` (moves, Melee's numbers, the
                                                         hurtboxes and collision joints as `source_tables`)
    <root>/gamedata/fighter/<fighter>/sound/             <name>.wav (16-bit PCM) and sounds.json ({name: {'file',
                                                         'also': [other words for it]}}), names in Ultimate's words
                                                         (se_<fighter>_..., vc_<fighter>_...)
    <root>/gamedata/fighter/<fighter>/identity/          series_icon.png, victory.wav, identity.json (the
                                                         sounds stage's emblem and fanfare: harness/own_identity.py),
                                                         announcer.wav (the announcer calling the name: voice.announcer)

The route reads the skeleton, body and clips from those files as it reads Ultimate's, and takes the rest from
game.json in place of the archive, the scripts and vl.prc: it never opens the game itself. (Slap City, a Unity
game, 2026-11-13, was the first; Rivals of Aether 2, an Unreal game, the second.)

Reader conventions (checklist 10.12):
  - ordinary moves' `time_keys` stop on the frame BEFORE their cancel frame (the driver plays the clip on
    past it and frees the move there); keys to the clip's end free every ordinary move at its clip's end;
  - conditional-only branch states, like specials, retain their recovery keys: their runtime adapter
    handles input interrupts separately from natural completion;
  - an `also` name is Ultimate's whole name with its number (vc_<fighter>_attack01, vc_<fighter>_win01): the
    donor's table (voice.DONOR) takes some in number order and finds no plain word.
The identity folder may be left out, or any file of it: the donor's emblem and fanfare then stay, and with no
announcer.wav the port is called by the app's "Bonus Character" line; the sounds stage says each.
"""
from __future__ import annotations

import json
from pathlib import Path

GAMES = ('slapcity', 'rivals2')   # every such game: the commands' --game choices are these and Ultimate's, Brawl's


def written(game):
    """True for a game whose fighters come written out in Ultimate's shapes (see the head)."""
    return game in GAMES


def folder(root, fighter):
    return Path(root) / 'gamedata' / 'fighter' / fighter


def game_data(root, fighter):
    """The driver's `game`, as the game's reader wrote it."""
    path = folder(root, fighter) / 'game.json'
    if not path.is_file():
        raise SystemExit(f'{path} is not there: the game\'s reader writes it (python -m echo_<game> <the game\'s '
                         f'folder> {fighter} {root})')
    return json.loads(path.read_text('utf-8'))


def tables(root, fighter):
    """dict(hurt, ecb): the fighter's hurtboxes and collision joints (own_data.source_tables' shape)."""
    return game_data(root, fighter)['source_tables']


def wav(path):
    """A 16-bit WAV as voice reads a sound: {'pcm': int16 mono, 'rate'}."""
    import wave

    import numpy as np
    with wave.open(str(path)) as w:
        ch, rate = w.getnchannels(), w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, ch).mean(axis=1)
    return {'pcm': np.round(pcm).astype(np.int16), 'rate': rate}


def announcer(root, fighter):
    """The announcer calling the fighter's name as the reader wrote it (identity/announcer.wav), or None."""
    path = folder(root, fighter) / 'identity' / 'announcer.wav'
    return wav(path) if path.is_file() else None


def sounds(root, fighter):
    """The fighter's sounds as fighter_port.voice reads a bank: {'se', 'vc', 'cheer'}: {lower-case name: (name,
    {'pcm': int16 mono, 'rate'})}. Each is found under its `also` words too, as the same (name, sound), so that a
    donor table row that looks for one of those words places the sound under its own name. A game with no sound
    folder has empty banks (every donor voice sample is then made silent, every other left as the donor's)."""
    folder = folder_of_sounds = Path(root) / 'gamedata' / 'fighter' / fighter / 'sound'
    index_file = folder_of_sounds / 'sounds.json'
    index = json.loads(index_file.read_text('utf-8')) if index_file.is_file() else {}
    out = {'se': {}, 'vc': {}, 'cheer': {}}
    for name, row in index.items():
        sound = (name, wav(folder / row['file']))
        for key in [name] + list(row.get('also') or []):
            out['vc' if key.lower().startswith('vc_') else 'se'][key.lower()] = sound
    return out
