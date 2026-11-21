"""What says whose fighter this is outside the fight: its series emblem and its victory fanfare, from the game.

Usage (cwd app/backend): python own_identity.py <work> <fighter> <game root> [<series name in the game's files, or ->
    [<the series' name as shown>]]   (the series is read from the game's roster table when not given)
Writes <work>/package/series_icon.png, series_emblem.obj (the picture's shape as the flat model Melee draws behind a
fighter's damage: with the picture alone the game shows only a piece of it) and series.json ({"name": ...}),
victory_theme.hps and victory.json
({"name": ...}); `package_build.py` adds the series and the music to the project and points the fighter at them.
Without these a port keeps the donor's: the donor's emblem behind its damage and on the results screen, the
donor's fanfare when it wins.

The emblem is the game's own series picture (ui/replace/series/series_0/series_0_<series>.bntx). The fanfare is
a stream sound/bgm/bgm_z<nn>_f_<name>.nus3audio, and <name> is NOT the series: a series' fanfare is named for the
series' first fighter (Star Fox's is bgm_z07_f_fox; nothing answers to `starfox`, nor to `wolf`). The archive's
path list holds no stream paths at all, so no name can be looked up, only tried: the fighter's own name first (a
fanfare of its own comes before its series'), then the series' name, then each fighter the roster table puts in
the same series, in the table's order, each with every number 00 to 99 (`fanfare_names`, `fanfare_streams`). Which
stream was taken, and whose name it was under, is printed and written in victory.json.

A game written out by its own reader (fighter_port/source_game.py: no archive) gives both as files under
<root>/gamedata/fighter/<fighter>/identity/ (`from_written`).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from echo_ultimate.gamedata import arc  # noqa: E402

ROSTER = 'ui/param/database/ui_chara_db.prc'       # the game's roster table: each fighter's series, in its own order


def _roster(root, known):
    """The roster table's rows, read with the names in `known` (the table holds hashes), or None when the game's
    files cannot give it."""
    from echo_ultimate.gamedata.prc import Prc
    root = Path(root)
    path = arc.extract(root, root / 'gamedata', [ROSTER]).get(ROSTER)
    if not path or not (root / 'Hashes_FullPath').exists():
        return None
    return Prc(Path(path).read_bytes(), known).root.get('db_root', [])


def _listing(root):
    return (Path(root) / 'Hashes_FullPath').read_text('utf-8', errors='replace')


def series_of(root, fighter):
    """The series the game's roster table puts the fighter in (ui_chara_db.prc: ui_series_<name>), else its own name."""
    listing = Path(root) / 'Hashes_FullPath'
    if not listing.exists():
        return fighter
    every = set(re.findall(r'ui/replace/series/series_0/series_0_([a-z0-9_]+)\.bntx', _listing(root)))
    known = {'db_root', 'ui_chara_id', 'ui_series_id', f'ui_chara_{fighter}'} | {f'ui_series_{n}' for n in every}
    for row in _roster(root, known) or []:
        if str(row.get('ui_chara_id')) == f'ui_chara_{fighter}' and str(row.get('ui_series_id')).startswith('ui_series_'):
            return str(row['ui_series_id'])[len('ui_series_'):]
    return fighter


def series_mates(root, series):
    """The fighters the game's roster table puts in a series, in the table's order. A series' fanfare is named for
    its first fighter, not for the series (Star Fox's is `..._f_fox`: Wolf found none under `wolf` or `starfox`)."""
    listing = Path(root) / 'Hashes_FullPath'
    if not listing.exists():
        return []
    fighters = sorted(set(re.findall(r'^fighter/([a-z0-9_]+)/', _listing(root), re.M)))
    known = {'db_root', 'ui_chara_id', 'ui_series_id', f'ui_series_{series}'} | {f'ui_chara_{n}' for n in fighters}
    return [str(row['ui_chara_id'])[len('ui_chara_'):] for row in _roster(root, known) or []
            if str(row.get('ui_series_id')) == f'ui_series_{series}' and str(row.get('ui_chara_id')).startswith('ui_chara_')]


def fanfare_names(fighter, series, mates):
    """The names a fanfare is looked for under, in the order they are tried: the fighter's own, the series', then
    the series' fighters in the roster table's order, each once."""
    return list(dict.fromkeys([fighter, series] + list(mates)))


def fanfare_streams(names):
    """Every stream path a fanfare might have under these names, in the order they are tried (00 to 99 a name)."""
    return [f'stream:/sound/bgm/bgm_z{n:02d}_f_{who}.nus3audio' for who in names for n in range(100)]


def named_for(stream):
    """The name a fanfare's stream path is under (bgm_z07_f_fox -> fox)."""
    return stream.rsplit('_f_', 1)[1][:-len('.nus3audio')]


def found(root, paths):
    """{archive path: local file} for those of `paths` the archive holds (taken out under <root>/gamedata)."""
    return {k: v for k, v in arc.extract(root, Path(root) / 'gamedata', paths).items() if v}


def from_written(work, fighter, folder, ffmpeg, mexcli):
    """A game written out by its own reader (fighter_port/source_game.py) gives its series picture and fanfare as
    files: <root>/gamedata/fighter/<fighter>/identity/ series_icon.png, victory.wav and identity.json."""
    import subprocess
    from PIL import Image
    from fighter_port import series_emblem
    pkg = Path(work) / 'package'
    pkg.mkdir(parents=True, exist_ok=True)
    told = json.loads((folder / 'identity.json').read_text('utf-8')) if (folder / 'identity.json').is_file() else {}
    if (folder / 'series_icon.png').is_file():
        image = Image.open(folder / 'series_icon.png').convert('RGBA')
        image.save(pkg / 'series_icon.png')
        made = series_emblem.write(image, pkg / 'series_emblem.obj')
        series = told.get('series') or fighter
        (pkg / 'series.json').write_text(json.dumps({'name': told.get('shown') or series.replace('_', ' ').title(),
                                                     'game': series}), 'utf-8')
        print('series emblem:', told.get('picture') or 'series_icon.png', image.size, made)
    else:
        print("no series picture written by the game's reader: the donor's stays")
    if (folder / 'victory.wav').is_file():
        wav = pkg / 'sound-work' / 'victory.wav'
        wav.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([str(ffmpeg), '-y', '-loglevel', 'error', '-i', str(folder / 'victory.wav'), '-ar', '32000',
                            '-ac', '2', '-c:a', 'pcm_s16le', str(wav)], capture_output=True, text=True)
        if r.returncode or not wav.exists():
            raise SystemExit(f'the fanfare would not convert: {(r.stdout + r.stderr)[-300:]}')
        hps = pkg / 'victory_theme.hps'
        r = subprocess.run([str(mexcli), 'audio-to-hps', str(wav), str(hps)], capture_output=True, text=True)
        if r.returncode or not hps.exists():
            raise SystemExit(f'the fanfare would not convert: {(r.stdout + r.stderr)[-300:]}')
        fan = told.get('fanfare') or {}
        (pkg / 'victory.json').write_text(json.dumps({'name': f"{told.get('series') or fighter} victory",
                                                      'stream': fan.get('clip'), 'named_for': fighter,
                                                      'path': str(folder / 'victory.wav'), 'note': fan}), 'utf-8')
        print(f"victory fanfare: {fan.get('clip') or 'victory.wav'} ({fan.get('seconds')} s; {fan.get('shared') or ''}), "
              f'{hps.stat().st_size} bytes')
    else:
        print("no fanfare written by the game's reader: the donor's stays")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from fighter_port import compat
    compat.install()
    from core.config import MEXCLI_PATH
    from core.media_tools import get_ffmpeg
    from echo_ultimate import effects, lopus, nus3audio
    from fighter_port import series_emblem

    work, fighter, root = Path(argv[0]), argv[1], Path(argv[2])
    written = root / 'gamedata' / 'fighter' / fighter / 'identity'
    if not (root / 'Hashes_FullPath').exists() and written.is_dir():
        return from_written(work, fighter, written, get_ffmpeg() or 'ffmpeg', MEXCLI_PATH)
    if not (root / 'Hashes_FullPath').exists() and (root / 'gamedata' / 'fighter' / fighter / 'game.json').is_file():
        # a written game whose reader gave no identity folder (Slap City's writes none; Rivals 2's echo_rivals2/
        # identity.py writes one): the donor's emblem and fanfare stay; there is no archive to look in
        print("the game's reader wrote no identity folder: the donor's series emblem and victory fanfare stay")
        return 0
    series = argv[3] if len(argv) > 3 and argv[3] != '-' else series_of(root, fighter)
    shown = argv[4] if len(argv) > 4 else series.replace('_', ' ').title()
    pkg = work / 'package'
    pkg.mkdir(parents=True, exist_ok=True)
    icon = f'ui/replace/series/series_0/series_0_{series}.bntx'
    whose = fanfare_names(fighter, series, series_mates(root, series))
    streams = fanfare_streams(whose)
    got = found(root, [icon] + streams)
    if icon in got:
        data = Path(got[icon]).read_bytes()
        name, image = effects.textures(data[data.index(b'BNTX'):])[0]
        # Melee draws an emblem from a picture's shape: white where the emblem is, clear elsewhere
        image.save(pkg / 'series_icon.png')
        made = series_emblem.write(image, pkg / 'series_emblem.obj')
        (pkg / 'series.json').write_text(json.dumps({'name': shown, 'game': series}), 'utf-8')
        print('series emblem:', name, image.size, made)
    else:
        print(f'no series emblem named {series} in the game: the donor\'s stays')
    taken = next((s for s in streams if s in got), None)
    stream = got[taken] if taken else None
    if stream:
        under = named_for(taken)
        name, sound = next(iter(nus3audio.sounds(stream).items()))
        wav = lopus.to_wav(sound, pkg / 'sound-work' / 'victory.wav', 32000, get_ffmpeg() or 'ffmpeg')
        hps = pkg / 'victory_theme.hps'
        r = subprocess.run([str(MEXCLI_PATH), 'audio-to-hps', str(wav), str(hps)], capture_output=True, text=True)
        if r.returncode or not hps.exists():
            raise SystemExit(f'the fanfare would not convert: {(r.stdout + r.stderr)[-300:]}')
        (pkg / 'victory.json').write_text(json.dumps({'name': f'{series} victory', 'stream': name, 'named_for': under,
                                                      'path': taken}), 'utf-8')
        print(f"victory fanfare: {taken.rsplit('/', 1)[1]}, named for {under}"
              + ('' if under == fighter else f" (not for {fighter}: none under its own name; tried, in order, {whose})")
              + f'; {name}, {hps.stat().st_size} bytes;', (r.stdout or '').strip()[-200:])
    else:
        print(f"no victory fanfare in the game under any of {whose} (bgm_z00 to z99_f_<name>): the donor's stays. If the "
              "game's own is under another name, that name is the one to find: the archive lists no stream paths")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
