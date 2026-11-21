"""
Echo package: the materialise step over a synthetic donor package.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from vault.echo import package as echo_package
from vault.echo import ops as echo_ops
from tests.backend.test_echo_ops import build_synthetic_dat


def _synthetic_donor_zip() -> bytes:
    dat = build_synthetic_dat()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('fighter.json', json.dumps({'name': 'Test', 'files': {'fighterDataPath': 'PlTe.dat'}}))
        zf.writestr('PlTe.dat', dat)
        zf.writestr('PlTeAJ.dat', b'\0' * 64)
        zf.writestr('PlTeNr.zip', b'PK')
    return buf.getvalue()


def test_materialize_patches_only_the_data_dat_and_renames():
    donor = _synthetic_donor_zip()
    echo = {'donor': 'Test', 'donor_prefix': 'PlTe', 'name': 'Echo Test',
            'ops': [{'op': 'set_hitbox', 'move': 'ftilt', 'hitbox': 0, 'field': 'damage', 'value': 14}]}
    out, report = echo_package.materialize(donor, echo)
    assert report['changed'] == 1 and report['data_dat'] == 'PlTe.dat'
    with zipfile.ZipFile(io.BytesIO(out)) as zf:
        assert set(zf.namelist()) == {'fighter.json', 'PlTe.dat', 'PlTeAJ.dat', 'PlTeNr.zip', 'echo.json'}
        assert json.loads(zf.read('fighter.json'))['name'] == 'Echo Test'
        assert zf.read('PlTeAJ.dat') == b'\0' * 64
        assert json.loads(zf.read('echo.json'))['version'] == echo_package.VERSION
    assert echo_package.read_echo(out)['name'] == 'Echo Test'
    assert echo_package.read_echo(donor) is None
    # the diff comes back out of the materialised package
    recovered = echo_package.recover_ops(donor, out)
    assert recovered == [{'op': 'set_hitbox', 'hitbox': 0, 'move': 'ftilt', 'part': 'mid',
                          'field': 'damage', 'value': 14}]
    # deterministic: same inputs, same data DAT
    out2, _ = echo_package.materialize(donor, echo)
    assert echo_package.donor_dat_bytes(out2) == echo_package.donor_dat_bytes(out)


def test_materialize_refuses_bad_ops():
    donor = _synthetic_donor_zip()
    with pytest.raises(echo_ops.OpError):
        echo_package.materialize(donor, {'name': 'x', 'ops': [{'op': 'set_hitbox', 'move': 'usmash', 'hitbox': 0, 'field': 'damage', 'value': 1}]})
