"""The shipped split is reproducible without DAT tools, Dolphin, or network."""
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from tests.left_out import left_out

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('stage_bake', ROOT / 'tools/liteaudit/stage_bake.py')
bake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bake)


@left_out('app/frontend/src/tracker/replays/data/stageSim/10.json',
          why='stage simulation tables read from the game')
def test_split_roundtrip_is_byte_identical():
    # Scratch stays inside the workspace, including on restricted Windows
    # workers where pytest's private ACL on tmp_path is inaccessible.
    tmp_path = ROOT / 'app/scratch/liteaudit/stage-data-tests' / uuid4().hex
    tmp_path.mkdir(parents=True)
    source = ROOT / 'app/frontend/src/tracker/replays/data'
    stages = json.loads((source / 'stageCollision.json').read_text())['stages']
    output = tmp_path / 'stageCollision.json'
    bake.write_stage_data(stages, output)
    files = ['stageCollision.json', 'meleeMovers.json', 'stageSim/10.json',
             'stages/10.json', 'stages/11.json', 'stages/22.json', 'stages/23.json']
    for name in files:
        assert (tmp_path / name).read_bytes() == (source / name).read_bytes(), name
    bake.write_stage_data(json.loads(output.read_text())['stages'], output)
    for name in files:
        assert (tmp_path / name).read_bytes() == (source / name).read_bytes(), name


def test_only_large_tables_are_deferred():
    source = ROOT / 'app/frontend/src/tracker/replays/data'
    stages = json.loads((source / 'stageCollision.json').read_text())['stages']
    assert {sid for sid, entry in stages.items() if entry.get('deferred')} == {'10', '11', '22', '23'}
    for sid, entry in stages.items():
        assert len(bake.compact(entry).encode()) < bake.HEAVY_BYTES
        if not entry.get('deferred'):
            continue
        assert entry['groups'] == entry['tracks'] == []
        packed = json.loads((source / f'stages/{sid}.json').read_text())
        assert len(bake.compact(packed['collision']).encode()) > bake.HEAVY_BYTES
        assert len(bake.compact(packed).encode()) > bake.HEAVY_BYTES
