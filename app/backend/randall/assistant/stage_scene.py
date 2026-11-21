"""Bounded stage scenery operations over immutable, server-owned file handles."""
import json
import math
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from shared import mod_files

SCENE_OPERATIONS = {
    'stage_scene': 'Inspect stage groups and exact scene object IDs. Preview IDs before selecting scenery.',
    'preview_stage_objects': 'Render selected scene object IDs in isolation; does not edit the working file.',
    'copy_stage_objects': 'Copy objects from one donor group into a target render group, retaining materials and supported animation; returns a new DAT and scenery instance ID.',
    'transform_stage_scenery': 'Move, rotate or uniformly scale a previously copied scenery instance; returns a new DAT.',
    'hide_stage_objects': 'Hide exact scene objects while retaining joints, animation indices and collision data; returns a new DAT.',
}


def run_scene(operation, file_id, *, donor_file_id=None, object_ids=None, target_group=None,
              instance_id=None, transform=None, animation_index=None):
    from .hsdraw import _run
    action = {'stage_scene': 'inspect', 'preview_stage_objects': 'preview', 'copy_stage_objects': 'copy',
              'transform_stage_scenery': 'transform', 'hide_stage_objects': 'hide'}[operation]
    allowed = {'inspect': set(), 'preview': {'object_ids'}, 'hide': {'object_ids'},
               'copy': {'donor_file_id', 'object_ids', 'target_group', 'transform', 'animation_index'},
               'transform': {'instance_id', 'transform'}}[action]
    args = dict(donor_file_id=donor_file_id, object_ids=object_ids, target_group=target_group,
                instance_id=instance_id, transform=transform, animation_index=animation_index)
    if any(value is not None and key not in allowed for key, value in args.items()):
        raise ValueError('Unsupported arguments for this scene operation')
    if action in {'copy', 'hide', 'preview'}:
        if not isinstance(object_ids, list) or not 1 <= len(object_ids) <= 256 or any(not isinstance(i, str) or not re.fullmatch(r'\d{1,4}:\d{1,4}:\d{1,4}', i) for i in object_ids) or len(set(object_ids)) != len(object_ids):
            raise ValueError('Choose 1..256 unique object IDs from scene inspection')
    if transform is not None:
        if not isinstance(transform, dict) or not transform or set(transform) - {'x','y','z','rx','ry','rz','scale'}:
            raise ValueError('Use x/y/z, rx/ry/rz in degrees, and uniform scale')
        for key, value in transform.items():
            bounds = (0.01,100) if key == 'scale' else (-360,360) if key.startswith('r') else (-10000,10000)
            if type(value) not in (int,float) or not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
                raise ValueError('Invalid scenery transform')
    source, info = mod_files.resolve(file_id)
    mod_files.dat_roots(source)
    origin = mod_files.origin_of(info)
    instances = dict(origin.get('scene_instances') or {})
    spec = {'action': action}
    if object_ids is not None: spec['object_ids'] = object_ids
    if transform is not None: spec['transform'] = transform
    if action == 'transform':
        if not isinstance(instance_id,str) or instance_id not in instances or transform is None:
            raise ValueError('Choose a scenery instance ID copied into this working file and provide its absolute transform')
        spec['instance'] = instances[instance_id]
    donor = None
    if action == 'copy':
        if type(target_group) is not int or not 0 <= target_group <= 4095:
            raise ValueError('Choose a can_receive target group from scene inspection')
        if animation_index is not None and (type(animation_index) is not int or not 0 <= animation_index <= 255):
            raise ValueError('Invalid animation index')
        donor, _ = mod_files.resolve(donor_file_id); mod_files.dat_roots(donor)
        spec.update(target_group=target_group, animation_index=animation_index or 0)
    with tempfile.TemporaryDirectory(prefix='stage-scene-', dir=mod_files.root()) as scratch:
        directory = Path(scratch); input_path = directory/'target.dat'; shutil.copyfile(source,input_path)
        report = directory/'report.json'; output = directory/'result.dat'
        if donor:
            donor_path=directory/'donor.dat'; shutil.copyfile(donor,donor_path); spec['donor']=str(donor_path)
        if action == 'inspect':
            _run(['--stage-scene','inspect',input_path,report],directory)
            return {'operation': operation, **json.loads(report.read_text()), 'files': []}
        spec_path=directory/'spec.json'; spec_path.write_text(json.dumps(spec))
        _run(['--stage-scene','edit',input_path,spec_path,output,report],directory)
        if not output.is_file() or not 0 < output.stat().st_size <= mod_files.MAX_FILE:
            raise ValueError('Scenery result exceeds the 128 MB file limit')
        mod_files.dat_roots(output)
        result=json.loads(report.read_text()); result.update(operation=operation,files=[])
        if action == 'preview':
            picture=directory/'selection.png'; _run(['--stage-render',output,picture],directory)
            result['files']=[mod_files.register(picture.read_bytes(),'Selected stage scenery.png')]
            return result
        if action == 'copy':
            instance_id=uuid.uuid4().hex; instances[instance_id]=result.pop('instance')
        origin['scene_instances']=instances
        result['instance_id']=instance_id
        result['files']=[mod_files.register(output.read_bytes(),Path(info['name']).stem+'-scenery.dat',origin=origin,edited=True)]
        return result
