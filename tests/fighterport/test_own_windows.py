from copy import deepcopy
import pytest
from fighter_port.own_windows import release_loop


def paths():
    windows=[[1,'Startup',8],[9,'Charge 1',24],[33,'Charge 2',24],[57,'Charge 3',24],[81,'Full',24]]
    cancels=[dict(window=n,first=f,last=f+l-1,condition=dict(WindowCancelType='::SpecialReleased',
        PostCancelWindowStringTableKey='Throw',WindowCancelPrerequisite='::None',CancelIntoAttack='::None'))
        for f,n,l in windows[1:]]
    return dict(windows=windows,end=105,path_end='Full',window_cancels=cancels),dict(
        windows=[[1,'Throw',2],[3,'Active',7],[10,'Recovery',31]],conditional_only=True,path_end='',end=41)


def test_release_plan_keeps_full_charge_loop_and_distinct_release_start():
    a,b=paths()
    assert release_loop(a,b)==dict(release_first=9,stages=[9,33,57,81],loop_first=81,loop_end=105,destination='Throw')
    # Different recovery never changes the charge-loop clock.
    b['windows'][-1][2]=24;b['end']=34
    assert release_loop(a,b)['loop_end']==105


@pytest.mark.parametrize('change',[
    lambda a,b:a.update(path_end='Missing'),
    lambda a,b:a.update(path_end='Charge 2'),
    lambda a,b:a['windows'][2].__setitem__(0,34),
    lambda a,b:a['window_cancels'].pop(1),
    lambda a,b:a['window_cancels'][0].update(last=30),
    lambda a,b:a['window_cancels'][0]['condition'].update(NegatePrerequisite=True),
    lambda a,b:a['window_cancels'][0]['condition'].update(WindowCancelPrerequisite='::CharacterSpecific1'),
    lambda a,b:a['window_cancels'][0]['condition'].update(bPreseveWindowTimer=True),
    lambda a,b:a['window_cancels'][0]['condition'].update(CancelIntoAttack='::FirstSpecialAir'),
    lambda a,b:b.update(conditional_only=False),
])
def test_unsupported_control_flow_is_refused_instead_of_silently_flattened(change):
    a,b=paths();change(a,b)
    with pytest.raises(ValueError):release_loop(a,b)
