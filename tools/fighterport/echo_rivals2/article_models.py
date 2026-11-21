"""Export an article renderer's explicit skeletal mesh through the normal model path."""
from pathlib import Path
from .visuals import package


class Unsupported(ValueError):
    pass


def mesh_reference(pak, renderer):
    defaults, seen, current = {}, set(), renderer
    chain = []
    while current:
        if current in seen:raise Unsupported('cyclic article renderer inheritance')
        seen.add(current)
        objects = pak.props(current)
        cls = next((o for o in objects if o.get('Type') == 'BlueprintGeneratedClass'), {})
        chain.append(next((o.get('Properties') or {} for o in objects if o.get('Name','').startswith('Default__')), {}))
        current = package(cls.get('SuperStruct'))
    for values in reversed(chain):defaults.update(values)

    def resolve(ref):
        target = package(ref)
        name = (ref or {}).get('ObjectName','').rstrip("'").split(':')[-1]
        objects = pak.props(target) if target else []
        matches = [o for o in objects if o.get('Name') == name]
        if len(matches)!=1:raise Unsupported('article renderer component is unresolved')
        return matches[0].get('Properties') or {}

    reference = defaults.get('ArticleMeshComponent')
    component = resolve(reference)
    mesh = package(component.get('SkeletalMesh') or component.get('SkinnedAsset'))
    if not mesh:raise Unsupported('article renderer has no explicit skeletal mesh')
    current = component
    seen = set()
    while current:
        for key, default in [('RelativeLocation',0),('RelativeRotation',0),('RelativeScale3D',1)]:
            if any(abs(float(v)-default)>1e-6 for v in (current.get(key) or {}).values()):
                raise Unsupported('article renderer needs a component-transform adapter')
        if current.get('bHiddenInGame') or current.get('bVisible') is False:
            raise Unsupported('article mesh has conditional source visibility')
        parent = current.get('AttachParent')
        if not parent:break
        identity = parent.get('ObjectPath')
        if identity in seen:raise Unsupported('cyclic article component attachment')
        seen.add(identity);current=resolve(parent)
    return mesh


def export(pak, projectiles, fighter, short, root, unit, ssbh):
    from . import actorx, transcode, palettes
    out, limits = {}, []
    cache = Path(root)/'rivals2-cache'/'export'
    for name, data in sorted(projectiles.items()):
        renderer = package(((data.get('program') or {}).get('source') or {}).get('DefaultRendererClass'))
        if not renderer:continue
        try:
            mesh_pkg = mesh_reference(pak, renderer)
            files = pak.export([mesh_pkg], cache)[mesh_pkg]
            path = next((f for f in files if f.endswith('.psk')), None)
            if path is None:raise Unsupported('article skeletal mesh export is unavailable')
            mesh_obj = next(o for o in pak.props(mesh_pkg) if o.get('Type')=='SkeletalMesh')
            materials = mesh_obj.get('SkeletalMaterials') or (mesh_obj.get('Properties') or {}).get('SkeletalMaterials') or []
            slots = [m['MaterialSlotName'] for m in materials]
            packages = [package(m['Material']) for m in materials]
            bakes=[]
            pictures=palettes.costumes(pak,short,packages,slots,cache,names=['Neutral'],log=lambda text:None,report=bakes)[0][1]
            mesh=actorx.Mesh(path);sk=transcode.Skeleton(mesh,unit)
            folder='article_'+name
            target=Path(root)/'gamedata'/'fighter'/fighter/'model'/folder/'c00'
            target.mkdir(parents=True,exist_ok=True)
            transcode.write_skeleton(sk,ssbh,target/'model.nusktb')
            parts=transcode.write_model(sk,ssbh,mesh,pictures,target,slots)
            positions=transcode.body(mesh,sk)[0]
            out[name]=dict(folder=folder,renderer=renderer,mesh=mesh_pkg,parts=parts,material_bakes=bakes,
                bounds=[positions.min(0).tolist(),positions.max(0).tolist()],
                adaptations=['source mesh in its rest pose; flat material bake; renderer particles remain separate'])
        except (Unsupported, KeyError, StopIteration) as exc:
            limits.append(dict(id=name,reason=str(exc)))
    return out,limits
