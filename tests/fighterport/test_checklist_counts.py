"""The checklist's own count of its lines by mark is the count of `checklist_marks.json`."""
import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parents[2] / 'tools' / 'fighterport' / 'fighter_port'


def test_the_checklist_says_how_many_lines_each_mark_has_and_it_is_so():
    text = (HERE / 'PORT_CHECKLIST.md').read_text('utf-8')
    marks = Counter(v['mark'] for v in json.loads((HERE / 'checklist_marks.json').read_text('utf-8')).values())
    said = re.search(r'(\d+) are rules of the system.*?(\d+) are answered from the files the build wrote, (\d+) from the '
                     r'files with one reading in the game to confirm, (\d+) need\s+the game in the same way for every '
                     r'fighter, and (\d+) need it only because of code', text, re.S)
    assert said, 'the passage that counts the lines by mark is not where it was'
    assert [int(n) for n in said.groups()] == [marks['rule'], marks['files'], marks['files+boot'], marks['boot'], marks['code']]
