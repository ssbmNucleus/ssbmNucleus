"""Calibrated scalar material opacity, on each exported clip's actual source clock.

The source uses screen-door dithering; the native adapter uses material alpha. Shader names alone
are not semantics: only the explicitly calibrated material lineage below is accepted.
"""
from __future__ import annotations
import math
from bisect import bisect_right
from .visuals import package
from .rules import GAME_SHA256

LINEAGE = 'Rivals2/Content/Characters/Ranno/MI_Ran_Sash_Standard'
EVIDENCE = 'fighter_port/benchmarks/2026-11-14-rivals-material-opacity.md'


def curve_value(curve, seconds):
    """Unweighted Unreal rich-curve constant/linear/Hermite evaluation; unknown modes fail closed."""
    keys = curve.get('Keys') or []
    if not keys:
        raise ValueError('opacity curve has no keys')
    if not math.isfinite(seconds):
        raise ValueError('non-finite curve clock')
    for mode in ('PreInfinityExtrap', 'PostInfinityExtrap'):
        if curve.get(mode, 'RCCE_Constant') != 'RCCE_Constant':
            raise ValueError('unsupported opacity curve extrapolation')
    times = [float(k['Time']) for k in keys]
    if any(not math.isfinite(x) for x in times) or any(a >= b for a,b in zip(times,times[1:])):
        raise ValueError('invalid curve key clock')
    if any(not math.isfinite(float(k['Value'])) for k in keys):
        raise ValueError('non-finite curve value')
    if seconds <= times[0]: return float(keys[0]['Value'])
    if seconds >= times[-1]: return float(keys[-1]['Value'])
    i=bisect_right(times,seconds)-1
    a,b=keys[i:i+2];dt=times[i+1]-times[i];u=(seconds-times[i])/dt
    av,bv=float(a['Value']),float(b['Value']);mode=a.get('InterpMode')
    if mode=='RCIM_Constant':return av
    if mode=='RCIM_Linear':return av+(bv-av)*u
    if mode!='RCIM_Cubic':raise ValueError(f'unsupported opacity interpolation {mode}')
    if any(k.get('TangentWeightMode','RCTWM_WeightedNone')!='RCTWM_WeightedNone' for k in (a,b)):
        raise ValueError('weighted opacity tangents are unsupported')
    ta,tb=float(a.get('LeaveTangent',0)),float(b.get('ArriveTangent',0))
    if not math.isfinite(ta) or not math.isfinite(tb):raise ValueError('non-finite opacity tangent')
    return (2*u**3-3*u*u+1)*av+(u**3-2*u*u+u)*dt*ta+(-2*u**3+3*u*u)*bv+(u**3-u*u)*dt*tb


def samples(record, name, frames):
    curves=[c['FloatCurve'] for c in (record.get('curves') or {}).get('FloatCurves',[])
            if c.get('CurveName','').casefold()==name.casefold()]
    if len(curves)!=1:raise ValueError(f'missing or ambiguous curve {name}')
    n=int(record['frames']);seconds=float(record['seconds'])
    if n<2 or not math.isfinite(seconds) or seconds<=0:raise ValueError('invalid source animation clock')
    out=[]
    for frame in frames:
        if not math.isfinite(frame) or frame<0 or frame>n-1+1e-5:
            raise ValueError('opacity source frame outside animation')
        value=curve_value(curves[0],float(frame)*seconds/(n-1))
        if not math.isfinite(value) or value < -1e-6 or value > 1+1e-6:
            raise ValueError('opacity value outside calibrated range')
        out.append(0.0 if abs(value)<1e-6 else 1.0 if abs(value-1)<1e-6 else value)
    if not out:raise ValueError('empty opacity timeline')
    return out


def material_chain(pak, material):
    chain=[]
    while material:
        if material in chain:raise ValueError('cyclic material inheritance')
        chain.append(material)
        material=package(pak.default(material).get('Parent'))
    return chain


def prepare(pak, source, summary, fighter, short):
    out=dict(version=1,bindings=[],clips={},unresolved=[],adaptation='source screen-door dithering -> native material alpha',
             evidence=EVIDENCE,game_sha256=GAME_SHA256)
    bound=source['renderer']['bindings']
    if not bound:return out
    mesh=next(o for o in pak.props(f'Rivals2/Content/Characters/{fighter}/Skins/Default/SK_{short}_Default')
              if o.get('Type')=='SkeletalMesh')
    mats=mesh.get('SkeletalMaterials') or mesh.get('Properties',{}).get('SkeletalMaterials') or []
    slots={m['MaterialSlotName']:package(m['Material']) for m in mats}
    claimed=set()
    for binding in bound:
        for slot in binding['slots']:
            chain=material_chain(pak,slots[slot]) if slot in slots else []
            if binding['parameter']!='Visible' or LINEAGE not in chain or not binding['exclude_shield_mesh']:
                out['unresolved'].append(dict(slot=slot,curve=binding['curve'],reason='uncalibrated material binding'))
                continue
            if slot in claimed:raise ValueError(f'multiple opacity bindings for {slot}')
            claimed.add(slot)
            out['bindings'].append(dict(mesh=slot+'Shape',curve=binding['curve'],default=1.0,material_chain=chain))
    for pkg,record in source['clips'].items():
        clip=pkg.rsplit('/',1)[-1]
        prefix=f'AN_{short}_'
        if not clip.startswith(prefix):continue
        stems=summary['stems'].get(clip[len(prefix):],[])
        for stem in stems:
            carry(out,source,pkg,stem,list(range(int(summary['lengths'][clip[len(prefix):]])+1)))
    return out


def carry(out,source,pkg,stem,frames):
    """Replace a raw clip's timeline when attack windows resample or split that source clip."""
    out['clips'].pop(stem,None)
    out['unresolved'] = [r for r in out['unresolved'] if r.get('clip') != stem]
    if not out['bindings']:return
    record=source['clips'].get(pkg)
    tracks={}
    for binding in out['bindings']:
        try:
            if record is None:raise ValueError('source curve record unavailable')
            # Animation windows can hold beyond the sequence. Match gamedata.resample's endpoint hold.
            if any(not math.isfinite(f) for f in frames):raise ValueError('non-finite source frame')
            shown = [min(max(f,0.0),int(record['frames'])-1) for f in frames]
            tracks[binding['mesh']]=samples(record,binding['curve'],shown)
        except ValueError as exc:
            out['unresolved'].append(dict(clip=stem,source=pkg,curve=binding['curve'],reason=str(exc)))
    if tracks:out['clips'][stem]=dict(end=len(frames)-1,tracks=tracks)
