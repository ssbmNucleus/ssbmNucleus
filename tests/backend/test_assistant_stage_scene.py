import importlib
import json
from pathlib import Path
import pytest
from shared import mod_files
from randall.recolor import stage_lab
from randall.assistant.hsdraw import hsdraw
from tests.backend.test_stage_editor import dat
from core import config


@pytest.fixture
def scene(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'STORAGE_PATH',tmp_path)
    target=mod_files.register(dat(),'GrNLa.dat',origin={'stage_workspace':'a'*32,'stage_code':'GrNLa'})
    donor=mod_files.register(dat(1),'GrGd.dat')
    calls=[]
    def run(argv,directory):
        assert argv[:2]==['--stage-scene','edit']
        spec=json.loads(Path(argv[3]).read_text());calls.append(spec)
        assert Path(argv[2]).is_relative_to(directory)
        if 'donor' in spec: assert Path(spec['donor']).is_relative_to(directory)
        Path(argv[4]).write_bytes(dat(2))
        Path(argv[5]).write_text(json.dumps({'scene':{'groups':[],'objects':[]},'instance':{'group':3,'joint':5,'base_scale':1}}))
        return ''
    monkeypatch.setattr(importlib.import_module('randall.assistant.hsdraw'),'_run',run)
    return target,donor,calls


def test_copy_transform_lineage_and_immutable_inputs(scene):
    target,donor,calls=scene
    result=hsdraw('copy_stage_objects',target['file_id'],donor_file_id=donor['file_id'],object_ids=['4:0:0'],target_group=3)
    copied=result['files'][0];instance=result['instance_id']
    assert len(instance)==32 and copied['file_id']!=target['file_id']
    moved=hsdraw('transform_stage_scenery',copied['file_id'],instance_id=instance,transform={'z':-50,'scale':1.2})
    assert moved['files'][0]['file_id']!=copied['file_id']
    assert calls[-1]['instance']=={'group':3,'joint':5,'base_scale':1}
    assert mod_files.resolve(target['file_id'])[0].read_bytes()==dat()
    assert mod_files.resolve(donor['file_id'])[0].read_bytes()==dat(1)
    with pytest.raises(ValueError,match='instance'):
        hsdraw('transform_stage_scenery',target['file_id'],instance_id=instance,transform={'x':5})


@pytest.mark.parametrize('changes',[
    {'object_ids':['../outside']},{'object_ids':['4:0:0','4:0:0']},
    {'target_group':True},{'donor_file_id':'C:/private.dat'},
    {'transform':{'scale':0}},{'transform':{'x':float('nan')}},
    {'transform':{'command':'delete'}},{'animation_index':-1},
])
def test_invalid_scene_arguments_never_launch_native(scene,changes):
    target,donor,calls=scene
    args=dict(donor_file_id=donor['file_id'],object_ids=['4:0:0'],target_group=3)
    with pytest.raises(ValueError): hsdraw('copy_stage_objects',target['file_id'],**(args|changes))
    assert not calls


def test_failed_replacement_viewer_keeps_current_working_session(scene,monkeypatch):
    target,donor,_=scene
    class Viewer:
        closed=False
        def export_dat(self):return dat()
        def close(self):self.closed=True
    viewer=Viewer()
    stage_lab._sessions['test']={'viewer':viewer,'source':{'stage_code':'GrNLa','datName':'GrNLa.dat'},'used':0}
    edited=hsdraw('copy_stage_objects',target['file_id'],donor_file_id=donor['file_id'],object_ids=['4:0:0'],target_group=3)
    monkeypatch.setattr(stage_lab,'run_scene',lambda *a,**kw:edited)
    def failed(*a,**kw):raise RuntimeError('Viewer failed')
    monkeypatch.setattr(stage_lab,'ViewerSession',failed)
    try:
        with pytest.raises(RuntimeError,match='Viewer failed'):
            stage_lab.stage_lab('test','hide_objects',object_ids=['1:0:0'])
        assert stage_lab._sessions['test']['viewer'] is viewer and not viewer.closed
    finally:stage_lab._sessions.pop('test')
