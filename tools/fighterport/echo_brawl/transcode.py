"""A Brawl fighter's skeleton and animations written out as the files the port driver reads (the formats Ultimate
keeps a skeleton and a clip in), laid out as the driver expects a fighter's folder:

    <root>/gamedata/fighter/<fighter>/model/body/c00/model.nusktb
    <root>/gamedata/fighter/<fighter>/motion/body/c00/<stem>.nuanmb

Bones the driver knows by name take the names it knows them by (Brawl's and Ultimate's skeletons are one lineage:
HipN is Hip, LShoulderJ is ShoulderL); the rest keep their own. A clip's stem is the one the driver's clip table
has for that action where it has one.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import arc, brres
from .gamedata import JOINED, JOINS, find

NAMES = {'TopN': 'Top', 'TransN': 'Trans', 'XRotN': 'RotX', 'YRotN': 'Rot', 'HipN': 'Hip', 'WaistN': 'Waist', 'BustN': 'Bust',
         'NeckN': 'Neck', 'HeadN': 'Head', 'ThrowN': 'Throw', 'LShoulderN': 'ClavicleL', 'RShoulderN': 'ClavicleR',
         'LShoulderJ': 'ShoulderL', 'RShoulderJ': 'ShoulderR', 'LArmJ': 'ArmL', 'RArmJ': 'ArmR', 'LHandN': 'HandL', 'RHandN': 'HandR',
         'LLegJ': 'LegL', 'RLegJ': 'LegR', 'LKneeJ': 'KneeL', 'RKneeJ': 'KneeR', 'LFootJ': 'FootL', 'RFootJ': 'FootR',
         'LToeN': 'ToeL', 'RToeN': 'ToeR', 'LHaveN': 'HaveL', 'RHaveN': 'HaveR', 'SwordN': 'Sword1'}
# Brawl's name for an action -> the name the driver's clip table has it under, where they differ
ALIASES = {'RunBrake': 'runbraker', 'CliffAttackQuick': 'cliffattack', 'CliffClimbQuick': 'cliffclimb',
           'CliffEscapeQuick': 'cliffescape', 'CliffJumpQuick1': 'cliffjump1', 'CliffJumpQuick2': 'cliffjump2',
           'AppealS': 'appeallwr', 'SpecialHi2': 'specialhi', 'SpecialAirHi2': 'specialairhi'}


def ultimate_name(name):
    return NAMES.get(name, name)


def quaternion(rotation):
    """(x, y, z, w) of a rotation given as degrees about x, then y, then z."""
    x, y, z = (math.radians(v) / 2 for v in rotation)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return [sx * cy * cz - cx * sy * sz, cx * sy * cz + sx * cy * sz, cx * cy * sz - sx * sy * cz, cx * cy * cz + sx * sy * sz]


def motion_file(root, fighter):
    """The BRRES that holds the fighter's animations, and {clip name: offset}."""
    folder, stem = find(root, fighter)
    _, groups = arc.read((folder / f'{stem}MotionEtc.pac').read_bytes())
    data = next(x['data'] for g in groups for x in arc.read(g['data'])[1] if x['data'][:4] == b'bres')
    return data, brres.folders(data)['AnmChr(NW4R)']


def skeleton(root, fighter):
    folder, stem = find(root, fighter)
    body = arc.read((folder / f'{stem}00.pac').read_bytes())[1][0]['data']
    return brres.bones(body, next(iter(brres.folders(body)['3DModels(NW4R)'].values())))[0]


def write(root, fighter, ssbh, table_stems=None):
    """Write the skeleton and every clip. `ssbh`: the ssbh_data_py module; `table_stems`: {name without its three-letter
    prefix: stem} from the driver's clip table. -> ({Brawl clip name: stem}, {Brawl clip name: frames})"""
    root = Path(root)
    bones = skeleton(root, fighter)
    out = root / 'gamedata' / 'fighter' / fighter
    (out / 'model' / 'body' / 'c00').mkdir(parents=True, exist_ok=True)
    (out / 'motion' / 'body' / 'c00').mkdir(parents=True, exist_ok=True)
    skel = ssbh.skel_data.SkelData()
    made = []
    for b in bones:
        rows = brres.matrix(b['scale'], b['rotation'], b['translation'])
        import numpy as np
        made.append(ssbh.skel_data.BoneData(ultimate_name(b['name']),
                                            np.array([[rows[r][c] for r in range(4)] for c in range(4)], dtype=np.float32),
                                            b['parent']))
    skel.bones = made
    skel.save(str(out / 'model' / 'body' / 'c00' / 'model.nusktb'))
    rest = {b['name']: b for b in bones}
    data, clips = motion_file(root, fighter)
    read = {name: brres.animation(data, at) for name, at in clips.items()}
    table_stems = table_stems or {}
    stems, lengths = {}, {name: a['frames'] for name, a in read.items()}

    def track(name, parts):
        """A bone's values over the clips in `parts`, one after another."""
        values = []
        for k, a in enumerate(parts):
            entry = a['bones'].get(name) or {}
            for f in range(a['frames'] - (1 if k + 1 < len(parts) else 0)):     # a clip hands over on its last frame
                s = entry['scale'][f] if entry.get('scale') else rest[name]['scale']
                r = entry['rotation'][f] if entry.get('rotation') else rest[name]['rotation']
                t = entry['translation'][f] if entry.get('translation') else rest[name]['translation']
                values.append(ssbh.anim_data.Transform([float(v) for v in s], quaternion(r), [float(v) for v in t]))
        return values

    for name, a in read.items():
        if name in JOINED:
            continue                                    # a wind-up: written as the front of the clip it leads into
        parts = [read[b] for b in JOINS.get(name, []) if b in read] + [a]
        animated = [n for n in rest if any(n in p['bones'] for p in parts)]
        anim = ssbh.anim_data.AnimData()
        anim.final_frame_index = float(sum(p['frames'] for p in parts) - len(parts))
        group = ssbh.anim_data.GroupData(ssbh.anim_data.GroupType.Transform)
        group.nodes = [ssbh.anim_data.NodeData(ultimate_name(n), [ssbh.anim_data.TrackData('Transform', values=track(n, parts))])
                       for n in animated]
        anim.groups = [group]
        low = ALIASES.get(name, name.lower())
        stem = table_stems.get(low, 'z00' + low)
        stems[name] = stem
        anim.save(str(out / 'motion' / 'body' / 'c00' / f'{stem}.nuanmb'))
    return stems, lengths
