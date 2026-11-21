"""Inherited Rivals material parameters, including the cooked master defaults.

The pinned CUE4Parse export retains typed parameter tables even when the shader
graph is stripped. Reading these values is exact; the static elemental ramp bake
below is an explicit approximation of the source shader, not its reconstructed graph.
"""
from __future__ import annotations
import math
import numpy as np
from .visuals import package

TABLES = {'scalar': ('RuntimeEntries', 'ScalarValues'),
          'vector': ('RuntimeEntries[1]', 'VectorValues'),
          'texture': ('RuntimeEntries[3]', 'TextureValues'),
          'switch': ('RuntimeEntries[8]', 'StaticSwitchValues')}


def global_name(info):
    if info.get('Association', 'EMaterialParameterAssociation::GlobalParameter').split('::')[-1] != 'GlobalParameter':
        raise ValueError('layered material parameters need a layer-aware bake')
    return info['Name']


def read(pak, material):
    """Closest override wins; non-overriding static switches inherit their parent."""
    out = {kind: {} for kind in TABLES}
    out['chain'] = []
    while material:
        if material in out['chain']:
            raise ValueError('cyclic material inheritance')
        out['chain'].append(material)
        rows = [r for r in pak.props(material) if r.get('Type') in ('MaterialInstanceConstant', 'Material')]
        if len(rows) != 1:
            raise ValueError(f'{material}: missing or ambiguous material export')
        row = rows[0]
        props = row.get('Properties') or {}
        for kind, field in [('scalar', 'ScalarParameterValues'), ('vector', 'VectorParameterValues'),
                            ('texture', 'TextureParameterValues')]:
            for item in props.get(field) or []:
                value = item.get('ParameterValue')
                if value is not None:
                    out[kind].setdefault(global_name(item['ParameterInfo']), value)
        for item in (props.get('StaticParametersRuntime') or {}).get('StaticSwitchParameters') or []:
            if item.get('bOverride'):
                out['switch'].setdefault(global_name(item['ParameterInfo']), item['Value'])
        cached = row.get('CachedExpressionData') or {}
        for kind, (entry, values) in TABLES.items():
            infos = (cached.get(entry) or {}).get('ParameterInfoSet') or []
            data = cached.get(values) or []
            if len(infos) != len(data):
                raise ValueError(f'{material}: incomplete {kind} material defaults')
            for info, value in zip(infos, data):
                out[kind].setdefault(global_name(info), value)
        material = package(props.get('Parent'))
    out['texture'] = {name: package(ref) for name, ref in out['texture'].items() if package(ref)}
    return out


def linear_rgb(value):
    rgb = np.asarray([value[c] for c in 'RGB'], dtype=float)
    if not np.isfinite(rgb).all():
        raise ValueError('non-finite material color')
    return rgb


def srgb(value):
    value = np.clip(np.asarray(value, dtype=float), 0, 1)
    return np.where(value <= .0031308, value * 12.92, 1.055 * value ** (1 / 2.4) - .055)


def elemental_colors(material):
    """Static linear-light ramp adaptation from declared elemental stops and sample times.

    This does not claim shader parity: curve-texture remapping, matcap, Fresnel,
    time variation and vertex displacement are not reconstructed by a flat picture.
    """
    if not material['switch'].get('UseElementalCustomColors'):
        return {}, None
    scalars, vectors = material['scalar'], material['vector']
    count = scalars.get('ElementalLerpCount')
    if type(count) not in (float, int) or not math.isfinite(count) or int(count) != count or not 1 <= count <= 11:
        raise ValueError('unsupported elemental color ramp count')
    count = int(count)
    try:
        stops = np.asarray([linear_rgb(vectors[f'ElementColor{i}']) for i in range(count + 1)])
    except KeyError as error:
        raise ValueError('incomplete elemental color ramp') from error
    colors, samples = {}, {}
    for suffix in ['X', *map(str, range(9))]:
        key = 'CustomColorSampleTime' + suffix
        if key not in scalars:
            continue
        value = scalars[key]
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f'unsupported elemental sample time: {key}')
        position = value * count
        lower = min(int(position), count - 1)
        color = stops[lower] + (stops[lower + 1] - stops[lower]) * (position - lower)
        colors['CustomColor' + suffix] = srgb(color)
        samples[key] = value
    if not samples:
        raise ValueError('elemental material has no color sample times')
    return colors, dict(kind='static elemental ramp approximation', intervals=count,
        samples=samples, linear_stops=stops.tolist(),
        not_carried=['shader curve remapping', 'matcap', 'Fresnel', 'time variation', 'vertex displacement'])
