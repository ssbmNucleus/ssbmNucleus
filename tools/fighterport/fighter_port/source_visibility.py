"""Explicit source visibility resolution shared by costume and pose builders."""
import hashlib
import math
from pathlib import Path


def sample_tracks(tracks, frame):
    if isinstance(frame, bool) or not isinstance(frame, (int, float)) or not math.isfinite(frame) or frame < 0:
        raise ValueError('Finite nonnegative source frame required')
    result = {}
    for name, values in tracks.items():
        if not isinstance(name, str) or not name or not values or any(type(v) is not bool for v in values):
            raise ValueError('Named nonempty boolean visibility tracks required')
        result[name] = values[min(math.floor(frame), len(values)-1)]
    return result


def resolve(selection, tracks, frame, *, fallback_tracks=None, fallback_frame=0, defaults=None):
    """Current track wins, then pinned fallback, then explicit initialization.

    Missing tracks remain unresolved. No character-name guesses or implicit
    false defaults; this sidecar does not install runtime visibility switching.
    """
    primary = sample_tracks(tracks, frame)
    fallback = sample_tracks(fallback_tracks or {}, fallback_frame)
    defaults = {} if defaults is None else defaults
    if any(not isinstance(k, str) or not k or type(v) is not bool for k,v in defaults.items()):
        raise ValueError('Explicit named boolean initialization required')
    rows, identities = [], set()
    for i, item in enumerate(selection['meshes']):
        identity = (item['name'], item['subindex'])
        if identity in identities:
            raise ValueError('Duplicate selected mesh')
        identities.add(identity)
        node = item.get('visibility_node')
        if node is not None and (not isinstance(node, str) or not node):
            raise ValueError('Visibility node must be a name or null')
        value, origin = None, 'UNRESOLVED'
        if node is None:
            value, origin = True, 'UNCONTROLLED_MESH'
        else:
            for values, label in ((primary,'CURRENT_TRACK'), (fallback,'FALLBACK_TRACK'), (defaults,'EXPLICIT_INITIALIZATION')):
                if node in values:
                    value, origin = values[node], label
                    break
        rows.append(dict(dobj=i, mesh=identity[0], subindex=identity[1], visibility_node=node, visible=value, source=origin))
    if not rows:
        raise ValueError('Nonempty mesh selection required')
    return dict(schema='source-visibility-v1', status='VISIBILITY_UNRESOLVED' if any(r['visible'] is None for r in rows) else 'OFFLINE_VISIBILITY_RESOLVED',
                rows=rows, hidden_dobjs=[r['dobj'] for r in rows if r['visible'] is False],
                unresolved_nodes=sorted({r['visibility_node'] for r in rows if r['visible'] is None}), native_accepted=False)


def read_tracks(path, frame):
    import ssbh_data_py as ssbh
    path = Path(path)
    payload = path.read_bytes()
    anim = ssbh.anim_data.read_anim(str(path))
    if isinstance(frame, bool) or not isinstance(frame, (int,float)) or not math.isfinite(frame) or not 0 <= frame <= anim.final_frame_index:
        raise ValueError('Frame outside source motion')
    tracks = {}
    for group in anim.groups:
        if group.group_type.name != 'Visibility':
            continue
        for node in group.nodes:
            for track in node.tracks:
                if track.name != 'Visibility':
                    continue
                if node.name in tracks:
                    raise ValueError('Ambiguous source visibility track')
                tracks[node.name] = list(track.values)
    sample_tracks(tracks, frame)
    return tracks, dict(path=str(path.resolve()), sha256=hashlib.sha256(payload).hexdigest(), frame=frame)
