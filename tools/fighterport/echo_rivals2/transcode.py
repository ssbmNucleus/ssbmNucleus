"""A Rivals 2 fighter written out as the files the port reads a fighter from (Ultimate's shapes), at a root of the
port's own (the game's folder is never written):

    <root>/gamedata/fighter/<fighter>/model/body/c0N/  model.nusktb .numshb .numdlb .numatb, pictures .nutexb
    <root>/gamedata/fighter/<fighter>/motion/body/c00/<stem>.nuanmb
    <root>/gamedata/fighter/<fighter>/rivals2.json     what has no such file: units, stems, lengths, bones

Where the game keeps them (Unreal 5; `uetool` reads the pak): the skeleton and body are one skeletal mesh
(`Skins/Default/SK_<short>_Default`: 143 bones with the sockets, 5 materials), the clips are `Animation/**/AN_<short>_*`
(an AnimSequence each, 60 frames a second, a key on every frame from 0 to its length), all on the skeleton
`SK_<short>_Standard`. They are exported as ActorX (`actorx.py`).

The axes. Unreal's fighter stands Z up and faces +X with his left side at +Y; the port's (Ultimate's) stands Y up
and faces +Z with his left at +X. The same turn of hand (up x ahead = left in both), so it is a turn, not a mirror:
port = A @ unreal, A taking (x, y, z) to (y, z, x). Lengths are centimetres; the port's are Ultimate's units, which
the route's drawn scale (0.97 on Marth) takes to Melee's. MELEE_PER_CM is the one number that says how big he is.

The skeleton. `Group` (the actor's origin) becomes `Trans` and `DeformationSystem` `Rot`, as an Ultimate skeleton
starts; `Root_M` (the pelvis) is the `Hip`. The bones the route binds by name are renamed (NAMES); the rest keep their
own. The game's sockets (`*Socket`: places the game's code hangs things on) are left out but for the item socket in
the right hand (`HaveR`) and the left wrist's (`HaveL`). `Grab_M` (where a grabbed fighter is held, the game's
GrabOffset ahead of him on the floor at rest) becomes `Throw`: the route hangs the held fighter AND the shield from
it, and Melee scales that joint to the shield's size every frame, so outside the clips in which he holds someone it
stands at the middle of his height (THROW_MIDDLE), with nothing under it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import actorx

# STAND-IN: how big he is. Rivals 2 gives every length in centimetres; Zetterburn's collision box is 170 tall. 0.1
# Melee unit a centimetre makes him 17 tall (Marth's joints span 19.1 drawn) and puts his movement numbers in the
# span of Melee's own (dash 2.0, run 1.8, gravity 0.14, fall 2.8: Fox's fall is 2.8, Marth's run 1.8). No fighter is
# in both games to measure it on.
MELEE_PER_CM = 0.1
A = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]])
SMALLEST = 1e-4

NAMES = {'Group': 'Trans', 'DeformationSystem': 'Rot', 'Root_M': 'Hip', 'Spine1_M': 'Waist', 'Chest_M': 'Bust',
         'Neck_M': 'Neck', 'Head_M': 'Head', 'Grab_M': 'Throw', 'ItemSocket': 'HaveR', 'Wrist_LSocket': 'HaveL'}
for _s in ('L', 'R'):
    NAMES.update({f'Scapula_{_s}': f'Clavicle{_s}', f'Shoulder_{_s}': f'Shoulder{_s}', f'Elbow_{_s}': f'Arm{_s}',
                  f'Wrist_{_s}': f'Hand{_s}', f'Hip_{_s}': f'Leg{_s}', f'Knee_{_s}': f'Knee{_s}',
                  f'Ankle_{_s}': f'Foot{_s}', f'Toes_{_s}': f'Toe{_s}'})
    for _d, _finger in enumerate(('Thumb', 'Index', 'Middle', 'Ring', 'Pinky'), 1):
        for _j in (1, 2, 3):
            NAMES[f'{_finger}Finger{_j}_{_s}'] = f'Finger{_s}{_d}{_j}'
KEEP_SOCKETS = ('ItemSocket', 'Wrist_LSocket')
THROW = 'Throw'
THROW_MIDDLE = 0.5              # of his height, where the shield is centred (STAND-IN: the game's shield is a mesh of its own)

# The clips under the stems the route knows (as echo_slapcity's table), by the game's clip name after `AN_<short>_`.
# Several stems: the same clip for each. A clip not here is written as z00<name>.
STEMS = {
    'Idle': ['a00wait1'], 'Idle_Fidget_1': ['a00wait2'], 'Item_Idle': ['a00waititem'],
    'Walk': ['a01walkslow', 'a01walkmiddle', 'a01walkfast'], 'Walk_Turn': ['a01turn'],
    'Run': ['a02run'], 'Dash': ['a02dash'], 'Run_Stop': ['a02runbrakel'], 'Run_Turn': ['a02turnrun'],
    'Crouch_Start': ['a05squat'], 'Crouch': ['a05squatwait'], 'Crouch_Stand': ['a05squatrv'],
    'Item_Crouch': ['a05squatwaititem'],
    'JumpSquat': ['a03kneebend'], 'Jump': ['a03jumpf'], 'Jump_Backward': ['a03jumpb'],
    'DJump': ['a03jumpaerialf'], 'DJump_Backward': ['a03jumpaerialb'],
    'Fall': ['a04fall', 'a04fallf', 'a04fallb', 'a04fallaerial', 'a04fallaerialf', 'a04fallaerialb'],
    'Tumble': ['a04damagefall', 'a04fallspecial', 'a04fallspecialf', 'a04fallspecialb'],
    'Land': ['a05landingheavy'],
    'Landing_Lag': ['c05landingairn', 'c05landingairf', 'c05landingairb', 'c05landingairhi', 'c05landingairlw',
                    'a05landingfallspecial'],
    'Shield_Start': ['b00guardon'], 'Shield': ['b00guard'], 'Shield_Release': ['b00guardoff'],
    'Shield_Stun': ['b01guarddamage'],
    'Spot_Dodge': ['b02escapen'], 'Roll_Forward': ['b02escapef'], 'Roll_Backward': ['b02escapeb'],
    'AirDodge': ['b02escapeair'], 'Parry_Stun': ['b02rebound'],
    'Jab': ['c00attack11', 'c00attack12', 'c00attack13'], 'Ftilt': ['c02attacks3s', 'c02attacks3hi', 'c02attacks3lw'],
    'Dash_Attack': ['c00attackdash'], 'UTilt': ['c02attackhi3'], 'DTilt': ['c02attacklw3'],
    'FStrong': ['c03attacks4s'], 'UStrong': ['c04attackhi4'], 'DStrong': ['c04attacklw4'],
    'NAir': ['c05attackairn'], 'FAir': ['c05attackairf'], 'BAir': ['c05attackairb'], 'UAir': ['c05attackairhi'],
    'DAir': ['c05attackairlw'],
    'NSpecial': ['d00specialn'], 'NSpecialAir': ['d00specialairn'],
    'FSpecial': ['d01specials'], 'FSpecialAir': ['d01specialairs'],
    'USpecial': ['d02specialhi', 'd02specialairhi'],
    'DSpecial': ['d03speciallw'], 'DSpecialAir': ['d03specialairlw'],
    'Grab': ['e00catch'], 'Dash_Grab': ['e00catchdash'], 'Pivot_Grab': ['e00catchturn'], 'Pummel': ['e00catchattack'],
    'FThrow': ['e01throwf'], 'BThrow': ['e01throwb'], 'UThrow': ['e01throwhi'], 'DThrow': ['e01throwlw'],
    'Grabbed': ['e02capturewaithi', 'e03capturewaitlw'], 'Grabbed_Hurt': ['e02capturedamagehi', 'e03capturedamagelw'],
    'Grabbed_Escape': ['e03capturecut'], 'Grabbed_Escape_Jump': ['e03capturejump'],
    'Pulled_Forward': ['e02capturepulledhi', 'e03capturepulledlw'],
    'Flinch_Light': ['f00damagen1', 'f00damagehi1', 'f00damagelw1', 'f01damageair1'],
    'Flinch_Heavy': ['f00damagen2', 'f00damagen3', 'f00damagehi2', 'f00damagehi3', 'f00damagelw2', 'f00damagelw3',
                     'f01damageair2', 'f01damageair3'],
    'Hitstun_Medium': ['f01damageflyn'], 'Hitstun_Heavy': ['f01damageflyroll'], 'Hitstun_Up': ['f01damageflyhi'],
    'Hitstun_Down': ['f01damageflylw'], 'Hitstun_Light': ['f01damageflytop'],
    'Knockdown_Start': ['f03downboundu', 'f04downboundd'], 'Knockdown': ['f03downwaitu', 'f04downwaitd'],
    'Knockdown_Hurt': ['f03downdamageu', 'f04downdamaged'],
    'Getup_Roll_Forward': ['f03downforwardu', 'f04downforwardd'], 'Getup_Roll_Backward': ['f03downbacku', 'f04downbackd'],
    'Neutral_Getup': ['f03downstandu', 'f04downstandd'], 'Getup_Attack': ['f03downattacku', 'f04downattackd'],
    'Tech_Ground': ['f05passive'], 'Tech_Roll_Forward': ['f05passivestandf'], 'Tech_Roll_Backward': ['f05passivestandb'],
    'Wall_Tech': ['f05passivewall'], 'Ceiling_Tech': ['f05passiveceil'], 'WallJump': ['f05passivewalljump'],
    'Shield_Break': ['f06furafura'], 'Wall_Bounce': ['g00walldamage'], 'Teeter': ['g00ottottowait'],
    'TeeterStart': ['g00ottotto'], 'PlatDrop': ['g00pass'],
    'Ledge_Grab': ['g01cliffcatch'], 'Ledge_Hang': ['g01cliffwait'], 'Ledge_Attack': ['g02cliffattack'],
    'Ledge_Stand': ['g02cliffclimb'], 'Ledge_Roll': ['g02cliffescape'], 'Ledge_Jump_Start': ['g02cliffjump1'],
    'Ledge_Jump': ['g02cliffjump2'],
    'Item_Pickup': ['h00lightget', 'h03heavyget'], 'Item_Throw_Forward': ['h01lightthrowf', 'h03heavythrowf'],
    'Item_Throw_Up': ['h01lightthrowhi', 'h03heavythrowhi'], 'Item_Throw_Down': ['h01lightthrowlw', 'h03heavythrowlw'],
    'Item_Throw_Dash': ['h01lightthrowdash'], 'Item_Toss': ['h01lightthrowdrop', 'h01lightthrowb', 'h03heavythrowb'],
    'Item_Throw_Air_Forward': ['h02lightthrowairf', 'h02lightthrowairb'], 'Item_Throw_Air_Up': ['h02lightthrowairhi'],
    'Item_Throw_Air_Down': ['h02lightthrowairlw'],
    'Intro': ['j00entryr'], 'Taunt_Default': ['j01appeallwr'], 'Taunt_Flexing': ['j01appealsr'],
    'Victory': ['j02win1', 'j02win2', 'j02win3'], 'CSS_Default': ['j02win1wait'],
}
# The clips the game plays IN PLACE while its code moves him (a roll, a getup or tech roll, the ledge roll and climb):
# Melee's states for them follow the clip's root, so each is given root travel here. {clip: (the character data's
# speed for it, which way)}. STAND-IN: the game's code holds that speed for a stretch it does not write down; it is
# held here over the clip's middle third (a roll then goes about Melee's own distance, 35 units).
TRAVEL = {'Roll_Forward': ('RollSpeed', 1), 'Roll_Backward': ('RollSpeed', -1),
          'Tech_Roll_Forward': ('TechRollSpeed', 1), 'Tech_Roll_Backward': ('TechRollSpeed', -1),
          'Getup_Roll_Forward': ('GetupRollSpeed', 1), 'Getup_Roll_Backward': ('GetupRollSpeed', -1),
          'Ledge_Roll': ('LedgeRollSpeed', 1), 'Ledge_Stand': ('LedgeStandSpeed', 1)}


def travel_of(frames, speed):
    """How far ahead (cm) the origin has gone on each of a clip's frames: `speed` a frame over its middle third."""
    a, b = frames // 3, max(frames // 3 + 1, (2 * frames) // 3)
    steps = np.array([speed if a <= f < b else 0.0 for f in range(frames)])
    return np.concatenate([[0.0], np.cumsum(steps)[:-1]])


def give_travel(clip, name, speeds):
    """Root travel on an in-place clip of TRAVEL (its `Group` track moved ahead in Unreal's X). -> cm, or None."""
    if name not in TRAVEL or TRAVEL[name][0] not in speeds:
        return None
    k = next((i for i, b in enumerate(clip.bones) if b['name'] == 'Group'), None)
    if k is None:
        return None
    word, way = TRAVEL[name]
    d = travel_of(clip.frames, float(speeds[word])) * way
    clip.t[:, k, 0] += d
    return float(d[-1])


# the clips in which he holds someone: the Throw joint follows Grab_M there
HOLDING = ('Grab', 'Dash_Grab', 'Pivot_Grab', 'Pummel', 'Special_Pummel', 'FThrow', 'BThrow', 'UThrow', 'DThrow')


def quat_matrix(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def quaternion(m):
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


def trs(t, q, s=(1.0, 1.0, 1.0)):
    m = np.eye(4)
    m[:3, :3] = quat_matrix(q) * np.asarray(s, float)
    m[:3, 3] = t
    return m


def ported(m, unit):
    """A 4x4 of Unreal's (in cm) in the port's space and units."""
    out = np.eye(4)
    out[:3, :3] = A @ m[:3, :3] @ A.T
    out[:3, 3] = A @ m[:3, 3] * unit
    return out


def point(p, unit):
    return A @ np.asarray(p, float) * unit


class Skeleton:
    """The body's bones as the port's skeleton (from the body's own .psk, which carries the sockets)."""

    def __init__(self, mesh: actorx.Mesh, unit):
        self.unit = unit
        bones = mesh.bones
        names = [b['name'] for b in bones]
        self.source = names
        keep = [i for i, n in enumerate(names) if not n.endswith('Socket') or n in KEEP_SOCKETS]
        keep = [i for i in keep if not names[i].endswith('Socket') or names[i] in KEEP_SOCKETS]
        self.kept = keep
        self.joint_of = {names[i]: NAMES.get(names[i], names[i]) for i in keep}
        self.names = [self.joint_of[names[i]] for i in keep]
        self.parent = {}
        for i in keep:
            p = bones[i]['parent']
            self.parent[self.joint_of[names[i]]] = None if p is None else self.joint_of[names[p]]
        self.rest_local = {self.joint_of[names[i]]: (bones[i]['t'], bones[i]['q'], np.ones(3)) for i in keep}
        self.height = None
        self.rest = self.worlds(self.rest_local)

    def worlds(self, local, holding=False):
        """{joint: 4x4 in Unreal's space} from {joint: (t, q, s)} (the Throw joint placed as the module head says)."""
        out = {}
        for j in self.names:
            t, q, s = local[j]
            m = trs(t, q, np.where(np.abs(s) < SMALLEST, SMALLEST, s))
            out[j] = m if self.parent[j] is None else out[self.parent[j]] @ m
        if not holding and self.height:
            m = np.eye(4)
            m[:3, 3] = out['Trans'][:3, 3] + [0.0, 0.0, self.height * THROW_MIDDLE]
            out[THROW] = m
        return out

    def port_locals(self, worlds):
        """{joint: 4x4 local in the port's space} from Unreal worlds."""
        pw = {j: ported(m, self.unit) for j, m in worlds.items()}
        return {j: (np.linalg.inv(pw[self.parent[j]]) @ pw[j]) if self.parent[j] else pw[j] for j in self.names}


def decompose(m):
    s = np.linalg.norm(m[:3, :3], axis=0)
    s = np.where(s < SMALLEST, SMALLEST, s)
    return m[:3, 3].copy(), quaternion(m[:3, :3] / s), s


def write_skeleton(sk, ssbh, path):
    skel = ssbh.skel_data.SkelData()
    loc = sk.port_locals(sk.rest)
    index = {j: k for k, j in enumerate(sk.names)}
    skel.bones = [ssbh.skel_data.BoneData(j, np.ascontiguousarray(loc[j].T, dtype=np.float32),
                                          None if sk.parent[j] is None else index[sk.parent[j]]) for j in sk.names]
    skel.save(str(path))


def clip_locals(sk, clip: actorx.Clip, frame):
    """{joint: (t, q, s)} of a clip's frame, the rest where the clip has no track."""
    local = dict(sk.rest_local)
    for k, b in enumerate(clip.bones):
        j = sk.joint_of.get(b['name'])
        if j is None:
            continue
        s = clip.scale[frame, k] if clip.scale is not None else np.ones(3)
        local[j] = (clip.t[frame, k], clip.q[frame, k], s)
    return local


def write_clip(sk, ssbh, clip: actorx.Clip, paths, holding=False):
    """One clip, every joint on every frame. -> its last frame."""
    last = clip.frames - 1
    frames = [sk.port_locals(sk.worlds(clip_locals(sk, clip, f), holding=holding)) for f in range(clip.frames)]
    anim = ssbh.anim_data.AnimData()
    anim.final_frame_index = float(max(last, 1))
    group = ssbh.anim_data.GroupData(ssbh.anim_data.GroupType.Transform)
    nodes = []
    for j in sk.names:
        values = []
        for loc in frames:
            t, q, s = decompose(loc[j])
            values.append(ssbh.anim_data.Transform([float(x) for x in s], [float(x) for x in q], [float(x) for x in t]))
        if len(values) == 1:
            values.append(values[0])
        nodes.append(ssbh.anim_data.NodeData(j, [ssbh.anim_data.TrackData('Transform', values=values)]))
    group.nodes = nodes
    anim.groups = [group]
    for p in paths:
        anim.save(str(p))
    return last


# ---- the skin --------------------------------------------------------------------------------------------------------
def body(mesh: actorx.Mesh, sk: Skeleton):
    """The mesh at rest in the port's space: (positions per wedge, normals, uvs, {wedge: [(joint, weight)]},
    {material index: triangles (wedge indices)}). The psk's own wedge is a vertex here. The winding is turned where
    the faces' own turn disagrees with the normals (checked, not assumed)."""
    unit = sk.unit
    pts = np.array([point(p, unit) for p in mesh.points])
    wp = np.array([w[0] for w in mesh.wedges])
    pos = pts[wp]
    uv = np.array([[w[1], w[2]] for w in mesh.wedges], float)
    nor = (A @ mesh.normals.T).T if mesh.normals is not None else np.zeros_like(pos)
    nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-12)
    by_point = {}
    names = mesh.bones
    for p, b, w in mesh.weights:
        if w <= 0:
            continue
        j = sk.joint_of.get(names[b]['name'])
        if j is None:
            raise ValueError(f'point {p} is skinned to {names[b]["name"]}, which is not kept')
        row = by_point.setdefault(p, {})
        row[j] = row.get(j, 0.0) + w
    links = []
    for p in wp:
        row = by_point.get(int(p), {'Hip': 1.0})
        total = sum(row.values())
        links.append(sorted((j, w / total) for j, w in row.items()))
    faces = mesh.faces.copy()
    a, b, c = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    fn = np.cross(b - a, c - a)
    agree = np.einsum('ij,ij->i', fn, nor[faces].mean(axis=1))
    flipped = bool((agree < 0).sum() > (agree > 0).sum())
    if flipped:
        faces = faces[:, ::-1]
    tris = {m: faces[mesh.face_material == m] for m in sorted(set(mesh.face_material.tolist()))}
    return pos, nor, uv, links, tris, flipped


def write_model(sk, ssbh, mesh, pictures, out, slot_names):
    """One costume's body: numshb (a mesh object per material, named by its slot), numdlb, numatb and a nutexb per
    material. `pictures`: {material index: PIL picture}. -> rows saying what each part is."""
    from echo_ultimate import nutexb
    out.mkdir(parents=True, exist_ok=True)
    pos, nor, uv, links, tris, _flipped = body(mesh, sk)
    meshd, modl, matl = ssbh.mesh_data.MeshData(), ssbh.modl_data.ModlData(), ssbh.matl_data.MatlData()
    modl.model_name, modl.skeleton_file_name, modl.material_file_names = 'model', 'model.nusktb', ['model.numatb']
    modl.mesh_file_name = 'model.numshb'
    rows, objects, entries, mats = [], [], [], []
    for k, tri in tris.items():
        label = slot_names[k] if k < len(slot_names) else f'material{k}'
        used = np.unique(tri)
        remap = -np.ones(len(pos), int)
        remap[used] = np.arange(len(used))
        o = ssbh.mesh_data.MeshObjectData(f'{label}Shape', 0)
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
        name = f'{label.lower()}_col'
        nutexb.write(out / f'{name}.nutexb', pictures[k], name)
        e = ssbh.matl_data.MatlEntryData(label, 'SFX_PBS_0100000008008269_opaque')
        e.textures = [ssbh.matl_data.TextureParam(ssbh.matl_data.ParamId.Texture0, name)]
        mats.append(e)
        entries.append(ssbh.modl_data.ModlEntryData(o.name, 0, label))
        rows.append(dict(part=o.name, triangles=int(len(tri)), vertices=int(len(used)), picture=name))
    meshd.objects, modl.entries, matl.entries = objects, entries, mats
    meshd.save(str(out / 'model.numshb'))
    modl.save(str(out / 'model.numdlb'))
    matl.save(str(out / 'model.numatb'))
    return rows


def write(fighter, root, ssbh, files, costumes, log=print):
    """Everything: the skeleton, each costume's body and every clip. `files`: the exported .psk and .psa files
    ({'body': path, 'clips': {clip name after AN_<short>_: path}}); `costumes`: [(costume name, {material index:
    picture})] (palettes.py). -> the summary written to rivals2.json."""
    from fighter_port import own_data
    drawn = own_data.default_scale(own_data.DONOR['Marth'])
    unit = MELEE_PER_CM / drawn
    out = Path(root) / 'gamedata' / 'fighter' / fighter
    motion = out / 'motion' / 'body' / 'c00'
    motion.mkdir(parents=True, exist_ok=True)
    mesh = actorx.Mesh(files['body'])
    sk = Skeleton(mesh, unit)
    pos, _n, _uv, _l, _t, flipped = body(mesh, sk)
    sk.height = float(pos[:, 1].max()) / unit           # in cm
    sk.rest = sk.worlds(sk.rest_local)
    slot_names = files['slots']
    rows_all = []
    for k, (name, pictures) in enumerate(costumes):
        folder = out / 'model' / 'body' / f'c{k:02d}'
        folder.mkdir(parents=True, exist_ok=True)
        write_skeleton(sk, ssbh, folder / 'model.nusktb')
        rows = write_model(sk, ssbh, mesh, pictures, folder, slot_names)
        rows_all.append(dict(costume=f'c{k:02d}', palette=name, parts=rows))
        log(f'  c{k:02d}: {name}, {sum(r["triangles"] for r in rows)} triangles')
    stems, lengths, travelled = {}, {}, {}
    for name, path in sorted(files['clips'].items()):
        clip = actorx.Clip(path)
        went = give_travel(clip, name, files.get('speeds') or {})
        if went is not None:
            travelled[name] = round(went * MELEE_PER_CM, 2)
        names = STEMS.get(name, ['z00' + name.replace('_', '').lower()])
        lengths[name] = write_clip(sk, ssbh, clip, [motion / f'{s}.nuanmb' for s in names], holding=name in HOLDING)
        stems[name] = names
    summary = dict(game='rivals2', fighter=fighter, unit=unit, melee_per_cm=MELEE_PER_CM, drawn=drawn,
                   height_cm=sk.height, winding_turned=flipped, joints=sk.names, parent=sk.parent,
                   bones=sk.joint_of, stems=stems, lengths=lengths, costumes=rows_all, travel=travelled,
                   material_bakes=files.get('material_bakes', []))
    log(f'  root travel given to in-place clips (Melee units, STAND-IN: the speed over the middle third): {travelled}')
    (out / 'rivals2.json').write_text(json.dumps(summary, indent=1), 'utf-8')
    return summary, sk
