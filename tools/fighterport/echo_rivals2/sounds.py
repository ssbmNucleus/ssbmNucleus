"""A Rivals 2 fighter's sounds, written as WAVs under Ultimate's sound words (source_game.py's sound folder).

The game keeps its sounds in FMOD banks, loose beside the paks (`Rivals2/Content/FMOD/Desktop`): the fighter's own
(`Character/<F>/<F>`, its voice `Character/<F>/<F>VO`) and the shared ones (`Universal/Basic_Swipes`, `Hits`,
`General_Movement`). Each bank is a metadata `<name>.bank` (its events: what each plays) and the sounds
`<name>.assets.bank` (an FSB5 table of Vorbis samples).

Which sound is which is READ, three steps, none of them a guess by name:
1. a move names a sound by its SoundName (`SFXCreationData.SoundName`: "Fire Swipe Medium"); the fighter's sound
   table `SFX_<Fighter>` (then the shared `Characters/SFX_Universal`) gives that name's FMOD EVENT
   (`/Game/FMOD/Events/SFX/Universal/Basic_Swipes/Fire/snd_swipe_fire_medium`; the asset path writes `_` where the
   event path has a space);
2. the banks' event table (`uetool fmod-events`, CUE4Parse's own FMOD reader: each event's timeline, instruments
   and playlists resolved to the samples they reach, named from `Master.strings.bank`) gives the event's samples;
3. `fmodtool` (Fmod5Sharp, from the NuGet cache) writes each sample by its own name (.ogg), ffmpeg a mono WAV.

An event plays one of several samples (the game picks at random): the first is written for it (a stand-in for
the choice). A sample only a skin plays (`_mech`, `_dandelion`, `_plush`, `lowpoly`: the costumes carried are the
Default skin's) is never the one. Every sound of the fighter's table is written, the ones no move names too: his
code plays some (the burn's: `Burn Applied`, `Burn End`, `Consume`, `Flame Puddle Create`), and the bank
chooser takes only what the moves and the fighter's code play. ALSO gives the Ultimate words the donor's table
looks for, by the event (and which of its samples) that plainly is that occasion.

    <root>/gamedata/fighter/<fighter>/sound/<sample>.wav     each sample used, mono
    <root>/gamedata/fighter/<fighter>/sound/sounds.json      {name: {'file', 'also', 'sample', 'bank', 'event'}}
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
TOOL = HERE / 'fmodtool'
# the banks whose events and samples are read: the fighter's own two and the shared ones its table names
BANKS = ('Character/{F}/{F}', 'Character/{F}/{F}VO', 'Universal/Basic_Swipes', 'Universal/Hits',
         'Universal/General_Movement')
TABLES = ('Characters/{F}/SFX_{F}', 'Characters/SFX_Universal')
SKIN_WORDS = ('_mech', '_dandelion', '_plush', 'lowpoly', '_louie')
# The Ultimate words the donor's table looks for, by the occasion's event: (SoundName or event path, which of its
# samples (index, or the first whose name starts so), [words]). A word the table takes in number order (voice.DONOR's
# `+vc_{f}_attack`) must carry its number: vc_{f}_attack01, never vc_{f}_attack.
ALSO = (
    ('Effort Medium', 0, ['vc_{f}_attack01']), ('Effort Medium', 1, ['vc_{f}_attack02']),
    ('Effort Medium', 2, ['vc_{f}_attack03']),
    ('event:/Animation/Victory/{F}/an_victory_{f}', 'vo_', ['vc_{f}_win01']),
    ('Default Taunt VO', 0, ['vc_{f}_appeal01']), ('Ledge Grab VO', 0, ['vc_{f}_cliffcatch']),
    ('Final KO VO', 0, ['vc_{f}_knockout']),
    ('Hit Heavy', 0, ['vc_{f}_damagefly01']), ('Hit Heavy', 1, ['vc_{f}_damagefly02']),
    ('Hit Medium', 0, ['vc_{f}_damage01']), ('Jump VO', 0, ['vc_{f}_jump01']),
    ('Dspecial Start VO', 0, ['vc_{f}_special_l01']), ('Burn VO', 0, ['vc_{f}_special_h01']),
    ('Charged Nspecial VO', 0, ['vc_{f}_special_n01']),
    ('Swipe Weak', 0, ['se_{f}_swing_s']), ('Swipe Medium', 0, ['se_{f}_swing_m']),
    ('Swipe Heavy', 0, ['se_{f}_swing_l']),
    ('FStrong', 0, ['se_{f}_smash_s01']), ('UStrong', 0, ['se_{f}_smash_h01']), ('DStrong', 0, ['se_{f}_smash_l01']),
    ('Uspecial Start', 0, ['se_{f}_special_h01']), ('Dspecial Start', 0, ['se_{f}_special_l01']),
    ('Fire Swipe Medium', 0, ['se_{f}_special_s01']),
)


def tool():
    """The built fmodtool, built once from its project (offline: the NuGet cache holds Fmod5Sharp)."""
    exe = TOOL / 'bin' / 'out' / 'fmodtool.exe'
    if not exe.is_file():
        subprocess.run(['dotnet', 'build', '-c', 'Release', '-o', str(exe.parent), '--nologo', '-v', 'q'], cwd=TOOL,
                       check=True, capture_output=True, text=True)
    return exe


def extract(bank, out):
    """{sample name: file} of every sample of one .assets.bank, written under `out` (kept: done once)."""
    listing = Path(out) / 'samples.tsv'
    if not listing.is_file():
        Path(out).mkdir(parents=True, exist_ok=True)
        r = subprocess.run([str(tool()), str(bank), str(out)], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f'fmodtool could not read {bank}: {(r.stdout + r.stderr)[-300:]}')
        listing.write_text(r.stdout, 'utf-8')
    got = {}
    for line in listing.read_text('utf-8').splitlines():
        name, file, *_ = line.split('\t')
        if file != '-':
            got[name] = Path(out) / file
    return got


def event_key(path):
    """An event path as both spellings meet: `event:/SFX/Universal/Basic Swipes/...` and the asset
    `/Game/FMOD/Events/SFX/Universal/Basic_Swipes/....x` -> `sfx/universal/basic_swipes/...`."""
    p = str(path)
    if p.startswith('event:/'):
        p = p[len('event:/'):]
    elif '/FMOD/Events/' in p:
        p = p.split('/FMOD/Events/', 1)[1].split('.', 1)[0]
    return p.replace(' ', '_').lower()


def table(objs):
    """{SoundName: {'event', 'voice', 'skins'}} of one RivalsSoundEffectContainer's objects (`uetool props`)."""
    out = {}
    for o in objs:
        for kv in (o.get('Properties') or {}).get('SoundEffectData') or []:
            v = kv.get('Value') or {}
            path = ((v.get('SoundEffect') or {}).get('AssetPathName')) or ''
            if path:
                out[kv['Key']] = {'event': path, 'voice': bool(v.get('bIsVoiceLine')),
                                  'skins': {s['Key']: s['Value'] for s in v.get('SkinOverrideNames') or []}}
    return out


def events(desktop, banks, cache, run):
    """{event key: {'event', 'bank', 'samples'}} of the named banks (`uetool fmod-events`, kept in `cache`)."""
    keep = Path(cache) / 'events.json'
    kept = json.loads(keep.read_text('utf-8')) if keep.is_file() else {}
    if kept.get('banks') != list(banks):
        kept = {'banks': list(banks), 'events': json.loads(run('fmod-events', str(desktop), ','.join(banks)))}
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_text(json.dumps(kept, indent=1), 'utf-8')
    return {event_key(k): dict(v, event=k) for k, v in kept['events'].items()}


def variants(samples):
    """An event's samples the Default skin plays, in order (a skin's own variants left out unless none else)."""
    plain = [s for s in samples if not any(w in s.lower() for w in SKIN_WORDS)]
    return plain or list(samples)


def word_of(name, fighter):
    """The event word of a sound's Ultimate-shaped name (se_zetterburn_fair -> fair)."""
    for head in (f'se_{fighter}_', f'vc_{fighter}_'):
        if name.startswith(head):
            return name[len(head):]
    return name


def word(sound_name):
    """The word a move's SoundName becomes in its Ultimate-shaped name (gamedata.sounds): "Fire Swipe Medium" ->
    fire_swipe_medium."""
    return sound_name.lower().replace(' ', '_')


def resolve(tables, evs, sound_name):
    """(event row, [samples]) of a SoundName, the fighter's table first, or (None, why)."""
    for t in tables:
        row = t.get(sound_name)
        if row is not None:
            ev = evs.get(event_key(row['event']))
            if ev is None:
                return None, f"its event {row['event']} is in none of the banks read ({', '.join(BANKS)})"
            if not ev['samples']:
                return None, f"its event {ev['event']} reaches no sample"
            return dict(ev, voice=row['voice']), variants(ev['samples'])
    return None, 'in neither sound table'


def write(game_dir, fighter, game_name, root, named, ffmpeg='ffmpeg', log=print, pak=None):
    """The sounds the moves name (`named`: their Ultimate-shaped names), every sound of the fighter's own table and
    the donor's occasions (ALSO), as WAVs and sounds.json. -> {'written', 'silent': {name: why}}"""
    from . import pak as pak_mod
    p = pak or pak_mod.Pak(game_dir, Path(root) / 'rivals2-cache')
    desktop = Path(game_dir) / 'Rivals2' / 'Content' / 'FMOD' / 'Desktop'
    cache = Path(root) / 'rivals2-cache' / 'fmod'
    banks = [b.format(F=game_name) for b in BANKS]
    evs = events(desktop, banks, cache, p.run)
    tables = []
    missing_tables = []
    for t in TABLES:
        name = t.format(F=game_name).rsplit('/', 1)[1]
        under = 'Rivals2/Content/' + t.format(F=game_name).rsplit('/', 1)[0] + '/'
        try:
            tables.append(table(p.props(p.find(name, under))))
        except KeyError:
            tables.append({})
            missing_tables.append(t.format(F=game_name))
    folder = Path(root) / 'gamedata' / 'fighter' / fighter / 'sound'
    folder.mkdir(parents=True, exist_ok=True)
    by_word = {}
    for t in reversed(tables):
        by_word.update({word(k): k for k in t})
    wanted, silent, references = {}, {}, {}

    def want(ev, sample, name):
        wanted.setdefault((ev['bank'], sample), {'names': [], 'event': ev['event']})['names'].append(name)

    for name in sorted(named):
        sound_name = by_word.get(word_of(name, fighter))
        ev, samples = resolve(tables, evs, sound_name) if sound_name else (None, 'no SoundName of the tables')
        if ev is None:
            silent[name] = samples
            # A reference absent from BOTH successfully read source tables cannot
            # play a sample. Missing banks/failed extraction are different: those
            # remain missing exports, never certified source silence.
            if sound_name is None and not missing_tables:
                references[name] = dict(bank='rivals2_sound_tables', exists=False,
                                        reason='no playable entry in the fighter or universal sound table')
            continue
        want(ev, samples[0], name)
    # every sound of his own table, under the name a move would give it (his code plays some of them); not the
    # ones a skin plays in another's place (`Land Mech` for `Land` on the Mecha skin)
    skins_only = {v for row in tables[0].values() for v in row['skins'].values()}
    for sound_name, row in sorted(tables[0].items()):
        name = f"{'vc' if row['voice'] else 'se'}_{fighter}_{word(sound_name)}"
        if name in named or sound_name in skins_only:
            continue
        ev, samples = resolve(tables, evs, sound_name)
        if ev is not None:
            want(ev, samples[0], name)
    for key, pick, words in ALSO:
        key = key.format(F=game_name, f=game_name.lower())
        if key.startswith('event:/'):
            ev = evs.get(event_key(key))
            samples = variants(ev['samples']) if ev else []
        else:
            ev, samples = resolve(tables, evs, key)
            samples = samples if ev else []
        if isinstance(pick, int):
            sample = samples[pick] if pick < len(samples) else None
        else:
            sample = next((s for s in samples if s.startswith(pick)), None)
        if sample is not None:
            for w in words:
                want(ev, sample, w.format(f=fighter))
    samples_of = {}
    index = {}
    for (bank, sample), row in sorted(wanted.items()):
        if bank not in samples_of:
            samples_of[bank] = extract(desktop / (bank + '.assets.bank'), cache / re.sub(r'[\\/ ]', '_', bank))
        if sample not in samples_of[bank]:
            for n in row['names']:
                silent[n] = f'{sample} is not in {bank}.assets.bank'
            continue
        names = row['names']
        file = folder / (sample.replace(' ', '_') + '.wav')
        if not file.is_file():
            r = subprocess.run([str(ffmpeg), '-y', '-loglevel', 'error', '-i', str(samples_of[bank][sample]), '-ac',
                                '1', '-c:a', 'pcm_s16le', str(file)], capture_output=True, text=True)
            if r.returncode or not file.is_file():
                raise SystemExit(f'{sample} would not convert: {(r.stdout + r.stderr)[-300:]}')
        index[names[0]] = {'file': file.name, 'also': sorted(set(names[1:])), 'sample': sample, 'bank': bank,
                           'event': row['event']}
    (folder / 'sounds.json').write_text(json.dumps(index, indent=1), 'utf-8')
    log(f'  sounds: {len(index)} samples for {sum(1 + len(v["also"]) for v in index.values())} names, read from '
        f'the sound tables and the banks\' event table; silent: {silent or "none"}')
    receipt = {'written': len(index), 'silent': silent, 'references': references,
               'missing_tables': missing_tables}
    (folder / 'extraction.json').write_text(json.dumps(receipt, indent=1), 'utf-8')
    return receipt


def annotate(data, receipt):
    """Carry verified absent source entries into game.json, not only the export log.

    Clear old annotations first: a subsequent source version may supply the sound.
    Export failures deliberately receive no exists=False annotation.
    """
    references = receipt.get('references') or {}
    for move in data.get('moves', {}).values():
        for event in move.get('sounds') or []:
            if (event.get('source_sound') or {}).get('bank') == 'rivals2_sound_tables':
                event.pop('source_sound')
            if event.get('name') in references:
                event['source_sound'] = dict(references[event['name']])
