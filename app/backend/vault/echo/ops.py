"""
ops.py -- the Echo op surface: fully parameterised edits against a donor
fighter DAT, applied as a DIFF.

This is the harness. A UI inspector, a chat copilot, a test script and a
cold JSON file all speak exactly this and nothing else:

    {"op": "set_hitbox",    "move": "ftilt", "part": "mid", "hitbox": 0,
                            "field": "damage", "value": 14}
    {"op": "set_hitbox",    "move": "usmash", "hitbox": "all",
                            "field": "knockback_growth", "delta": 20}
    {"op": "set_throw",     "move": "dthrow", "field": "angle", "value": 90}
    {"op": "set_command",   "move": "neutralb", "part": "start", "command": 3,
                            "field": "frame", "value": 4}
    {"op": "set_attribute", "name": "gravity", "value": 0.13}

`hitbox` is the ORDINAL of the Create Hitbox command within the part's script
(0-based, in script order), not the game's hitbox id -- ids get reused when a
move re-creates hitboxes on later frames; ordinals never collide.

Rules:
- validation first, then writes: an invalid op anywhere means NOTHING is
  written (plan() reports every problem at once).
- every op is idempotent given the donor -- applying the same diff twice
  yields the same file.
- `diff()` recovers a diff from an edited file, so a DAT hand-edited in
  HSDRawViewer's script editor can be imported as ops.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .commands import COMMANDS, BY_KEY, CREATE_HITBOX, THROW, END_OF_SCRIPT, POINTER_COMMANDS
from .subactions import FighterDat
from .moves import MoveTable
from .attributes import Attributes, ATTRIBUTES, resolve_key

HITBOX_FIELD_ALIASES = {
    "dmg": "damage", "percent": "damage",
    "kbg": "knockback_growth", "growth": "knockback_growth", "knockbackgrowth": "knockback_growth",
    "bkb": "base_knockback", "base": "base_knockback", "baseknockback": "base_knockback",
    "wdsk": "weight_set_knockback", "setknockback": "weight_set_knockback",
    "weightdependentsetknockback": "weight_set_knockback", "weightsetknockback": "weight_set_knockback",
    "radius": "size", "x": "x_offset", "y": "y_offset", "z": "z_offset",
    "xoffset": "x_offset", "yoffset": "y_offset", "zoffset": "z_offset",
    "shielddamage": "shield_damage", "sfx": "hit_sfx_kind", "hitsfxkind": "hit_sfx_kind",
    "hitsfxseverity": "hit_sfx_severity", "hitgroup": "hit_group",
}

# What the inspector shows by default; everything else is behind "More".
HITBOX_PRIMARY = ["damage", "angle", "knockback_growth", "base_knockback",
                  "weight_set_knockback", "size"]
THROW_PRIMARY = ["damage", "angle", "knockback_growth", "base_knockback",
                 "weight_knockback"]

KNOWN_OPS = ("set_hitbox", "set_throw", "set_command", "set_attribute",
             "set_script", "insert_command", "delete_command")

# Script-authoring ops. Commands are given as dicts in the same shape
# inspect_move() reports them, so read -> edit -> write round-trips:
#     {"cmd": "create_hitbox", "damage": 25, "size": 2000, "bone": 40, ...}
#     {"cmd": "asynchronous_timer", "frame": 3}
#     {"cmd": "subroutine", "pointer": 0x1A2B0}   # data offset of an existing script
# Unlisted fields are 0. An End Of Script is appended automatically.
#     {"op": "set_script",     "move": "ftilt", "part": "mid", "commands": [...]}
#     {"op": "insert_command", "move": "ftilt", "at": 2 | "end", "command": {...} | "commands": [...]}
#     {"op": "delete_command", "move": "ftilt", "command": 3 | [3, 4]}
# `at` / `command` are indices in the CURRENT script (as inspect_move lists
# them); the closing End Of Script cannot be deleted. Later ops in the same
# batch see the rewritten script. The rewritten script is appended to the
# DAT and the action slot repointed -- nothing existing moves -- so value ops
# and `diff()` keep working on every untouched move.
SCRIPT_OPS = ("set_script", "insert_command", "delete_command")

# Create Hitbox size / offsets are stored x256: the engine does
# `hitbox->scale = 0.003906f * size` (decomp src/melee/ft/ftaction.c:326).
# Ops take RAW ints; the inspector adds `<key>_units` floats for display.
SCALED_256 = ("size", "x_offset", "y_offset", "z_offset")
UNIT_SCALE = 1.0 / 256.0


class OpError(ValueError):
    def __init__(self, index: int, op: dict, msg: str):
        super().__init__(f"op[{index}] {op.get('op')}: {msg}")
        self.index, self.op, self.msg = index, op, msg


@dataclass
class Planned:
    index: int
    op: dict
    kind: str
    action: int | None
    command: int | None
    key: str
    before: float | int
    after: float | int
    offset: int | None = None
    payload: object = None      # script ops: the full item list to write

    def as_dict(self) -> dict:
        d = {"index": self.index, "op": self.op, "kind": self.kind,
             "action": self.action, "command": self.command, "field": self.key,
             "before": self.before, "after": self.after, "offset": self.offset}
        if self.payload is not None:
            d["commands"] = [items_to_dict(it) for it in self.payload]
        return d


def items_to_dict(item) -> dict:
    code, fields, pointer = item
    spec = COMMANDS[code]
    d = {"cmd": spec.key, **{k: v for k, v in fields.items() if not k.startswith("_pad")}}
    if code in POINTER_COMMANDS:
        d["pointer"] = pointer if pointer is not None else fields.get("pointer")
    return d


@dataclass
class Plan:
    steps: list[Planned] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _field_key(spec, name: str) -> str:
    n = re.sub(r"[^0-9a-z_]+", "", str(name).lower())
    if n in {p.key for p in spec.params}:
        return n
    n2 = n.replace("_", "")
    alias = HITBOX_FIELD_ALIASES.get(n2)
    if alias and any(p.key == alias for p in spec.params):
        return alias
    for p in spec.params:
        if p.key.replace("_", "") == n2:
            return p.key
    raise KeyError(f"unknown field {name!r} for {spec.key} "
                   f"(fields: {[p.key for p in spec.params if not p.is_padding]})")


def _new_value(op: dict, before, is_float: bool):
    if "value" in op:
        v = op["value"]
        return float(v) if is_float else int(round(float(v)))
    if "delta" in op:
        v = before + float(op["delta"])
        return float(v) if is_float else int(round(v))
    if "scale" in op:
        v = before * float(op["scale"])
        return float(v) if is_float else int(round(v))
    raise KeyError("op needs one of value / delta / scale")


def _hitbox_or_throw_targets(fd: FighterDat, mt: MoveTable, op: dict, code: int, which: str) -> list[int]:
    """Command indices addressed by a set_hitbox / set_throw op."""
    action = mt.action_index(op["move"], op.get("part"))
    s = fd.script(action)
    if s is None:
        raise KeyError(f"{op['move']} has no script")
    cmds = s.of_code(code)
    if not cmds:
        raise KeyError(f"{op['move']}/{mt.resolve(op['move'], op.get('part'))[1]} "
                       f"has no {'hitboxes' if code == CREATE_HITBOX else 'throw'}")
    sel = op.get(which, 0 if code == THROW else None)
    if sel is None:
        raise KeyError(f"op needs {which!r} (0..{len(cmds) - 1} or 'all')")
    if sel == "all":
        return [c.index for c in cmds]
    sel = int(sel)
    if not 0 <= sel < len(cmds):
        raise KeyError(f"{which} {sel} out of range (0..{len(cmds) - 1})")
    return [cmds[sel].index]


def _command_spec(name):
    """'create_hitbox' | 'Create Hitbox' | 11 -> Command."""
    if isinstance(name, int) or (isinstance(name, str) and name.strip().isdigit()):
        code = int(name)
        if code not in COMMANDS:
            raise KeyError(f"unknown command code {code}")
        return COMMANDS[code]
    if name is None:
        raise KeyError("command needs 'cmd' (e.g. 'create_hitbox')")
    n = re.sub(r"[^0-9a-z]+", "", str(name).lower())
    for c in COMMANDS.values():
        if c.key.replace("_", "") == n or re.sub(r"[^0-9a-z]+", "", c.name.lower()) == n:
            return c
    raise KeyError(f"unknown command {name!r} (known: {sorted(BY_KEY)})")


def normalize_command(d: dict) -> tuple[int, dict, int | None]:
    """A command dict -> (code, fields, pointer), validating names + ranges."""
    if not isinstance(d, dict):
        raise TypeError(f"command must be an object, got {type(d).__name__}")
    d = dict(d)
    name = d.pop("cmd", d.pop("command", d.pop("key", d.pop("name", None))))
    spec = _command_spec(name)
    nested = d.pop("fields", None)
    if isinstance(nested, dict):
        d.update(nested)
    for k in ("index", "frame_abs", "in_loop", "after_end"):
        d.pop(k, None)   # inspect_move metadata, not fields
    fields: dict[str, int] = {}
    pointer = None
    for k, v in d.items():
        if k == "pointer" and spec.code in POINTER_COMMANDS:
            pointer = int(v)
            continue
        key = _field_key(spec, k)
        p = spec.param(key)
        iv = int(round(float(v)))
        if not (p.min <= iv <= p.max):
            raise ValueError(f"{spec.key}.{key}={iv} out of range [{p.min}, {p.max}]")
        fields[key] = iv
    if spec.code in POINTER_COMMANDS:
        if pointer is None:
            pointer = fields.get("pointer")
        if pointer is None:
            raise KeyError(f"{spec.key} needs 'pointer' (data offset of the target script)")
        fields["pointer"] = pointer
    return spec.code, fields, pointer


def _plan_script_op(fd: FighterDat, mt: MoveTable, op: dict, kind: str):
    """Resolve a script op against the CURRENT scratch state; returns
    (action, body_before, body_after, old_offset)."""
    action = mt.action_index(op["move"], op.get("part"))
    cur = [it for it in fd.script_items(action) if it[0] != END_OF_SCRIPT]
    if kind == "set_script":
        cmds = op.get("commands")
        if not isinstance(cmds, list):
            raise KeyError("set_script needs 'commands': [...]")
        new = [normalize_command(c) for c in cmds]
    elif kind == "insert_command":
        cmds = op.get("commands")
        if cmds is None:
            cmds = [op["command"]] if "command" in op else None
        if not isinstance(cmds, list) or not cmds:
            raise KeyError("insert_command needs 'command': {...} or 'commands': [...]")
        at = op.get("at", "end")
        at = len(cur) if at == "end" else int(at)
        if not 0 <= at <= len(cur):
            raise ValueError(f"at={at} out of range (0..{len(cur)}; {len(cur)} = before End Of Script)")
        new = cur[:at] + [normalize_command(c) for c in cmds] + cur[at:]
    else:  # delete_command
        sel = op.get("command", op.get("commands"))
        if sel is None:
            raise KeyError("delete_command needs 'command': index or [indices]")
        idxs = sorted({int(x) for x in (sel if isinstance(sel, list) else [sel])})
        for x in idxs:
            if not 0 <= x < len(cur):
                raise ValueError(f"command {x} out of range (0..{len(cur) - 1}; "
                                 f"the End Of Script at {len(cur)} cannot be deleted)")
        new = [it for i, it in enumerate(cur) if i not in idxs]
    for code, fields, pointer in new:
        if code in POINTER_COMMANDS and not (0 <= int(pointer) < fd.dat.data_size):
            raise ValueError(f"pointer 0x{int(pointer):X} is outside the data section")
    return action, cur, new, fd.actions[action].script_offset


def plan(donor: bytes, ops: list[dict]) -> Plan:
    """Resolve every op against the donor WITHOUT writing. All errors at once.
    Script ops are applied to a scratch copy as they are planned so that
    later ops in the batch address the rewritten script."""
    fd = FighterDat(donor)
    mt = MoveTable(fd)
    attrs = Attributes(fd)
    out = Plan()
    for i, op in enumerate(ops):
        try:
            kind = op.get("op")
            if kind not in KNOWN_OPS:
                raise KeyError(f"unknown op {kind!r} (known: {KNOWN_OPS})")
            if kind in SCRIPT_OPS:
                action, cur, new, old_off = _plan_script_op(fd, mt, op, kind)
                fd.replace_script(action, new)
                out.steps.append(Planned(i, op, kind, action, None, "script",
                                         len(cur), len(new), old_off, payload=new))
                continue
            if kind == "set_attribute":
                key = resolve_key(op["name"])
                typ = next(a[2] for a in ATTRIBUTES if a[1] == key)
                before = attrs.get(key)
                after = _new_value(op, before, typ == "f")
                out.steps.append(Planned(i, op, kind, None, None, key, before, after,
                                         attrs.base + next(a[0] for a in ATTRIBUTES if a[1] == key)))
                continue
            if kind == "set_command":
                action = mt.action_index(op["move"], op.get("part"))
                targets = [int(op["command"])]
            else:
                code = CREATE_HITBOX if kind == "set_hitbox" else THROW
                which = "hitbox" if kind == "set_hitbox" else "throw"
                action = mt.action_index(op["move"], op.get("part"))
                targets = _hitbox_or_throw_targets(fd, mt, op, code, which)
            for ci in targets:
                cmd = fd._cmd(action, ci)
                key = _field_key(cmd.spec, op["field"])
                p = cmd.spec.param(key)
                before = cmd.fields[key]
                after = _new_value(op, before, False)
                if not (p.min <= after <= p.max):
                    raise ValueError(f"{key}={after} out of range [{p.min}, {p.max}]")
                out.steps.append(Planned(i, op, kind, action, ci, key, before, after, cmd.offset))
        except (KeyError, ValueError, IndexError, TypeError) as e:
            msg = e.args[0] if e.args else str(e)
            out.errors.append(f"op[{i}] {op.get('op')}: {msg}")
    return out


@dataclass
class ApplyResult:
    data: bytes
    plan: Plan
    changed: int

    def as_dict(self) -> dict:
        return {"ok": self.plan.ok, "changed": self.changed,
                "steps": [s.as_dict() for s in self.plan.steps],
                "errors": self.plan.errors}


def apply(donor: bytes, ops: list[dict]) -> ApplyResult:
    """Validate everything, then write. Raises OpError on the first problem
    (after collecting all of them into .plan)."""
    p = plan(donor, ops)
    if not p.ok:
        raise OpError(-1, {"op": "apply"}, "; ".join(p.errors))
    fd = FighterDat(donor)
    attrs = Attributes(fd)
    changed = 0
    for s in p.steps:
        if s.kind == "set_attribute":
            attrs.set(s.key, s.after)
        elif s.kind in SCRIPT_OPS:
            fd.replace_script(s.action, s.payload)
            changed += 1
            continue
        else:
            fd.set_field(s.action, s.command, s.key, s.after)
        if s.before != s.after:
            changed += 1
    return ApplyResult(fd.to_bytes(), p, changed)


# ---------------------------------------------------------------------------
# read side: what the inspector / chat sees
# ---------------------------------------------------------------------------
def describe(donor: bytes, include_other: bool = False) -> dict:
    fd = FighterDat(donor)
    mt = MoveTable(fd)
    attrs = Attributes(fd)
    return {"fighter": fd.fighter_name, "root": fd.ft_root_name,
            "actions": len(fd.actions),
            "moves": mt.listing(include_other=include_other),
            "attributes": attrs.listing()}


def inspect_move(donor: bytes, move: str, part: str | None = None,
                 donor_ref: bytes | None = None) -> dict:
    """Everything about one move part: hitboxes (with the donor's values
    alongside when `donor_ref` is given), throws, and the raw command list."""
    fd = FighterDat(donor)
    mt = MoveTable(fd)
    mv, part = mt.resolve(move, part)
    action = mv.parts[part]
    ref_hbs = ref_throws = None
    if donor_ref is not None:
        rfd = FighterDat(donor_ref)
        ref_hbs = rfd.hitboxes(action)
        ref_throws = rfd.throws(action)
    hitboxes = []
    for h in fd.hitboxes(action):
        item = dict(h)
        for k in SCALED_256:
            item[k + "_units"] = round(h[k] * UNIT_SCALE, 4)
        if ref_hbs is not None and h["ordinal"] < len(ref_hbs):
            item["donor"] = {p.key: ref_hbs[h["ordinal"]][p.key]
                             for p in COMMANDS[CREATE_HITBOX].params if not p.is_padding}
        hitboxes.append(item)
    throws = []
    for t in fd.throws(action):
        item = dict(t)
        if ref_throws is not None and t["ordinal"] < len(ref_throws):
            item["donor"] = {p.key: ref_throws[t["ordinal"]][p.key] for p in COMMANDS[THROW].params}
        throws.append(item)
    s = fd.script(action)
    commands = [{"index": c.index, "frame": c.frame, "key": c.key, "name": c.name,
                 "fields": {k: v for k, v in c.fields.items() if not k.startswith("_pad")},
                 "pointer": c.pointer, "in_loop": c.in_loop, "after_end": c.after_end}
                for c in (s.commands if s else [])]
    a = fd.actions[action]
    return {"move": mv.id, "label": mv.label, "part": part, "parts": list(mv.parts),
            "action": action, "motion": a.motion, "symbol": a.symbol,
            "anim_offset": a.anim_offset, "anim_size": a.anim_size,
            "hitboxes": hitboxes, "throws": throws, "commands": commands,
            "primary_fields": {"hitbox": HITBOX_PRIMARY, "throw": THROW_PRIMARY},
            "field_specs": {
                "hitbox": [_param_spec(p) for p in COMMANDS[CREATE_HITBOX].params if not p.is_padding],
                "throw": [_param_spec(p) for p in COMMANDS[THROW].params if not p.is_padding],
            }}


def _param_spec(p) -> dict:
    return {"key": p.key, "label": p.name, "bits": p.bits, "signed": p.signed,
            "min": p.min, "max": p.max, "enums": list(p.enums) if p.enums else None}


# ---------------------------------------------------------------------------
# diff: recover ops from an edited file
# ---------------------------------------------------------------------------
def diff(donor: bytes, edited: bytes) -> list[dict]:
    """Ops that turn `donor` into `edited` (scripts + attributes). The two
    files must share the donor's structure (same action table / script
    layout) -- that is exactly what an in-place edit guarantees."""
    a, b = FighterDat(donor), FighterDat(edited)
    if len(a.actions) != len(b.actions):
        raise ValueError("action tables differ in size -- not an in-place edit")
    mt = MoveTable(a)
    by_action = {}
    for mv in mt.moves.values():
        for part, idx in mv.parts.items():
            by_action[idx] = (mv.id, part)
    ops: list[dict] = []
    for act in a.actions:
        sa, sb = a.script(act.index), b.script(act.index)
        if sa is None or sb is None:
            continue
        if len(sa.commands) != len(sb.commands):
            raise ValueError(f"action {act.index} {act.motion}: script layout differs")
        hb_ord = {c.index: i for i, c in enumerate(sa.of_code(CREATE_HITBOX))}
        th_ord = {c.index: i for i, c in enumerate(sa.of_code(THROW))}
        move, part = by_action.get(act.index, (f"action{act.index}", None))
        for ca, cb in zip(sa.commands, sb.commands):
            if ca.code != cb.code:
                raise ValueError(f"action {act.index} cmd {ca.index}: opcode differs")
            for k, va in ca.fields.items():
                vb = cb.fields[k]
                if va == vb or k.startswith("_pad"):
                    continue
                base = {"move": move, "field": k, "value": vb}
                if part is not None and part != "main":
                    base["part"] = part
                if ca.code == CREATE_HITBOX:
                    ops.append({"op": "set_hitbox", "hitbox": hb_ord[ca.index], **base})
                elif ca.code == THROW:
                    ops.append({"op": "set_throw", "throw": th_ord[ca.index], **base})
                else:
                    ops.append({"op": "set_command", "command": ca.index, **base})
    aa, ab = Attributes(a), Attributes(b)
    for _, key, typ, _ in ATTRIBUTES:
        va, vb = aa.get(key), ab.get(key)
        if va != vb:
            ops.append({"op": "set_attribute", "name": key, "value": vb})
    return ops
