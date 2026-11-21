"""What a port sounds like, checked against what the game put out.

Usage: python audio_check.py <port work dir> <fighter> <dump.wav> <probe log>
<dump.wav> is the game's own sound, written by Dolphin while look_probe.py ran the `snd_*` moves (PROBE_AUDIO);
<probe log> is that run's output (it says how far into the file each move began).

For each move: the sounds the source game's script plays that are in the port's bank, each looked for in the stretch of
the dump that is that move. A sound is found by sliding its own waveform (as it went into the bank) along the dump:
`match` is how alike the best place is (1 the same, 0 nothing in common; a voice under a swing at the same moment
scores low and is told by standing well above every other place in the move), `frame` how many frames after the move began
it was heard, `script` the frame the source game's script plays it on.
"""
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

work, fighter, dump_path, log_path = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
# the probe's moves -> the source game's scripts that play during each (in the order they play)
SCRIPTS = {
    'snd_jab': ['game_attack11'], 'snd_fsmash': ['game_attacks4s'], 'snd_usmash': ['game_attackhi4'], 'snd_dsmash': ['game_attacklw4'],
    'snd_ftilt': ['game_attacks3s'], 'snd_utilt': ['game_attackhi3'], 'snd_dtilt': ['game_attacklw3'],
    'snd_eruption': ['game_specialnstart', 'game_specialnend'], 'snd_eruption_full': ['game_specialnstart', 'game_specialnend__2'],
    'snd_quickdraw': ['game_specialsstart', 'game_specialsdash'], 'snd_quickdraw_hit': ['game_specialsstart', 'game_specialsdash', 'game_specialsattack'],
    'snd_aether': ['game_specialhi', 'game_specialhi3', 'game_specialhi4'], 'snd_counter': ['game_speciallw'],
    'snd_grab': ['game_catch'], 'snd_jump': [], 'snd_taunt': [], 'snd_quiet': [],
    # Wolf's specials (each move's scripts in the order his own states play their clips)
    'snd_w_n': ['game_specialn', 'game_fly'], 'snd_w_s': ['game_specialsstart', 'game_specials', 'game_specialairsend'],
    'snd_w_hi': ['game_specialhihold', 'game_specialhi', 'game_specialhifall'],
    'snd_w_lw': ['game_speciallwstart', 'game_speciallwloop', 'game_speciallwend'],
    # Incineroar's own tests (round 1 looked for his jump alone: a test not named here is heard by nobody)
    'ig_lariat': ['game_specialn'], 'ig_lariat_air': ['game_specialairn'],
    'ig_whip': ['game_specialsstart', 'game_throwf'], 'ig_whip_miss': ['game_specialsstart'],
    'ig_chop': ['game_specialhistart', 'game_specialairhiturn', 'game_specialairhifall', 'game_specialhibound'],
    'ig_chop_air': ['game_specialairhistart', 'game_specialairhiturn', 'game_specialairhifall', 'game_specialhibound'],
    'ig_revenge': ['game_speciallwstart', 'game_speciallw', 'game_attacks3'], 'ig_revenge_air': ['game_specialairlwstart'],
    'ig_revenge_power': ['game_speciallwstart', 'game_speciallw', 'game_attacks3'], 'ig_ftilt': ['game_attacks3'],
    # Shulk's arts (leftovers): each press plays the art's clip, whose script says its name (vc_shulk_special_n0X);
    # the cold trial's round listened for none of its tests
    'sk_arts_show': ['game_specialnjump', 'game_specialnspeed', 'game_specialnshield'],
    'sk_buster_throw': ['game_specialnjump', 'game_specialnspeed', 'game_specialnshield', 'game_specialnbuster'],
    'sk_smash_throw': ['game_specialnjump', 'game_specialnspeed', 'game_specialnshield', 'game_specialnbuster',
                       'game_specialnsmash'],
    'sk_trail': ['game_attacklw4'],
    # Ittle Dew's (Slap City): each test is one move, played by one script
    'id_fire': ['game_specialn'], 'id_fire_air': ['game_specialairn'], 'id_side': ['game_specials'],
    'id_up': ['game_specialhi'], 'id_up_air': ['game_specialairhi'], 'id_down': ['game_speciallw'], 'id_down_air': ['game_specialairlw'],
    'id_fsmash': ['game_attacks4s'], 'id_usmash': ['game_attackhi4'], 'id_dsmash': ['game_attacklw4'], 'id_dtilt': ['game_attacklw3'],
    'id_nair': ['game_attackairn'], 'id_fair': ['game_attackairf'],
    'id_fire_hold': ['game_specialn'], 'id_fair_alone': ['game_attackairf'], 'id_drift': [],
    'id_fair_pinned': ['game_attackairf'],
    # Fishbunjin's (Slap City)
    'fb_neutral': ['game_specialn'], 'fb_side': ['game_specials'], 'fb_up': ['game_specialhi'],
    'fb_down_air': ['game_specialairlw'], 'fb_fsmash': ['game_attacks4s'], 'fb_usmash': ['game_attackhi4'],
    'fb_dsmash': ['game_attacklw4'],
    # Zetterburn's (Rivals 2): the parts each test's states play, in order (the round of the cold trial listened
    # for none of them until these were named)
    'zt_burst_tap': ['game_specialn', 'game_specialnuncharged'], 'zt_burst_held': ['game_specialn'],
    'zt_fireball': ['game_specials'], 'zt_up': ['game_specialhi'], 'zt_up_aim': ['game_specialhi'],
    'zt_up_hit': ['game_specialhi'], 'zt_slam': ['game_speciallw'], 'zt_puddle': ['game_speciallw'],
    'zt_dive': ['game_specialairlw', 'game_specialairlwdive', 'game_speciallwslam'],
    'zt_consume': ['game_specialn', 'game_specialnuncharged', 'game_attacks4s'],
}
ENGINE = {'snd_jump': [f'vc_{fighter}_jump01'], 'snd_taunt': [f'vc_{fighter}_appeal01', f'vc_{fighter}_appeal02'],
          # sounds a port's own code plays, which no script does: Ittle Dew's bomb as it bursts
          'id_side': [f'se_{fighter}_explosion'],
          # Zetterburn's burn and puddle (own_zetterburn.py CODE_SOUNDS, archived: the game plays them from code)
          'zt_burst_tap': [f'se_{fighter}_burn_applied', f'se_{fighter}_burn_end'],
          'zt_fireball': [f'se_{fighter}_burn_applied'],
          'zt_slam': [f'se_{fighter}_flame_puddle_create', f'se_{fighter}_burn_applied'],
          'zt_puddle': [f'se_{fighter}_flame_puddle_create', f'se_{fighter}_burn_applied'],
          'zt_consume': [f'se_{fighter}_burn_applied', f'se_{fighter}_consume']}


def mono(path):
    with wave.open(str(path)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels()).astype(float)
        return a.mean(axis=1), w.getframerate()


def find(sample, stretch):
    """(match 0..1, where in `stretch` in samples) of the best place for `sample`."""
    if len(stretch) < len(sample) or not np.abs(sample).max():
        return 0.0, 0, 0.0
    s = sample - sample.mean()
    # (the same as sliding the sample along sample by sample, done through a transform: seconds, not minutes)
    size = 1 << (len(stretch) + len(s) - 2).bit_length()
    top = np.fft.irfft(np.fft.rfft(stretch, size) * np.conj(np.fft.rfft(s, size)), size)[:len(stretch) - len(s) + 1]
    run = np.concatenate([[0.0], np.cumsum(stretch ** 2)])
    energy = np.sqrt(np.maximum(run[len(s):] - run[:-len(s)], 0.0) * (s ** 2).sum())
    score = np.where(energy > 1e-3, top / np.maximum(energy, 1e-9), 0.0)
    at = int(score.argmax())
    # how far the best place stands above the best anywhere else (a tenth of a second or more away)
    away = np.ones(len(score), bool)
    away[max(0, at - RATE // 10):at + RATE // 10] = False
    other = float(score[away].max()) if away.any() else 0.0
    return float(score[at]), at, (float(score[at]) / other if other > 1e-6 else 99.0)


dump, rate = mono(dump_path)
RATE = rate
report = json.loads((work / 'package' / 'sound.json').read_text('utf-8'))
import os  # noqa: E402
moves = json.loads((work / os.environ.get('PORT_DIR', 'port') / 'game.json').read_text('utf-8'))['moves']
# a fighter whose forward tilt and smash have one script each (no angled ones) names them without the last letter
SCRIPTS = {k: [n if n in moves or n.split('__')[0] in moves else (n[:-1] if n[:-1] in moves else n) for n in v] for k, v in SCRIPTS.items()}
# the taunt, when the port writes its script from the game's (the driver marks such a script `port_plays`)
SCRIPTS['snd_taunt'] = [k for k, v in moves.items() if isinstance(v, dict) and v.get('port_plays')]
# a fighter with no voice for a jump makes its jump sound there (the donor's kept jump script plays that place)
ENGINE['snd_jump'].append(f'se_{fighter}_jump01')
waves = {}
for row in report['swapped']:
    waves.setdefault(row['sound'].lower(), work / 'package' / 'sound-work' / 'wav' / f"{row['sample']}.wav")
for k, row in enumerate(report.get('added') or []):
    waves.setdefault(row['sound'].lower(), work / 'package' / 'sound-work' / 'wav' / f'added-{k}.wav')
starts = []
for line in open(log_path, encoding='utf-8', errors='replace'):
    m = re.match(r'(\w+): sound file at (\d+) bytes', line)
    if m:
        starts.append((m[1], max(0, (int(m[2]) - 44) // 4)))
starts.append(('end', len(dump)))
found_all, missed = 0, []
for (name, first), (_next, last) in zip(starts, starts[1:]):
    stretch = dump[first:last]
    loud = float(np.sqrt((stretch ** 2).mean())) if len(stretch) else 0.0
    print(f'{name}: {len(stretch) / rate:.1f} s of sound, loudness {loud:.0f}')
    expected, shift = [], 0
    for script in SCRIPTS.get(name, []):
        entry = moves.get(script) or {}
        for e in entry.get('sounds') or []:
            n = str(e.get('name') or '').lower()
            if n == f'vc_{fighter}_attack':                 # a grunt the game picks itself: any of the fighter's attack voices
                expected.append((e['real'], script, 'one of the attack voices', [w for w in waves if re.fullmatch(rf'vc_{fighter}_attack\d+', w)]))
            elif n in waves:
                expected.append((e['real'], script, n, [n]))
    for n in ENGINE.get(name, []):
        if n in waves:
            expected.append((None, 'the engine', n, [n]))
    for frame, script, label, names in expected:
        best = (0.0, 0, None, 0.0)
        for n in names:
            sample, srate = mono(waves[n])
            if srate != rate:
                sample = np.interp(np.arange(int(len(sample) * rate / srate)) * (srate / rate), np.arange(len(sample)), sample)
            score, at, stands = find(sample, stretch)
            if score > best[0]:
                best = (score, at, n, stands)
        # heard: much like it, or (under other sounds at the same moment) clearly the one place in the move that is like it
        heard = best[0] >= 0.5 or (best[0] >= 0.25 and best[3] >= 1.8)
        found_all += heard
        if not heard:
            missed.append((name, label))
        print(f"   {'heard ' if heard else 'NOT heard'} {label}{'' if len(names) == 1 or not best[2] else ' (' + best[2] + ')'}: match {best[0]:.2f} ({best[3]:.1f} times the next best place), "
              f"frame {best[1] * 60 / rate:.0f} of the move; {script} plays it on frame {frame}")
print(f'{found_all} sounds heard; not heard: {missed}')
# the fighter's own tests this check knows no scripts for: nothing of theirs was listened for (said, not passed over)
unknown = [n for n, _ in starts[:-1] if n not in SCRIPTS and n not in ENGINE and not re.match(r'(look|step|match|w|face)_', n)
           and n not in ('spotdodge', 'roll_f', 'roll_b', 'shield_drop', 'airdodge', 'grab_whiff', 'dashgrab_whiff')]
if unknown:
    print(f'not listened for (no scripts named for them in audio_check.SCRIPTS): {sorted(set(unknown))}')
