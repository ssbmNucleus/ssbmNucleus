"""Separate source fitting from encoding with identical sampled FK/skin gates.

This measures each stage; maxima are never subtracted to infer a cause. A
packed-to-authored pass cannot substitute for packed-to-source acceptance.
"""
import math
import numpy as np
from . import batch_evaluation as batch


def _limits(limits):
    expected = {'integer_pivot', 'fine_pivot', 'integer_skin', 'fine_skin', 'basis'}
    if set(limits) != expected or any(type(v) not in (int,float) or not math.isfinite(v) or v <= 0 for v in limits.values()):
        raise ValueError('Explicit finite positive integer/fractional pivot/skin and basis limits required')


def measure_stages(times, source, authored, packed, skin, *, limits, parent, chunk_frames=8):
    _limits(limits)
    ts = np.asarray(times, dtype=float)
    if ts.ndim != 1 or not len(ts) or not np.isfinite(ts).all() or ts[0] != 0 or not float(ts[-1]).is_integer():
        raise ValueError('Complete source clock required')
    if not np.array_equal(ts, np.arange(int(ts[-1])*16+1)/16):
        raise ValueError('Complete 1/16 source-frame grid required')
    if skin is None or set(parent) != set(source):
        raise ValueError('Full skin and exact parent domain required')
    for joint in parent:
        seen, p = set(), joint
        while p is not None:
            if p not in parent or p in seen:
                raise ValueError('Cyclic or unknown parent')
            seen.add(p); p = parent[p]
    integers = np.flatnonzero(ts == np.floor(ts))
    comparisons = {}
    for name, a, b in (('authored_vs_source', authored, source), ('packed_vs_authored', packed, authored), ('packed_vs_source', packed, source)):
        fine = batch.measure_worlds(ts,a,b,skin,chunk_frames=chunk_frames)['metrics']
        integer = batch.measure_worlds(ts[integers],{j:w[integers] for j,w in a.items()},
                                     {j:w[integers] for j,w in b.items()},skin,chunk_frames=chunk_frames)['metrics']
        measurements = dict(integer_pivot=integer['pivot'], fine_pivot=fine['pivot'],
                            integer_skin=integer['skin'], fine_skin=fine['skin'], basis=fine['basis'])
        gates = {key:dict(witness=measurements[key], limit=limit, ratio=measurements[key]['value']/limit,
                         passed=measurements[key]['value'] <= limit) for key,limit in limits.items()}
        comparisons[name] = dict(metrics=fine, integer_metrics=integer, gates=gates,
                                 passed=all(v['passed'] for v in gates.values()))
    fit = comparisons['authored_vs_source']['passed']
    packing = comparisons['packed_vs_authored']['passed']
    total = comparisons['packed_vs_source']['passed']
    if total:
        diagnosis = 'SOURCE_POSE_GATES_PASS'
    elif not fit and packing:
        diagnosis = 'REPAIR_AUTHORED_FIT_FIRST'
    elif fit and not packing:
        diagnosis = 'INSPECT_SERIALIZATION_FIRST'
    elif not fit and not packing:
        diagnosis = 'BOTH_STAGES_EXCEED_LIMITS'
    else:
        diagnosis = 'COMBINED_ERROR_EXCEEDS_LIMITS'
    worst_key = max(limits, key=lambda k: comparisons['packed_vs_source']['gates'][k]['ratio'])
    witness = comparisons['packed_vs_source']['gates'][worst_key]['witness']
    weighted = []
    if 'vertex' in witness:
        for joint, ids, weights, _, _ in skin.parts:
            amount = float(np.sum(weights[ids == witness['vertex']]))
            if amount > 0:
                weighted.append(dict(joint=joint, weight=amount))
    elif witness.get('joint'):
        weighted.append(dict(joint=witness['joint']))
    ancestors = set()
    for item in weighted:
        p = item['joint']
        while p is not None:
            ancestors.add(p); p = parent[p]
    return dict(schema='animation-stage-diagnosis-v1', status='DIAGNOSTIC_NOT_RUNTIME_ADMISSION',
                diagnosis=diagnosis, source_pose_passed=total, comparisons=comparisons,
                sample_count=len(ts), subdivisions=16, limits=dict(limits),
                worst_gate=worst_key, worst_witness=witness, weighted_joints=weighted,
                affected_ancestors=[j for j in parent if j in ancestors], native_accepted=False)
