"""A Slap City fighter written out as the files the port reads a fighter from (the shapes Ultimate keeps them in),
laid out as the route expects a fighter's folder, at a root of the port's own (the game's folder is never
written):

    <root>/gamedata/fighter/<fighter>/model/body/c0N/  model.nusktb .numshb .numdlb .numatb, pictures .nutexb
    <root>/gamedata/fighter/<fighter>/motion/body/c00/<stem>.nuanmb
    <root>/gamedata/fighter/<fighter>/slapcity.json    what has no such file: units, stems, lengths, bones

The axes. Slap City's fighter faces +Z in its model node's space with +Y up, in Unity's left-handed axes; the
port's (Ultimate's) face +Z with +Y up, right-handed. Mirroring X turns one into the other and keeps her left
hand her left (in both, +X is the side her left hand is on, seen from behind). The Armature's scale (about 45.6)
is taken off every joint and the lengths are put in the port's units by UNIT.

The skeleton. `root` (at the floor, the bone that travels in a roll) becomes `Trans`, with `Rot` under it, as an
Ultimate skeleton starts; `superbody` is the `Hip`. The bones the route binds by name are renamed (NAMES); the rest
keep their own. The game's effect holders (`zzzFX`, `SmashChargeFX` ...) and the `_end` tips no clip, skin or
script uses are left out. One bone is added, as every Ultimate skeleton has it: `Throw` (see THROW).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .fighter import Fighter, curves, length, sample, trs, worlds

# Ittle Dew's height in the port's own units (the drawn scale takes them to Melee's: 12.4 x 0.97 is about 12, Young
# Link's size). STAND-IN: Slap City's units are not Ultimate's, and the route's drawn scale assumes they are.
HEIGHT = 12.4
# ONE unit for the whole game (port units per Slap City unit), set by her: 12.4 over her height at rest in the game's
# units (2.6323). Until 2026-11-13 every fighter was made 12.4 tall, so a second fighter came out Ittle Dew's size
# and his speeds (game units a second, times the same unit) shrank with him: Fishbunjin, 4.86 game units tall, was
# drawn as tall as she is and moved at 0.62 of his speed. The roster keeps its own proportions now.
UNIT = HEIGHT / 2.6323025431380094
# What a fighter's prefab puts ABOVE the clip holder scales his body (Fishbunjin's `pos` node: 1.15; Ittle Dew's 1)
# and everything on his bones with it, but not his speeds (they move the prefab's root). `Skeleton.unit` (lengths on
# the body: the model, bone offsets) has it; `UNIT` (speeds, a hit's radius, an offset in the world's axes) has not
# (READING: a hit's radius is taken as the world's; the game's code that sizes it was not read).
NAMES = {'superbody': 'Hip', 'body': 'Bust', 'head': 'Head',
         'l_arm1': 'ShoulderL', 'l_arm2': 'ArmL', 'l_fist': 'HandL', 'r_arm1': 'ShoulderR', 'r_arm2': 'ArmR',
         'r_fist': 'HandR', 'l_leg1': 'LegL', 'l_leg2': 'KneeL', 'l_foot': 'FootL', 'l_foot_end': 'ToeL',
         'r_leg1': 'LegR', 'r_leg2': 'KneeR', 'r_foot': 'FootR', 'r_foot_end': 'ToeR'}
# The first two fighters have fists named l_fist/r_fist; most of the roster does not.
# Fill missing landmarks from the game's semantic bone references, keeping the existing mappings when present
# (Fishbunjin has both a hand and a fist; Ittle's "head" shortcut points at midhead, not the head joint).
LANDMARK_SHORTCUTS = {
    'Hip': ('superbody', 'hips'), 'Bust': ('body',), 'Head': ('head',),
    'ShoulderL': ('l_shoulder', 'shoulder_l'), 'ShoulderR': ('r_shoulder', 'shoulder_r'),
    'ArmL': ('l_elbow', 'elbow_l', 'arm_l'), 'ArmR': ('r_elbow', 'elbow_r', 'arm_r'),
    'HandL': ('l_hand', 'hand_l', 'l_fist', 'fist_l'), 'HandR': ('r_hand', 'hand_r', 'r_fist', 'fist_r'),
    'LegL': ('l_hip', 'hip_l', 'l_leg1', 'leg_l', 'l_leg'),
    'LegR': ('r_hip', 'hip_r', 'r_leg1', 'leg_r', 'r_leg'),
    'KneeL': ('l_knee', 'knee_l', 'l_leg2', 'leg2_l'), 'KneeR': ('r_knee', 'knee_r', 'r_leg2', 'leg2_r'),
    'FootL': ('l_heel', 'heel_l', 'l_foot', 'foot_l'), 'FootR': ('r_heel', 'heel_r', 'r_foot', 'foot_r'),
    'ToeL': ('l_toe', 'toe_l'), 'ToeR': ('r_toe', 'toe_r'),
}
TRAVEL = 'root'                 # the bone that becomes Trans
SMALLEST = 1e-4                 # the least size a joint is given (the game hides a part at 0)
# Ultimate's skeletons all have a `Throw` bone under `Trans` that no skin uses; the route binds it as the joint a
# held fighter hangs from, and Melee hangs the SHIELD from the same joint (it scales that joint to the shield's
# size each frame: `ftCo_Guard.c:ftCo_80091D58`). Slap City has none: without it the route took the nearest joint
# above in the donor's tree, the engine's YRot, and her whole body grew with her shield. So the reader writes one:
# at the middle of her height (the shield's centre: STAND-IN, Slap City's shield is drawn by its own code), and in
# grab/throw clips at the source character's explicit grabPoint transform.
THROW = 'Throw'
THROW_MIDDLE = 0.5              # of her height
HOLDING = ('e00catch', 'e01throw')      # the stems of the clips in which she holds someone
HOLD_HAND = 'HandR'                     # legacy fallback only when the source has no grabPoint
C = np.diag([-1.0, 1.0, 1.0, 1.0])

# The clips under the stems the route's clip table knows (oneshot.motion_table), or under the donor's action name
# where it has none (`own_bank.default_jobs` matches a clip to an action by name). Several stems: the same clip
# for each. A clip not here is written as z00<name>.
STEMS = {
    'idle': ['a00wait1'], 'walk': ['a01walkslow', 'a01walkmiddle', 'a01walkfast'], 'run': ['a02run'],
    'dash': ['a02dash'], 'turn': ['a01turn'],
    'crouchbegin': ['a05squat'], 'crouchidle': ['a05squatwait'], 'crouchend': ['a05squatrv'],
    'kneebend': ['a03kneebend'], 'jump': ['a03jumpf', 'a03jumpb'],
    'doublejump': ['a03jumpaerialf', 'a03jumpaerialb'],
    'fall': ['a04fall', 'a04fallf', 'a04fallb', 'a04fallaerial', 'a04fallaerialf', 'a04fallaerialb'],
    'tumble': ['a04damagefall', 'a04fallspecial', 'a04fallspecialf', 'a04fallspecialb'],
    'easyland': ['a05landingheavy'],
    'hardland': ['c05landingairn', 'c05landingairf', 'c05landingairb', 'c05landingairhi', 'c05landingairlw',
                 'a05landingfallspecial'],
    'shieldup': ['b00guardon'], 'shieldhold': ['b00guard'], 'shieldrelease': ['b00guardoff'],
    'spotdodge': ['b02escapen'], 'rollforward': ['b02escapef'], 'rollback': ['b02escapeb'],
    'airdodge': ['b02escapeair'], 'rebound': ['b02rebound'],
    'jab': ['c00attack11'], 'secondjab': ['c00attack12'], 'thirdjab': ['c00attack13'],
    'ftilt': ['c02attacks3s', 'c00attackdash'], 'utilt': ['c02attackhi3'], 'dtilt': ['c02attacklw3'],
    'fsmash': ['c03attacks4s'], 'usmash': ['c04attackhi4'], 'dsmash': ['c04attacklw4'],
    'nair': ['c05attackairn'], 'fair': ['c05attackairf'], 'bair': ['c05attackairb'], 'uair': ['c05attackairhi'],
    'dair': ['c05attackairlw'],
    'specialneutral': ['d00specialn'], 'specialneutralair': ['d00specialairn'],
    'specialforward': ['d01specials'], 'specialforwardair': ['d01specialairs'],
    'specialup': ['d02specialhi'], 'specialupair': ['d02specialairhi'],
    'specialdown': ['d03speciallw', 'd03specialairlw'], 'specialdownimpact': ['d03speciallwimpact'],
    # (the same, as other fighters name a special's ground clip: Fishbunjin's `specialneutralground` ...; until
    # 2026-11-13 they went out as z00 clips and no special had a clip on its stem)
    'specialneutralground': ['d00specialn'], 'specialforwardground': ['d01specials'],
    'specialupground': ['d02specialhi'], 'specialdownground': ['d03speciallw'], 'specialdownair': ['d03specialairlw'],
    'grab': ['e00catch', 'e00catchdash'], 'grabbegin': ['e00catchpull'], 'grabhold': ['e00catchwait'],
    'grabpummel': ['e00catchattack'], 'grabrebound': ['e00catchcut'],
    'throwforward': ['e01throwf'], 'throwback': ['e01throwb'], 'throwup': ['e01throwhi'], 'throwdown': ['e01throwlw'],
    'grabflinch': ['e02capturedamagehi', 'e03capturedamagelw'], 'grabstruggle': ['e02capturewaithi', 'e03capturewaitlw'],
    'flinch': ['f00damagen1', 'f00damagen2', 'f00damagen3', 'f00damagehi1', 'f00damagehi2', 'f00damagehi3',
               'f00damagelw1', 'f00damagelw2', 'f00damagelw3', 'f01damageair1', 'f01damageair2', 'f01damageair3'],
    'fly': ['f01damageflyhi', 'f01damageflyn', 'f01damageflylw', 'f01damageflytop', 'f01damageflyroll'],
    'flop': ['f03downboundu', 'f04downboundd'], 'down': ['f03downwaitu', 'f04downwaitd'],
    'flinchdown': ['f03downdamageu', 'f04downdamaged'],
    'getupforward': ['f03downforwardu', 'f04downforwardd'], 'getupback': ['f03downbacku', 'f04downbackd'],
    'getupinplace': ['f03downstandu', 'f04downstandd'], 'getupattack': ['f03downattacku', 'f04downattackd'],
    'techland': ['f05passive'], 'techrollforward': ['f05passivestandf'], 'techrollback': ['f05passivestandb'],
    'techwall': ['f05passivewall'], 'techceiling': ['f05passiveceil'],
    'shieldbreakdizzy': ['f06furafura'],
    'edgegrab': ['g01cliffcatch'], 'edgehold': ['g01cliffwait'], 'edgeattack': ['g02cliffattack'],
    'edgeclimbup': ['g02cliffclimb'], 'edgeroll': ['g02cliffescape'],
    'entrance': ['j00entryr', 'j00entryl'], 'taunt': ['j01appeallwr', 'j01appeallwl', 'j01appealsr', 'j01appealsl',
                                                     'j01appealhir', 'j01appealhil'],
    'winner': ['j02win1', 'j02win2', 'j02win3'], 'loser': ['j02lose'],
}


# ---- matrices -------------------------------------------------------------------------------------------------------
def quaternion(m):
    """(x, y, z, w) of a 3x3 rotation."""
    t = np.trace(m)
    if t > 0:
        s = 2.0 * np.sqrt(t + 1.0)
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    q = np.array(q)
    return q / np.linalg.norm(q)


def decompose(m):
    """4x4 -> (translation, rotation (x, y, z, w), scale); a scale is the length of each axis."""
    s = np.linalg.norm(m[:3, :3], axis=0)
    return m[:3, 3].copy(), quaternion(m[:3, :3] / s), s


def scale_above(nodes, holder):
    """The size the prefab's nodes above the clip holder give it (their scales' product; a uniform scale is
    assumed, and the x axis's is taken)."""
    s, i = 1.0, nodes[holder]['parent']
    while i is not None:
        s *= float(abs(nodes[i]['s'][0]))
        i = nodes[i]['parent']
    return s


def armature_of(nodes, holder, skin_bones):
    """The node holding the body's bones: the child of the clip holder that the skin's bones are under. Not found by
    its name: Ittle Dew's is `Armature`, Fishbunjin's `Armature.001`, and his dizzy stars hold `Armature`s of their
    own under other nodes."""
    def chain(i):
        while i is not None:
            yield i
            i = nodes[i]['parent']
    tops = {next((j for j in chain(b) if nodes[j]['parent'] == holder), None) for b in skin_bones}
    tops.discard(None)
    if len(tops) != 1:
        raise ValueError(f"the skin's bones hang from {len(tops)} children of {nodes[holder]['name']}, not one")
    return tops.pop()


def landmark_names(bones, shortcuts):
    """{source bone: port joint}; only kept bones may supply a missing landmark.

    A reference may name a helper or an effect outside the skeleton. Never rename such a node, or take a bone
    already serving another landmark. Conflicting references need a reading of the fighter, not a guess.
    """
    out = {name: NAMES.get(name, name) for name in bones}
    for joint, aliases in LANDMARK_SHORTCUTS.items():
        if joint in out.values():
            continue
        candidates = list(dict.fromkeys(shortcuts[a] for a in aliases if a in shortcuts
                                        and shortcuts[a] in out and out[shortcuts[a]] == shortcuts[a]
                                        and out[shortcuts[a]] not in LANDMARK_SHORTCUTS))
        if len(candidates) > 1:
            raise ValueError(f'{joint}: conflicting bone shortcuts {candidates}; resolve the landmark in the reader')
        if candidates:
            out[candidates[0]] = joint
    # A body without a separate pelvis still needs the engine's body-root binding.
    # Use the source's semantic body joint (Ruby); do not invent arms or legs.
    if 'Hip' not in out.values():
        body = shortcuts.get('body')
        if body in out and out[body] == 'Bust':
            out[body] = 'Hip'
    return out


class Skeleton:
    """The fighter's bones as the port's skeleton, and the way from the game's poses to the port's."""

    def __init__(self, f: Fighter):
        self.f = f
        nodes = self.nodes = f.nodes()
        self.holder, self.clips = f.animation()
        smr = f.skinned()
        self.skin_bones = [f.node_of(b.path_id) for b in smr.m_Bones]
        self.armature = armature_of(nodes, self.holder, self.skin_bones)
        self.path_index = {f.path(i, self.holder): i for i in range(len(nodes)) if self._under(i, self.holder)}
        animated = {self.path_index[p] for clip in self.clips.values() for p in curves(clip) if p in self.path_index}
        named = {i for i, n in enumerate(nodes) if n['name'] in set(f.shortcuts().values())}
        self.collision_nodes = f.collision_points()
        named.update(self.collision_nodes)
        grab_node = f.grab_point()
        if grab_node is not None:
            if not self._under(grab_node, self.armature):
                raise ValueError(f'{f.name}: grabPoint is outside the body armature')
            named.add(grab_node)
        effects = {i for i, n in enumerate(nodes) if set(n['kinds']) - {'Transform'} and self._under(i, self.armature)}
        wanted = {i for i in set(self.skin_bones) | animated | named
                  if self._under(i, self.armature) and i != self.armature
                  and not any(self._under(i, e) for e in effects)}
        self.kept = [i for i in range(len(nodes)) if i in wanted]           # parents first (the walk's order)
        self.travel = next(i for i in self.kept if nodes[i]['name'] == TRAVEL)
        rest = worlds(nodes, self.holder, self.kept)
        self.arm = abs(np.linalg.det(rest[self.armature][:3, :3])) ** (1 / 3)
        renamed = landmark_names([nodes[i]['name'] for i in self.kept if i != self.travel], f.shortcuts())
        self.grab_joint = renamed.get(nodes[grab_node]['name']) if grab_node is not None else None
        if self.grab_joint is None:
            self.grab_joint = HOLD_HAND if HOLD_HAND in renamed.values() else None
        if self.grab_joint is None:
            raise ValueError(f'{f.name}: no source grabPoint or hand for grab clips')
        self.names = ['Trans', 'Rot'] + [renamed[nodes[i]['name']] for i in self.kept if i != self.travel]
        self.joint_of = {i: renamed[nodes[i]['name']] for i in self.kept if i != self.travel}
        self.joint_of[self.travel] = 'Trans'
        self.unit = 1.0
        self.measured = self.height()                   # in the game's units (the holder's: before the scale above)
        self.above = scale_above(nodes, self.holder)
        self.unit = UNIT * self.above
        self.world_unit = UNIT
        self.tall = self.measured * self.unit           # his height at rest in the port's units
        self.parent = {'Trans': None, 'Rot': 'Trans'}
        for i in self.kept:
            if i == self.travel:
                continue
            up = nodes[i]['parent']
            while up not in set(self.kept) and up is not None:
                up = nodes[up]['parent']
            self.parent[self.joint_of[i]] = 'Rot' if up == self.travel else self.joint_of[up]
        self.synthetic_hold = 'HandR' not in self.names and 'HandL' not in self.names
        if self.synthetic_hold:
            # Melee has items even when the source has no hands. Reuse its explicit grab attachment.
            self.names.append('Have')
            self.parent['Have'] = self.grab_joint
        self.names.append(THROW)
        self.parent[THROW] = 'Trans'
        self.rest_travel = (C @ rest[self.travel] @ C)[:3, 3] * self.unit
        self.rest = self.joint_worlds(rest)

    def _under(self, i, top):
        while i is not None:
            if i == top:
                return True
            i = self.nodes[i]['parent']
        return False

    def joint_worlds(self, w, hold=False):
        """{joint: 4x4 in the port's space} from {node: 4x4 in the model node's space}. `hold`: a clip in which
        she holds someone (the Throw joint at her grabbing hand, else at her middle)."""
        out = {}
        for i in self.kept:
            m = C @ w[i] @ C
            m[:3, :3] /= self.arm
            m[:3, 3] *= self.unit
            out[self.joint_of[i]] = m
        trans = np.eye(4)
        trans[:3, 3] = out['Trans'][:3, 3] - getattr(self, 'rest_travel', out['Trans'][:3, 3])
        out['Trans'] = out['Rot'] = trans
        throw = np.eye(4)
        throw[:3, 3] = out[self.grab_joint][:3, 3] if hold else trans[:3, 3] + [0.0, getattr(self, 'tall', HEIGHT) * THROW_MIDDLE, 0.0]
        out[THROW] = throw
        if getattr(self, 'synthetic_hold', False):
            out['Have'] = out[self.grab_joint].copy()
        return out

    def locals(self, joint_world):
        return {j: np.linalg.inv(joint_world[self.parent[j]]) @ joint_world[j] if self.parent[j] else joint_world[j]
                for j in self.names}

    def pose(self, clip, frame):
        """{node: 4x4 in the model node's space} at a clip's frame."""
        local = {}
        rate = clip.m_SampleRate or 60.0
        for path, ch in curves(clip).items():
            i = self.path_index.get(path)
            if i is None:
                continue
            n = self.nodes[i]
            t = sample(ch['t'], frame / rate) if 't' in ch else n['t']
            q = sample(ch['q'], frame / rate, rotation=True) if 'q' in ch else n['q']
            s = sample(ch['s'], frame / rate) if 's' in ch else n['s']
            # (a part hidden by a size of nothing is kept just above nothing: a joint under it must still be
            # placed from it)
            s = np.where(np.abs(s) < SMALLEST, SMALLEST, s)
            local[i] = trs(t, q, s)
        return worlds(self.nodes, self.holder, self.kept, local)

    def hidden(self, clip='idle'):
        """The joints the standing clip hides on its first frame (the game hides a held thing by making it small:
        the raft, the oar, the chest stand out of the rest pose)."""
        w = self.joint_worlds(self.pose(self.clips[clip], 0))
        return {j for j, m in w.items() if np.linalg.norm(m[:3, 0]) < 0.5}

    def height(self):
        """The body's height at rest, in the port's units: the top of the skin above the floor, of the parts the
        standing clip shows."""
        pos, _n, _uv, links, _t = skinned_rest(self, self.f.skinned().m_Mesh.read())
        hidden = self.hidden()
        shown = [k for k, l in enumerate(links) if max(l, key=lambda x: x[1])[0] not in hidden]
        return float(pos[shown, 1].max())


# ---- the skin -------------------------------------------------------------------------------------------------------
def matrix(m):
    return np.array([[getattr(m, f'e{r}{c}') for c in range(4)] for r in range(4)], float)


def handler(mesh):
    from .unity import unitypy
    unitypy()
    from UnityPy.helpers.MeshHelper import MeshHandler
    h = MeshHandler(mesh)
    h.process()
    return h


def skin_influences(h, vertex_count, bone_count):
    """Read explicit weights or Unity's single-index, implicit-unit-weight skin layout.

    Unity SkinWeights.OneBone stores only bone indices, with weight 1:
    https://docs.unity.com/en-us/engine/6000.7/script-reference/unityengine/skinweights/onebone
    Multi-influence data without weights is incomplete, not an excuse to guess a binding.
    """
    idx = np.asarray(h.m_BoneIndices, int)
    if idx.ndim != 2 or idx.shape[0] != vertex_count or idx.shape[1] == 0:
        raise ValueError('mesh bone indices do not match its vertices')
    if h.m_BoneWeights is None:
        if idx.shape[1] != 1:
            raise ValueError('multi-influence mesh has no bone weights')
        wts = np.ones(idx.shape, float)
    else:
        wts = np.asarray(h.m_BoneWeights, float)
    if wts.shape != idx.shape or not np.isfinite(wts).all() or (wts < 0).any():
        raise ValueError('mesh bone weights are malformed')
    if (wts.sum(axis=1) <= 0).any():
        raise ValueError('mesh has a vertex without a positive skin weight')
    used = idx[wts > 0]
    if (used < 0).any() or (used >= bone_count).any():
        raise ValueError('mesh uses a bone index outside its renderer')
    return idx, wts


def skinned_rest(sk: Skeleton, mesh):
    """The mesh at the prefab's rest, in the port's space: (positions, normals, uvs (top-left V), {vertex: [(joint,
    weight)]}, [triangles of each submesh])."""
    h = handler(mesh)
    rest = worlds(sk.nodes, sk.holder, sk.kept)
    binds = [matrix(b) for b in mesh.m_BindPose]
    if len(binds) != len(sk.skin_bones):
        raise ValueError(f'{mesh.m_Name}: {len(binds)} bind poses for {len(sk.skin_bones)} bones')
    skin = [rest[b] @ bp for b, bp in zip(sk.skin_bones, binds)]
    v = np.asarray(h.m_Vertices, float)
    n = np.asarray(h.m_Normals, float)
    idx, wts = skin_influences(h, len(v), len(skin))
    pos, nor, links = np.zeros_like(v), np.zeros_like(n), []
    for k in range(len(v)):
        total = wts[k].sum()
        row = {}
        for b, w in zip(idx[k], wts[k]):
            if w <= 0:
                continue
            w = w / total
            m = skin[b]
            pos[k] += w * (m[:3, :3] @ v[k] + m[:3, 3])
            nor[k] += w * (np.linalg.inv(m[:3, :3]).T @ n[k])
            joint = sk.joint_of.get(sk.skin_bones[b])
            if joint is None:
                raise ValueError(f'vertex {k} is skinned to {sk.nodes[sk.skin_bones[b]]["name"]}, which is not kept')
            row[joint] = row.get(joint, 0.0) + w
        links.append(sorted(row.items()))
    pos = (pos * [-1, 1, 1]) * sk.unit
    nor = nor * [-1, 1, 1]
    nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-12)
    uv = np.asarray(h.m_UV0, float)[:, :2].copy()
    uv[:, 1] = 1.0 - uv[:, 1]
    tris = [np.asarray(t, int)[:, ::-1] for t in h.get_triangles()]      # the mirror turns the winding
    return pos, nor, uv, links, tris


# ---- writing --------------------------------------------------------------------------------------------------------
def write_skeleton(sk, ssbh, path):
    skel = ssbh.skel_data.SkelData()
    loc = sk.locals(sk.rest)
    index = {j: k for k, j in enumerate(sk.names)}
    skel.bones = [ssbh.skel_data.BoneData(j, np.ascontiguousarray(loc[j].T, dtype=np.float32),
                                          None if sk.parent[j] is None else index[sk.parent[j]]) for j in sk.names]
    skel.save(str(path))


def write_clip(sk, ssbh, clip, paths):
    """One clip, every kept joint on every frame. -> its last frame."""
    last = length(clip)
    hold = any(Path(p).stem.startswith(HOLDING) for p in paths)
    frames = [sk.locals(sk.joint_worlds(sk.pose(clip, f), hold=hold)) for f in range(last + 1)]
    anim = ssbh.anim_data.AnimData()
    anim.final_frame_index = float(last)
    group = ssbh.anim_data.GroupData(ssbh.anim_data.GroupType.Transform)
    nodes = []
    for j in sk.names:
        values = []
        for loc in frames:
            t, q, s = decompose(loc[j])
            values.append(ssbh.anim_data.Transform([float(x) for x in s], [float(x) for x in q], [float(x) for x in t]))
        track = ssbh.anim_data.TrackData('Transform', values=values)
        nodes.append(ssbh.anim_data.NodeData(j, [track]))
    group.nodes = nodes
    anim.groups = [group]
    for p in paths:
        anim.save(str(p))
    return last


def flat_picture(color, size=8):
    from PIL import Image
    return Image.new('RGBA', (size, size), tuple(int(round(max(0.0, min(1.0, c)) * 255)) for c in color))


def material_picture(material, atlas):
    """The picture a material is drawn with here, and how it was chosen. The toon shader's colours come from its
    ramp picture, which the body's UVs index as a palette; a material with neither ramp nor picture is its colour."""
    texs = {name: te.m_Texture for name, te in material.m_SavedProperties.m_TexEnvs}
    for key in ('_RampTex', '_MainTex'):
        ref = texs.get(key)
        if ref is not None and ref.path_id:
            t = ref.read()
            if t.m_Name != 'white':
                return t.image.convert('RGBA'), f'{key} {t.m_Name}'
    if atlas is not None and any(texs.get(k) is not None and texs[k].path_id for k in ('_RimRamp', '_SpecularRamp')):
        return atlas, 'the body ramp (its UVs point into it; its own ramps are a rim light: STAND-IN)'
    colors = dict(material.m_SavedProperties.m_Colors)
    c = colors.get('_Color')
    return flat_picture((c.r, c.g, c.b, c.a) if c else (1, 1, 1, 1)), 'its _Color, flat (no picture)'


def write_model(sk, ssbh, mesh, materials, main_picture, out):
    """One costume's body: numshb (a mesh object per submesh, named by its material), numdlb, numatb and a nutexb
    per material. -> rows saying what each part is drawn with."""
    from echo_ultimate import nutexb
    out.mkdir(parents=True, exist_ok=True)
    pos, nor, uv, links, tris = skinned_rest(sk, mesh)
    meshd = ssbh.mesh_data.MeshData()
    modl = ssbh.modl_data.ModlData()
    matl = ssbh.matl_data.MatlData()
    modl.model_name, modl.skeleton_file_name, modl.material_file_names = 'model', 'model.nusktb', ['model.numatb']
    modl.mesh_file_name = 'model.numshb'
    rows, objects, entries, mats = [], [], [], []
    atlas = main_picture
    for k, tri in enumerate(tris):
        if k >= len(materials):
            break
        mat = materials[k].read()
        used = np.unique(tri)
        remap = -np.ones(len(pos), int)
        remap[used] = np.arange(len(used))
        o = ssbh.mesh_data.MeshObjectData(f'{mat.m_Name}Shape', 0)
        o.positions = [ssbh.mesh_data.AttributeData('Position0', np.ascontiguousarray(pos[used], np.float32))]
        o.normals = [ssbh.mesh_data.AttributeData('Normal0', np.ascontiguousarray(nor[used], np.float32))]
        o.texture_coordinates = [ssbh.mesh_data.AttributeData('map1', np.ascontiguousarray(uv[used], np.float32))]
        o.vertex_indices = np.ascontiguousarray(remap[tri].reshape(-1), np.uint32)
        by_joint = {}
        for new, old in enumerate(used):
            for joint, w in links[old]:
                by_joint.setdefault(joint, []).append(ssbh.mesh_data.VertexWeight(int(new), float(w)))
        o.bone_influences = [ssbh.mesh_data.BoneInfluence(j, ws) for j, ws in sorted(by_joint.items())]
        objects.append(o)
        label = mat.m_Name
        picture, how = (main_picture, 'the suit\'s main picture') if k == 0 and main_picture is not None \
            else material_picture(mat, atlas)
        name = f'{label.lower()}_col'
        nutexb.write(out / f'{name}.nutexb', picture, name)
        e = ssbh.matl_data.MatlEntryData(label, 'SFX_PBS_0100000008008269_opaque')
        e.textures = [ssbh.matl_data.TextureParam(ssbh.matl_data.ParamId.Texture0, name)]
        mats.append(e)
        entries.append(ssbh.modl_data.ModlEntryData(o.name, 0, label))
        rows.append(dict(part=o.name, triangles=int(len(tri)), vertices=int(len(used)), picture=name, drawn_with=how))
    meshd.objects = objects
    modl.entries = entries
    matl.entries = mats
    meshd.save(str(out / 'model.numshb'))
    modl.save(str(out / 'model.numdlb'))
    matl.save(str(out / 'model.numatb'))
    return rows


def node_worlds(f, top):
    """[(GameObject, 4x4 in the space of transform `top`)] of every node under `top` (itself first), parents first."""
    out = []

    def walk(tr, above):
        p, q, s = tr.m_LocalPosition, tr.m_LocalRotation, tr.m_LocalScale
        m = above @ trs([p.x, p.y, p.z], [q.x, q.y, q.z, q.w], [s.x, s.y, s.z]) if out else np.eye(4)
        out.append((tr.m_GameObject.read(), m))
        for ch in tr.m_Children:
            walk(ch.read(), m)
    walk(top, np.eye(4))
    return out


def plain_mesh(mesh, m, unit):
    """A mesh that no bones move, placed by `m` (4x4) and in the port's space: (positions, normals, uvs, triangles of
    each submesh), as `skinned_rest` gives a body's."""
    h = handler(mesh)
    v = np.asarray(h.m_Vertices, float)
    n = np.asarray(h.m_Normals, float) if h.m_Normals is not None and len(h.m_Normals) else np.zeros_like(v)
    pos = (np.c_[v, np.ones(len(v))] @ m.T)[:, :3] * [-1, 1, 1] * unit
    nor = (n @ np.linalg.inv(m[:3, :3])) * [-1, 1, 1]
    nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-12)
    uv = np.asarray(h.m_UV0, float)[:, :2].copy() if h.m_UV0 is not None and len(h.m_UV0) else np.zeros((len(v), 2))
    uv[:, 1] = 1.0 - uv[:, 1]
    return pos, nor, uv, [np.asarray(t, int)[:, ::-1] for t in h.get_triangles()]


def write_article(ssbh, f, art_id, behaviour, unit, out):
    """An article's model as Ultimate keeps one (`model/<id>/c00`: one joint, a mesh per material, each with its
    picture), from the meshes its prefab draws (a `MeshFilter`, not particles), placed as they stand about the
    article's own point. -> rows saying what each part is drawn with, or [] when it draws no mesh."""
    from echo_ultimate import nutexb
    go = behaviour.read().m_GameObject.read()
    top = next(c.read() for c in f.components(go, 'Transform'))
    rows, objects, entries, mats = [], [], [], []
    for node, m in node_worlds(f, top):
        filters = f.components(node, 'MeshFilter')
        renderers = f.components(node, 'MeshRenderer')
        if not filters or not renderers:
            continue
        mesh = filters[0].read().m_Mesh.read()
        pos, nor, uv, tris = plain_mesh(mesh, m, unit)
        for k, (tri, mref) in enumerate(zip(tris, renderers[0].read().m_Materials)):
            mat = mref.read()
            used = np.unique(tri)
            remap = -np.ones(len(pos), int)
            remap[used] = np.arange(len(used))
            # (two parts drawn with one material, as the dumbbell's two weights are, are two objects of one name: each
            # its own subindex, and the material written once)
            sub = sum(1 for x in objects if x.name == f'{mat.m_Name}Shape')
            o = ssbh.mesh_data.MeshObjectData(f'{mat.m_Name}Shape', sub)
            o.parent_bone_name = 'Trans'
            o.positions = [ssbh.mesh_data.AttributeData('Position0', np.ascontiguousarray(pos[used], np.float32))]
            o.normals = [ssbh.mesh_data.AttributeData('Normal0', np.ascontiguousarray(nor[used], np.float32))]
            o.texture_coordinates = [ssbh.mesh_data.AttributeData('map1', np.ascontiguousarray(uv[used], np.float32))]
            o.vertex_indices = np.ascontiguousarray(remap[tri].reshape(-1), np.uint32)
            picture, how = material_picture(mat, None)
            name = f'{mat.m_Name.lower()}_col'
            out.mkdir(parents=True, exist_ok=True)
            nutexb.write(out / f'{name}.nutexb', picture, name)
            e = ssbh.matl_data.MatlEntryData(mat.m_Name, 'SFX_PBS_0100000008008269_opaque')
            e.textures = [ssbh.matl_data.TextureParam(ssbh.matl_data.ParamId.Texture0, name)]
            objects.append(o)
            if not any(x.material_label == mat.m_Name for x in mats):
                mats.append(e)
            entries.append(ssbh.modl_data.ModlEntryData(o.name, sub, mat.m_Name))
            rows.append(dict(part=o.name, node=node.m_Name, mesh=mesh.m_Name, triangles=int(len(tri)), vertices=int(len(used)),
                             picture=name, drawn_with=how))
    if not objects:
        return []
    skel = ssbh.skel_data.SkelData()
    skel.bones = [ssbh.skel_data.BoneData('Trans', np.eye(4, dtype=np.float32), None)]
    skel.save(str(out / 'model.nusktb'))
    meshd, modl, matl = ssbh.mesh_data.MeshData(), ssbh.modl_data.ModlData(), ssbh.matl_data.MatlData()
    modl.model_name, modl.skeleton_file_name, modl.material_file_names = 'model', 'model.nusktb', ['model.numatb']
    modl.mesh_file_name = 'model.numshb'
    meshd.objects, modl.entries, matl.entries = objects, entries, mats
    meshd.save(str(out / 'model.numshb'))
    modl.save(str(out / 'model.numdlb'))
    matl.save(str(out / 'model.numatb'))
    return rows


def call_pictures(f, game, unit, out):
    """The flat pictures a custom call's object is drawn with (a `Quad` with a picture: Ittle Dew's teleport ball):
    {object field: {'picture': its file under `out`, 'size': [width, height], 'at': [x, y] of its middle above the
    object's own point, in the port's units}}. Particles under it are not read."""
    rows = {}

    def walk(tr):
        go = tr.m_GameObject.read()
        for c in f.components(go, 'MonoBehaviour'):
            name = game.script(c)
            if not (name.endswith('CC') or name.endswith('CustomCall')):
                continue
            d = game.mono(c)
            for key, ref in d.items():
                if not (isinstance(ref, dict) and set(ref) == {'m_FileID', 'm_PathID'} and ref['m_PathID']):
                    continue
                obj = game.deref(c.assets_file, ref)
                if obj is None or obj.type.name != 'Transform':
                    continue
                for node, m in node_worlds(f, obj.read()):
                    if node.m_Name != 'Quad' or not f.components(node, 'MeshRenderer'):
                        continue
                    mat = f.components(node, 'MeshRenderer')[0].read().m_Materials[0].read()
                    texs = {k: te.m_Texture for k, te in mat.m_SavedProperties.m_TexEnvs}
                    tex = texs.get('_MainTex')
                    if tex is None or not tex.path_id:
                        continue
                    t = tex.read()
                    out.mkdir(parents=True, exist_ok=True)
                    path = out / f'{name.lower()}_{key.lower()}.png'
                    t.image.convert('RGBA').save(path)
                    colour = dict(mat.m_SavedProperties.m_Colors).get('_Color') or dict(mat.m_SavedProperties.m_Colors).get('_TintColor')
                    rows[f'{name}.{key}'] = {'picture': path.name, 'texture': t.m_Name,
                                             'size': [float(np.linalg.norm(m[:3, 0])) * unit, float(np.linalg.norm(m[:3, 1])) * unit],
                                             'at': [float(-m[0, 3]) * unit, float(m[1, 3]) * unit],
                                             'colour': [colour.r, colour.g, colour.b, colour.a] if colour is not None else None}
        for ch in tr.m_Children:
            walk(ch.read())
    walk(next(c.read() for c in f.components(f.prefab, 'Transform')))
    return rows


def clip_stems(clips, moveset, inputs):
    """Map actual source entry clips to control slots and jab follow-ups.

    A dormant zero-weight clip is not a competing entry (Tetron's side special). Conditional
    choices or two active clips still need their own reading. Existing separate air clips win.
    """
    from .gamedata import ALSO, events, move_table, starting_clip
    out = {name: list(STEMS.get(name, ['z00' + name.replace('_', '')])) for name in clips}
    used = {stem for stems in out.values() for stem in stems}
    for move, stems in move_table(inputs, moveset).items():
        clip = starting_clip(events(moveset.get(move, {})))
        if clip not in out:
            continue
        for stem in stems:
            for alias in [stem] + ALSO.get(stem, []):
                if alias not in used:
                    out[clip].append(alias)
                    used.add(alias)
    return out


def write(game, fighter_name, root, ssbh, fighter=None, log=print):
    """Everything: the skeleton, each suit's body and every clip. -> the summary written to slapcity.json."""
    f = Fighter(game, fighter_name)
    sk = Skeleton(f)
    out = Path(root) / 'gamedata' / 'fighter' / (fighter or fighter_name)
    motion = out / 'motion' / 'body' / 'c00'
    motion.mkdir(parents=True, exist_ok=True)
    smr = f.skinned()
    skin = next(iter(f.skins().values()))
    default = f.skins().get('default', skin)
    costumes = []
    for k in range(int(default['suits'])):
        folder = out / 'model' / 'body' / f'c{k:02d}'
        folder.mkdir(parents=True, exist_ok=True)
        write_skeleton(sk, ssbh, folder / 'model.nusktb')
        mesh = f.ref(default['meshes'][k]).read() if k < len(default['meshes']) else smr.m_Mesh.read()
        main = None
        for swap in default['swapTextures']:
            if swap['textureId'] == 'main' and k < len(swap['textures']):
                main = f.ref(swap['textures'][k]).read().image.convert('RGBA')
        rows = write_model(sk, ssbh, mesh, list(smr.m_Materials), main, folder)
        costumes.append(dict(costume=f'c{k:02d}', mesh=mesh.m_Name, parts=rows))
        log(f'  c{k:02d}: {mesh.m_Name}, {sum(r["triangles"] for r in rows)} triangles')
    # the articles that draw a model (Ittle Dew's bomb), each as its own model folder; and the pictures of what her
    # custom calls draw (the teleport's ball)
    articles = {}
    for bank in f.articles().values():
        for art_id, behaviour in bank.items():
            if behaviour is None or behaviour.type.name != 'MonoBehaviour':
                continue
            rows = write_article(ssbh, f, art_id, behaviour, sk.unit, out / 'model' / art_id / 'c00')
            if rows:
                articles[art_id] = {'folder': art_id, 'parts': rows}
                log(f'  article {art_id}: {sum(r["triangles"] for r in rows)} triangles')
    pictures = call_pictures(f, game, sk.unit, out / 'pictures')
    stems = clip_stems(sk.clips, f.moveset(), f.character.get('standardSCinputTrigger') or {})
    lengths = {}
    for name, clip in sorted(sk.clips.items()):
        names = stems[name]
        lengths[name] = write_clip(sk, ssbh, clip, [motion / f'{s}.nuanmb' for s in names])
    summary = dict(game='slapcity', fighter=fighter_name, data_dir=str(game.dir), unit=sk.unit, world_unit=sk.world_unit,
                   scale_above=sk.above, armature_scale=sk.arm, height=sk.tall, height_in_game_units=sk.measured,
                   joints=sk.names, parent=sk.parent, grab_joint=sk.grab_joint,
                   item_hold_adaptation='Have at source grabPoint' if sk.synthetic_hold else None,
                   collision_joints=[sk.joint_of[i] for i in sk.collision_nodes],
                   bones={sk.nodes[i]['name']: sk.joint_of[i] for i in sk.kept},
                   shortcuts={k: sk.joint_of.get(next((i for i in sk.kept if sk.nodes[i]['name'] == v), -1))
                              for k, v in f.shortcuts().items()},
                   stems=stems, lengths=lengths, costumes=costumes, articles=articles, call_pictures=pictures)
    (out / 'slapcity.json').write_text(json.dumps(summary, indent=1), 'utf-8')
    return summary, sk, f
