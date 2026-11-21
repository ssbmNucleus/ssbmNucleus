"""Read back what a finished port says of its common actions: how long each lasts, the frames nothing can touch the
fighter on (from the script as installed), and where its grabs reach.  python shared_check.py <work dir> [<work dir> ...]"""
import json
import sys
import _where  # noqa: E402
from pathlib import Path

sys.path.insert(0, str(_where.PORT_REPO))
sys.path.insert(0, str(_where.BACKEND))
from fighter_port.oneshot import absolute, clip_frames  # noqa: E402
from vault.echo.subactions import FighterDat  # noqa: E402

WANT = ('EscapeN', 'EscapeF', 'EscapeB', 'EscapeAir', 'GuardOn', 'GuardOff', 'Passive', 'PassiveStandF', 'PassiveStandB', 'PassiveCeil',
        'DownStandU', 'DownStandD', 'DownForwardU', 'DownBackU', 'DownForwardD', 'DownBackD', 'CliffClimbQuick', 'CliffClimbSlow',
        'CliffEscapeQuick', 'CliffEscapeSlow', 'CliffJumpQuick1', 'CliffCatch', 'Catch', 'CatchDash', 'Turn', 'SquatRv', 'CatchCut',
        'DownAttackU', 'DownAttackD', 'CliffAttackQuick', 'CliffAttackSlow')
for work in sys.argv[1:]:
    w = Path(work)
    donor_pl, donor_aj = (w / 'donor/PlMs.dat').read_bytes(), (w / 'donor/PlMsAJ.dat').read_bytes()
    pl, aj = (w / 'final/PlMs.dat').read_bytes(), (w / 'final/PlMsAJ.dat').read_bytes()
    was, now = clip_frames(donor_aj, donor_pl), clip_frames(aj, pl)
    fd = FighterDat(pl)
    report = json.loads((w / 'report.json').read_text('utf-8'))
    print('=====', w.parent.name, '| shared:', json.dumps(report.get('shared'))[:900])
    for motion in WANT:
        act = next((x for x in fd.actions if x.motion == motion and x.script_offset is not None), None)
        if act is None:
            continue
        read = absolute(fd.script_items(act.index))
        events = read[0] if read else []
        body = [(f, it[1].get('body_state')) for f, it in events if it[0] == 26]
        boxes = [(f, it[1]['element'], round(it[1]['x_offset'] / 256, 1), round(it[1]['y_offset'] / 256, 1), round(it[1]['size'] / 256, 1),
                  'g' * it[1]['hit_grounded_fighters'] + 'a' * it[1]['hit_aerial_fighters']) for f, it in events if it[0] == 11]
        clear = [f for f, it in events if it[0] == 16]
        iasa = [f for f, it in events if it[0] == 23]
        print(f"  {motion:18s} donor {was.get(motion)!s:>4} now {now.get(motion)!s:>4}  untouchable {body}  "
              + (f"boxes (frame, element, ahead, up, size, who) {boxes[:4]} cleared {clear} " if boxes else '') + (f"free at {iasa}" if iasa else ''))
