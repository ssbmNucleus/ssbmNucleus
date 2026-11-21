"""Actual browse/share functions against synthetic SQLite; no startup/network."""
from tests.paths import BACKEND
import ast
import json
from pathlib import Path
import sqlite3
import types

from flask import Flask, jsonify, request
import pytest

from tracker.combos import combo_index
from tracker.store import indexer
from tracker.cloud import vault_client, vault_sync


@pytest.mark.parametrize('moves,hits,kill,expected', [
    ([{}] * 3, 3, False, False), ([{}] * 3, 10, True, False),
    ([{}], 8, False, False), ([{}] * 4, 4, False, True),
    ([{}] * 5, 5, True, True), ([], 3, True, False), ([], 4, False, True),
])
def test_four_move_policy_and_legacy_hit_fallback(moves, hits, kill, expected):
    assert vault_client._worth_uploading(moves, hits, kill) is expected


class OwnedConnection(sqlite3.Connection):
    def close(self):
        pass  # Multiple fake requests share this fixture; teardown really closes it.


@pytest.fixture
def api_fixture(monkeypatch):
    conn = sqlite3.connect(':memory:', factory=OwnedConnection)
    conn.row_factory = sqlite3.Row
    indexer._init_schema(conn)
    conn.executemany('INSERT INTO games(id,path,mtime,size,players) VALUES(?,?,0,1,?)',
                     [(1, 'one.slp', '[]'), (2, 'two.slp', '[]')])
    for cid, gid, moves, hits, wire in [(1, 1, 2, 8, 10), (2, 1, 4, 4, 200),
                                       (3, 1, 5, 5, 100), (4, 1, 0, 4, 300), (5, 2, 4, 4, 400)]:
        conn.execute('''INSERT INTO combos(id,game_id,port,opp_port,start_frame,end_frame,
                       start_rf,end_rf,moves,hits,moves_json,damage,did_kill)
                       VALUES(?,?,1,2,?,?,?, ?,?,?,?,50,1)''',
                     (cid, gid, cid * 10, cid * 10 + 100, wire, wire + 100, moves, hits,
                      json.dumps([{'move_id': 1, 'hits': 1}] * moves)))
    conn.execute('CREATE TABLE vault_objects(game_id INTEGER, content_hash TEXT, pushed_at TEXT)')
    calls = []

    def sync(token, conn, game_ids, should_cancel=None):
        calls.append(('sync', game_ids))
        conn.execute('INSERT INTO vault_objects VALUES(?, ?, ?)', (game_ids[0], 'synthetic-hash', 'now'))

    def mint(token, content_hash):
        calls.append(('mint', content_hash))
        return {'id': 'synthetic-share'}

    monkeypatch.setattr(vault_client, 'sync', sync)
    monkeypatch.setattr(vault_client, 'mint_share', mint)
    monkeypatch.setattr(vault_client, '_call', lambda *a, **kw: pytest.fail('Unexpected network call'))
    # Importing the whole blueprint starts an animation downloader. Compile just
    # the unchanged route bodies under test, without module startup/decorators.
    sources = {'_combo_ordinal': BACKEND / 'tracker/share/links.py',
               'share_link': BACKEND / 'tracker/routes/share.py',
               'list_combos': BACKEND / 'tracker/routes/combos.py'}
    nodes = [n for name, source in sources.items()
             for n in ast.parse(source.read_text(encoding='utf8')).body
             if isinstance(n, ast.FunctionDef) and n.name == name]
    assert [n.name for n in nodes] == list(sources)
    for node in nodes:
        node.decorator_list = []
    namespace = dict(request=request, jsonify=jsonify, json=json, sqlite3=sqlite3,
                     indexer=types.SimpleNamespace(connect=lambda: conn), combo_index=combo_index,
                     vault_client=vault_client, vault_sync=vault_sync,
                     _token_or_error=lambda: ('synthetic-token', None),
                     _stored_token=lambda c: 'synthetic-token',
                     _user_codes=lambda c: [], _synced_game_ids=lambda c, ids: set(),
                     _int_arg=lambda name: int(request.args[name]) if name in request.args else None,
                     _float_arg=lambda name: float(request.args[name]) if name in request.args else None,
                     _day_arg=lambda name: request.args.get(name))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'tracker-share-routes', 'exec'), namespace)
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.add_url_rule('/share', view_func=namespace['share_link'], methods=['POST'])
    app.add_url_rule('/combos', view_func=namespace['list_combos'])
    yield app.test_client(), conn, calls, namespace
    sqlite3.Connection.close(conn)


@pytest.mark.parametrize('combo_id', [1, 5, 999])
def test_short_wrong_game_and_missing_combos_do_not_upload(api_fixture, combo_id):
    client, _conn, calls, _namespace = api_fixture
    result = client.post('/share', json={'game_id': 1, 'combo_id': combo_id})
    assert result.status_code == 404
    assert calls == []


def test_eligible_unsynced_combo_uploads_on_demand_with_wire_order_ordinal(api_fixture):
    client, _conn, calls, _namespace = api_fixture
    result = client.post('/share', json={'game_id': 1, 'combo_id': 2})
    assert result.status_code == 200
    assert result.json['combo'] == 2  # The other eligible combo starts earlier on the wire.
    assert result.json['url'].endswith('/combo/2')
    assert calls == [('sync', [1]), ('mint', 'synthetic-hash')]


def test_browse_upload_and_share_ordinal_use_same_rule(api_fixture):
    client, conn, _calls, namespace = api_fixture
    result = client.get('/combos')
    assert result.status_code == 200
    eligible = {c['id'] for c in result.json['combos'] if c['game']['id'] == 1 and c['shareable']}
    assert eligible == {2, 3, 4}
    assert all(not c['synced'] for c in result.json['combos'])  # Upload state does not hide eligible shares.
    assert len(vault_client._combos_for(conn, 1)) == len(eligible)
    assert {cid for cid in range(1, 6) if namespace['_combo_ordinal'](conn, 1, cid)} == eligible
