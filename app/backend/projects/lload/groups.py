"""The project's L-load groups, stored by fighter name in `nucleus_lload.json`.

Names, not ids: m-ex shifts external ids when a fighter is removed (the same
reason Any Climbers pairs and the FSM bake store names). Ids are resolved from
`get-css-layout`'s fighter list whenever they are needed.
"""
from __future__ import annotations

from pathlib import Path

from core.metadata import load_metadata, save_metadata

LLOAD_FILE = 'nucleus_lload.json'

# The last six internal slots are the non-selectable specials (hands,
# wireframes, Giga Bowser, Sandbag); m-ex inserts added fighters before them.
_SPECIAL_SLOT_COUNT = 6
# Nana's slot (m-ex names it "Popo") has no CSS icon and is never selectable;
# Sheik is chosen through Zelda; NONE is m-ex's placeholder for broken slot 34.
_NANA_INTERNAL = 11
_BLOCKED_NAMES = {'sheik', 'none'}


def _path(project_path) -> Path:
    return Path(project_path).parent / LLOAD_FILE


def load(project_path) -> list[dict]:
    """[{"base": name, "alts": [name, ...]}] -- [] when none are stored."""
    path = _path(project_path)
    if not path.exists():
        return []
    data = load_metadata(default={}, path=path)
    groups = data.get('groups') if isinstance(data, dict) else None
    return groups if isinstance(groups, list) else []


def save(project_path, groups: list[dict]) -> None:
    save_metadata({'groups': groups}, path=_path(project_path))


def selectable(fighters: list[dict]) -> list[dict]:
    """The layout's fighters ({externalId, internalId, name}) that can be in a
    group: everything a CSS icon could pick."""
    count = len(fighters)
    return [f for f in fighters
            if f['internalId'] < count - _SPECIAL_SLOT_COUNT
            and f['internalId'] != _NANA_INTERNAL
            and f['name'].strip().lower() not in _BLOCKED_NAMES]


def _by_name(fighters: list[dict]) -> dict[str, dict]:
    """First fighter per lower-cased name (a playable custom comes before a
    same-named special, e.g. ACE's Giga Bowser)."""
    out: dict[str, dict] = {}
    for f in fighters:
        out.setdefault(f['name'].strip().lower(), f)
    return out


def normalize(groups: list[dict], fighters: list[dict],
              icons: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    """Clean `groups` against the project's fighters: drop unknown or blocked
    names, duplicates, and groups left without alternates. Given the layout's
    `icons`, also drop a group whose base has no CSS icon -- its alternates
    have nothing to hide behind. This is the one place that decides which
    groups are in effect; the editor, the layout routes and export all use it.
    Returns the kept groups (names as the project spells them) and one
    message per drop."""
    names = _by_name(selectable(fighters))
    with_icon = None if icons is None else {ic['fighter'] for ic in icons}
    seen: set[str] = set()
    kept, problems = [], []
    for group in groups or []:
        base = str((group or {}).get('base', '')).strip()
        base_f = names.get(base.lower())
        if base_f is None:
            problems.append(f'"{base}" is not a selectable fighter in this project')
            continue
        if base.lower() in seen:
            problems.append(f'"{base}" is already in another L group')
            continue
        alts = []
        for alt in (group.get('alts') or []):
            alt = str(alt).strip()
            alt_f = names.get(alt.lower())
            if alt_f is None:
                problems.append(f'"{alt}" is not a selectable fighter in this project')
            elif alt.lower() in seen or alt.lower() == base.lower() or alt_f in alts:
                problems.append(f'"{alt}" is already in an L group')
            else:
                alts.append(alt_f)
        if not alts:
            continue
        if with_icon is not None and base_f['externalId'] not in with_icon:
            problems.append(f'{base_f["name"]} has no select-screen icon, so its L group is off')
            continue
        seen.add(base.lower())
        seen.update(a['name'].strip().lower() for a in alts)
        kept.append({'base': base_f['name'], 'alts': [a['name'] for a in alts]})
    return kept, problems


def resolve(groups: list[dict], fighters: list[dict]) -> list[dict]:
    """Normalized name groups -> [{"base": ext, "alts": [ext, ...]}]."""
    names = _by_name(selectable(fighters))
    return [{'base': names[g['base'].strip().lower()]['externalId'],
             'alts': [names[a.strip().lower()]['externalId'] for a in g['alts']]}
            for g in groups]


def without_fighter(groups: list[dict], name: str) -> list[dict]:
    """`groups` with `name` taken out: its own group goes if it was a base, and
    a group left without alternates goes too."""
    key = name.strip().lower()
    out = []
    for g in groups:
        if g['base'].strip().lower() == key:
            continue
        alts = [a for a in g['alts'] if a.strip().lower() != key]
        if alts:
            out.append({'base': g['base'], 'alts': alts})
    return out


def forget_fighter(project_path, name: str) -> None:
    """Take a removed fighter out of the stored groups."""
    stored = load(project_path)
    kept = without_fighter(stored, name)
    if kept != stored:
        save(project_path, kept)
