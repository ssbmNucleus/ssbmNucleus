"""MCP entry points for repeatable native-port inspection and isolated repairs."""
import json
import hashlib
from pathlib import Path

def handle(args, log):
    from .compat import install
    install()
    op=args.get('op','info')
    from .port_preparation import OPERATIONS as preparation_ops
    if op in preparation_ops:
        from .port_preparation import handle as prepare
        return prepare(args,log)
    if op=='port':
        # Match the current CLI; gameplay calibration and the fidelity backlog are optional.
        from types import SimpleNamespace
        from . import port as whole
        need=[k for k in ('fighter','name','work','root') if not args.get(k)]
        if need:
            return dict(error=f'port needs {need}',takes=['fighter','game (ultimate|brawl|slapcity|rivals2)','donor','name','work','root','body','iso','mextk','own','from','to','only','calibrate'])
        return whole.run(SimpleNamespace(fighter=args['fighter'],game=args.get('game','ultimate'),donor=args.get('donor','Marth'),
            name=args['name'],work=args['work'],root=args['root'],body=args.get('body'),rip=args.get('rip'),iso=args.get('iso'),mextk=args.get('mextk'),
            repo=args.get('repo'),start=args.get('from'),to=args.get('to'),only=args.get('only'),
            own=args.get('own',args.get('game') in ('slapcity','rivals2')),calibrate=args.get('calibrate',False),
            tests=args.get('tests'),forms_from=args.get('forms_from'),allow_large=args.get('allow_large',False)),log)
    if op=='checklist':
        # The list a port is finished against. With `work`: that port's answers. With `line`, `answer`, `how`: record one.
        from . import port as whole
        work=args.get('work')
        if work and args.get('line'):
            whole.record(work,args['line'],args.get('answer'),args.get('how'))
        rows=whole.lines();got=whole.answers(work) if work else {}
        return dict(file=str(whole.CHECKLIST),lines=len(rows),answered=sum(1 for r in rows if r['id'] in got),
            unanswered=[dict(id=r['id'],section=r['section'],text=r['text']) for r in rows if r['id'] not in got],
            differences=whole.differences(work) if work else [],answers=list(whole.ANSWERS),
            rule='Optional fidelity backlog; unfilled lines do not block packaging. Build completion does not prove full source fidelity.')
    if op=='info':
        return dict(pipeline=str(Path(__file__).with_name('ULTIMATE_PORT_PIPELINE.md')),
            checklist=str(Path(__file__).with_name('PORT_CHECKLIST.md')),
            operations=['info','port','checklist','audit','movement_audit','movement_repair','hitbox_rebase','source_combat_audit','source_combat_install','compress','scale','materials','costume','visibility','pack','preflight',*preparation_ops],
            preparation=str(Path(__file__).with_name('PORT_PREPARATION.md')),
            internal_build_services=['special_physics_hooks.compose (explicit fighter_state_id selection; no raw-C MCP endpoint)'],
            compiler=str(Path(__file__).parent/'tools/FigaCodec/README.md'),
            rules=['Every owned action must use the native joint domain; foreign victim rows require explicit ownership.',
                   'Run plan_rig on raw selected meshes; animation alone does not keep an otherwise unused joint live.',
                   'Run source_visibility with an explicit fallback; missing tracks remain unresolved. Offline hiding needs a bound runtime visibility manifest.',
                   'Run costume_budget before decimation; when tiled image bytes dominate, reduce texture dimensions first.',
                   'Run animation_diagnose before fitting or codec changes; never infer source fidelity from incremental packing error.',
                   'Audit reachable subroutine/jump and demo scripts, not only action entry blocks.',
                   'Use source_mesh_handoff.prepare(..., uv_convention="hsd_smd") for Ultimate -> HSD SMD.',
                   'Texture1 eye layers require explicit secondary UV bake; SMD roundtrip cannot prove texture orientation.',
                   'Model scale changes bone matrices and root travel, not script hitbox radii.',
                   'Assign travel to the actual physics consumer; never blanket-zero unknown special roots.',
                   'Hitbox coordinates are bone-local XYZ; packed editor x_offset is local Z, z_offset is local X.',
                   'Changing a hitbox bone requires a measured coordinate transform, not a global mirror switch.',
                   'Donor combat scripts do not become source attacks when an animation is replaced; bind named source bones and the actual converted pose clock.',
                   'Separate geometry, byte-layout, source-fidelity, live-contact and full-gameplay acceptance.'])
    if op=='audit':
        from .compat.fighter_scale import reachable_commands, scale_offset
        from vault.echo.subactions import FighterDat
        import struct
        path=Path(args['fighter']);blob=path.read_bytes();ft=FighterDat(blob)
        cmds=reachable_commands(ft)
        hits=[c for c in cmds.values() if c.code==0x0B]
        return dict(path=str(path.resolve()),sha256=hashlib.sha256(blob).hexdigest(),
                    roots=ft.dat.roots,actions=len(ft.actions),reachable_commands=len(cmds),
                    hitboxes=len(hits),ignore_runtime_scale=sum(bool(c.fields['ignore_fighter_scale']) for c in hits),
                    model_scale=struct.unpack_from('>f',ft.dat.buf,scale_offset(ft))[0],
                    acceptance='INVENTORY_ONLY')
    if op=='movement_audit':
        from .compat.movement_ownership import audit_bank
        return audit_bank(Path(args['fighter']).read_bytes(),Path(args['animation']).read_bytes(),
                          root_joint=args['root_joint'],motions=args['motions'],
                          engine_root_joint=args.get('engine_root_joint'),contracts=args.get('movement_contracts'))
    if op in ('source_combat_audit','source_combat_install'):
        from .source_combat import handle as source_combat
        return source_combat(args)
    if op=='compress':
        from .animation_compression import compress
        return compress(args,log)
    if op=='preflight':
        from shared.ingame.rig_preflight import prepare,costume_binding
        costume=Path(args['costume']).read_bytes()
        report=prepare(costume,Path(args['fighter']).read_bytes(),Path(args['animation']).read_bytes(),
                       required_actions=args['required_actions'],foreign_skeletons=args.get('foreign_skeletons',{}),
                       animation_capacity=args.get('animation_capacity',32768),
                       movement_root=args.get('movement_root'),
                       visibility_manifest=json.loads(Path(args['visibility_manifest']).read_text()) if args.get('visibility_manifest') else None)
        if args.get('definition'):report['costume_binding']=costume_binding(costume,json.loads(Path(args['definition']).read_text()))
        return report
    out=Path(args['out']).resolve()
    if out.exists():raise ValueError('Choose a new output path to preserve earlier evidence')
    if op=='movement_repair':
        from .compat.movement_ownership import repair_common_bank,audit_bank
        pl=Path(args['fighter']).read_bytes();aj=Path(args['animation']).read_bytes()
        options=dict(root_joint=args['root_joint'],motions=args['motions'],
                     engine_root_joint=args.get('engine_root_joint'),contracts=args.get('movement_contracts'))
        fixed_pl,fixed_aj,changes=repair_common_bank(pl,aj,**options)
        receipt=audit_bank(fixed_pl,fixed_aj,**options)
        if receipt['status']!='MOVEMENT_CONTRACTS_PASS':raise ValueError('Movement repair failed readback')
        receipt.update(changes=changes,input_pl_sha256=hashlib.sha256(pl).hexdigest(),
                       input_aj_sha256=hashlib.sha256(aj).hexdigest(),
                       output_pl_sha256=hashlib.sha256(fixed_pl).hexdigest(),
                       output_aj_sha256=hashlib.sha256(fixed_aj).hexdigest())
        out.mkdir(parents=True);(out/'fighter.dat').write_bytes(fixed_pl);(out/'animation.dat').write_bytes(fixed_aj)
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2));return dict(output=str(out),**receipt)
    if op=='hitbox_rebase':
        from .hitbox_coordinates import apply
        blob,receipt=apply(Path(args['fighter']).read_bytes(),json.loads(Path(args['bindings']).read_text()))
        out.parent.mkdir(parents=True);out.write_bytes(blob)
        out.with_suffix('.hitboxes.json').write_text(json.dumps(receipt,indent=2));return dict(output=str(out),**receipt)
    if op=='visibility':
        from .static_visibility import apply
        blob,receipt=apply(Path(args['fighter']).read_bytes())
        out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(blob)
        out.with_suffix('.visibility.json').write_text(json.dumps(receipt,indent=2))
        return dict(output=str(out),**receipt)
    if op=='pack':
        from .compat.animation_archive import pack
        from vault.echo.subactions import FighterDat,ACTION_SIZE
        pl=Path(args['fighter']).read_bytes();aj=Path(args['animation']).read_bytes();ft=FighterDat(pl)
        entries={x.symbol:(x.symbol,aj[x.anim_offset:x.anim_offset+x.anim_size]) for x in ft.actions if x.symbol and x.anim_size}
        options={}
        if args.get('target_rig') or args.get('clip_receipts'):
            from .rig_dependencies import rig_fingerprint
            if not args.get('target_rig') or not args.get('clip_receipts'):raise ValueError('target_rig and clip_receipts are required together')
            options=dict(rig_sha256=rig_fingerprint(json.loads(Path(args['target_rig']).read_text())),
                         clip_receipts={symbol:json.loads(Path(path).read_text()) for symbol,path in args['clip_receipts'].items()})
        bank,spans,receipt=pack(entries.values(),**options);table,_=ft.action_table
        for act in ft.actions:
            if act.symbol in spans:
                offset,size=spans[act.symbol];base=table+act.index*ACTION_SIZE
                ft.dat.set_u32(base+4,offset);ft.dat.set_u32(base+8,size)
        out.mkdir(parents=True);(out/'fighter.dat').write_bytes(ft.dat.to_bytes());(out/'animation.dat').write_bytes(bank)
        receipt.update(input_pl_sha256=hashlib.sha256(pl).hexdigest(),input_aj_sha256=hashlib.sha256(aj).hexdigest(),
                       output_aj_sha256=hashlib.sha256(bank).hexdigest(),acceptance='LOSSLESS_ARCHIVE_PACKING')
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2));return dict(output=str(out),**receipt)
    if op=='scale':
        from .compat.fighter_scale import apply
        baseline=Path(args['baseline']).read_bytes() if args.get('baseline') else None
        blob,receipt=apply(Path(args['fighter']).read_bytes(),float(args['target']),
                           baseline=baseline,offset_policy=args.get('offset_policy','preserve_local'))
        out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(blob)
        out.with_suffix('.scale.json').write_text(json.dumps(receipt,indent=2))
        return dict(output=str(out),**receipt)
    if op=='materials':
        import ssbh_data_py as ssbh
        from .ultimate_materials import bake
        root=Path(args['model_dir'])
        mesh=ssbh.mesh_data.read_mesh(str(root/'model.numshb'))
        selection=json.loads(Path(args['selection']).read_text())
        rows=bake(root,mesh,selection,out,args['texture_tool'],color_layers=args.get('color_layers'),
                  max_texture_dimension=args.get('max_texture_dimension'),preserve_materials=args.get('preserve_materials',[]))
        receipt=dict(schema='ultimate-materials-v1',uv_origin='top_left',rows=rows,acceptance='STATIC_COLOR_BAKE')
        (out/'materials.json').write_text(json.dumps(receipt,indent=2))
        return receipt
    if op=='costume':
        from .costume import add_empty_material_tree,static_materials
        from core.config import HSDRAW_EXE
        blob,receipt=add_empty_material_tree(Path(args['costume']).read_bytes())
        staged=out.with_suffix('.empty-material-tree.dat')
        if staged.exists():raise ValueError('Staging output already exists')
        staged.parent.mkdir(parents=True,exist_ok=True);staged.write_bytes(blob)
        return static_materials(staged,args['fighter'],args['joint_symbol'],out,HSDRAW_EXE)
    raise ValueError(f'Unknown native_port operation: {op}')
