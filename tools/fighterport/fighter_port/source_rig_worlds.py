"""One source-to-helper world expansion for authoring and repair tools."""
import numpy as np
from . import batch_evaluation as batch, scale_helpers as scale, rotation_charts as charts


def expand(raw,times,scaled,charted,target):
    # (a source bone the rig folded is no joint of it, and a bone that makes up for an even scale has no helper:
    # its own size track does it; own_skeleton.fold_plan, even_scale)
    reference={j:w for j,w in batch.raw_worlds(raw,times).items() if j in scaled.original_order}
    comp={j for j,tr in raw.tracks.items() if tr.compensate_scale and j in scaled.helpers}
    scales={j:np.array([raw.parts(raw.parent[j],float(f))[2] if raw.parent[j] in raw.tracks else np.ones(3) for f in times]) for j in comp}
    worlds=charts.expand_worlds(charted,scale.expand_worlds(scaled,reference,scales,comp))
    if set(worlds)-set(target.order):raise ValueError('Target omits expanded source joints')
    for j in target.order:
        if j not in worlds:
            if not j.startswith('__engine_') or target.rest[j]!=dict(r=[0.,0.,0.],t=[0.,0.,0.],s=[1.,1.,1.]):
                raise ValueError('Only explicit identity engine controls may extend source worlds')
            parent=target.parent[j]
            worlds[j]=(worlds[parent] if parent is not None else np.broadcast_to(np.eye(4),(len(times),4,4))).copy()
    return worlds


