import sqlite3

import pytest

from tracker.combos import combo_index
from tracker.store import indexer


@pytest.fixture
def conn():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    indexer._init_schema(db)
    for i in range(1, 13):
        db.execute('INSERT INTO games(id,path,mtime,size,stage,is_teams,players) VALUES(?,?,1,1,31,0,?)',
                   (i, f'fixture-{i}.slp', '[]'))
        for port in (1, 2):
            db.execute('INSERT INTO game_players(game_id,port,type,character) VALUES(?,?,0,2)', (i, port))
    for i in range(1, 101):
        db.execute('''INSERT INTO combos(id,game_id,port,opp_port,code,opp_code,
            character,opp_character,stage,start_at,start_frame,end_frame,
            damage,moves,start_percent,true_combo,did_kill,moves_json)
            VALUES(?,?,1,2,?,?,2,20,31,?,?,?,?,?,?,?,?,?)''',
                   (i, i % 12 + 1, 'ME' if i % 2 else 'ALT', 'OPP',
                    f'2026-01-{i % 3 + 1:02}', i % 5, i % 5 + i % 7,
                    i % 120, i % 8 + 1, i % 30, i % 2, i % 3 == 0, '[]'))
    db.commit()
    yield db
    db.close()


@pytest.mark.parametrize('sort', list(combo_index.SORT_FIELDS))
@pytest.mark.parametrize('direction', ['asc', 'desc'])
@pytest.mark.parametrize('codes,mine,column', [(['ME'], 'me', 'code'), (['ME', 'ALT'], 'me', 'code'), (['OPP'], 'vs', 'opp_code')])
def test_paged_query_preserves_filters_and_stable_order(conn, sort, direction, codes, mine, column):
    marks = ','.join('?' for _ in codes)
    expected = [r['id'] for r in conn.execute(
        f'''SELECT c.id FROM combos c JOIN games g ON g.id=c.game_id
            WHERE c.{column} IN ({marks}) AND c.moves >= 4 AND c.damage >= 50
            ORDER BY {combo_index._order_by(sort, direction)}''', codes)]
    actual = []
    for offset in range(0, len(expected) + 5, 5):
        result = combo_index.query_combos(conn, codes, mine=mine, min_moves=4, min_damage=50,
                                          sort=sort, direction=direction, limit=5, offset=offset)
        assert result['total'] == len(expected)
        actual.extend(c['id'] for c in result['combos'])
        for c in result['combos']:
            assert c['game']['path'] == f"fixture-{c['game']['id']}.slp"
            assert c['moves_list'] == []
    assert actual == expected


def test_pending_count_matches_extraction_eligibility_without_fetching_candidate_payloads(conn, monkeypatch):
    conn.execute('UPDATE games SET combos_at=mtime WHERE id=1')
    conn.execute('UPDATE games SET parse_ok=0 WHERE id=2')
    conn.execute('UPDATE games SET is_teams=1 WHERE id=3')
    conn.execute('UPDATE games SET stage=900 WHERE id=4')
    conn.execute('DELETE FROM game_players WHERE game_id=5 AND port=2')
    conn.execute('UPDATE game_players SET character=99 WHERE game_id=6 AND port=2')
    conn.execute('UPDATE games SET combos_at=mtime-1 WHERE id=7')
    expected = len(combo_index._candidates(conn))
    monkeypatch.setattr(combo_index, '_candidates', lambda _: pytest.fail('Header materialized the candidate list'))
    visible = conn.execute('SELECT COUNT(*) FROM combos WHERE moves >= 4').fetchone()[0]
    assert visible < 100  # Short sequences must not inflate the header.
    assert combo_index.counts(conn) == {'combos': visible, 'games_scanned': 2, 'games_pending': expected}


def test_new_indexes_migrate_idempotently_without_changing_rows(conn):
    before = conn.execute('SELECT COUNT(*) FROM combos').fetchone()[0]
    for name in ('idx_combos_code_recent', 'idx_combos_opp_recent'):
        conn.execute(f'DROP INDEX {name}')
    indexer._init_schema(conn)
    indexer._init_schema(conn)
    names = {r['name'] for r in conn.execute("PRAGMA index_list('combos')")}
    assert {'idx_combos_code_recent', 'idx_combos_opp_recent'} <= names
    assert conn.execute('SELECT COUNT(*) FROM combos').fetchone()[0] == before
