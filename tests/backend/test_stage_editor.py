import io
import json
import struct
import zipfile
from contextlib import contextmanager
from pathlib import Path
import pytest
from PIL import Image
from flask import Flask
from core import config
from shared.rendering import stage_editor
from randall.recolor import stage_lab as lab


def dat(value=0):
    body = bytes([value]) * 32
    name = b'map_head\0'
    return struct.pack('>5I', 32 + len(body) + 8 + len(name), len(body), 0, 1, 0) + bytes(12) + body + struct.pack('>2I',0,0) + name


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path)
    folder = tmp_path/'das/dreamland';folder.mkdir(parents=True)
    source = folder/'source.zip'
    with zipfile.ZipFile(source,'w') as z:
        z.writestr('GrOp-custom.dat',dat())
        z.writestr('companion.bin',b'untouched')
    metadata = {}
    @contextmanager
    def transaction(**kwargs):
        yield metadata
    monkeypatch.setattr(stage_editor,'metadata_transaction',transaction)
    return source,metadata


def test_save_preserves_archive_original_and_same_name_copies(vault):
    source, metadata = vault
    original=source.read_bytes()
    workspace=stage_editor.open_stage('GrOp','source')
    first=stage_editor.save_copy(workspace['id'],dat(1),'My Stage')
    second=stage_editor.save_copy(workspace['id'],dat(2),'My Stage')
    assert first['variantId'] != second['variantId']
    assert source.read_bytes() == original
    for result, value in ((first,1),(second,2)):
        with zipfile.ZipFile(source.parent/(result['variantId']+'.zip')) as z:
            assert z.read('companion.bin') == b'untouched'
            assert z.read('GrOp-custom.dat') == dat(value)
    assert len(metadata['stages']['dreamland']['variants']) == 2
    assert not metadata['stages']['dreamland']['variants'][0]['slippi_tested']


@pytest.mark.parametrize('bad',['../source','..','x/y','C:\\temp'])
def test_invalid_variants_never_resolve_paths(vault,bad):
    with pytest.raises(ValueError): stage_editor.open_stage('GrOp',bad)


def test_unknown_stage_and_changed_source_rejected(vault):
    with pytest.raises(ValueError): stage_editor.open_stage('../bad','source')
    ws=stage_editor.open_stage('GrOp','source')
    Path(ws['datFile']).write_bytes(dat(2))
    with pytest.raises(ValueError,match='changed'): stage_editor.save_copy(ws['id'],dat(3),'New')


def test_invalid_export_does_not_create_vault_entry(vault):
    source, metadata=vault;ws=stage_editor.open_stage('GrOp','source')
    with pytest.raises(ValueError): stage_editor.save_copy(ws['id'],b'invalid','New')
    assert list(source.parent.glob('*.zip')) == [source]
    assert metadata == {}


def test_http_open_save_and_errors(vault):
    from vault.routes.stage_editor import stage_editor_bp
    app=Flask(__name__);app.register_blueprint(stage_editor_bp)
    client=app.test_client()
    ws=client.post('/api/mex/stage-editor/open',json={'stageCode':'GrOp','variantId':'source'}).get_json()
    import base64
    response=client.post('/api/mex/stage-editor/save',json={'workspaceId':ws['id'],'name':'HTTP copy','data':base64.b64encode(dat(1)).decode()})
    assert response.status_code == 200 and response.json['vault_changed']
    assert client.post('/api/mex/stage-editor/save',json={'data':'%%%%'}).status_code == 400


def test_randall_actions_use_working_session_and_export_images(vault,monkeypatch):
    png=io.BytesIO();Image.new('RGBA',(4,4),'red').save(png,format='PNG')
    class Viewer:
        textures=[{'index':0,'name':'Group 0 / Texture 0','width':4,'height':4}]
        closed=False
        def material_command(self,command): return {'materials': []}
        def get_full_texture(self,index): return png.getvalue()
        def update_texture(self,index,data): self.updated=data
        def grab_frame(self): return png.getvalue()
        def export_dat(self): return dat(3)
        def close(self): self.closed=True
    viewer=Viewer();ws=stage_editor.open_stage('GrOp','source')
    lab._sessions[ws['id']]={'viewer':viewer,'source':ws,'used':0}
    try:
        result=lab.stage_lab(ws['id'],'texture',texture_index=0)
        assert result['files'][0]['extension']=='.png'
        result=lab.stage_lab(ws['id'],'recolor',hue_shift=60)
        assert result['changed']==[0] and viewer.updated
        with pytest.raises(ValueError): lab.stage_lab(ws['id'],'texture',texture_index=4)
        with pytest.raises(ValueError): lab.stage_lab(ws['id'],'camera',camera={'path':'bad'})
        result=lab.stage_lab(ws['id'],'save',name='Randall stage')
        assert result['vault_changed']
        assert lab.stage_lab(ws['id'],'close')['closed'] and viewer.closed
    finally: lab._sessions.pop(ws['id'],None)


def test_stage_edits_checkpoint_a_dat_for_the_workbench(vault):
    from randall.assistant import continuity
    from shared import mod_files
    png=io.BytesIO();Image.new('RGBA',(4,4),'red').save(png,format='PNG')
    class Viewer:
        textures=[{'index':0,'name':'Group 0 / Texture 0','width':4,'height':4}]
        def get_full_texture(self,index): return png.getvalue()
        def update_texture(self,index,data): pass
        def grab_frame(self): return png.getvalue()
        def material_command(self,command): return {"materials": []}
        def export_dat(self): return dat(5)
        def close(self): pass
    ws=stage_editor.open_stage('GrOp','source')
    lab._sessions[ws['id']]={'viewer':Viewer(),'source':ws,'used':0}
    try:
        opened=continuity.record_stage_result('stage_lab_open',{},{'session_id':ws['id']})
        assert mod_files.resolve(opened['checkpoint_file']['file_id'])[0].read_bytes()==dat()
        assert opened['stage_target']['stage_code']=='GrOp' and opened['revision']==1
        # Looking is not an edit: the checkpoint stays the opened source.
        looked=continuity.record_stage_result('stage_lab',{'session_id':ws['id'],'action':'frame'},lab.stage_lab(ws['id'],'frame'))
        assert looked['checkpoint_file']==opened['checkpoint_file']
        edited=continuity.record_stage_result('stage_lab',{'session_id':ws['id'],'action':'recolor'},lab.stage_lab(ws['id'],'recolor',hue_shift=60))
        assert mod_files.resolve(edited['checkpoint_file']['file_id'])[0].read_bytes()==dat(5)
        assert edited['revision']==3
        # Randall's own working context never offers a stage as a skin session to reopen.
        state=continuity.working_context([{'name':'stage_lab','arguments':{'session_id':ws['id']},'result':edited}])
        assert state['skin_sessions']==[]
    finally: lab._sessions.pop(ws['id'],None)


def test_checkpoint_viewer_paths_accept_a_stage(vault):
    from shared import mod_files
    from shared.routes.viewer import viewer_bp
    app=Flask(__name__);app.register_blueprint(viewer_bp)
    file=mod_files.register(dat(2),'GrOp.dat')
    response=app.test_client().post('/api/mex/viewer/paths-checkpoint',json={'stageCode':'GrOp','fileId':file['file_id']})
    assert response.status_code==200
    assert Path(response.json['datFile']).read_bytes()==dat(2) and 'sceneFile' not in response.json
