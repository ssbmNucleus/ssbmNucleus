"""What says whose fighter this is outside the fight, from Rivals 2's own files: the emblem, the victory fanfare
and the announcer calling the name.

All three are named by the character's own data (`Char_<Short>`, its class default object), none by a guess:

- the emblem: Rivals 2's fighters share one series, and the game's character screen shows each fighter's ELEMENT
  emblem (`RivalsElement` Fire -> `UI/Assets/menus_css_emblem_fire`, white on clear): that is the picture Melee's
  series emblem takes;
- the fanfare: the arcade data (`ArcadeModeData` -> `AMD_<Fighter>`) names its `VictoryJingle`, an FMOD event
  (`Music/Arcade Victory/ms_win_fire`: the fire element's, every fire fighter wins to it); the event table gives
  its sample, written from the first bank that holds it (the fighter's own bank holds it too: the whole Music bank
  is not unpacked for one sample);
- the announcer: `AnnouncerLine`, an FMOD event in the Announcer bank ("Announcer - 17 Zetterburn").

    <root>/gamedata/fighter/<fighter>/identity/series_icon.png   the element's emblem (white on clear)
    <root>/gamedata/fighter/<fighter>/identity/victory.wav       the fanfare (16-bit, its own rate, stereo)
    <root>/gamedata/fighter/<fighter>/identity/announcer.wav     the announcer saying the name (mono)
    <root>/gamedata/fighter/<fighter>/identity/identity.json     {'series', 'shown', 'picture', 'fanfare', 'announcer'}
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from . import sounds

SERIES, SHOWN = 'rivals2', 'Rivals of Aether II'


def object_path(ref):
    """An object reference as `uetool props` gives it ({'ObjectPath'} or {'AssetPathName'}) -> its path."""
    if isinstance(ref, dict):
        return ref.get('ObjectPath') or ref.get('AssetPathName') or ''
    return str(ref or '')


def first_sample(evs, ref, prefix=''):
    """(event row, sample) an event reference plays: the first of its Default-skin samples (starting so)."""
    ev = evs.get(sounds.event_key(object_path(ref)))
    if ev is None:
        return None, None
    names = [s for s in sounds.variants(ev['samples']) if s.startswith(prefix)]
    return ev, (names[0] if names else None)


def write(p, game_dir, fighter, game_name, short, root, ffmpeg='ffmpeg', log=print):
    """Write the identity folder. -> identity.json's dict (what was found; None where nothing was)."""
    root = Path(root)
    folder = root / 'gamedata' / 'fighter' / fighter / 'identity'
    folder.mkdir(parents=True, exist_ok=True)
    cache = root / 'rivals2-cache'
    desktop = Path(game_dir) / 'Rivals2' / 'Content' / 'FMOD' / 'Desktop'
    char = p.default(p.find(f'Char_{short}', f'Characters/{game_name}/'))
    made = {'series': SERIES, 'shown': SHOWN, 'picture': None, 'fanfare': None, 'announcer': None}

    # the emblem: his element's, as the character screen shows it
    element = str(char.get('RivalsElement') or '').split('::')[-1].lower()
    if element:
        pkg = f'Rivals2/Content/UI/Assets/menus_css_emblem_{element}'
        got = p.export([pkg], cache / 'export', psk=False).get(pkg) or []
        png = next((f for f in got if f.lower().endswith('.png')), None)
        if png:
            shutil.copyfile(png, folder / 'series_icon.png')
            made['picture'] = f'{pkg.rsplit("/", 1)[1]} (his element, {element.title()}: the emblem the game\'s ' \
                              f'character screen shows; every Rivals fighter is one series)'

    banks = [f'Character/{game_name}/{game_name}', 'Music', 'Announcer']
    evs = sounds.events(desktop, banks, cache / 'fmod' / 'identity', p.run)
    extracted = {}

    def sample_file(sample, ev):
        # the first bank holding the sample, the fighter's own before the event's (Music: 69 MB for one sample)
        for bank in [banks[0], ev['bank']]:
            if bank not in extracted:
                extracted[bank] = sounds.extract(desktop / (bank + '.assets.bank'),
                                                 cache / 'fmod' / re.sub(r'[\\/ ]', '_', bank))
            if sample in extracted[bank]:
                return extracted[bank][sample], bank
        return None, None

    def to_wav(src, out, mono):
        r = subprocess.run([str(ffmpeg), '-y', '-loglevel', 'error', '-i', str(src)] + (['-ac', '1'] if mono else [])
                           + ['-c:a', 'pcm_s16le', str(out)], capture_output=True, text=True)
        if r.returncode or not Path(out).is_file():
            raise SystemExit(f'{src} would not convert: {(r.stdout + r.stderr)[-300:]}')
        import wave
        with wave.open(str(out)) as w:
            return round(w.getnframes() / w.getframerate(), 2)

    # the fanfare: the arcade data's VictoryJingle
    amd_ref = object_path(char.get('ArcadeModeData'))
    if amd_ref:
        amd_name = amd_ref.rsplit('/', 1)[1].split('.')[0]
        amd = p.default(p.find(amd_name, f'Characters/{game_name}/'))
        ev, sample = first_sample(evs, amd.get('VictoryJingle'))
        src, bank = sample_file(sample, ev) if sample else (None, None)
        if src:
            seconds = to_wav(src, folder / 'victory.wav', mono=False)
            made['fanfare'] = {'clip': sample, 'seconds': seconds, 'event': ev['event'], 'bank': bank,
                               'shared': f'his element\'s ({element}): {amd_name}.VictoryJingle'}
    # the announcer: AnnouncerLine
    ev, sample = first_sample(evs, char.get('AnnouncerLine'))
    src, bank = sample_file(sample, ev) if sample else (None, None)
    if src:
        seconds = to_wav(src, folder / 'announcer.wav', mono=True)
        made['announcer'] = {'clip': sample, 'seconds': seconds, 'event': ev['event'], 'bank': bank}
    (folder / 'identity.json').write_text(json.dumps(made, indent=1), 'utf-8')
    log(f"identity: emblem {made['picture'] or 'none'}; fanfare {(made['fanfare'] or {}).get('clip')}; "
        f"announcer {(made['announcer'] or {}).get('clip')}")
    return made
