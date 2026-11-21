"""A fighter's swing bones: the parts the game moves by physics, not by clips (ears, hair, capes, tails).

`motion/body/c00/swing.prc` lists the chains (first and last bone, then one set of numbers per moving joint), and the
shapes the chains must not pass through (spheres, ellipsoids, capsules, each on a bone). `swingblend.prc` says, clip by
clip, how much of each swing bone is left to the physics: its groups are named by the clip's file name
(`hash40("c02attacks3s.nuanmb")`), with `default` for every clip that has no group of its own.

Bone names in both files are hashes of the lowercased name; they are turned back with the skeleton's own names.
Angles are in degrees. What the numbers mean is the community's reading of their names, not something read from code.
"""
from __future__ import annotations

from pathlib import Path

from .prc import Prc, hash40

LABELS = '''swingbones spheres ovals ellipsoids capsules planes connections name start_bonename end_bonename params
airresistance waterresistance minanglez maxanglez minangley maxangley collisionsizetip collisionsizeroot frictionrate
goalstrength inertialmass localgravity fallspeedscale groundhit windaffect collisions bonename cx cy cz radius rx ry rz
sx sy sz start_offset_x start_offset_y start_offset_z end_offset_x end_offset_y end_offset_z start_radius end_radius
nx ny nz distance isskirt rotateorder curverotatex default bones'''.split()
PHYSICS = '0x0a18c3a29f'             # in swingblend: how much of the bone is the physics' (1) and how much the clip's (0)


def _bones(names):
    return {hash40(n): n for n in names}


def _name(value, known):
    return known.get(getattr(value, 'value', value), str(value))


def read(motion_dir, bone_names):
    """-> {'chains': [...], 'spheres': [...], 'ellipsoids': [...], 'capsules': [...]}; None when the fighter has no
    swing file. A chain: name, start, end (bone names), joints (one dict of numbers per moving joint, root first; a
    joint's 'collisions' are the names of the shapes it is kept out of)."""
    path = Path(motion_dir) / 'swing.prc'
    if not path.exists():
        return None
    known = _bones(bone_names)
    root = Prc(path.read_bytes(), LABELS).root
    shapes = {}
    out = dict(chains=[], spheres=[], ellipsoids=[], capsules=[])
    for kind in ('spheres', 'ellipsoids', 'capsules'):
        for row in root.get(kind) or []:
            shape = {k: (_name(v, known) if k.endswith('bonename') else v) for k, v in row.items() if k != 'name'}
            shape['name'] = f"{kind[:-1]}{len(out[kind])}"
            shapes[row['name'].value] = shape['name']
            out[kind].append(shape)
    for row in root.get('swingbones') or []:
        joints = []
        for p in row['params']:
            joint = {k: v for k, v in p.items() if k != 'collisions'}
            joint['collisions'] = [shapes.get(c.value, str(c)) for c in p.get('collisions') or []]
            joints.append(joint)
        out['chains'].append(dict(name=_name(row['start_bonename'], known), start=_name(row['start_bonename'], known),
                                  end=_name(row['end_bonename'], known), joints=joints))
    return out


def blend(motion_dir, bone_names, clips):
    """-> {clip stem: {bone name: share left to the physics, 0..1}} for the clips that have a group of their own, and
    under None the default every other clip gets. None when the fighter has no swing-blend file."""
    path = Path(motion_dir) / 'swingblend.prc'
    if not path.exists():
        return None
    known = _bones(bone_names)
    wanted = {f'0x{hash40(c + ".nuanmb"):010x}': c for c in clips}
    root = Prc(path.read_bytes(), ['name', 'default', 'bones']).root

    def shares(rows):
        return {_name(r['name'], known): float(r[PHYSICS]) for r in rows if PHYSICS in r}
    out = {}
    for key, group in root.items():
        rows = group.get('bones') if isinstance(group, dict) else group
        if key == 'default':
            out[None] = shares(rows)
        elif key in wanted and rows:
            out[wanted[key]] = shares(rows)
    return out
