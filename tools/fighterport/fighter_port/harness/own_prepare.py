"""A fighter that keeps its OWN skeleton: its rig, its body, the engine's joint table and the donor's fighter data
rewritten for it, from the game's own files.

Usage (cwd app/backend): python own_prepare.py <work> <fighter> <donor> <game root>
Reads the donor's own files from <work>/project/files (the `project` stage makes it). Writes <work>/rig, <work>/body,
<work>/data, and the first costume to <work>/package/costumes/<prefix>Nr.dat. Takes a few minutes (the rig reads
every clip of the fighter's to find the joints Melee cannot turn the way the game does). The fighter's files are
taken out of the game's archive first when they are not out yet (`own_skeleton.prepare`); nothing has to be written
for a new fighter before this runs (`fighters.py` says what may be, and `fighter_port.preflight` what stands in).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fighter_port import compat  # noqa: E402

compat.install()
from fighter_port import fighters, own_skeleton  # noqa: E402

work, fighter, donor, root = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
if fighters.donor_problem(donor):
    raise SystemExit(fighters.donor_problem(donor))
names = own_skeleton.DONOR[donor]
got = own_skeleton.prepare(fighter, root, work, donor, work / 'project' / 'files')
first = work / 'package' / 'costumes' / names['costume']
# (only new bytes are copied: the same body keeps its file's time, and the round's pictures of it stay good)
print('the first costume:', 'written' if own_skeleton.put_costume(got['costume'], first) else 'the same bytes, kept', first)
print('ready:', {k: str(v) for k, v in got.items()})
