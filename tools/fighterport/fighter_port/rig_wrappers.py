"""Insert explicit identity engine parents without changing offline source motion."""
import copy
from .rig_dependencies import validate_rig


def insert_identity_parents(rig, insertions):
    order,parent,_=validate_rig(rig)
    if not isinstance(insertions,dict) or not insertions or set(insertions)-set(order):
        raise ValueError('Known anchor joints required')
    names=[]
    for chain in insertions.values():
        if not isinstance(chain,list) or not chain or any(not isinstance(j,str) or not j for j in chain):
            raise ValueError('Explicit nonempty wrapper chains required')
        names.extend(chain)
    if len(set(names))!=len(names) or set(names)&set(order):
        raise ValueError('Wrapper names collide')
    out=copy.deepcopy(rig);out['order']=[];operations=[]
    for joint in order:
        previous=parent[joint]
        for wrapper in insertions.get(joint,[]):
            out['order'].append(wrapper);out['parent'][wrapper]=previous
            out['rest'][wrapper]=dict(r=[0.,0.,0.],t=[0.,0.,0.],s=[1.,1.,1.])
            previous=wrapper
        out['parent'][joint]=previous;out['order'].append(joint)
        if joint in insertions:operations.append(dict(anchor=joint,old_parent=parent[joint],wrappers=insertions[joint][:]))
    validate_rig(out)
    out['identity_parent_insertions']=operations
    return out


def canonical_jobj_order(rig):
    """Single-root DFS, retaining sibling order from the explicit input order."""
    order,parent,_=validate_rig(rig)
    children={j:[] for j in order};roots=[]
    for joint in order:
        if parent[joint] is None:roots.append(joint)
        else:children[parent[joint]].append(joint)
    if len(roots)!=1:raise ValueError('Fighter costume requires one explicit root')
    stack=roots[:];canonical=[]
    while stack:
        joint=stack.pop();canonical.append(joint);stack.extend(reversed(children[joint]))
    result=copy.deepcopy(rig);result['order']=canonical
    result['traversal_contract']=dict(kind='SINGLE_ROOT_DEPTH_FIRST',
        reordered=sum(a!=b for a,b in zip(order,canonical)),
        old_to_new={str(i):canonical.index(j) for i,j in enumerate(order)})
    return result


