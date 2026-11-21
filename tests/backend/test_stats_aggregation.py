"""Stats payload/result regressions using synthetic rows and an in-memory DB."""
from collections import Counter
from datetime import datetime
import itertools
import json
import sqlite3

from tracker.store import indexer
from tracker.stats import aggregate


def test_result_preserves_shared_placement_and_lras_rules():
    states = [None, {}, {'1': {'stocks': 1, 'percent': 40}, '2': {'stocks': 0, 'percent': 0}},
              {'1': {'stocks': 2, 'percent': 90}, '2': {'stocks': 2, 'percent': 30}},
              {'1': {'stocks': 2, 'percent': 30}, '2': {'stocks': 2, 'percent': 30}}]
    for port, placements, ending, state in itertools.product(
            (None, 1, 2, 4), (None, [], [0, 1], [1, 0], [None, None]), (None, 3, 7), states):
        row = {'my_port': port, 'placements': json.dumps(placements) if placements else None,
               'end_method': ending, 'lras_initiator': 0,
               'final_state': json.dumps(state) if state else None}
        assert aggregate._result(row) is indexer.infer_result(port, placements, ending, 0, state)


def test_decisive_placements_do_not_require_final_state_decoding(monkeypatch):
    final = '{"1":{"stocks":1,"percent":40},"2":{"stocks":0,"percent":0}}'
    original_loads = json.loads
    decoded = []

    def decode(value):
        decoded.append(value)
        return original_loads(value)

    monkeypatch.setattr(aggregate.json, 'loads', decode)
    row = {'my_port': 1, 'placements': '[1,0]', 'end_method': 3,
           'lras_initiator': 0, 'final_state': final}
    assert aggregate._result(row) is False
    assert final not in decoded
    row['end_method'] = 7  # LRAS must use final state even if placements disagree.
    assert aggregate._result(row) is True
    assert final in decoded


def test_repeated_rival_months_and_timezone_payload(monkeypatch):
    dates = ['2024-03-10T01:30:00-05:00', '2024-03-10T03:00:00-04:00',
             '2024-03-10T03:10:00-04:00', '2024-04-01T00:00:00+00:00',
             '2024-04-01T00:20:00+00:00', '2024-04-01T00:30:00+00:00']
    rows = [{'id': i, 'start_at': at, 'stage': 31, 'duration_s': 60,
             'end_method': 3, 'lras_initiator': None, 'placements': '[0,1]',
             'final_state': None, 'my_port': 1, 'my_char': 2, 'opp_char': 20,
             'opp_code': 'OPP#1', 'opp_name': f'name-{i}'} for i, at in enumerate(dates)]
    monkeypatch.setattr(aggregate, '_fetch_rows', lambda *args, **kwargs: rows)
    result = aggregate.compute_stats(None, ['ME#1'])
    assert result['overview'] == {'games': 6, 'playtime_s': 360, 'first_at': dates[0],
                                  'last_at': dates[-1], 'wins': 6, 'losses': 0,
                                  'winrate': 1.0, 'opponents': 1, 'active_days': 2}
    assert result['months'] == [dict(month=m, games=3, wins=3, losses=0, winrate=1.0)
                                for m in ('2024-03', '2024-04')]
    rival, = result['rivals']
    assert rival == {'code': 'OPP#1', 'name': 'name-5', 'games': 6, 'wins': 6,
                     'losses': 0, 'last_at': dates[-1], 'opp_quits': 0, 'my_quits': 0,
                     'top_char': 20, 'winrate': 1.0}
    assert result['sessions']['count'] == 2
    assert result['sessions']['length_distribution'] == [{'games': 3, 'sessions': 2}]
    # Preserve per-instant local conversion across DST and source UTC offsets.
    expected = Counter((d.weekday(), d.hour) for d in
                       (datetime.fromisoformat(at).astimezone() for at in dates))
    assert result['time_heatmap'] == [dict(d=d, h=h, games=n, wins=n, losses=0, winrate=1.0)
                                      for (d, h), n in sorted(expected.items())]


def test_identity_deduplication_and_inclusive_source_day_bounds():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    indexer._init_schema(conn)
    try:
        conn.execute('''INSERT INTO games(id,path,mtime,size,start_at,stage,is_teams,placements)
                        VALUES(1,'synthetic.slp',0,1,'2024-04-01T00:00:00+14:00',31,0,'[0,1]')''')
        conn.executemany('INSERT INTO game_players(game_id,port,type,character,code) VALUES(1,?,0,?,?)',
                         [(1, 2, 'ME#1'), (2, 20, 'ALT#1')])
        assert aggregate.compute_stats(conn, ['me#1', 'alt#1'])['overview']['games'] == 1
        assert aggregate.compute_stats(conn, ['ME#1'], start='2024-04-01', end='2024-04-01')['overview']['games'] == 1
        assert aggregate.compute_stats(conn, ['ME#1'], end='2024-03-31')['overview']['games'] == 0
        assert aggregate.compute_stats(conn, ['ME#1'], my_char=20)['overview']['games'] == 0
    finally:
        conn.close()
