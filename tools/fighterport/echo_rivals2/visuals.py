"""Source animation curves and their renderer bindings, retained without shader guesses.

Blueprints may compute or condition their material changes. Only the straight-line ReceiveTick
form understood below produces bindings; all original functions are retained, and an unfamiliar
instruction leaves the event unresolved instead of converting it into an unconditional rule.
Floating material parameters are NOT Boolean model visibility tracks.
"""
from __future__ import annotations


class Unsupported(ValueError):
    pass


def package(ref):
    path = (ref or {}).get('AssetPathName') or (ref or {}).get('ObjectPath') or ''
    if path.startswith('/Game/'):
        path = 'Rivals2/Content/' + path[len('/Game/'):]
    return path.rsplit('.', 1)[0] if not path.startswith('/Script/') else ''


def function_name(expr):
    value = expr.get('Function') or ''
    if isinstance(value, str):
        return value
    return value.get('ObjectName', '').rstrip("'").split(':')[-1]


def tick_bindings(functions, groups):
    """Proven unconditional bindings of one effective renderer; unknown control flow rejects the event."""
    by_name = {f['Name']: f for f in functions}
    bindings, active = [], set()
    mesh_set = ('GetRecolorableMeshComponents',)

    def local(expr):
        if expr.get('Token') != 'EX_LocalVariable':
            raise Unsupported('non-local assignment')
        return expr['Variable']['Property']['Name']

    def value(expr, values):
        token = expr.get('Token')
        if token in ('EX_NameConst', 'EX_IntConst'):
            return expr['Value']
        if token in ('EX_True', 'EX_False'):
            return token == 'EX_True'
        if token == 'EX_LocalVariable':
            name = local(expr)
            if name not in values:
                raise Unsupported(f'unresolved local {name}')
            return values[name]
        if token == 'EX_VirtualFunction' and function_name(expr) == 'GetRecolorableMeshComponents' \
                and not expr.get('Parameters'):
            return mesh_set
        raise Unsupported(f'expression {token}')

    def run(name, entry=None):
        if name in active or name not in by_name:
            raise Unsupported(f'unknown or recursive function {name}')
        active.add(name)
        code = by_name[name].get('ScriptBytecode') or []
        if not code or code[-1].get('Token') != 'EX_EndOfScript':
            raise Unsupported(f'incomplete bytecode: {name}')
        if entry is not None:
            dispatch = code[0]
            if dispatch.get('Token') != 'EX_ComputedJump' or \
                    local(dispatch.get('CodeOffsetExpression') or {}) != 'EntryPoint':
                raise Unsupported(f'unrecognized event dispatch: {name}')
            matches = [i for i, op in enumerate(code) if op.get('StatementIndex') == entry]
            if len(matches) != 1 or matches[0] == 0:
                raise Unsupported(f'unknown entry {name}[{entry}]')
            code = code[matches[0]:]
        values = {}
        for op in code:
            token = op.get('Token')
            if token == 'EX_SetArray':
                values[local(op['AssigningProperty'])] = [value(x, values) for x in op['Elements']]
            elif token == 'EX_Let':
                values[local(op['Variable'])] = value(op['Expression'], values)
            elif token == 'EX_LetValueOnPersistentFrame':
                # Tick's parameter copy. A later attempt to USE it stays unresolved above.
                if op.get('AssignmentExpression', {}).get('Token') != 'EX_LocalVariable':
                    raise Unsupported('computed persistent assignment')
            elif token == 'EX_LocalFinalFunction':
                args = [value(x, values) for x in op.get('Parameters', [])]
                if len(args) != 1 or type(args[0]) is not int:
                    raise Unsupported('non-entry local call')
                run(function_name(op), args[0])
            elif token == 'EX_FinalFunction' and function_name(op) == 'SetParameterFromAnimCurve' \
                    and op.get('Function', {}).get('ObjectPath') == '/Script/Rivals2':
                args = [value(x, values) for x in op.get('Parameters', [])]
                if len(args) != 5 or args[0] != mesh_set or not isinstance(args[1], list) \
                        or not all(isinstance(x, str) for x in args[1] + args[2:4]) or type(args[4]) is not bool:
                    raise Unsupported('unresolved curve binding arguments')
                slots = []
                for group in args[1]:
                    if group not in groups:
                        raise Unsupported(f'unknown material group {group}')
                    slots.extend(groups[group])
                bindings.append(dict(event='ReceiveTick', function=name, statement=op['StatementIndex'],
                                     mesh_set=mesh_set[0], groups=args[1], slots=list(dict.fromkeys(slots)),
                                     parameter=args[2], curve=args[3], exclude_shield_mesh=args[4]))
            elif token == 'EX_Return' and op.get('Expression', {}).get('Token') == 'EX_Nothing':
                break
            elif token == 'EX_EndOfScript':
                break
            else:
                raise Unsupported(f'{name} statement {op.get("StatementIndex")}: {token}')
        active.remove(name)

    if 'ReceiveTick' in by_name:
        run('ReceiveTick')
    return bindings


def renderer(pak, short):
    """Follow the actual default skin's renderer and its Blueprint parents, child overrides last."""
    skin = pak.find(f'Skin_{short}_Default')
    current = package(pak.default(skin).get('CharacterRendererClass'))
    chain, seen = [], set()
    while current:
        if current in seen:
            raise ValueError(f'cyclic renderer inheritance: {current}')
        seen.add(current)
        objs = pak.props(current)
        cls = next(o for o in objs if o.get('Type') == 'BlueprintGeneratedClass')
        defaults = next((o.get('Properties') or {} for o in objs
                         if o.get('Name', '').startswith('Default__')), {})
        chain.append(dict(package=current, defaults=defaults, functions=pak.scripts(current),
                          parent=cls.get('SuperStruct')))
        current = package(cls.get('SuperStruct'))
    defaults, functions = {}, {}
    for row in reversed(chain):
        defaults.update(row['defaults'])
        functions.update({f['Name']: f for f in row['functions']})
    groups = {r['Key']: r['Value']['MaterialSlotNames'] for r in defaults.get('MaterialSlotGroups') or []}
    unresolved = []
    try:
        bindings = tick_bindings(list(functions.values()), groups)
    except Unsupported as exc:
        bindings = []
        unresolved.append(str(exc))
    if not chain:
        unresolved.append('default skin has no Blueprint renderer reference')
    return dict(skin=skin, hierarchy=chain, material_groups=groups, bindings=bindings,
                unresolved=unresolved, native_material_curves='not yet carried')


def load(pak, fighter, short):
    base = f'Rivals2/Content/Characters/{fighter}/'
    clips = sorted(f[:-7] for f in pak.files() if f.startswith(base) and f.endswith('.uasset')
                   and f'/AN_{short}_' in f and ('/Animation/' in f or '/Taunts/' in f))
    return dict(renderer=renderer(pak, short), clips=pak.animation_curves(clips))
