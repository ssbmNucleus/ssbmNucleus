"""Give the port its own voice and sounds: the donor's bank with the fighter's own samples in it.

Usage (cwd app/backend): python make_sounds.py <work> <fighter> <Name> <donor> [<game> <game root>]
(<game>: ultimate, the default, or brawl; <game root>: the folder the game's files are under)
Reads <work>/<donor>.zip (its sound.zip), writes <work>/package/sound.zip and sound.json (what went where),
and <work>/package/announcer.wav (the game's announcer saying the fighter's name) when the game has one.
package_build.py puts the bank in the fighter package and installs the name call when they are there.
"""
import io
import json
import sys
import _where  # noqa: E402
import zipfile
from pathlib import Path

sys.path.insert(0, str(_where.BACKEND))
sys.path.insert(0, str(_where.PORT_REPO))
from core.config import MEXCLI_PATH, PROJECT_ROOT, get_subprocess_args  # noqa: E402
from fighter_port import voice  # noqa: E402

work, fighter, name, donor = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
GAME = sys.argv[5] if len(sys.argv) > 5 else 'ultimate'
ROOT = sys.argv[6] if len(sys.argv) > 6 else str(_where.ULTIMATE)
with zipfile.ZipFile(work / f'{donor}.zip') as z:
    sound_zip = z.read('sound.zip')
with zipfile.ZipFile(io.BytesIO(sound_zip)) as z:
    names = [s['name'] for s in json.loads(z.read('group.json'))['sounds']]
import os  # noqa: E402
game = work / os.environ.get('PORT_DIR', 'port') / 'game.json'      # the game's move scripts as the port's driver read them
moves = json.loads(game.read_text('utf-8'))['moves'] if game.exists() else None
# the route the driver took (a fighter on its own skeleton writes more scripts anew, which frees more of the donor's samples)
report_file = game.parent / 'report.json'
route = json.loads(report_file.read_text('utf-8')).get('route') if report_file.exists() else None
chosen, left = voice.choose(donor, fighter, ROOT, names, moves, GAME, sound_zip, route=route)
print(f'{len(chosen)} of the donor\'s {len(names)} samples have a sound of the fighter\'s for the same thing')
for line in left:
    print('  left as the donor\'s:', line)
data, report = voice.build(sound_zip, donor, name, chosen, MEXCLI_PATH, work / 'package' / 'sound-work',
                           dict(cwd=str(PROJECT_ROOT), **get_subprocess_args()))
(work / 'package' / 'sound.zip').write_bytes(data)
report['left'] = left
(work / 'package' / 'sound.json').write_text(json.dumps(report, indent=1), 'utf-8')
print(f"bank {report['file']}: {report['bank_bytes']} bytes (the donor's {report['donor_bank_bytes']}), "
      f"{report['seconds']} s at {report['rate']} Hz")
print('  ', ', '.join(f"{r['sample']}<-{r['sound']}" for r in report['swapped']))
said = voice.announcer(ROOT, fighter, GAME)
if said:
    wav = voice.to_wav(said, work / 'package' / 'announcer.wav', 24000)
    print('the announcer says the name:', wav)
else:
    # the game has no call of the fighter's name (Slap City has no announcer): STAND-IN, the app's own line for a
    # fighter with no call of its own, "Bonus Character" (core/narrator.py: spliced from the project's own banks);
    # with nothing, the donor's call stays and the port is announced by the donor's name
    from core import narrator  # noqa: E402
    bonus = narrator.build_bonus_clip(work / 'project', MEXCLI_PATH, work / 'package' / 'announcer.wav')
    print('the game has no announcer clip for this fighter: '
          + (f'STAND-IN, the "Bonus Character" line: {bonus}' if bonus else "and the project's banks would not give the "
             "\"Bonus Character\" line: the donor's call stays"))
