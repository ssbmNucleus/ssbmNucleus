"""Article window graphs in source order, with every named hit and velocity operation.

The old one-speed/one-hit summary remains for existing adapters. New adapters use
this program: sibling windows are alternatives, not an implicit timeline.
"""
from copy import deepcopy
from .transcode import MELEE_PER_CM


def enum(value):
    return str(value or '').split('::')[-1]


def program(data, unit, hit_values):
    attributes = {h['Name']: h for h in data.get('HitboxAttributes') or []}
    properties = {h['Name']: h for h in data.get('HitboxOnHitProperties') or []}
    phases = []
    for window in data.get('Windows') or []:
        length = int(window['WindowLengthFrames'])
        velocities = []
        for value in window.get('VelocityData') or []:
            kinds = [enum(value.get(k)) for k in ('HorizontalVelocityType', 'VerticalVelocityType')]
            velocities.append(dict(first=int(value.get('ApplyVelocityOnWindowFrame', 0)),
                last=int(value.get('ApplyVelocityUntilFrame', 9999)),
                kinds=kinds, values=[float((value.get('Velocity') or {}).get(axis, 0)) *
                    (1 if kind == 'MultiplyVelocity' else MELEE_PER_CM) for axis, kind in zip('XY', kinds)],
                modifiers=deepcopy(value.get('VelocityModifiers') or [])))
        hits = []
        for active in window.get('HitboxWindows') or []:
            name = active['HitboxName']
            attribute = attributes.get(name)
            props = properties.get((attribute or {}).get('OnHitPropertiesName'))
            hits.append(dict(name=name, first=int(active['StartFrame']), length=int(active['LengthInFrames']),
                hit=hit_values(attribute, props) if attribute is not None and props is not None else None,
                attribute=deepcopy(attribute), properties=deepcopy(props)))
        advanced = window.get('AdvancedProperties') or {}
        phases.append(dict(name=window['StringTableKey'], length=length,
            next=window.get('NextWindowStringTableKey') or '', velocities=velocities, hits=hits,
            refresh=bool(window.get('bRefreshHasHit')), gravity=float(advanced.get('Gravity', 0))*MELEE_PER_CM,
            max_fall=float(advanced.get('MaxFallSpeed', 9999))*MELEE_PER_CM,
            friction_air=float(advanced.get('FrictionAir', 0))*MELEE_PER_CM,
            friction_ground=float(advanced.get('FrictionGround', 0))*MELEE_PER_CM,
            source=deepcopy(window)))
    return dict(schema=1, package_unit=unit, phases=phases, source=deepcopy(data))
