"""Create a vanilla m-ex project for the test build and export the donor's package from it.

Usage (from app/backend): python make_project.py <work dir> <donor name>
"""
import json
import sys
import _where  # noqa: E402
from pathlib import Path

sys.path.insert(0, str(_where.BACKEND))
import mexcli.commands  # noqa: E402
from shared.vanilla_extract import vanilla_refs  # noqa: E402

work, donor = Path(sys.argv[1]), sys.argv[2]
proj = work / 'project'
if not (proj / 'project.mexproj').exists():
    iso = vanilla_refs.known_vanilla_iso()
    r = mexcli.commands.run(['create', iso, proj, 'ByleteTest'], check=False)
    print('create rc', r.returncode, (r.stdout or '')[-300:], (r.stderr or '')[-300:])
print('project:', (proj / 'project.mexproj').exists())
listing = mexcli.commands.run_json(['list-fighters', proj / 'project.mexproj'])
fighters = listing.get('fighters') or []
print(len(fighters), 'fighters; keys', list(fighters[0].keys()) if fighters else None)
row = next(f for f in fighters if f.get('name') == donor)
print('donor row:', row)
out = work / f'{donor}.zip'
if not out.exists():
    res = mexcli.commands.run_json(['export-fighter', proj / 'project.mexproj', row['internalId'], out])
    print('export-fighter:', {k: res[k] for k in list(res)[:6]})
print('donor zip:', out, out.exists(), out.stat().st_size if out.exists() else '')
