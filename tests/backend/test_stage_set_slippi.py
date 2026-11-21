"""
/api/mex/storage/stages/set-slippi: true / false set a manual verdict; an
explicit null clears it back to "unknown" (the edit page's third option, which
used to be rejected with a 400 so Unknown could never be chosen).
"""
from tests.paths import BACKEND
import sys
from pathlib import Path

from flask import Flask

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import vault.routes.storage_stages as ss  # noqa: E402


def _client(monkeypatch, meta):
    saved = {}
    monkeypatch.setattr(ss, 'load_metadata', lambda: meta)
    monkeypatch.setattr(ss, 'save_metadata', lambda m: saved.update(m))
    app = Flask(__name__)
    app.register_blueprint(ss.storage_stages_bp)
    return app.test_client(), saved


def _meta(**variant):
    return {'stages': {'stadium': {'variants': [{'id': 'v1', 'name': 'V1', **variant}]}}}


def _post(client, value):
    return client.post('/api/mex/storage/stages/set-slippi',
                       json={'stageName': 'stadium', 'variantId': 'v1', 'slippiSafe': value})


def test_true_and_false_set_a_manual_override(monkeypatch):
    for value in (True, False):
        meta = _meta()
        client, saved = _client(monkeypatch, meta)
        resp = _post(client, value)
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()['slippi_safe'] is value
        v = saved['stages']['stadium']['variants'][0]
        assert v['slippi_safe'] is value
        assert v['slippi_manual_override'] is True
        assert 'slippi_test_date' in v


def test_null_clears_to_unknown(monkeypatch):
    meta = _meta(slippi_safe=True, slippi_manual_override=True, slippi_test_date='x')
    client, saved = _client(monkeypatch, meta)
    resp = _post(client, None)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body['slippi_safe'] is None and 'Unknown' in body['message']
    v = saved['stages']['stadium']['variants'][0]
    assert v['slippi_safe'] is None
    assert v['slippi_manual_override'] is False
    assert 'slippi_test_date' not in v


def test_missing_key_and_bad_type_are_400(monkeypatch):
    client, _ = _client(monkeypatch, _meta())
    assert client.post('/api/mex/storage/stages/set-slippi',
                       json={'stageName': 'stadium', 'variantId': 'v1'}).status_code == 400
    assert _post(client, 'yes').status_code == 400
