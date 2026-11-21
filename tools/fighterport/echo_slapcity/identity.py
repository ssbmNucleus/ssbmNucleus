"""What says whose fighter this is outside the fight, from Slap City: its series picture and the victory fanfare.

The series pictures are one MonoBehaviour (`SeriesIcons`, Resources `smash/seriesicons`): rows of a series id and a
Texture2D. The game names a fighter's series nowhere this reader found (SmashCharacter has no such field), so the
row whose id is the fighter's own name is taken (`ittledew` has one); none such: no picture, the donor's stays.
The fanfare is one for every fighter (`smash/music/fanfare`, a SmashMusic: the clip, and the loop it plays past
its first `loopTime` seconds): the clip up to its loop is written.

    <root>/gamedata/fighter/<fighter>/identity/series_icon.png   the series' shape (white on clear: `logo`)
    <root>/gamedata/fighter/<fighter>/identity/series_picture.png  the game's own series picture
    <root>/gamedata/fighter/<fighter>/identity/victory.wav       the fanfare (16-bit, the clip's own rate)
    <root>/gamedata/fighter/<fighter>/identity/identity.json     {'series', 'shown', 'fanfare': {...}}
"""
from __future__ import annotations

import io
import json
import wave
from pathlib import Path

from .unity import audio


def _mono_behaviour(game, key, script):
    go = game.container()[key].read()
    return next(game.mono(c.deref()) for c in go.m_Components
                if c.deref().type.name == 'MonoBehaviour' and game.script(c.deref()) == script), go


def logo(image):
    """The game's series picture is a whole card (Ittle Dew's: the name's letters on a blue sky with clouds), and
    Melee's emblem is a shape. The shape is the letters: what is neither sky (blue over red and green) nor cloud
    (every channel bright), white on clear. A stand-in for a shape the game never draws."""
    import numpy as np
    from PIL import Image
    im = np.asarray(image.convert('RGBA')).astype(int)
    r, g, b, a = (im[..., i] for i in range(4))
    keep = (a > 128) & ~((b >= g) & (b > r + 15)) & ~(np.minimum(np.minimum(r, g), b) > 170)
    out = np.zeros(im.shape, np.uint8)
    out[..., :3] = 255
    out[..., 3] = keep * 255
    return Image.fromarray(out)


def write(game, fighter, out, shown=None, log=print):
    folder = Path(out) / 'identity'
    folder.mkdir(parents=True, exist_ok=True)
    made = {'series': None, 'shown': shown, 'fanfare': None}
    # the fanfare before the picture: once a picture is decoded, FMOD refuses a clip it has not opened one like
    # before (INVALID PARAM; see unity.fmod)
    music, go = _mono_behaviour(game, 'smash/music/fanfare', 'SmashMusic')
    clip = game.deref(go.assets_file, music['clip']).read()
    wav = audio(clip)
    with wave.open(io.BytesIO(wav)) as w:
        ch, rate, width = w.getnchannels(), w.getframerate(), w.getsampwidth()
        keep = min(w.getnframes(), int(float(music.get('loopTime') or clip.m_Length) * rate))
        frames = w.readframes(keep)
    with wave.open(str(folder / 'victory.wav'), 'wb') as w:
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames)
    icons, go = _mono_behaviour(game, 'smash/seriesicons', 'SeriesIcons')
    row = next((r for r in icons['icons'] if r['seriesID'] == fighter), None)
    if row is not None:
        tex = game.deref(go.assets_file, row['seriesIcon']).read()
        tex.image.save(folder / 'series_picture.png')
        logo(tex.image).save(folder / 'series_icon.png')
        made.update(series=fighter, picture=tex.m_Name, shape='the logo cut from the card (sky and clouds left out)')
    made['fanfare'] = {'clip': clip.m_Name, 'seconds': round(keep / rate, 2), 'shared': 'every fighter wins to it',
                       'cut_at': 'its loop (loopTime)'}
    (folder / 'identity.json').write_text(json.dumps(made, indent=1), 'utf-8')
    log(f"identity: series picture {made.get('picture') or 'none'}, fanfare {clip.m_Name} ({made['fanfare']['seconds']} s)")
    return made
