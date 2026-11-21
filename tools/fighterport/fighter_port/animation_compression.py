"""Reusable C1 curve reduction with packed FK/skin gates and stock admission.

No campaign paths, anatomical guesses, DOL edits, unguarded pruning or implicit
tolerance relaxation. Unselected actions are losslessly packed. Geometry error
is incremental against the supplied bank, sampled at 1/16 game frames.
"""
import collections,hashlib,json,re,struct,subprocess
from pathlib import Path
import numpy as np
from vault.echo.subactions import FighterDat,ACTION_SIZE
from vault.echo.datroot import build as build_dat
from fighter_port import rig_benchmark as b, batch_evaluation as batch
from .compat import animation_archive as archive
from .native_port import rig_from_meta
from .rig_archive import read_skeleton
from .compat.rig_inventory import costume_inventory
from .compat.fighter_scale import scale_offset
from .curves_c1 import reduce_track_c1

def sha(data):return hashlib.sha256(data).hexdigest()

def _run(command,logfile):
    with logfile.open('w',encoding='utf-8') as log:
        subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)

def _skin(path,rig):
    from .compat import smd
    model=smd.load(str(path),strict=True);points=[];seen={};weights=collections.defaultdict(dict)
    bones={x.id:x for x in model.bones}
    for i,j in enumerate(rig.order):
        expected=-1 if rig.parent[j] is None else rig.order.index(rig.parent[j])
        if i not in bones or bones[i].parent!=expected:raise ValueError('Costume readback skeleton differs')
    for triangle in model.triangles:
        for v in triangle.verts:
            key=(tuple(v.pos),tuple(sorted(v.weights)))
            if key in seen:continue
            index=len(points);seen[key]=index;points.append(v.pos)
            for joint,amount in v.weights:
                if not 0<=joint<len(rig.order):raise ValueError('Skin influence outside rig')
                d=weights[rig.order[joint]];d[index]=d.get(index,0)+amount
    return b.Skin(points,{j:(np.array(list(d)),np.array(list(d.values()))) for j,d in weights.items()},rig.world)

def _restore_streams(original,candidate,keep):
    head,counts,old,names=archive.tracks(original);_,newcounts,new,_=archive.tracks(candidate)
    if counts!=newcounts:raise ValueError('Compression changed the channel domain')
    rows=[];at=0
    for node,count in enumerate(counts):
        for i in range(at,at+count):
            if old[i][0][4]!=new[i][0][4]:raise ValueError('Compression reordered channel identity')
            rows.append(old[i] if (node,old[i][0][4]) in keep else new[i])
        at+=count
    cp=20;countbuf=counts+b'\xff';countbuf+=bytes(-len(countbuf)%4);tp=cp+len(countbuf)
    data=bytearray(head+struct.pack('>II',cp,tp)+countbuf+bytes(12*len(rows)));rel=[12,16];buffers={}
    for i,(desc,buf) in enumerate(rows):
        if buf not in buffers:data+=bytes(-len(data)%4);buffers[buf]=len(data);data+=buf
        data[tp+12*i:tp+12*i+12]=desc+struct.pack('>I',buffers[buf]);rel.append(tp+12*i+8)
    return build_dat(bytes(data),rel,[(0,n) for n in names],[])

def compress(args,log):
    out=Path(args['out']).resolve()
    if out.exists():raise ValueError('Choose a new compression output directory')
    plpath,ajpath=Path(args['fighter']).resolve(),Path(args['animation']).resolve()
    pl,aj=plpath.read_bytes(),ajpath.read_bytes();ft=FighterDat(pl)
    mode=args.get('compression_mode','lossless');capacity=args.get('animation_capacity',32768)
    if mode not in ('lossless','bounded'):raise ValueError('Unknown compression mode')
    if type(capacity) is not int or capacity not in (32768,65504,131040):raise ValueError('Explicit supported buffer capacity required')
    chosen=args.get('required_actions',[])
    if not isinstance(chosen,list) or any(type(i) is not int or not 0<=i<len(ft.actions) for i in chosen) or len(set(chosen))!=len(chosen):
        raise ValueError('Unique valid action indices required')
    selected=set(chosen);max_error=args.get('max_displacement',.15);max_basis=args.get('max_basis_error',.025)
    if any(type(x) not in (int,float) or not np.isfinite(x) or x<=0 for x in (max_error,max_basis)):
        raise ValueError('Finite positive error limits required')
    protected=set(args.get('protected_joints',[0,1,2,3]))
    combat_manifest=None;combat_path=None;combat_bones=set()
    if args.get('combat_contract'):
        from .source_combat import prepare_contract
        combat_path=Path(args['combat_contract']).resolve();combat_manifest=json.loads(combat_path.read_text())
        _,combat_check=prepare_contract(pl,aj,combat_manifest,combat_path.parent)
        if combat_check['status']!='SOURCE_SCRIPTS_MATCH':raise ValueError('Install the declared source combat scripts before compressing')
        combat_bones={b['bone'] for e in combat_manifest['actions'] for b in e['bindings'].values()}
    if mode=='bounded':
        if not selected:raise ValueError('Bounded compression requires explicit owned action indices')
        costume=Path(args['costume']).resolve();codec=Path(args['codec']).resolve()
        if not codec.is_file():raise ValueError('Build FigaCodec first; see tools/FigaCodec/README.md')
        inventory=costume_inventory(costume.read_bytes());order=[f'JOBJ_{i}' for i in range(inventory['joint_count'])]
        if any(type(i) is not int or not 0<=i<len(order) for i in protected):raise ValueError('Protected joint outside rig')
        meta,_=read_skeleton(costume.read_bytes(),order);rig=rig_from_meta(meta)
        if any(not 0<=i<len(order) for i in combat_bones):raise ValueError('Source combat bone outside costume rig')
        for i in combat_bones:
            joint=order[i]
            while joint is not None:
                protected.add(order.index(joint));joint=rig.parent[joint]
        scale=struct.unpack_from('>f',ft.dat.buf,scale_offset(ft))[0]
        if not np.isfinite(scale) or scale<=0:raise ValueError('Invalid fighter model scale')
    out.mkdir(parents=True);rows=[];entries={};processed={}
    report=dict(schema='animation-compression-v1',status='RUNNING',compression_mode=mode,
                input_pl_sha256=sha(pl),input_aj_sha256=sha(aj),input_bytes=len(aj),
                capacity=capacity,max_displacement=max_error,max_basis_error=max_basis,
                protected_joints=sorted(protected),rows=rows,native_accepted=False)
    if combat_manifest is not None:
        report.update(combat_contract_sha256=sha(combat_path.read_bytes()),source_combat_bones=sorted(combat_bones),
                      combat_protection='Preserve named source hitbox bones and their ancestor streams verbatim; does not restore previously pruned channels')
    if mode=='bounded':
        from core.config import HSDRAW_EXE
        smdpath=out/'costume-readback.smd'
        _run([HSDRAW_EXE,'--model','export',costume,inventory['root'],smdpath],out/'costume-export.log')
        skin=_skin(smdpath,rig)
        report.update(costume_sha256=sha(costume.read_bytes()),codec_sha256=sha(codec.read_bytes()),
                      skin_vertices=skin.count,model_scale=scale,sampling_subdivisions=16,
                      policy='No joint pruning or channel deletion; constant/protected streams kept verbatim')
    for act in ft.actions:
        if not act.symbol or not act.anim_size:
            if act.index in selected:raise ValueError('Selected action has no owned animation')
            continue
        key=(act.symbol,act.index in selected)
        if key in processed:entries[act.symbol]=(act.symbol,processed[key]);continue
        original=aj[act.anim_offset:act.anim_offset+act.anim_size];best=archive.compact(original,symbols=[act.symbol])
        row=dict(action=act.index,motion=act.motion,original_bytes=len(original),policy='LOSSLESS',trials=[])
        if mode=='bounded' and act.index in selected:
            if not re.fullmatch(r'[A-Za-z0-9_]+',act.motion):raise ValueError('Plain motion name required by codec')
            work=out/f'action-{act.index}';work.mkdir();(work/'input.dat').write_bytes(best)
            _run([codec,'audit',work/'input.dat',work/'input.json'],work/'audit.log')
            anim=b.packed_animation(json.loads((work/'input.json').read_text()),order)
            if anim.end<=0 or anim.end!=int(anim.end):
                row['policy']='PRESERVED_NONINTEGER_OR_EMPTY_DURATION'
            else:
                authored=b.frame_grid(int(anim.end),4);verify=b.frame_grid(int(anim.end),16)
                reference=batch.animation_worlds(anim,rig,verify)
                channels={(j,t):keys for j,chs in anim.channels.items() for t,label in b.TYPES.items() if (keys:=chs.get(label))}
                values={k:batch.curve_values(v,authored) for k,v in channels.items()}
                keep={(order.index(j),t) for (j,t),v in values.items() if order.index(j) in protected or np.ptp(v)==0}
                # Explicit fixed ladder, independently tested after packing; never relax a caller's gate.
                for trial_index,tau in enumerate((.02,.01,.005,.002)):
                    # Protected/constant streams are restored verbatim below.
                    # Do not spend a curve solve on channels the caller forbids
                    # us to change (important for small accessory-only passes).
                    candidate={k:channels[k] if (order.index(k[0]),k[1]) in keep else
                               reduce_track_c1(authored,v,list(range(0,len(authored),4)),tau if k[1]<8 else .00002)
                               for k,v in values.items()}
                    spec=b.codec_spec(rig,candidate,anim.end,act.motion)
                    for channel in spec['channels']:channel['quantization']=.0001 if channel['type']<8 else .00001
                    trial=work/f'trial-{trial_index}';trial.mkdir();(trial/'curves.json').write_text(json.dumps([spec]))
                    _run([codec,'encode',work/'input.dat',trial/'curves.json',trial,act.motion],trial/'encode.log')
                    packed=_restore_streams(best,(trial/(act.motion+'.uncompacted.dat')).read_bytes(),keep)
                    (trial/'packed.dat').write_bytes(packed)
                    _run([codec,'audit',trial/'packed.dat',trial/'readback.json'],trial/'audit.log')
                    read=b.packed_animation(json.loads((trial/'readback.json').read_text()),order)
                    metrics=batch.measure_worlds(verify,batch.animation_worlds(read,rig,verify),reference,skin)['metrics']
                    passed=metrics['skin']['value']*scale<=max_error and metrics['pivot']['value']*scale<=max_error and metrics['basis']['value']<=max_basis
                    row['trials'].append(dict(bytes=len(packed),passed=passed,metrics=metrics,tau=tau))
                    if passed and len(packed)<len(best):best=packed;row['policy']='BOUNDED_C1';break
        if act.symbol in entries and archive.tracks(entries[act.symbol][1])[:3]!=archive.tracks(best)[:3]:
            raise ValueError('One symbol is shared by selected and unselected actions; select its whole ownership group')
        processed[key]=best;entries[act.symbol]=(act.symbol,best);row['bytes']=len(best);rows.append(row)
        log(f"{act.motion}: {len(original)} -> {len(best)} bytes ({row['policy']})")
        (out/'receipt.json').write_text(json.dumps(report,indent=2))
    bank,spans,packing=archive.pack(entries.values());oversized=[]
    for act in ft.actions:
        if act.symbol not in spans:continue
        offset,size=spans[act.symbol];at=ft.action_table[0]+act.index*ACTION_SIZE
        ft.dat.set_u32(at+4,offset);ft.dat.set_u32(at+8,size)
        if size>capacity:oversized.append(dict(action=act.index,motion=act.motion,bytes=size))
    report.update(output_bytes=len(bank),saved_bytes=len(aj)-len(bank),largest_clip=max(s for _,s in spans.values()),
                  packing=packing,oversized=oversized,status='CAPACITY_BLOCKED' if oversized else 'PACKED_GATES_PASS',
                  scope='Incremental sampled packed skin/FK error; source fidelity, blending and live gameplay are separate')
    if not oversized:
        output_pl=ft.to_bytes();(out/'fighter.dat').write_bytes(output_pl);(out/'animation.dat').write_bytes(bank)
        report.update(output_pl_sha256=sha(output_pl),output_aj_sha256=sha(bank))
        if combat_manifest is not None:
            updated=dict(combat_manifest,fighter_sha256=sha(output_pl),animation_sha256=sha(bank))
            updated['actions']=[]
            for entry in combat_manifest['actions']:
                act=ft.actions[entry['action']];offset,size=spans[act.symbol]
                updated['actions'].append(dict(entry,source=str((combat_path.parent/entry['source']).resolve()),
                                               animation_sha256=sha(bank[offset:offset+size])))
            _,check=prepare_contract(output_pl,bank,updated,out)
            if check['status']!='SOURCE_SCRIPTS_MATCH':raise ValueError('Compression changed the source combat contract')
            (out/'combat-contract.json').write_text(json.dumps(updated,indent=2))
    (out/'receipt.json').write_text(json.dumps(report,indent=2))
    return {k:v for k,v in report.items() if k not in ('rows','packing')}|dict(receipt=str(out/'receipt.json'),output=str(out),ok=not oversized)
