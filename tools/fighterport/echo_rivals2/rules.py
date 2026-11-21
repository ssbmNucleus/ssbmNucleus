"""Compiled source-game rules calibrated against the identified offline game build.

These describe behavior absent from attack assets; normal ports consume them without running a harness.
"""
GAME_SHA256 = '5fa30a728fb75aa1e703c4b3f7447154b7bd8e7cf449b3222ce291ec711a57c1'
BURN = {
    'duration': 150,
    'tick_interval': 30,
    'tick_damage': 1.0,
    'pause_in_hitstun': True,
    'refresh': 'reset_duration',
    'evidence': 'fighter_port/benchmarks/2026-11-14-rivals-status-calibration.md',
    'source': 'Observed Rivals 2 1.7.5 (30985), Zetterburn fireball vs Absa; source-calibration burn traces',
    'game_sha256': GAME_SHA256,
}

RANNO_DARTS = {
    'max_darts': 4,
    'interval': 2,
    'ground_angle_degrees': 0.0,
    'air_angle_degrees': -45.0,
    'spread_degrees': 7.0,
    'launch_offset_cm': 100.0,
    'source': 'Observed Rivals 2 1.7.5 (30985), Ranno vs Olympia, grounded four-dart and aerial two-dart traces',
    'evidence': 'fighter_port/benchmarks/2026-11-14-ranno-neutral.md',
    'game_sha256': GAME_SHA256,
}

POISON = {'max_stacks': 4,
 'attack_start_damage': 1.0,
 'remove_on_body_hit': 1,
 'idle_damage': 0,
 'source': 'Observed Rivals 2 1.7.5 (30985): poisoned Olympia jump, aerial, jab, strong, special, '
           'shield and direct contact',
 'evidence': 'fighter_port/benchmarks/2026-11-14-ranno-poison.md',
 'game_sha256': '5fa30a728fb75aa1e703c4b3f7447154b7bd8e7cf449b3222ce291ec711a57c1'}
