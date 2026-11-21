import pytest
from shared.ingame.pose import validate_captured_worlds, CaptureError


def table():
    return [dict(index=i,world=[0.]*12) for i in range(3)]


def test_complete_world_table_retained():
    rows=table()
    assert validate_captured_worlds(rows,3) is rows


@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,None,'0'])
def test_nonfinite_or_nonnumeric_matrix_cannot_pass(value):
    rows=table(); rows[1]['world'][2]=value
    with pytest.raises(CaptureError): validate_captured_worlds(rows,3)


@pytest.mark.parametrize('defect',['empty','duplicate','order','shape','bool_index'])
def test_malformed_domain_refused(defect):
    rows=table()
    if defect=='empty': rows=[]
    if defect=='duplicate': rows[1]['index']=0
    if defect=='order': rows.reverse()
    if defect=='shape': rows[1]['world'].pop()
    if defect=='bool_index': rows[1]['index']=True
    with pytest.raises(CaptureError): validate_captured_worlds(rows,3)
