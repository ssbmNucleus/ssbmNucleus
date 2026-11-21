"""Portable implementation notes, derived from the actual driver report.

Compilation, file checks and optional gameplay evidence are separate facts.
This summary never promotes a custom module into a claim of completed gameplay.
"""
from __future__ import annotations

import json


def _unique(rows):
    return list(dict.fromkeys(str(row) for row in rows if row))


def _notes(value, kind):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == kind and isinstance(child, list):
                yield from (s for s in child if isinstance(s, str))
            else:
                yield from _notes(child, kind)
    elif isinstance(value, list):
        for child in value:
            yield from _notes(child, kind)


def summarize(report):
    """Summarize evidence in a driver report without inferring source-game parity."""
    features = list(report.get('code') or [])
    numbers = report.get('special_numbers') or {}
    placeholder, missing = [], []
    for special in ('neutral', 'side', 'up', 'down'):
        rows = numbers.get(special) or []
        if not isinstance(rows, list):
            continue
        labels = {row.get('what') for row in rows if isinstance(row, dict)}
        if 'PLAIN' in labels:
            placeholder.append(special)
        if 'NOT BUILT' in labels:
            missing.append(special)
    own = report.get('route') == 'own skeleton'
    if not own:
        runtime = 'donor-based adaptation'
    elif not features or not report.get('own_states'):
        runtime = 'special runtime not built'
    elif numbers.get('movement'):
        runtime = 'shared source-program execution with known gaps'
    elif report.get('specials_not_written'):
        runtime = 'animation and hitbox placeholders'
    elif placeholder or missing:
        runtime = 'custom code with unfinished special slots'
    else:
        runtime = 'custom native code'
    incomplete = [s for s in features if s.startswith(('INCOMPLETE:', 'NOT BUILT'))
                  or ' limitations:' in s.casefold()]
    adaptations = [s for s in features if s.startswith('ADAPTATION:') or 'STAND-IN' in s or 'READING:' in s]
    adaptations += list(_notes(numbers, 'adaptations'))
    limitations = _unique([*incomplete, report.get('specials_not_written'), *_notes(numbers, 'limits')])
    coverage=report.get('mechanic_coverage') or dict(schema=1,assessed=False,entries=[],unfinished=[])
    limitations += [f"Unfinished mechanic: {row['label']}" for row in coverage.get('entries',[]) if row['status']=='unfinished']
    return dict(schema='fighter-port-implementation-v1', fighter=report.get('fighter'),
                route=report.get('route'), runtime=runtime,
                placeholder_specials=placeholder, missing_specials=missing,
                features=[s for s in features if s not in incomplete and not s.startswith('ADAPTATION:')],
                adaptations=_unique(adaptations), limitations=limitations,
                mechanic_coverage=coverage,
                generated_files_read_back=(report.get('check') or {}).get('ok'),
                gameplay_evidence='not assessed by this build receipt')


def text(receipt, name=None):
    rows = [f"{name or receipt.get('fighter') or 'Fighter'} — port notes", '',
            f"Special runtime: {receipt['runtime']}",
            'This describes the implementation included in this package.',
            'Gameplay calibration is optional; source frame parity is a separate polish task.']
    for label, key in [('Placeholder special slots', 'placeholder_specials'),
                       ('Missing special slots', 'missing_specials'),
                       ('Included behavior', 'features'), ('Adaptations', 'adaptations'),
                       ('Known limits and unfinished work', 'limitations')]:
        values = receipt.get(key) or []
        if values:
            rows.extend(['', label + ':', *('- ' + str(v) for v in values)])
    coverage=receipt.get('mechanic_coverage') or {}
    if coverage.get('assessed'):
        rows.extend(['','Mechanic coverage (implementation declarations, not gameplay certification):'])
        rows.extend(f"- [{entry['status']}] {entry['label']}: {entry['detail']}" for entry in coverage['entries'])
    else:
        rows.extend(['','Mechanic coverage: not assessed. Working special slots do not establish complete mechanics.'])
    rows.extend(['', 'These implementation notes do not certify gameplay testing or exact source parity.'])
    return '\n'.join(rows) + '\n'


def package_members(report, name):
    """Standalone notes travel with a normal importable fighter zip."""
    receipt = summarize(report)
    return {'PORT_NOTES.txt': text(receipt, name).encode('utf-8'),
            'port-implementation.json': json.dumps(receipt, indent=2).encode('utf-8')}
