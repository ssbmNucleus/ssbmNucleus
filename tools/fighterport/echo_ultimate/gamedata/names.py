"""Candidate names for the hash40 values the game files use.

The files store names only as hashes, so a name can be shown only if it was
guessed. Script names follow the animation file names (``c00attack11.nuanmb``
-> ``game_attack11``), which the archive path list gives for every fighter.
Anything not guessed prints as ``0x...``.
"""
import re
from pathlib import Path

SCRIPT_KINDS = ('game_', 'effect_', 'sound_', 'expression_')

# scripts whose name is not an animation file name
EXTRA_SCRIPTS = ('attack13', 'attack100', 'attack100end', 'attack100start', 'attacks3', 'attacks3hi', 'attacks3lw',
                 'attacks4', 'attacks4hi', 'attacks4lw', 'attacks4charge', 'attackhi4charge', 'attacklw4charge',
                 'catchturn', 'specialhi', 'specialairhi', 'specialhi2', 'specialairhi2', 'specials', 'specialairs',
                 'specialn', 'specialairn', 'speciallw', 'specialairlw', 'cliffattack', 'downattacku', 'downattackd',
                 'slipattack', 'final', 'finalair',
                 'fly', 'regular', 'regularair')            # a projectile's own scripts

BONES = ('top', 'trans', 'rot', 'hip', 'waist', 'bust', 'neck', 'head', 'throw', 'clavicler', 'claviclel',
         'shoulderr', 'shoulderl', 'armr', 'arml', 'handr', 'handl', 'haver', 'havel', 'have', 'legr', 'legl', 'kneer',
         'kneel', 'footr', 'footl', 'toer', 'toel', 'tail1', 'tail2', 'tail3', 'sword', 'sword1', 'sword2',
         'swordr', 'swordl', 'mouth', 'nose', 'bodyn')

# a voice the game plays as one of a set of lines picked at random (`PLAY_SEQUENCE`) is named
# `seq_<fighter>_rnd_<occasion>`; the game's tables of what each set holds are not read (their names are hashes too),
# so these are the occasions guessed. Shulk's scripts play three: attack (his normals), special_s (Back Slash),
# special_h (Air Slash); left as hashes, the specials were silent of his voice (fighter_port voice.name_sequences)
SEQUENCE_WORDS = ('attack', 'attack_s', 'attack_h', 'attack_l', 'smash', 'smash_s', 'smash_h', 'smash_l', 'special',
                  'special_n', 'special_s', 'special_h', 'special_l', 'special_n1', 'special_n2', 'special_s1',
                  'special_s2', 'special_h1', 'special_h2', 'special_l1', 'special_l2', 'damage', 'damage_s',
                  'damage_l', 'damagefly', 'futtobi', 'futtobi01', 'futtobi02', 'ottotto', 'missfoot', 'cliffcatch',
                  'jump', 'appeal', 'win', 'catch', 'throw', 'passive', 'down', 'escape', 'heavy', 'final',
                  # found by trying each fighter's own voice words (2026-11-13): Greninja's smash attacks, Incineroar's
                  # attack appeal, Wolf's air attack
                  'attack_smash_s', 'attack_smash_h', 'attack_smash_l', 'attackappeal', 'attackappeal01',
                  'attackappeal02', 'attack_air', 'attack_air_n', 'attack_air_f', 'attack_air_b', 'attack_air_h',
                  'attack_air_l',
                  # Wolf's third jab (2026-11-13): `attack_` and two letters, every one tried (the only name of the
                  # 1369 to fit; 17 million names of an occasion word and up to four letters more give no other)
                  'attack_a3')

EFFECTS = tuple('collision_attr_' + a for a in (
    'normal', 'cutup', 'sting', 'fire', 'elec', 'ice', 'water', 'slash', 'kick', 'punch', 'bat', 'magic', 'purple',
    'aura', 'paralyze', 'bury', 'saving', 'sleep', 'flower', 'coin', 'pierce', 'turn', 'none', 'search', 'stop'))


# files that hold effect and sound names as plain text ({f} = the fighter)
LABEL_FILES = ('effect/fighter/{f}/ef_{f}.eff', 'effect/system/common/ef_common.eff',
               'sound/bank/fighter/se_{f}.nus3bank', 'sound/bank/fighter_voice/vc_{f}.nus3bank',
               'sound/bank/common/se_common.nus3bank')


def labels_in(path):
    """Every name-like run of text in a file, lower case (an effect file lists its effects, a bank its sounds)."""
    return {m.group().decode().lower() for m in re.finditer(rb'[A-Za-z][A-Za-z0-9_]{3,63}', Path(path).read_bytes())}


def animation_stems(fighter, path_list):
    """Animation file stems for a fighter from the archive path list
    (``Hashes_FullPath`` from ultimate-research/archive-hashes)."""
    prefix = f'fighter/{fighter}/motion/'
    stems = set()
    with open(path_list, encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith(prefix):
                line = line.strip()
                if line.endswith('.nuanmb'):
                    stems.add(line.rsplit('/', 1)[1][:-len('.nuanmb')])
    return stems


def fighter_param_names():
    return [n for n in (Path(__file__).parent / 'fighter_param_names.txt').read_text('utf-8').split() if n]


def candidates(fighter, path_list=None, extra=()):
    names = set(BONES) | set(EFFECTS) | set(extra)
    names |= {kind + s for s in EXTRA_SCRIPTS for kind in SCRIPT_KINDS}
    names |= {f'fighter_kind_{fighter}', 'fighter_param_table', 'fighter_kind'}
    names |= {f'seq_{fighter}_rnd_{w}' for w in SEQUENCE_WORDS}
    names |= set(fighter_param_names())
    if path_list and Path(path_list).exists():
        trail = f'effect/fighter/{fighter}/trail/'
        with open(path_list, encoding='utf-8', errors='replace') as f:      # a sword trail names its textures
            names |= {line.strip()[len(trail):-len('.nutexb')] for line in f
                      if line.startswith(trail) and line.strip().endswith('.nutexb')}
        for stem in animation_stems(fighter, path_list):
            names.add(stem + '.nuanmb')
            for kind in SCRIPT_KINDS:
                names.add(kind + stem[3:])
    return names
