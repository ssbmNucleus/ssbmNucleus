import json
import struct
from pathlib import Path

import pytest

from fighter_port import compat
compat.install()
from fighter_port import own_opacity as native
from echo_rivals2 import opacity as source
from host_c import compile_and_run


def data():
    return dict(version=1, bindings=[dict(mesh='SashShape', default=1.0)], clips={
        'fade': dict(end=6, tracks={'SashShape': [0, 0, .25, .5, .75, 1, 1]}),
        'idle': dict(end=4, tracks={'SashShape': [1]})})


def test_unreal_curve_sampling_uses_source_seconds_and_retains_partial_values():
    curve = dict(Keys=[dict(Time=0, Value=0, InterpMode='RCIM_Cubic'),
                       dict(Time=4.9, Value=0, InterpMode='RCIM_Linear'),
                       dict(Time=5, Value=1, InterpMode='RCIM_Cubic')])
    record = dict(frames=390, seconds=389/60, curves=dict(FloatCurves=[dict(CurveName='sashvisible', FloatCurve=curve)]))
    assert source.samples(record, 'SashVisible', [0, 294, 295.5, 297, 300, 389]) == pytest.approx([0, 0, .25, .5, 1, 1])
    curve['Keys'] = [dict(Time=0, Value=0, InterpMode='RCIM_Cubic', LeaveTangent=2),
                     dict(Time=1, Value=1, InterpMode='RCIM_Cubic', ArriveTangent=0)]
    assert source.curve_value(curve, .5) == pytest.approx(.75)
    curve['Keys'][0]['TangentWeightMode'] = 'RCTWM_WeightedBoth'
    with pytest.raises(ValueError, match='weighted'):
        source.curve_value(curve, .5)
    curve['Keys'][0]['InterpMode'] = 'RCIM_Constant'
    assert source.curve_value(curve, .5) == 0
    curve['Keys'][0]['InterpMode'] = 'unexpected'
    with pytest.raises(ValueError, match='interpolation'):
        source.curve_value(curve, .5)


def test_source_only_maps_calibrated_material_lineage_and_replaces_a_split_clock():
    class Pak:
        def props(self, _):
            return [dict(Type='SkeletalMesh', SkeletalMaterials=[dict(MaterialSlotName='Sash', Material={
                'ObjectPath': 'Rivals2/Content/Characters/Ranno/MI_Ran_Sash_Standard.MI_Ran_Sash_Standard'})])]
        def default(self, _): return {}
    binding=dict(slots=['Sash'], parameter='Visible', curve='SashVisible', exclude_shield_mesh=True)
    pkg='Rivals2/Content/Characters/Ranno/Animation/Victory/AN_Ran_Victory'
    record=dict(frames=7, seconds=.1, curves=dict(FloatCurves=[dict(CurveName='SashVisible', FloatCurve=dict(
        Keys=[dict(Time=0, Value=0, InterpMode='RCIM_Linear'), dict(Time=.1, Value=1, InterpMode='RCIM_Linear')]))]))
    src=dict(renderer=dict(bindings=[binding]), clips={pkg:record})
    out=source.prepare(Pak(),src,dict(stems={'Victory':['win']},lengths={'Victory':6}), 'Ranno','Ran')
    assert out['clips']['win']['tracks']['SashShape'] == pytest.approx([i/6 for i in range(7)])
    source.carry(out,src,pkg,'win',[3,4,6])
    assert out['clips']['win']['end'] == 2
    assert out['clips']['win']['tracks']['SashShape'] == pytest.approx([.5,2/3,1])
    source.carry(out,src,pkg,'win',[-1,3,7])
    assert out['clips']['win']['tracks']['SashShape'] == pytest.approx([0,.5,1])
    binding['parameter']='Dissolve'
    other=source.prepare(Pak(),src,dict(stems={},lengths={}), 'Ranno','Ran')
    assert not other['bindings'] and other['unresolved'][0]['reason']=='uncalibrated material binding'


def test_jobs_follow_split_hold_and_retimed_animation_clocks():
    d=data()
    j=dict(parts=[dict(stem='fade', keys=[[0,1],[2,5]]), dict(stem='idle',keys=[[0,0],[1,4]])])
    assert native.job_tracks(d,j,{'fade':6,'idle':4}) == {'SashShape':[(0.,0.),(2.,1.),(4.,1.)]}
    j=dict(parts=[dict(stem='fade',keys=[[0,3]])])
    assert native.job_tracks(d,j,{'fade':6}) == {'SashShape':[(0.,.5),(1.,.5)]}
    with pytest.raises(ValueError,match='clocks disagree'):
        native.job_tracks(d,dict(parts=[dict(stem='fade')]),{'fade':7})


def test_binding_resolves_each_mesh_subindex_and_only_its_low_detail_copies():
    receipt=dict(mesh_groups=[dict(name=n) for n in ['Body','SashShape','SashShape','Eye']],
                 pieces=dict(high=[0],groups=[[[3],[]],[[1,2]]],rest=[1,0],low=[4,5,6]),
                 faces=dict(opacity={'SashShape':2}))
    binding=native.pieces(data(),receipt)[0]
    assert binding['pieces']==[1,2,5,6] and binding['group']==2
    layout=native.low_lists(receipt['pieces'],receipt['faces'])
    assert layout['low']==[4,5,6] and layout['low_body']==[4] and layout['low_groups']==[[],[[5,6]]]


def test_opacity_reserves_independent_visibility_groups_and_low_detail_tables():
    from fighter_port import own_faces,own_data
    faces=own_faces.plan({'idle':dict(end=4,tracks={})},'idle')
    reserved=native.reserve_faces(faces,data())
    assert not faces['groups'] and reserved['opacity']=={'SashShape':1}
    assert reserved['shown_at_rest']==['Sash'] and reserved['groups'][0]['choices']==[['Sash']]
    with pytest.raises(ValueError,match='combining'):
        native.reserve_faces(reserved,data())
    blob,slots,at=own_data.model_lists([1],[3],[[[0]]],[[[2]]])(0)
    def u(o):return struct.unpack_from('>I',blob,o)[0]
    def pieces(table,group):
        row=at[table]+8*group
        assert u(row)==1
        choice=u(row+4);start=u(choice+4)
        return list(blob[start:start+u(choice)])
    assert pieces('high',0)==[1] and pieces('high',1)==[0]
    assert pieces('low',0)==[3] and pieces('low',1)==[2]
    assert u(at['metal'])==u(at['metal']+8)==0
    with pytest.raises(ValueError,match='choices'):
        own_data.model_lists([1],[3],[[[0]]],[[[2],[3]]])


def archive():
    # A real descriptor layout, with one controlled material and one untouched material.
    body=bytearray(0x108)
    def u(off,value):struct.pack_into('>I',body,off,value)
    u(16,0x40);u(0x44,0x50);u(0x48,0x60);u(0x58,0x78)
    u(0x64,0x105);u(0x6C,0x90);u(0x74,0xB8)
    u(0x7C,0x105);u(0x84,0xA4)
    struct.pack_into('>f',body,0x9C,1);struct.pack_into('>f',body,0xB0,1)
    body[0xB8:0xC4]=bytes([0x39,1,2,0,0,1,0,15,3,6,0,6])
    rel=[16,0x44,0x48,0x58,0x6C,0x74,0x84]
    table=b''.join(struct.pack('>I',p) for p in rel)+struct.pack('>II',0,0)+b'test_joint\0'
    header=struct.pack('>5I',32+len(body)+len(table),len(body),len(rel),1,0)+bytes(12)
    return header+body+table


def test_costume_blends_before_shader_creation_preserves_unbound_material_and_relocations():
    from fighter_port.compat.rig_inventory import Archive
    before=archive()
    after,changed=native.patch_costume(before,'test_joint',[dict(mesh='SashShape',pieces=[0],default=1.)])
    old,new=Archive(before),Archive(after)
    assert changed==[0] and new.relocs==old.relocs
    assert new.u32(0x64)==0x60002105 and new.u32(0x7C)==old.u32(0x7C)
    assert after[32+0x78:32+0x90]==before[32+0x78:32+0x90]
    assert after[32+0xA4:32+0xB8]==before[32+0xA4:32+0xB8]
    assert after[32+0xB8:32+0xC4]==bytes([0x19,1,2,0,1,4,5,15,3,7,0,7])
    old.set_u32(0x84,0x90)
    with pytest.raises(ValueError,match='shared'):
        native.patch_costume(old.to_bytes(),'test_joint',[dict(mesh='SashShape',pieces=[0],default=1.)])


def test_generated_runtime_fractional_clock_interrupt_two_fighters_demo_and_unknown_table(tmp_path):
    bindings=[dict(mesh='SashShape',pieces=[0,2],default=1.,group=1)]
    tracks={'SashShape':[(0.,0.),(4.,0.),(6.,1.)]}
    generated=native.code(None,bindings,{7:tracks},{3:tracks})
    header='''#include <assert.h>
#include <stdint.h>
#include <math.h>
typedef int FtAction;
typedef struct {float alpha;} Material;
typedef struct {Material *mat;} MOBJ;
typedef struct {MOBJ *mobj;} DOBJ;
typedef struct {FtAction *ftaction;uintptr_t x14;} Data;
typedef struct {int action_id;struct {float frame;} state;DOBJ **dobj_lookup;FtAction *ftaction;Data *ftData;int group[2];} FighterData;
typedef struct {FighterData *userdata;} GOBJ;
void Fighter_SetVisGroupCurrent(GOBJ *g,int group,int choice){g->userdata->group[group]=choice;}
'''
    main='''int main(void){
FtAction main_table=0,demo=0,unknown=0;Data data={&main_table,(uintptr_t)&demo};
Material m[6]={{1},{.75f},{1},{1},{.75f},{1}};
MOBJ mm[6];DOBJ dd[6];DOBJ *one[3],*two[3];
for(int i=0;i<6;i++){mm[i].mat=&m[i];dd[i].mobj=&mm[i];if(i<3)one[i]=&dd[i];else two[i-3]=&dd[i];}
FighterData a={7,{4.5f},one,&main_table,&data},b={7,{6},two,&main_table,&data};
GOBJ ga={&a},gb={&b};
OpacityFrame(&a,&ga);OpacityFrame(&b,&gb);
assert(m[0].alpha==.25f && m[2].alpha==.25f && m[3].alpha==1 && m[5].alpha==1 && m[1].alpha==.75f);
OpacityFrame(&a,&ga);assert(m[0].alpha==.25f); /* frozen clock/hitlag does not advance */
a.action_id=99;OpacityFrame(&a,&ga);assert(m[0].alpha==1 && m[2].alpha==1 && a.group[1]==0);
a.ftaction=&demo;a.action_id=3;a.state.frame=4;OpacityFrame(&a,&ga);assert(m[0].alpha==0 && a.group[1]==-1);
a.state.frame=5.5f;OpacityFrame(&a,&ga);assert(m[0].alpha==.75f && a.group[1]==0);
a.state.frame=100;OpacityFrame(&a,&ga);assert(m[0].alpha==1);
a.state.frame=-1;OpacityFrame(&a,&ga);assert(m[0].alpha==0 && a.group[1]==-1);
a.ftaction=&unknown;OpacityFrame(&a,&ga);assert(m[0].alpha==1 && a.group[1]==0);
a.dobj_lookup=0;OpacityFrame(&a,&ga);return 0;}
'''
    compile_and_run(tmp_path,header+'\n'.join(generated['source'])+main)
    assert generated['load']==['GObj_AddProc(gobj, OpacityProc, 23);'] and not generated['frame']


def test_reader_schema_rejects_nonfinite_wrong_duration_and_ambiguous_names(tmp_path):
    path=tmp_path/'gamedata/fighter/example/game.json';path.parent.mkdir(parents=True)
    d=data()
    for mutate in (lambda: d['clips']['fade']['tracks']['SashShape'].append(1),
                   lambda: d['bindings'].append(d['bindings'][0]),
                   lambda: d['bindings'][0].update(default=float('nan'))):
        mutate();path.write_text(json.dumps(dict(material_opacity=d)))
        with pytest.raises(ValueError):native.read(tmp_path,'example')
        d=data()
