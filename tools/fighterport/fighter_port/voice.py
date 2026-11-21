"""A port's own voice and sounds, in the donor's sound bank.

A Melee fighter's sounds are a bank of samples, small scripts that play them, and calls to those
scripts from the fighter's data (its move scripts, and a table the engine reads for a jump, a hit taken,
a fall). A port keeps the donor's scripts and calls, so the cheapest true change is in the samples: each
of the donor's is swapped for the Ultimate fighter's sound for the same thing (an attack grunt for an
attack grunt, the ledge grunt for the ledge grunt, the side special's swing for the side special's
swing). The bank is then the port's own: it gets its own name and file name, so installing it adds a
bank instead of reusing the donor's, and the tool that installs it points the port's calls there.

What each donor sample is for is the donor's side of the table (DONOR). The Ultimate side is the game's
own sound names, the same words for every fighter (vc_<fighter>_attack01, se_<fighter>_special_s01, ...).

  choose(donor, fighter, root)        -> {donor sample: (Ultimate name, sound bytes)}, what was not found
  build(sound_zip, name, chosen, ...) -> the port's own sound package
"""
from __future__ import annotations

import io
import json
import re
import struct
import subprocess
import zipfile
from pathlib import Path

# The donor's samples by what they are for: the Ultimate sounds to try for each, in order. {f} is the
# fighter's name in the game's files. `+` takes that kind's sounds in number order, one per donor sample
# of the row, round again when the fighter has fewer. A name starting `cheer:` is the first sound of that
# bank (the crowd's chant has a bank of its own). A name starting `@` is a move script of the game's: the
# first sound of the fighter's own that it plays (which of a fighter's numbered sounds a move uses is the
# script's word, not the number's: a bow's release is its third, a beam's its first).
# `@vc:` is the same for a voice line. A name starting `~vc:` or `~se:` is a word: the fighter's voice lines (or
# sounds) whose name ends in that word and a number, whatever comes before it (a game may name a fighter's lines
# by who speaks: `vc_duckhunt_dog_damage01`, `vc_duckhunt_duck_attack02`), in name order, one per donor sample.
DONOR = {'Marth': {
    'bank': 'mars',
    'roles': [
        (('se_call_mars',), ['cheer:vc_{f}_cheer']),
        # six sounds of sword and sheath from the donor's own victory poses, which a port does not play: room
        # for the sounds a sword fighter makes most, its three weights of swing and its smash attacks
        (('se_mars_sw_demo_simau',), ['se_{f}_swing_s']), (('se_mars_sw_demo_nuki',), ['se_{f}_swing_m']),
        (('se_mars_sw_demo1',), ['se_{f}_swing_l']), (('se_mars_sw_demo2',), ['se_{f}_smash_s01']),
        (('se_mars_sw_demo3',), ['se_{f}_smash_h01']), (('se_mars_sw_demo4',), ['se_{f}_smash_l01']),
        (('v_mars_atk1', 'v_mars_atk2', 'v_mars_atk3', 'v_mars_atk4', 'v_mars_atk5', 'v_mars_atk6', 'v_mars_atk7',
          'v_mars_atk8', 'v_mars_atk10'), ['+vc_{f}_attack', '~vc:attack']),
        (('v_mars_bokuwa', 'v_mars_konkaiwa', 'v_mars_kyoumo'), ['+vc_{f}_win']),          # after a win
        (('v_mars_letsdance', 'v_mars_miteite'), ['+vc_{f}_appeal']),                       # a taunt
        # a special's voice: by its name, else the first voice line its script plays (a game that numbers its lines)
        (('v_mars_count1', 'v_mars_count2', 'v_mars_count3'), ['+vc_{f}_special_l', '@vc:game_speciallwhit', '@vc:game_speciallw']),
        (('v_mars_dolphin',), ['vc_{f}_special_h01', '@vc:game_specialhi']),                # the up special
        (('v_mars_shiedbreak',), ['vc_{f}_special_n01', '@vc:game_specialnend', '@vc:game_specialn']),   # the neutral special
        (('v_mars_gake',), ['vc_{f}_cliffcatch']),                                          # catching a ledge
        (('v_mars_hosikie',), ['vc_{f}_knockout', 'vc_{f}_damage_twinkle']),                # sent off as a star
        (('v_mars_hura',), ['vc_{f}_furafura']),                                            # dizzy
        (('v_mars_huttobi', 'v_mars_huttobi2'), ['+vc_{f}_damagefly', '~vc:damage']),       # sent flying
        (('v_mars_yarare',), ['vc_{f}_damage01', '~vc:damage']),                            # hit
        # (a fighter that says nothing as it jumps may still make a sound of its own there: the game plays it
        # from its code, the donor's kept jump scripts play this sample)
        (('v_mars_jump',), ['vc_{f}_jump01', 'se_{f}_jump01']),
        (('v_mars_motiage',), ['vc_{f}_heavyget']),                                         # lifting something heavy
        (('v_mars_nemuru',), ['vc_{f}_furasleep']),                                         # asleep
        (('v_mars_otto',), ['vc_{f}_ottotto']),                                             # teetering on an edge
        (('v_mars_rakka4',), ['vc_{f}_missfoot01']),                                        # falling off
        # the neutral special: what its release plays, and what its start holds while charging (the donor plays
        # that one in a loop with the pitch rising, see `calls`)
        (('se_mars_sbreak',), ['@game_specialn', '@game_specialnend', '+se_{f}_special_n']),
        (('se_mars_sbreak_tame',), ['@game_specialnstart', 'se_{f}_special_n02']),
        (('se_mars_sw_conbo1', 'se_mars_sw_conbo2', 'se_mars_sw_conbo3', 'se_mars_sw_conbo4'), ['+se_{f}_special_s']),
        (('se_mars_dolphin',), ['se_{f}_special_h01']),
        (('se_mars_counter_kamae', 'se_mars_counter'), ['+se_{f}_special_l']),
    ],
    # Voice samples that nothing plays any more on a route, and so are room there. On a fighter's own skeleton the
    # specials' scripts, the results screen's and the taunt's are all written anew with nothing of the donor's in
    # them, and the engine itself plays none of these (it plays the hurt, jump, ledge, sleep ... ones).
    # The specials' own sounds are in the same case there: such a sample is no more than a place the port calls a
    # sound of its own from, so a row does not go round again onto one (see `choose`).
    'unplayed': {'own skeleton': ('v_mars_count1', 'v_mars_count2', 'v_mars_count3', 'v_mars_dolphin', 'v_mars_shiedbreak',
                                  'v_mars_bokuwa', 'v_mars_konkaiwa', 'v_mars_kyoumo', 'v_mars_letsdance',
                                  'v_mars_miteite',
                                  'se_mars_sbreak', 'se_mars_sbreak_tame', 'se_mars_sw_conbo1', 'se_mars_sw_conbo2',
                                  'se_mars_sw_conbo3', 'se_mars_sw_conbo4', 'se_mars_dolphin', 'se_mars_counter_kamae',
                                  'se_mars_counter')},
    }}
RATES = (32000, 24000, 16000)       # tried in turn until the bank fits
ROOM = 640_000                      # bytes a bank may take: one of 690 KB has loaded in game, one of 3 MB has not
LONGEST = 3.5                       # seconds kept of any one sound


def name_sequences(game, fighter, voices):
    """A special's voice that the game plays by a SEQUENCE (`PLAY_SEQUENCE seq_<fighter>_rnd_special_s`: one of a set
    of lines, picked at random) is given the first of the fighter's lines of that occasion (`vc_<fighter>_special_s01`),
    a stand-in for the pick, named on the event (`sequence`, `stand_in`). Left a sequence, the dresser played nothing
    for it and the move was silent of his voice (Shulk's Back Slash and Air Slash). The other occasions (the normals'
    `attack`) are left as they are: the donor script's own voice cue stands for them, and it picks too.
    game: what `echo_ultimate.gamedata.moves.load` gives (changed in place). voices: the lower-case names of the
    fighter's voice bank. -> {sequence: the line it was given, or None when the bank has none of that occasion}"""
    out = {}
    prefix = f'seq_{fighter}_rnd_'.lower()
    for move in (game.get('moves') or {}).values():
        for e in move.get('sounds') or []:
            name = str(e.get('name') or '').lower()
            occasion = name[len(prefix):]
            if not (name.startswith(prefix) and occasion.startswith('special')):
                continue
            lines = sorted(v for v in voices if re.fullmatch(rf'vc_{re.escape(fighter.lower())}_{re.escape(occasion)}\d*', v))
            out[name] = lines[0] if lines else None
            if lines:
                e.update(sequence=name, name=lines[0], stand_in=f'the first of the {len(lines)} lines the game picks from')
    return out


def _banks(root, fighter, game='ultimate'):
    """{bank: {lower-case name: (name, sound)}} of the fighter's sound banks that are on disk or in the archive."""
    from . import source_game
    if source_game.written(game):
        return source_game.sounds(root, fighter)            # as the game's reader wrote them (WAVs)
    if game == 'brawl':
        from echo_brawl import gamedata
        return gamedata.sound_bank(root, fighter)
    from echo_ultimate import nus3audio
    from echo_ultimate.gamedata import arc
    root = Path(root)
    rel = {'se': f'sound/bank/fighter/se_{fighter}.nus3audio', 'vc': f'sound/bank/fighter_voice/vc_{fighter}.nus3audio',
           'cheer': f'sound/bank/fighter_voice/vc_{fighter}_cheer.nus3audio'}
    missing = [r for r in rel.values() if not (root / 'gamedata' / r).exists()]
    if missing:
        try:
            arc.extract(root, root / 'gamedata', missing)
        except OSError:
            pass                                        # no archive to take them from: the banks on disk are all there is
    out = {}
    for kind, r in rel.items():
        path = root / 'gamedata' / r
        out[kind] = ({n.lower(): (n, b) for n, b in nus3audio.sounds(path).items() if len(b) > 0x60} if path.exists() else {})
    return out


ADDED = '+'                         # before a sound's name in `chosen`: a sample the bank gains, not one swapped
SILENCE = 'nothing (silent)'        # the name in `chosen` of a donor voice sample the fighter has no line for


def silence():
    """A twentieth of a second of nothing: what a donor's voice sample becomes when the fighter's own game says
    nothing there (a dog does not grunt as it jumps), so that nothing of the donor's voice is left in the bank."""
    import numpy as np
    return {'pcm': np.zeros(1600, np.int16), 'rate': 32000}
PITCH = 12                          # a sound script command: the sample played lower or higher


def spare_scripts(scripts):
    """The places of the scripts in a donor's bank that a port's bank never plays: the big and the small form of a
    sound (the same sample as the script before it, played lower or higher). Melee plays those in place of the plain
    one while a fighter is giant or tiny, and only for its own fighters' banks (ft_80087D0C goes by the bank's
    number); a port's bank is a new one. A sound the bank gains takes one of these places: the installer points a
    port's sound calls at its own bank only for script numbers the donor's bank has, so a script joined on at the end
    would never be reached."""
    sample = lambda commands: next((v for c, v in commands if c == 1), None)
    return [i for i in range(1, len(scripts)) if any(c == PITCH for c, _ in scripts[i])
            and sample(scripts[i]) is not None and sample(scripts[i]) == sample(scripts[i - 1])]
MORE = 12                           # how many samples a bank may gain
# The sounds a port's own code plays (its items, its own states) are in no script of the game's. The driver puts
# them among the game's moves under this name, marked `code_plays`, in the order they matter (the sounds stage
# reads the same moves, so both choose one bank). Code calls a sound by its place in the bank, so each needs a
# plain place; one that has none is a thing that happens in silence, so the bank may gain a few more for them.
CODE = 'port_code'
CODE_MORE = 4                       # how many more samples a bank may gain for sounds only the port's code plays
SKIPPED_WORDS = ('cloth', 'step', 'landing', 'jump', 'squat')      # sounds of the fighter's a move script does not carry


def seconds(sound):
    """How long a sound is: one of Ultimate's (its bytes) or a decoded one ({'pcm', 'rate'})."""
    if isinstance(sound, dict):
        return len(sound['pcm']) / sound['rate']
    return struct.unpack_from('>I', sound, 0x10)[0] / struct.unpack_from('>I', sound, 0x0C)[0]


def to_wav(sound, path, rate, longest=None):
    """Write a sound of either kind as a WAV at `rate`."""
    if isinstance(sound, dict):
        from echo_brawl import brsar
        return brsar.to_wav(sound, path, rate, longest)
    from echo_ultimate import nus3audio
    return nus3audio.to_wav(sound, path, rate, longest) if longest is not None else nus3audio.to_wav(sound, path, rate)


def plain_samples(sound_zip: bytes):
    """The donor samples whose script only plays them (no loop, no bend of pitch): places a new sound can be
    called from by name."""
    with zipfile.ZipFile(io.BytesIO(sound_zip)) as z:
        scripts = json.loads(z.read('scripts.json')) if 'scripts.json' in z.namelist() else []
        steps = sound_steps(z.read('scripts.sem')) if 'scripts.sem' in z.namelist() else []
    out = set()
    for i, name in enumerate(scripts):
        if name.startswith('SFX') and i < len(steps) and not any(code in ALTERS for code in steps[i]):
            out.add(name[4:] if name.startswith('SFX_') else name[3:])
    return out


def choose(donor, fighter, root, sample_names, moves=None, game='ultimate', sound_zip=None, route=None):
    """Which of the fighter's sounds goes in each of the donor's samples. `moves`: the game's move scripts
    ({name: {sounds}}), for the rows that go by what a script plays. `game`: where the fighter is from.
    A sample whose row finds nothing is room: it goes to a sound the fighter's attacks and specials play that has
    no place yet, the most played first, then one whose move would have no sound of its own at all (`sound_zip`: the donor's package, to pass over places that loop or bend what
    they play). A donor VOICE sample still without a sound is made silent (`SILENCE`), unless nothing plays it any
    more on this `route` (the donor table's `unplayed`): then it is room like any other. A move the port writes a
    script for though it has no hitbox (`port_plays` in the move: the taunt) counts among what the bank should hold.
    So do the sounds the port's own code plays (the moves' entry `CODE`). Those are wanted in the order given,
    after the scripts' sounds whose move would otherwise be silent and before the ones whose move is heard already;
    none is put where the donor's script loops or bends what it plays; and the bank may gain `CODE_MORE` more
    samples for them.
    -> ({donor sample: (name, sound)}, [samples left as the donor's, with why])"""
    table = DONOR.get(donor)
    if not table:
        return {}, [f'no table of what {donor}\'s samples are for']
    banks = _banks(root, fighter, game)
    every = {**banks['se'], **banks['vc']}
    # a sound the game keeps as numbered variants (Incineroar's `se_gaogaen_special_h04_01` and `_02`: its sound code
    # picks one each time) is named by the scripts without the number. The first variant stands for the set (a
    # stand-in for the choice); passed over, the sound was silent and no receipt said so (verify 7.1)
    for m in (moves or {}).values():
        for e in m.get('sounds') or []:
            n = str(e.get('name') or '').lower()
            if n and n not in every and f'{n}_01' in every:
                every[n] = (n, every[f'{n}_01'][1])
    plain = plain_samples(sound_zip) if sound_zip else None
    unplayed = set(table.get('unplayed', {}).get(route, ()))
    # what the port plays: from its scripts, and from its own code
    plays = {}
    for script, m in sorted((moves or {}).items()):
        if not (m.get('hitboxes') or 'special' in script or m.get('port_plays') or m.get('code_plays')) or 'final' in script:
            continue                                    # a script the port does not write (a dodge, a final smash)
        for e in m.get('sounds') or []:
            n = str(e.get('name') or '').lower()
            if (str(e.get('cmd') or '').startswith('PLAY') and n in every and n.startswith((f'se_{fighter}_', f'vc_{fighter}_'))
                    and not any(w in n for w in SKIPPED_WORDS)):
                plays.setdefault(n, set()).add(script)
    code = [n for n in dict.fromkeys(str(e.get('name') or '').lower()
                                     for e in ((moves or {}).get(CODE) or {}).get('sounds') or []) if n in plays]
    chosen, left, room = {}, [], []
    for samples, tries in table['roles']:
        found, once = [], False
        for t in tries:
            want = t.format(f=fighter).lower()
            if want.startswith('cheer:'):
                found = list(banks['cheer'].values())[:1]
            elif want.startswith('@'):
                kind, script = ('vc', want[4:]) if want.startswith('@vc:') else ('se', want[1:])
                played = [str(e.get('name') or '').lower() for e in ((moves or {}).get(script) or {}).get('sounds') or []]
                found = [every[n] for n in played if n.startswith(f'{kind}_{fighter}_') and n in every][:1]
                once = True                             # one sound a script plays: one place, the row's others are room
            elif want.startswith('+'):
                found = [every[k] for k in sorted(every) if re.fullmatch(re.escape(want[1:]) + r'\d+', k)]
            elif want.startswith('~'):
                kind, word = want[1:3], want[4:]
                found = [every[k] for k in sorted(every) if re.fullmatch(rf'{kind}_{re.escape(fighter)}_(.+_)?{re.escape(word)}\d+', k)]
            elif want in every:
                found = [every[want]]
            if found:
                break
        for i, sample in enumerate(samples):
            if sample not in sample_names:
                continue
            sound = found[i % len(found)] if found and not (once and i) else None
            if sound and sample in unplayed and i >= len(found):
                # the row has gone round again onto a sample nothing plays on this route: the sound has its place
                # already, and this one is room (it keeps the sound if nothing wants the room)
                room.append((sample, f'{sample}: nothing plays it on this route, and {sound[0]} has a place already', sound))
            elif sound and plain is not None and sample not in plain and (
                    sound[0].lower() in code or (sample in unplayed and sound[0].lower() in plays)):
                # a place whose script loops or bends what it plays cannot be called by the port's code, nor by a
                # script the port writes (`calls` leaves it out); where nothing of the donor's plays it either (this
                # route's `unplayed`), a sound put there is never heard: it goes to a place that can be called
                chosen[sample] = (SILENCE, silence())
                who = "the port's code" if sound[0].lower() in code else 'a script the port writes'
                left.append(f"{sample}: its script loops or bends what it plays, and {who} plays {sound[0]} "
                            f'as it is (made silent)')
            elif sound:
                chosen[sample] = sound
            else:
                room.append((sample, f'{sample}: the fighter has no {tries[0].format(f=fighter).lstrip("+")}', None))
    # room goes to what the port plays and the bank does not hold yet where it can call it: a sound a row put
    # where the donor's script loops or bends (the donor's own charge code plays that place) is not held there for
    # the port's scripts, which call a sound only by a plain place (`calls` takes the plain one of the two)
    placed = {name.lower() for sample, (name, _) in chosen.items() if plain is None or sample in plain}
    silent = lambda n: not any(any(str(e.get('name') or '').lower() in placed for e in moves[sc].get('sounds') or [])
                               for sc in plays[n])
    if code:
        order = lambda n: (1, code.index(n)) if n in code else (0 if silent(n) else 2, -len(plays[n]), n)
    else:
        order = lambda n: (-len(plays[n]), not silent(n), n)
    wanted = sorted((n for n in plays if n not in placed), key=order)
    for sample, why, kept in room:
        if sample.startswith('v_') and sample not in unplayed:
            # a voice sample is never room: the engine and the donor's kept scripts play it on its own occasion (a
            # jump, a ledge caught, a hit taken, a win), and whatever sat in it would be heard there. The fighter's
            # own game says nothing on that occasion, so the port says nothing.
            chosen[sample] = (SILENCE, silence())
            left.append(why + ' (made silent)')
        elif wanted and (plain is None or sample in plain):
            chosen[sample] = every[wanted.pop(0)]
        elif kept:
            chosen[sample] = kept
        else:
            left.append(why)
    # what the port plays and no place was free for is added to the bank: a sample of its own, played by a script
    # the port's bank has no use for (see spare_scripts)
    most = MORE + min(CODE_MORE, sum(n in code for n in wanted))
    if sound_zip:
        with zipfile.ZipFile(io.BytesIO(sound_zip)) as z:
            most = min(most, len(spare_scripts(sem_read(z.read('scripts.sem'))))) if 'scripts.sem' in z.namelist() else 0
    for n in wanted[:most]:
        chosen[ADDED + n] = every[n]
    left += [f"{n}: {'its code plays' if n in code else 'its scripts play'} it, and the bank has no room for it"
             for n in wanted[most:]]
    for sample in sample_names:
        if sample not in chosen and not any(sample in s for s, _ in table['roles']):
            left.append(f'{sample}: nothing in the fighter is for the same thing')
    return chosen, left


ALTERS = (2, 3, 7, 13)             # sound script commands: start and end of a loop, a wait inside one, a bend of pitch


def sound_steps(sem: bytes):
    """The command codes of each script of a package's script file (.sem): the number of banks, where each
    bank's scripts start in a table of offsets, then four-byte commands (a code and a 24-bit value)."""
    if len(sem) < 20:
        return []
    count = struct.unpack_from('>I', sem, 8)[0]
    starts = struct.unpack_from(f'>{count + 1}I', sem, 12)
    table = 12 + 4 * (count + 1)
    offsets = struct.unpack_from(f'>{starts[-1] + 1}I', sem, table)
    out = []
    for k in range(starts[0], starts[1]):               # the first bank: a fighter's package has the one
        first, last = offsets[k], offsets[k + 1]
        if last == 0 or last < first:
            last = len(sem)
        out.append([sem[at] for at in range(first, last - 3, 4)])
    return out


def sem_read(sem: bytes):
    """A package's script file -> one list of (code, value) for each script (a fighter's package has one bank)."""
    count = struct.unpack_from('>I', sem, 8)[0]
    starts = struct.unpack_from(f'>{count + 1}I', sem, 12)
    if count != 1:
        raise ValueError('a script file with more than one bank')
    table = 12 + 4 * (count + 1)
    offsets = struct.unpack_from(f'>{starts[-1] + 1}I', sem, table)
    out = []
    for k in range(starts[0], starts[1]):
        first, last = offsets[k], offsets[k + 1]
        if last == 0 or last < first:
            last = len(sem)
        out.append([(sem[at], int.from_bytes(sem[at + 1:at + 4], 'big')) for at in range(first, last - 3, 4)])
    return out


def sem_write(scripts) -> bytes:
    """The script file of one bank holding `scripts` (lists of (code, value))."""
    table = 12 + 8 + 4 * (len(scripts) + 1)
    offsets, body = [], b''
    for commands in scripts:
        offsets.append(table + len(body))
        for code, value in commands:
            body += bytes([code]) + int(value).to_bytes(3, 'big')
    return (struct.pack('>3I', 0, 0, 1) + struct.pack('>2I', 0, len(scripts))
            + struct.pack(f'>{len(offsets) + 1}I', *offsets, 0) + body)


def ssm_read(ssm: bytes):
    """A sound bank -> {'start', 'sounds': [{'rate', 'channels': [{'loop_flag', 'format', 'loop', 'nibbles', 'rest',
    'data'}]}]} (the layout the project tool reads and writes; 'rest' is a channel's coefficients and frame state)."""
    head, _size, count, start = struct.unpack_from('>4i', ssm, 0)
    head += 0x10
    at, sounds = 0x10, []
    for _ in range(count):
        channels, rate = struct.unpack_from('>2i', ssm, at)
        at += 8
        sound = {'rate': rate, 'channels': []}
        for _c in range(channels):
            loop_flag, fmt, loop_start, end, current = struct.unpack_from('>2h3i', ssm, at)
            nibbles = end - current
            data_at = head + (current + 1) // 2 - 1
            sound['channels'].append({'loop_flag': loop_flag, 'format': fmt, 'loop': loop_start - current, 'nibbles': nibbles,
                                      'rest': ssm[at + 16:at + 0x40], 'data': ssm[data_at:data_at + (nibbles + 1) // 2 + 1]})
            at += 0x40
        sounds.append(sound)
    return {'start': start, 'sounds': sounds}


def ssm_write(bank) -> bytes:
    """The bank file for what `ssm_read` gives."""
    head = sum(8 + len(s['channels']) * 0x40 for s in bank['sounds'])
    entries, data = b'', b''
    for s in bank['sounds']:
        entries += struct.pack('>2i', len(s['channels']), s['rate'])
        for c in s['channels']:
            first = (len(data) + 1) * 2
            entries += struct.pack('>2h3i', c['loop_flag'], c['format'], first + c['loop'], first + c['nibbles'], first) + c['rest']
            data += c['data'] + bytes(-(0x10 + head + len(data) + len(c['data'])) % 8)
    data += bytes(-(0x10 + head + len(data)) % 0x20)
    size = len(data)
    if size % 0x20:
        data += bytes(0x20 - size % 0x20 + 8)
        size += 0x20 - size % 0x20
    return struct.pack('>4i', head, size, len(bank['sounds']), bank['start']) + entries + data


def announcer(root, fighter, game='ultimate'):
    """The announcer saying the fighter's name, as the game stores it, or None. The first fighters share one
    bank of names; a later one has a bank of its own."""
    if game == 'brawl':
        from echo_brawl import gamedata
        return next((sound for _name, sound in gamedata.sound_bank(root, fighter)['call'].values()), None)
    from . import source_game
    if source_game.written(game):
        # as the reader wrote it (identity/announcer.wav: Rivals 2's AnnouncerLine); Slap City has no announcer
        return source_game.announcer(root, fighter)
    from echo_ultimate import nus3audio
    from echo_ultimate.gamedata import arc
    from . import fighters
    root = Path(root)
    group, entry = fighters.group(fighter)
    if group is not None and group != fighter:
        # a form of a group (fighters.FORMS) is called by the group's name: the game has no call for the form
        got = announcer(root, entry.get('call') or group, game)
        if got is not None:
            return got
    for rel in (f'sound/bank/narration/vc_narration_characall_{fighter}.nus3audio', 'sound/bank/narration/vc_narration_characall.nus3audio'):
        path = root / 'gamedata' / rel
        if not path.exists():
            arc.extract(root, root / 'gamedata', [rel])
        if not path.exists():
            continue
        named = {n.lower(): b for n, b in nus3audio.sounds(path).items() if len(b) > 0x60}
        for name, sound in named.items():
            if name.endswith('_' + fighter) or name.endswith(f'_{fighter}_01') or (rel.endswith(f'_{fighter}.nus3audio') and len(named) == 1):
                return sound
        if rel.endswith(f'_{fighter}.nus3audio') and named:
            return next(iter(named.values()))
    return None


def aliases(root, fighter, game='ultimate'):
    """[{names}] of a written game's sounds that are ONE sample under several names (its reader's sounds.json: a
    name and its `also`): Rivals 2's `Fstrong VO` and `Ustrong VO` events play the sample `Effort Heavy` plays.
    A script may play any of the names; the bank holds the sample once, under one. [] for any other game."""
    from . import source_game
    if not source_game.written(game):
        return []
    path = source_game.folder(root, fighter) / 'sound' / 'sounds.json'
    index = json.loads(path.read_text('utf-8')) if path.is_file() else {}
    return [{n.lower()} | {a.lower() for a in row.get('also') or []} for n, row in index.items() if row.get('also')]


def calls(sound_zip: bytes, bank, chosen, aliases=()):
    """{Ultimate sound name, lower case: the number a move script plays it by} for the sounds the port's bank
    holds: the donor's bank number times 10000 plus the place of the script that plays that sample (the
    donor names each such script after its sample). Installing the port moves these to its own bank.
    A script that does more than play its sample (a loop, a bend of pitch: the donor's rising charge sound)
    is left out: the fighter's sound would come out looped and bent too. `aliases` (`aliases()`): groups of names
    of one sample; each name of a group the bank holds plays by the same number."""
    with zipfile.ZipFile(io.BytesIO(sound_zip)) as z:
        scripts = json.loads(z.read('scripts.json')) if 'scripts.json' in z.namelist() else []
        steps = sound_steps(z.read('scripts.sem')) if 'scripts.sem' in z.namelist() else []
        spare = spare_scripts(sem_read(z.read('scripts.sem'))) if 'scripts.sem' in z.namelist() else []
    out = {}
    more = [k for k in chosen if k.startswith(ADDED)]
    for sample, (name, _) in chosen.items():
        if sample.startswith(ADDED):                    # it takes a script the port has no use for, in the order chosen
            if bank is not None and more.index(sample) < len(spare):
                out.setdefault(name.lower(), int(bank) * 10000 + spare[more.index(sample)])
            continue
        at = next((i for i, s in enumerate(scripts) if s in ('SFX' + sample, 'SFX_' + sample)), None)
        if at is None or bank is None:
            continue
        if at < len(steps) and any(code in ALTERS for code in steps[at]):
            continue
        out.setdefault(name.lower(), int(bank) * 10000 + at)
    for group in aliases or ():
        held = next((out[n] for n in sorted(group) if n in out), None)
        if held is not None:
            for n in group:
                out.setdefault(n, held)
    return out


def build(sound_zip: bytes, donor, name, chosen, mexcli, work, run_args=None):
    """The port's own sound package from the donor's (`sound_zip`: group.json, scripts.sem, scripts.json and
    the bank): each chosen sample swapped in, and the bank renamed after the port so that it is installed
    as a bank of its own. -> (bytes of the new package, report)"""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(sound_zip)) as z:
        group = json.loads(z.read('group.json'))
        members = {n: z.read(n) for n in z.namelist()}
    ssm_name = next(n for n in members if n.lower() == group['fileName'].lower())
    donor_bank = members[ssm_name]
    index = {s['name']: i for i, s in enumerate(group['sounds'])}
    more = {k: v for k, v in chosen.items() if k.startswith(ADDED)}
    chosen = {k: v for k, v in chosen.items() if not k.startswith(ADDED)}
    lasts = {s: min(LONGEST, seconds(b)) for s, (_, b) in {**chosen, **more}.items()}
    # the highest rate at which the swapped-in samples fit (fourteen samples take eight bytes)
    rate = next((r for r in RATES if sum(lasts.values()) * r / 14 * 8 <= max(len(donor_bank), ROOM)), RATES[-1])
    current = work / 'bank-0.ssm'
    current.write_bytes(donor_bank)
    done = []
    for k, (sample, (ult, sound)) in enumerate(sorted(chosen.items(), key=lambda kv: index[kv[0]])):
        wav = to_wav(sound, work / 'wav' / f'{sample}.wav', rate, LONGEST)
        out = work / f'bank-{k + 1}.ssm'
        r = subprocess.run([str(mexcli), 'ssm-replace', str(current), str(index[sample]), str(wav), str(out)],
                           capture_output=True, text=True, **(run_args or {}))
        if r.returncode or not out.is_file():
            raise RuntimeError(f'the bank tool would not take {ult} for {sample}: {(r.stdout + r.stderr)[-300:]}')
        if current.name != 'bank-0.ssm':
            current.unlink()
        current = out
        done.append({'sample': sample, 'index': index[sample], 'sound': ult, 'seconds': round(lasts[sample], 2)})
    bank = current.read_bytes()
    added = []
    if more:
        # samples the bank gains: each is put through the bank tool once (in a copy, over its first sample) to be
        # encoded, then joined on at the end; a script the port has no use for is rewritten like the donor's plain
        # ones to play it
        whole, scripts = ssm_read(bank), sem_read(members['scripts.sem'])
        spare = spare_scripts(scripts)
        names = json.loads(members['scripts.json']) if 'scripts.json' in members else []
        plain = {'se': None, 'vc': None}
        for k, commands in enumerate(scripts):
            kind = 'vc' if k < len(names) and names[k].startswith('SFXv_') else 'se'
            if plain[kind] is None and [c for c, _ in commands] == [1, 16, 4, 6, 14]:
                plain[kind] = commands
        scratch = work / 'encode-in.ssm'
        scratch.write_bytes(donor_bank)
        for k, (key, (ult, sound)) in enumerate(more.items()):
            wav = to_wav(sound, work / 'wav' / f'added-{k}.wav', rate, LONGEST)
            out = work / f'encode-{k}.ssm'
            r = subprocess.run([str(mexcli), 'ssm-replace', str(scratch), '0', str(wav), str(out)],
                               capture_output=True, text=True, **(run_args or {}))
            if r.returncode or not out.is_file():
                raise RuntimeError(f'the bank tool would not take {ult}: {(r.stdout + r.stderr)[-300:]}')
            whole['sounds'].append(ssm_read(out.read_bytes())['sounds'][0])
            out.unlink()
            kind = 'vc' if ult.lower().startswith('vc_') else 'se'
            like = plain[kind] or plain['se'] or plain['vc']
            if like is None:
                raise RuntimeError('the donor has no plain script to make a new one like')
            sample = re.sub(r'^(se|vc)_[a-z0-9]+_', lambda m: ('v_' if m[1] == 'vc' else 'se_') + DONOR[donor]['bank'] + '_',
                            ult.lower())
            if k >= len(spare):
                raise RuntimeError(f'the bank has no script to spare for {ult}')
            scripts[spare[k]] = [(code, len(whole['sounds']) - 1 if code == 1 else value) for code, value in like]
            while len(names) <= spare[k]:
                names.append('SFX')
            names[spare[k]] = 'SFX' + sample
            group['sounds'].append({'name': sample})
            added.append({'sample': sample, 'index': len(whole['sounds']) - 1, 'script': spare[k], 'sound': ult,
                          'seconds': round(lasts[key], 2)})
        bank = ssm_write(whole)
        members['scripts.sem'] = sem_write(scripts)
        members['scripts.json'] = json.dumps(names).encode('utf-8')
    # its own names: the group, the bank file, each sample and script that carries the donor's
    key, own = DONOR[donor]['bank'], re.sub(r'[^a-z0-9]', '', name.lower()) or 'port'
    rename = lambda s: re.sub(key, own, s, flags=re.I)
    group['name'] = name
    group['fileName'] = f'{own}.ssm'
    for s in group['sounds']:
        s['name'] = rename(s['name'])
    members.pop(ssm_name)
    members['group.json'] = json.dumps(group, indent=1).encode('utf-8')
    if 'scripts.json' in members:
        members['scripts.json'] = json.dumps([rename(s) for s in json.loads(members['scripts.json'])]).encode('utf-8')
    members[group['fileName']] = bank
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, data in members.items():
            z.writestr(n, data)
    return out.getvalue(), {'rate': rate, 'bank_bytes': len(bank), 'donor_bank_bytes': len(donor_bank),
                            'seconds': round(sum(lasts.values()), 1), 'file': group['fileName'], 'swapped': done,
                            'added': added}
