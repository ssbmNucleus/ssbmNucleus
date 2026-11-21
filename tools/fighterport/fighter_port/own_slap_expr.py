"""Compile explicitly bound Slap scalar expressions and predicates to side-effect-free C.

Bindings are supplied by a runtime adapter. Unknown fields/operators are errors;
this does not infer execution phases or turn registered callbacks into one-shot events.
"""
import math


class Unsupported(ValueError):
    pass


def key(node):
    return node.get('t'),node.get('i',node.get('a',node.get('p')))


def scalar(node,bindings):
    if not isinstance(node,dict):
        raise Unsupported(f'expected scalar expression: {node!r}')
    if 'f' in node and not node.get('t'):
        number=float(node['f'])
        if not math.isfinite(number):raise Unsupported('non-finite scalar')
        return repr(number)+'f'
    binding = key(node)
    if not isinstance(binding[1], (dict, list)) and binding in bindings:
        return bindings[binding]
    if node.get('t')!='FSF':
        raise Unsupported(f'unbound scalar {key(node)!r}')
    op=node.get('fw')
    a=scalar(node.get('fa'),bindings)
    if op=='Abs':return f'SlapAbs({a})'
    if op=='Sign':return f'({a} < 0 ? -1.0f : 1.0f)'
    b=scalar(node.get('fb'),bindings)
    if op=='Div':return f'SlapDiv({a},{b})'
    binary={'Add':'+','Sub':'-','Mult':'*'}
    if op in binary:return f'({a} {binary[op]} {b})'
    if op in ('Min','Max'):return f'Slap{op}({a},{b})'
    c=scalar(node.get('fc'),bindings)
    if op=='Clamp':return f'SlapClamp({a},{b},{c})'
    if op=='Lerp':return f'SlapLerp({a},{b},{c})'
    if op=='MoveTo':return f'SlapMoveTo({a},{b},{c})'
    if op=='MoveToF':return f'SlapMoveTo({a},{b},({c})/60.0f)'
    raise Unsupported(f'unsupported scalar operation {op!r}')


def condition(node,bindings,*,input_condition=None):
    if node is None:return '1'
    if 'all' in node:
        return '('+' && '.join(condition(x,bindings,input_condition=input_condition) for x in node['all'])+')' if node['all'] else '1'
    if 'not' in node:return f'(!{condition(node["not"],bindings,input_condition=input_condition)})'
    if node.get('t')=='CTM' and node.get('m') in ('All','Any'):
        terms=node.get('c') or []
        if not terms:return '1' if node['m']=='All' else '0'
        return '('+(' && ' if node['m']=='All' else ' || ').join(condition(x,bindings,input_condition=input_condition) for x in terms)+')'
    if node.get('t')=='CTC':
        op={'Equal':'==','NotEqual':'!=','Larger':'>','Less':'<','EOLarger':'>=','EOLess':'<='}.get(node.get('w'))
        if op:return f'({scalar(node["a"],bindings)} {op} {scalar(node["b"],bindings)})'
    if node.get('t')=='CTI' and input_condition is not None:
        return input_condition(node)
    raise Unsupported(f'unsupported predicate {node!r}')


HELPERS='''
static float SlapAbs(float x){return x < 0 ? -x : x;}
static float SlapMin(float a,float b){return a < b ? a : b;}
static float SlapMax(float a,float b){return a > b ? a : b;}
static float SlapClamp(float x,float lo,float hi){return x < lo ? lo : x > hi ? hi : x;}
static float SlapLerp(float a,float b,float t){return a+(b-a)*SlapClamp(t,0,1);}
static float SlapDiv(float a,float b){return b==0 ? 0 : a/b;}
static float SlapMoveTo(float a,float b,float step){return a+SlapClamp(b-a,-SlapMax(0,step),SlapMax(0,step));}
'''
