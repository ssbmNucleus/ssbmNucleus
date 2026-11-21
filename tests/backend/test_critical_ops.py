"""Guards core.critical_ops -- the registry that defers app shutdown while an
ISO export/save/download is mid-flight (the truncated-ISO black-screen bug).
The hard constraints: an op is visible exactly for its lifetime, an op that
ends on an exception still ends, and a double end() is harmless."""
from tests.paths import BACKEND
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from core import critical_ops


def test_begin_end_lifecycle():
    assert critical_ops.active_ops() == []
    token = critical_ops.begin('ISO export')
    assert critical_ops.active_ops() == ['ISO export']
    critical_ops.end(token)
    assert critical_ops.active_ops() == []


def test_end_is_idempotent():
    token = critical_ops.begin('ISO save')
    critical_ops.end(token)
    critical_ops.end(token)  # must not raise or affect other ops
    assert critical_ops.active_ops() == []


def test_duplicate_names_are_independent():
    a = critical_ops.begin('ISO download')
    b = critical_ops.begin('ISO download')
    assert critical_ops.active_ops() == ['ISO download', 'ISO download']
    critical_ops.end(a)
    assert critical_ops.active_ops() == ['ISO download']
    critical_ops.end(b)
    assert critical_ops.active_ops() == []


def test_context_manager_releases_on_exception():
    with pytest.raises(RuntimeError):
        with critical_ops.critical_op('ISO export'):
            assert critical_ops.active_ops() == ['ISO export']
            raise RuntimeError('boom')
    assert critical_ops.active_ops() == []
