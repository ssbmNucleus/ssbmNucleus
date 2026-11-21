"""Astra's review of 789e6de5 (Randall keeps repairing): one test per finding.

Each of these failed on 789e6de5/c9cf57db and passes with the fix. Only the
streamed-response findings are left: the draft-lineage ones (best_draft) went
with the old model-import path.
"""
import json
import threading

import pytest

from shared.aiengine import model_upload
from randall.assistant import engine, main_model


# --- 1. a streamed response is bounded ------------------------------------------

def _wire(monkeypatch, lines):
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_lines(self, chunk_size=1):
            yield from lines
    monkeypatch.setattr(main_model.requests, 'post', lambda *a, **kw: Response())


def _clock(monkeypatch, step):
    ticks = iter(range(0, 10 ** 7, step))
    monkeypatch.setattr(engine.time, 'monotonic', lambda: next(ticks))


def test_keepalive_comments_alone_cannot_hold_a_turn_open(monkeypatch):
    _wire(monkeypatch, [b': OPENROUTER PROCESSING'] * 20)
    _clock(monkeypatch, 30)                    # a comment every 30 s, never a data line
    with pytest.raises(main_model.TurnStopped) as stopped:
        list(main_model._provider([], [], 'test', threading.Event()))
    assert stopped.value.reason == 'response_timeout'


def test_a_stream_that_keeps_sending_data_still_has_a_lifetime(monkeypatch):
    chunk = b'data: ' + json.dumps({'choices': [{'delta': {'content': 'x'}, 'finish_reason': None}]}).encode()
    _wire(monkeypatch, [chunk] * 40)
    _clock(monkeypatch, 60)                    # 40 minutes of trickle
    with pytest.raises(main_model.TurnStopped) as stopped:
        list(main_model._provider([], [], 'test', threading.Event()))
    assert stopped.value.reason == 'response_timeout'


def test_comment_bytes_count_toward_the_transfer_cap(monkeypatch):
    _wire(monkeypatch, [b': ' + b'x' * 16_000_001, b'data: [DONE]'])
    with pytest.raises(RuntimeError, match='reply got too big'):
        list(main_model._provider([], [], 'test', threading.Event()))
