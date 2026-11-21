"""A Slap City fighter as the game keeps it: one prefab (`smash/characters/<name>/<name>` in the Resources
container) whose root holds the `SmashCharacter` component, and beside it the moveset (a TextAsset of JSON), the
attack properties (`AtkPropBank`), the articles (`SmashArticleBank`), the skins (`CharacterSkin`) and the sounds.

The prefab's bones: `<root>/pos/rotate/<model>` holds the legacy `Animation` (its clips name bones by path from
there: `Armature/root/superbody/...`), the `Armature` (scaled by about 45.6), and the `SkinnedMeshRenderer`. The
fighter faces +Z in the model node's space, +Y up, in Unity's left-handed axes.

What the moveset calls a bone is a SHORTCUT (`useBones.shortcuts` on SmashCharacter): `l_foot` is the bone
`l_foot_end`, `r_elbow` is `r_arm2`.
"""
from __future__ import annotations

import json

import numpy as np

from .unity import Game


def quat_matrix(q):
    """3x3 of a unit quaternion (x, y, z, w)."""
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def trs(t, q, s):
    """4x4 (column vectors) of a Unity local transform."""
    m = np.eye(4)
    m[:3, :3] = quat_matrix(q) * np.asarray(s, float)
    m[:3, 3] = t
    return m


class Fighter:
    def __init__(self, game: Game, name: str):
        self.game, self.name = game, name
        prefix = f'smash/characters/{name}/'
        self.assets = {k[len(prefix):]: v for k, v in game.container().items() if k.startswith(prefix)}
        if name not in self.assets:
            raise KeyError(f'the game has no fighter {name!r} (its Resources hold no {prefix}{name})')
        self.prefab = self.assets[name].read()
        self.file = self.assets[name].assets_file
        self.character = next(self.game.mono(c) for c in self.components(self.prefab, 'MonoBehaviour')
                              if self.game.script(c) == 'SmashCharacter')
        self._nodes = None

    # ---- the prefab
    def components(self, go, kind=None):
        out = []
        for c in go.m_Components:
            obj = c.deref()
            if kind is None or obj.type.name == kind:
                out.append(obj)
        return out

    def ref(self, pptr, owner=None):
        return self.game.deref(owner or self.file, pptr)

    def nodes(self):
        """Every transform under the prefab, parents first: [{'name', 'id' (path id), 'parent' (index or None),
        't', 'q' (x, y, z, w), 's', 'kinds' (component type names)}]."""
        if self._nodes is None:
            out = []

            def walk(tr, parent):
                go = tr.m_GameObject.read()
                p, q, s = tr.m_LocalPosition, tr.m_LocalRotation, tr.m_LocalScale
                out.append(dict(name=go.m_Name, id=tr.object_reader.path_id, parent=parent,
                                t=[p.x, p.y, p.z], q=[q.x, q.y, q.z, q.w], s=[s.x, s.y, s.z],
                                kinds=[c.type.name for c in self.components(go)]))
                me = len(out) - 1
                for ch in tr.m_Children:
                    walk(ch.read(), me)
            walk(next(c.read() for c in self.components(self.prefab, 'Transform')), None)
            self._nodes = out
        return self._nodes

    def node_of(self, path_id):
        return next(i for i, n in enumerate(self.nodes()) if n['id'] == path_id)

    def path(self, index, base):
        """A node's path from node `base` (as an animation clip names it)."""
        parts, nodes = [], self.nodes()
        while index is not None and index != base:
            parts.append(nodes[index]['name'])
            index = nodes[index]['parent']
        return '/'.join(reversed(parts))

    def shortcuts(self):
        """{shortcut id: the bone's node name}."""
        out = {}
        for row in self.character['useBones']['shortcuts']:
            obj = self.ref(row['bone'])
            if obj is not None:
                out[row['id']] = obj.read().m_GameObject.read().m_Name
        return out

    def collision_points(self):
        """Nodes the source's TopNSizer measures, including non-anatomical helper points."""
        return [self.node_of(self.ref(ref).path_id) for ref in self.character.get('sizeBones') or []
                if ref and ref.get('m_PathID')]

    def grab_point(self):
        """Node the source attaches a grabbed fighter to; it need not be a hand."""
        ref = self.character.get('grabPoint')
        obj = self.ref(ref) if ref and ref.get('m_PathID') else None
        return self.node_of(obj.path_id) if obj is not None else None

    # ---- the game's numbers and scripts
    def moveset(self):
        """{move id: move}, from the moveset TextAsset (JSON: {uid: {'uid', 'gruid', 'id', 'move'}})."""
        text = self.ref(self.character['movesetfile']).read().m_Script
        raw = json.loads(text if isinstance(text, str) else text.decode('utf-8', 'replace'))
        return {m['id']: m['move'] for m in raw.values()}

    def props(self):
        """{prop id: {dmg, angle, basekb, kbgain, ...}} from the fighter's AtkPropBank."""
        bank = self.game.mono(self.ref(self.character['propbank']))
        return {row['id']: row['prop'] for row in bank['props']}

    def articles(self):
        """{bank id: {article id: its prefab GameObject}}."""
        out = {}
        for b in self.character['articlebankbank']['banks']:
            bank = self.game.mono(self.ref(b['bank']))
            out[b['id']] = {row['id']: self.ref(row['art']) for row in bank['arts']}
        return out

    def sound_bank(self):
        """The fighter's sound bank's fields (`SmashSFXBank`)."""
        return self.game.mono(self.ref(self.character['sfxbank']))

    def base(self):
        return dict(self.character['baseconfig'])

    # ---- the model
    def animation(self):
        """(the node index holding the Animation, {clip name: AnimationClip})."""
        anim = self.ref(self.character['characterAnim']).read()
        holder = self.node_of(next(c for c in self.components(anim.m_GameObject.read(), 'Transform')).path_id)
        clips = {}
        for c in anim.m_Animations:
            clip = c.read()
            clips[clip.m_Name] = clip
        return holder, clips

    def skinned(self):
        """The main SkinnedMeshRenderer (SmashCharacter.mainMesh), read."""
        return self.ref(self.character['mainMesh']).read()

    def skins(self):
        """{skin id: CharacterSkin fields} from the fighter's `skins/` folder."""
        out = {}
        for key, obj in sorted(self.assets.items()):
            if key.startswith('skins/'):
                go = obj.read()
                for c in self.components(go, 'MonoBehaviour'):
                    if self.game.script(c) == 'CharacterSkin':
                        d = self.game.mono(c)
                        out[d['skinId']] = d
        return out


# ---- poses ----------------------------------------------------------------------------------------------------------
def curves(clip):
    """{path: {'q': [(time, (x, y, z, w))], 't': [(time, (x, y, z))], 's': [...]}} of a legacy clip."""
    out = {}
    for kind, rows in (('q', clip.m_RotationCurves), ('t', clip.m_PositionCurves), ('s', clip.m_ScaleCurves)):
        for r in rows:
            keys = []
            for k in r.curve.m_Curve:
                v = k.value
                keys.append((k.time, (v.x, v.y, v.z, v.w) if kind == 'q' else (v.x, v.y, v.z)))
            out.setdefault(r.path, {})[kind] = keys
    return out


def length(clip):
    """The clip's last frame (frames at 60 a second, from its last key)."""
    times = [k.time for rows in (clip.m_RotationCurves, clip.m_PositionCurves, clip.m_ScaleCurves)
             for r in rows for k in r.curve.m_Curve]
    return int(round(max(times or [0.0]) * clip.m_SampleRate))


def sample(keys, time, rotation=False):
    """A curve's value at `time`, straight between keys (the clips are keyed every frame); a rotation goes the short
    way and is made whole again."""
    times = [k[0] for k in keys]
    if time <= times[0]:
        return np.array(keys[0][1], float)
    if time >= times[-1]:
        return np.array(keys[-1][1], float)
    i = int(np.searchsorted(times, time, side='right')) - 1
    (t0, a), (t1, b) = keys[i], keys[i + 1]
    u = 0.0 if t1 <= t0 else (time - t0) / (t1 - t0)
    a, b = np.array(a, float), np.array(b, float)
    if rotation:
        if a @ b < 0:
            b = -b
        v = a + (b - a) * u
        return v / np.linalg.norm(v)
    return a + (b - a) * u


def worlds(nodes, base, keep, local=None):
    """{node index: 4x4 in the space of node `base`} for the nodes in `keep` (and those above them), from the rest
    or from `local` ({node index: 4x4} overriding the rest)."""
    local = local or {}
    out = {base: np.eye(4)}

    def world(i):
        if i not in out:
            n = nodes[i]
            m = local.get(i)
            if m is None:
                m = trs(n['t'], n['q'], n['s'])
            out[i] = world(n['parent']) @ m
        return out[i]
    for i in keep:
        world(i)
    return out
