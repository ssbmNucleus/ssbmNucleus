from types import SimpleNamespace
import numpy as np
import pytest
from echo_slapcity import gamedata
from fighter_port.oneshot import stretches


class Skeleton:
    names=['Hip']
    clips={'spin':object()}
    def pose(self, clip, frame):
        angle=np.pi*frame/2
        c,s=np.cos(angle),np.sin(angle)
        # Bone scale and rotation must not change the separate world offset.
        matrix=np.eye(4)
        matrix[:3,:3]=np.array([[c,-s,0],[s,c,0],[0,0,1]])@np.diag([2,3,1])
        matrix[:3,3]=[1,2,3]
        return {'Hip':matrix}
    def joint_worlds(self, pose):
        return pose


def test_reader_preserves_world_units_and_rotating_bone_offsets_without_rehits():
    rd=gamedata.Reader(SimpleNamespace(name='sample'),{'attack':dict(dmg=10)},
        dict(unit=2,world_unit=5,armature_scale=3,shortcuts={'body':'Hip'}),1)
    hit=rd.hitbox(dict(h=0,p='attack',b='body',r=.8,l=[1,2,0],w=[2.1,1,0]),1,7)
    hit['last']=3
    assert hit['world_offset']==pytest.approx([-10.5,5,0])
    original=np.array([hit['x'],hit['y'],hit['z'],1])
    entry=dict(clip='spin',hitboxes=[hit],time_keys=[[0,0],[3,3]])
    gamedata.world_hit_offsets({'game_speciallw':entry},Skeleton())
    assert len(entry['hitboxes'])==3
    for frame,row in enumerate(entry['hitboxes']):
        matrix=Skeleton().pose(None,frame)['Hip']
        actual=matrix@np.array([row['x'],row['y'],row['z'],1])
        expected=matrix@original+np.array([-10.5,5,0,0])
        assert actual==pytest.approx(expected)
    assert [(a,b,continues) for a,b,_,continues in stretches(entry['hitboxes'],3)]==[(1,1,False),(2,2,True),(3,3,True)]
    assert all(h['run']==7 and h['damage']==10 for h in entry['hitboxes'])


def test_zero_offset_does_not_require_a_clip_and_missing_pose_does_not_collapse_geometry():
    zero=dict(bone='hip',first=1,last=4,world_offset=[0,0,0])
    entry=dict(hitboxes=[zero])
    gamedata.world_hit_offsets({'test':entry},Skeleton())
    assert entry['hitboxes']==[zero]
    zero['world_offset']=[1,0,0]
    with pytest.raises(ValueError,match='needs its source clip'):
        gamedata.world_hit_offsets({'test':entry},Skeleton())
