"""
effect_probe.py -- spec-driven live-poke effect probe. Generalizes
datram_probe.py (Fox/EfFxData) and datram_probe_ca.py (Falcon/EfCaData) into
ONE tool so future extras-mapping missions write a JSON spec instead of a new
Python driver.

ONE boot, many experiments: boots a vanilla ISO on the requested character +
stage (plain bg), locates every DAT named in the spec inside RAM, then per
experiment: poke test colors (with readback verification) -> run each move,
capturing the listed frames (recentering between moves so movement moves like
Falcon Kick / Raptor Boost don't slide off the stage -- see
datram_probe_ca.py's safe_reset) -> restore every poked region. No ISO
rebuilds, no reboots between experiments.

Run from backend/:  python devtools/effect_probe.py <spec.json>
                     python devtools/effect_probe.py <spec.json> --dry-run

See probes/effect_probe.example.json for a realistic spec (Falcon kick/raptor,
distilled from datram_probe_ca.py).

Spec schema (JSON):
{
  "iso": "path (default output/extras-audit-Fox-laser_ring-vanilla.iso)",
  "char": "name or 0xNN (resolved like frameshot --char)",
  "color": 0,                                        // costume slot, optional
  "stage": "finaldestination",                        // optional, default FD
  "bag": {"char": "dk", "dx": 8, "dy": 0},            // optional punching-bag
  //   2nd player (HUMAN port, no controller: stands still) parked dx units in
  //   front of the attacker each rep, so ON-HIT-ONLY effects are capturable;
  //   shorthand "bag": "dk". The bag's action state is logged per capture
  //   (damage state = the move connected).
  "kirby_copy": "ganon",                              // optional (Kirby only):
  //   give the attacker this donor's COPY ABILITY before the experiments run
  //   (KO->rebirth primitive, match_setup.install_kirby_copy_via_rebirth), so
  //   'neutralb' fires the COPIED special drawing the EfKb<XX> copy bank.
  //   Also valid per-experiment (overrides; re-rebirths on donor change).
  //   ⚠ the donor MUST be in the match ("bag" = the donor char) -- installing
  //   a copy of an absent donor HANGS the game (see match_setup.py); one boot
  //   per donor (backend/probes/kirby_copy/<donor>.json).
  "out": "output dir under scratch/ingame/ (default datram-probe-<char>)",
  "dats": {"alias": "path under storage/test-base/files/", ...},
  "moves": {"movename": [frames...], ...},             // capture frames/move
  //   a move may instead map to an object to schedule mid-move pipe inputs
  //   (frameshot --input-at style; e.g. fire Samus's charge shot with a
  //   second B press): {"frames": [...], "inputs": ["50:PRESS B|RELEASE B"]}
  "experiments": [
    {"name": "vanilla"},                               // control: no pokes
    {"name": "kick_core", "pokes": [
        {"dat": "alias", "offset": "0x1DE04", "rgb": "00FF00"},
        {"dat": "alias", "range": ["0x12F", "0x1C0"], "stride": 5,
         "bases": ["FFFFFF", "7F7F7F"], "rgb": "FF00FF"}
      ],
     "moves": ["downb"]}                                // optional subset
  ]
}

Poke forms:
- exact:  {"dat", "offset", "rgb"} -- unconditional 3-byte write at `offset`.
- table:  {"dat", "range": [start, end], "stride", "bases", "rgb"} --
  verify-before-poke recolor: only offsets (within [start,end), every
  `stride` bytes) whose current 3 bytes match one of `bases` get overwritten
  with `rgb`. Mirrors datram_probe.py's apply_group()/verify_group().
- fill:   {"dat", "offset", "size", "byte": "0xFF"} -- memset a whole block
  (texture regions: e.g. flood an IA8 image to a solid disc).
- copy:   {"dat", "offset", "size", "from_file": "path", "src_offset": opt}
  -- block-copy bytes out of another file (e.g. splice a community mod's
  texture region in live). `src_offset` defaults to `offset`; a relative
  `from_file` resolves against storage/test-base/files/ like 'dats'.

Captures -> scratch/ingame/<out>/<experiment>-<move>-f<NN>.png
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from core.config import STORAGE_PATH, PROJECT_ROOT  # noqa: E402
from shared.ingame.char_select import ckind as resolve_ckind  # noqa: E402
from shared.ingame.match_setup import KIRBY_COPY_FTKIND  # noqa: E402
from shared.ingame.melee_sss import INTERNAL_STAGE_ID  # noqa: E402
from shared.ingame.moves import MOVES  # noqa: E402

RUNS_ROOT = STORAGE_PATH / "test-runs"
ARTIFACTS_ROOT = PROJECT_ROOT / "scratch" / "ingame"
DAT_ROOT = STORAGE_PATH / "test-base" / "files"
DEFAULT_ISO = PROJECT_ROOT / "output" / "extras-audit-Fox-laser_ring-vanilla.iso"

REBIRTH, REBIRTH_WAIT = 12, 13   # gamestate ids: recovery states that can
                                  # leave a fighter off-stage after a
                                  # movement move (Falcon Kick, Raptor Boost)
START_X = -55.0                   # recenter target; matches datram_probe_ca.py


def log(m):
    print(f"[probe] {m}", flush=True)


# ---------------------------------------------------------------------------
# spec parsing
# ---------------------------------------------------------------------------

def parse_int(v):
    """Accept an int, a '0x..' string, or a plain decimal string."""
    if isinstance(v, int):
        return v
    return int(str(v), 0)


def parse_rgb(v):
    """Accept 'RRGGBB' hex string, [r,g,b] list, or 3-byte-hex-ish forms."""
    if isinstance(v, (list, tuple)):
        if len(v) != 3:
            raise ValueError(f"rgb list must have 3 components: {v}")
        return bytes(int(c) & 0xFF for c in v)
    s = str(v).lstrip("#")
    if len(s) != 6:
        raise ValueError(f"rgb hex string must be 6 hex chars: {v!r}")
    return bytes.fromhex(s)


class Poke:
    """One poke instruction, resolved from the spec JSON. Either an exact
    offset write, or a verify-before-poke table recolor (see module doc)."""

    def __init__(self, dat_alias, raw):
        self.dat_alias = dat_alias
        self.rgb = parse_rgb(raw["rgb"]) if "rgb" in raw else None
        if "fill" in raw or "byte" in raw or "from_file" in raw:
            # block poke over [offset, offset+size): memset or file-copy
            self.offset = parse_int(raw["offset"])
            self.size = parse_int(raw["size"])
            self.start = self.end = self.stride = None
            self.bases = None
            if "from_file" in raw:
                self.kind = "copy"
                src = Path(raw["from_file"])
                if not src.is_absolute():
                    src = DAT_ROOT / src
                self.src_path = src
                self.src_offset = parse_int(raw.get("src_offset",
                                                    raw["offset"]))
                self.block = None   # read lazily so --dry-run validates paths
            else:
                self.kind = "fill"
                self.block = bytes([parse_int(raw.get("byte", raw.get("fill", "0xFF"))) & 0xFF]) * self.size
            return
        if "range" in raw:
            self.kind = "table"
            start, end = raw["range"]
            self.start = parse_int(start)
            self.end = parse_int(end)
            self.stride = int(raw.get("stride", 3))
            bases = raw.get("bases") or ["FFFFFF"]
            self.bases = {parse_rgb(b) for b in bases}
            self.offset = None
        elif "offset" in raw:
            self.kind = "exact"
            self.offset = parse_int(raw["offset"])
            self.start = self.end = self.stride = None
            self.bases = None
        else:
            raise ValueError(f"poke needs 'offset' or 'range': {raw}")

    def describe(self):
        if self.kind == "fill":
            return (f"{self.dat_alias}@0x{self.offset:X}+0x{self.size:X} "
                    f"memset 0x{self.block[0]:02X}")
        if self.kind == "copy":
            return (f"{self.dat_alias}@0x{self.offset:X}+0x{self.size:X} "
                    f"<- {self.src_path.name}@0x{self.src_offset:X}")
        rgb_hex = self.rgb.hex().upper()
        if self.kind == "exact":
            return f"{self.dat_alias}@0x{self.offset:X} -> #{rgb_hex}"
        bases_hex = "/".join(b.hex().upper() for b in sorted(self.bases))
        return (f"{self.dat_alias}[0x{self.start:X}-0x{self.end:X} "
                f"stride {self.stride}, bases {bases_hex}] -> #{rgb_hex}")


class Experiment:
    def __init__(self, raw, default_moves):
        self.name = raw["name"]
        self.pokes = [Poke(p["dat"], p) for p in raw.get("pokes", [])]
        self.moves = raw.get("moves") or list(default_moves)
        # optional Kirby copy-ability donor: before this experiment runs, the
        # (Kirby) attacker is given the donor's copy ability via the
        # KO->rebirth primitive (match_setup.install_kirby_copy_via_rebirth),
        # so 'neutralb' fires the COPIED special drawing the EfKb<XX> bank.
        self.kirby_copy = raw.get("kirby_copy")

    @property
    def is_control(self):
        return not self.pokes


class Spec:
    def __init__(self, path):
        self.path = Path(path)
        raw = json.loads(self.path.read_text())

        self.iso = Path(raw.get("iso", str(DEFAULT_ISO))).resolve()
        self.char_raw = raw.get("char", "fox")
        self.color = int(raw.get("color", 0))
        self.stage = raw.get("stage", "finaldestination")

        # optional punching-bag 2nd player (a HUMAN port with no controller --
        # stands still, never attacks, never moves the camera) so on-hit-only
        # effects become capturable:
        #   "bag": {"char": "dk", "color": 0, "dx": 8, "dy": 0}
        # or the shorthand  "bag": "dk"  (defaults: dx=8 units in front, dy=0).
        bag_raw = raw.get("bag")
        if isinstance(bag_raw, str):
            bag_raw = {"char": bag_raw}
        self.bag = None
        if bag_raw:
            self.bag = {
                "char": bag_raw.get("char", "dk"),
                "color": int(bag_raw.get("color", 0)),
                "dx": float(bag_raw.get("dx", 8.0)),
                "dy": float(bag_raw.get("dy", 0.0)),
                # opt-in knockback suppression (rapid-jab / command-grab
                # finishers: keep the bag pinned in range through hard hits)
                "pin": bool(bag_raw.get("pin", False)),
            }

        char_label = (self.char_raw.lower()
                      if resolve_ckind(self.char_raw) is not None
                      else f"0x{parse_int(self.char_raw):02X}")
        self.out = Path(raw.get("out", f"datram-probe-{char_label}"))
        if not self.out.is_absolute():
            self.out = ARTIFACTS_ROOT / self.out

        dats = raw.get("dats")
        if not dats:
            raise SystemExit("spec needs a non-empty 'dats' map")
        self.dats = {}
        for alias, rel in dats.items():
            p = Path(rel)
            if not p.is_absolute():
                p = DAT_ROOT / rel
            self.dats[alias] = p

        moves = raw.get("moves")
        if not moves:
            raise SystemExit("spec needs a non-empty 'moves' map")
        self.moves = {}
        self.move_inputs = {}   # move -> {frame: [pipe lines]}
        for name, val in moves.items():
            if name not in MOVES:
                raise SystemExit(f"unknown move '{name}' "
                                 f"(known: {', '.join(MOVES)})")
            if isinstance(val, dict):
                frames = val.get("frames") or []
                sched = {}
                for spec_str in val.get("inputs", []):
                    n, _, lines = str(spec_str).partition(":")
                    sched.setdefault(int(n), []).extend(lines.split("|"))
                if sched:
                    self.move_inputs[name] = sched
            else:
                frames = val
            if not frames:
                raise SystemExit(f"move '{name}' has no capture frames")
            self.moves[name] = [int(f) for f in frames]

        # optional top-level Kirby copy donor (per-experiment key overrides)
        self.kirby_copy = raw.get("kirby_copy")

        exps_raw = raw.get("experiments")
        if not exps_raw:
            raise SystemExit("spec needs a non-empty 'experiments' list")
        self.experiments = [Experiment(e, self.moves) for e in exps_raw]
        for donor in {self.kirby_copy} | {e.kirby_copy
                                          for e in self.experiments}:
            if donor is not None and donor not in KIRBY_COPY_FTKIND:
                raise SystemExit(
                    f"unknown kirby_copy donor '{donor}' "
                    f"(known: {', '.join(sorted(KIRBY_COPY_FTKIND))})")
        for e in self.experiments:
            for m in e.moves:
                if m not in self.moves:
                    raise SystemExit(
                        f"experiment '{e.name}' references move '{m}' "
                        f"not present in the top-level 'moves' map")
            for pk in e.pokes:
                if pk.dat_alias not in self.dats:
                    raise SystemExit(
                        f"experiment '{e.name}' references dat "
                        f"'{pk.dat_alias}' not present in 'dats'")

    def char_kind(self):
        kind = resolve_ckind(self.char_raw)
        if kind is not None:
            return kind
        try:
            return parse_int(self.char_raw)
        except ValueError:
            raise SystemExit(f"unknown character '{self.char_raw}' "
                             f"(name or external id like 0x1A)")

    def char_label(self):
        return (self.char_raw.lower()
                if resolve_ckind(self.char_raw) is not None
                else f"0x{self.char_kind():02X}")

    def bag_kind(self):
        if not self.bag:
            return None
        kind = resolve_ckind(self.bag["char"])
        if kind is not None:
            return kind
        try:
            return parse_int(self.bag["char"])
        except ValueError:
            raise SystemExit(f"unknown bag character '{self.bag['char']}' "
                             f"(name or external id like 0x1A)")

    def validate_paths(self):
        problems = []
        if not self.iso.exists():
            problems.append(f"ISO missing: {self.iso}")
        if self.stage not in INTERNAL_STAGE_ID:
            problems.append(f"unknown stage '{self.stage}' "
                            f"(known: {', '.join(sorted(INTERNAL_STAGE_ID))})")
        for alias, p in self.dats.items():
            if not p.exists():
                problems.append(f"dat '{alias}' missing: {p}")
        for e in self.experiments:
            for pk in e.pokes:
                if pk.kind == "copy" and not pk.src_path.exists():
                    problems.append(f"copy poke source missing: {pk.src_path}")
        return problems

    def print_plan(self):
        log(f"spec: {self.path}")
        log(f"iso: {self.iso}")
        log(f"char: {self.char_raw} (ckind=0x{self.char_kind():02X}) "
            f"color={self.color} stage={self.stage}")
        if self.bag:
            log(f"bag: {self.bag['char']} (ckind=0x{self.bag_kind():02X}) "
                f"color={self.bag['color']} at dx={self.bag['dx']} "
                f"dy={self.bag['dy']} (human port, no controller)"
                + (" [PINNED: knockback suppressed]" if self.bag['pin'] else ""))
        log(f"out: {self.out}")
        log("dats:")
        for alias, p in self.dats.items():
            exists = "OK" if p.exists() else "MISSING"
            log(f"  {alias} -> {p} [{exists}]")
        log("moves (capture frames):")
        for name, frames in self.moves.items():
            extra = ""
            if name in self.move_inputs:
                extra = " inputs=" + "; ".join(
                    f"f{n}:{'|'.join(ls)}"
                    for n, ls in sorted(self.move_inputs[name].items()))
            log(f"  {name}: {frames}{extra}")
        log(f"experiments ({len(self.experiments)}):")
        for e in self.experiments:
            copy = e.kirby_copy or self.kirby_copy
            tag = f" [kirby-copy: {copy}]" if copy else ""
            if e.is_control:
                log(f"  {e.name}: CONTROL (no pokes), moves={e.moves}{tag}")
            else:
                log(f"  {e.name}: {len(e.pokes)} poke(s), moves={e.moves}{tag}")
                for pk in e.pokes:
                    log(f"    - {pk.describe()}")


# ---------------------------------------------------------------------------
# runtime helpers (mirrors datram_probe.py / datram_probe_ca.py)
# ---------------------------------------------------------------------------

def assert_plain_bg(d, rgb_hex="404040"):
    d.write_u32(0x80452C70, (int(rgb_hex, 16) & 0xFFFFFF) << 8)
    d.write_u32(0x80453000, 0x00C40000)


def capture(boot, shot, path):
    png = shot.capture_via_printwindow(boot.pid, max_width=1280)
    if not png:
        png = shot.capture_png(boot.pid, max_width=1280)
    if png:
        path.write_bytes(png)
    return bool(png)


def apply_poke(dat, pk):
    """Apply one Poke. Returns the number of records/bytes actually written."""
    if pk.kind in ("fill", "copy"):
        if pk.block is None:   # copy: read the source region lazily
            pk.block = pk.src_path.read_bytes()[pk.src_offset:
                                                pk.src_offset + pk.size]
            if len(pk.block) != pk.size:
                raise SystemExit(f"copy poke source too short: {pk.describe()}")
        dat.poke(pk.offset, pk.block)
        return pk.size
    if pk.kind == "exact":
        dat.poke(pk.offset, pk.rgb)
        return 1
    hit = 0
    cur = dat.read(pk.start, pk.end - pk.start)
    for off in range(0, pk.end - pk.start, pk.stride):
        if bytes(cur[off:off + 3]) in pk.bases:
            dat.poke(pk.start + off, pk.rgb)
            hit += 1
    return hit


def verify_poke(dat, pk):
    """Read back: for table pokes, no unpoked base-color record should
    remain (every match got overwritten). For exact pokes, the target bytes
    should now equal rgb."""
    if pk.kind in ("fill", "copy"):
        return bytes(dat.read(pk.offset, pk.size)) == pk.block
    if pk.kind == "exact":
        return bytes(dat.read(pk.offset, 3)) == pk.rgb
    cur = dat.read(pk.start, pk.end - pk.start)
    for off in range(0, pk.end - pk.start, pk.stride):
        if bytes(cur[off:off + 3]) in pk.bases:
            return False
    return True


def restore_poke(dat, pk):
    if pk.kind in ("fill", "copy"):
        dat.restore(pk.offset, pk.size)
    elif pk.kind == "exact":
        dat.restore(pk.offset, 3)
    else:
        dat.restore_range(pk.start, pk.end)


def safe_reset(runner, center_x=START_X):
    """reset(), but recover first if the previous move slid the fighter off
    the stage (RebirthWait on the halo -> drop, land, then normal reset).
    Movement moves like Falcon Kick / Raptor Boost travel far enough that a
    plain reset() can leave them stranded mid-air over the blast zone --
    see datram_probe_ca.py's safe_reset()."""
    st = runner.player.state()
    if st in (REBIRTH, REBIRTH_WAIT):
        runner.p.frame(["SET MAIN 0.500 0.000", "FLUSH"])  # drop off halo
        runner._step(3)
        runner.p.neutral()
        runner.player.set_pos(center_x, 25.0)              # fall to ground
        for _ in range(180):
            runner._step(1)
            if runner.player.state() == 14:                # Wait
                break
    runner.reset(center_x=center_x)


def _pinned_step(runner, bag, bag_pin, n):
    """Step n frames; if bag_pin, zero the bag's knockback each frame so a hard
    hit can't push it out of range (rapid-jab/command-grab finishers). Returns
    the real frame count."""
    if not (bag and bag_pin):
        return runner._step(n)
    got = 0
    for _ in range(n):
        got += runner._step(1)
        bag.pin()
    return got


def run_move_and_capture(runner, boot, shot, d, out_dir, move, frames, label,
                         sched=None, bag=None, bag_dx=8.0, bag_dy=0.0,
                         bag_pin=False):
    """sched: optional {move_frame: [pipe lines]} of mid-move inputs (e.g. a
    second B press to fire Samus's charge shot) -- frameshot --input-at.
    bag: optional gamestate.Bag (punching-bag 2nd player); parked `bag_dx`
    units in front of the attacker before the move so it connects, with the
    bag's action state logged per capture (damage state = proof of a hit).
    bag_pin: zero the bag's knockback velocity every stepped frame + re-pin its
    position, so it can't be launched out of range (rapid-jab Attack100 loop,
    Gerudo re-grab)."""
    from shared.ingame.moves import park_bag
    safe_reset(runner)
    if bag:
        park_bag(runner, bag, dx=bag_dx, dy=bag_dy)
    runner.execute(move)
    sched = sched or {}
    bag_hit = False
    cur = 1
    for target in frames:
        while cur < target:
            stops = [f for f in sched if cur < f <= target]
            nxt = min(stops) if stops else target
            cur += _pinned_step(runner, bag, bag_pin, nxt - cur)
            if cur in sched:
                runner.p.frame(list(sched[cur]) + ["FLUSH"])
                log(f"  (frame {cur}: sent {'; '.join(sched[cur])})")
        assert_plain_bg(d)
        time.sleep(0.1)
        p = out_dir / f"{label}-{move}-f{cur:02d}.png"
        capture(boot, shot, p)
        extra = ""
        if bag:
            bs = bag.snapshot()
            hit = bag.in_damage()
            bag_hit = bag_hit or hit
            extra = f" | bag={bs['state_name']}{' (HIT)' if hit else ''}"
        log(f"  captured {p.name}{extra}")
    if bag:
        log(f"  bag hit during {move}: {bag_hit}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("spec", help="path to the JSON probe spec")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse the spec, resolve char/dat paths, print the "
                         "experiment plan, and exit before boot")
    args = ap.parse_args()

    spec = Spec(args.spec)
    spec.print_plan()

    if args.dry_run:
        problems = spec.validate_paths()
        if problems:
            log("dry-run: PROBLEMS found:")
            for p in problems:
                log(f"  - {p}")
        else:
            log("dry-run: OK, no problems found")
        return 1 if problems else 0

    problems = spec.validate_paths()
    if problems:
        for p in problems:
            log(f"ERROR: {p}")
        raise SystemExit(1)

    # Imports that touch Dolphin/boot machinery are deferred past --dry-run
    # so the dry-run path never needs a live emulator or pipe.
    from shared.ingame.boot import DolphinBoot, _write_ini
    from shared.ingame.melee_mem import Dolphin
    from shared.ingame.melee_css import Cursor
    from shared.ingame.melee_sss import StageCursor
    from shared.ingame.observe import wait_in_game, wait_game_frames
    from shared.ingame import nav, match_setup, framestep
    from shared.ingame import screenshot as shot
    from shared.ingame.moves import MoveRunner, MoveError
    from shared.ingame.datram import DatRam

    out_dir = spec.out
    out_dir.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)

    char_kind = spec.char_kind()
    char_label = spec.char_label()

    boot = DolphinBoot(str(spec.iso), None, str(RUNS_ROOT), clean_osd=True, log=log)
    p = None
    try:
        boot.prepare()
        _write_ini(str(boot.user_dir / "Config" / "Dolphin.ini"),
                   lambda upsert, _r: upsert("Core", "SlippiOnlineDelay", "0"))
        boot.launch()
        if not boot.wait_for_pipe(timeout=45):
            raise SystemExit("input pipe never appeared")
        d = Dolphin(boot.pid)
        t0 = time.time()
        while not d.locate() and time.time() - t0 < 20:
            if not d.alive():
                raise SystemExit("Dolphin died during boot")
            time.sleep(0.4)

        match_setup.patch_one_player(d, log=log)
        uses_kirby_copy = any(e.kirby_copy or spec.kirby_copy
                              for e in spec.experiments)
        if uses_kirby_copy:
            # JIT gotcha: arm before Kirby's first spawn compiles the function
            if not match_setup.arm_kirby_copy_ondeath(d, log=log):
                raise SystemExit("could not arm the Kirby copy-ability patch")
        p = boot.open_pipe()
        if not nav.nav_to_css(d, p, log=log):
            raise SystemExit("never reached the offline CSS")
        nav.wait_css_ready(d, Cursor(d, p), log=log)
        match_setup.force_time_infinite(d, log=log)

        bag_kind = spec.bag_kind()

        def write_players():
            if bag_kind is None:
                match_setup.write_solo_player(d, char_kind, spec.color)
            else:
                match_setup.write_bag_player(d, char_kind, spec.color,
                                             bag_ckind=bag_kind,
                                             bag_color=spec.bag["color"])

        log(f"memory-select {char_label} (ckind=0x{char_kind:02X})"
            + (f" + bag 0x{bag_kind:02X}" if bag_kind is not None else " solo")
            + "...")
        write_players()
        match_setup.warp_to_stage_select(d)
        sc = StageCursor(d, p)
        if not sc.wait_for_stage_select(timeout=8.0):
            raise SystemExit("CSS->SSS warp did not land")
        write_players()
        if not sc.force_select(INTERNAL_STAGE_ID[spec.stage]):
            raise SystemExit("match never started")
        if not wait_in_game(d, timeout=25.0, log=log):
            raise SystemExit("never reached in-game")
        wait_game_frames(d, 200)
        # Route each fighter to its own pad -- the CSS->SSS warp skips the
        # vanilla PlayerInitData->StaticPlayer.player_id copy, so without this
        # every port polls pad 0 = the pipe and the bag MIRRORS the attacker.
        match_setup.fix_player_pad_indices(
            d, [0] if bag_kind is None else [0, 1], log=log)
        assert_plain_bg(d)

        # ---- locate every dat named in the spec ----
        def locate_dat(alias, dat):
            """Window-vote + targeted-signature fallback (datram_probe.py's
            trail-record fallback search). Returns True if any base found."""
            mem = d.snapshot()
            bases = dat.locate(mem=mem, min_votes=2)
            log(f"{alias} ({dat.path.name}) window-vote bases: "
                f"{', '.join(f'0x{b:08X}' for b in bases) or 'none'}")
            if not bases:
                for off, win in dat._windows():
                    hits = dat.find(win, mem=mem)
                    extra = [h - off for h in hits
                             if (h - off) not in dat.bases and (h - off) >= 0]
                    if extra:
                        dat.bases = sorted(set(dat.bases) | set(extra))
                        log(f"{alias}: targeted search found "
                            f"{len(extra)} copy(ies) the vote missed")
            return bool(dat.bases)

        dats = {}
        for alias, path in spec.dats.items():
            dat = DatRam(d, path)
            if not locate_dat(alias, dat):
                if uses_kirby_copy:
                    # Kirby copy banks load ON DEMAND when the copy ability
                    # installs (the classic swallow lag hitch) -- not at match
                    # start. Re-locate after the experiment's copy install.
                    log(f"{alias} ({path.name}) not in RAM yet (copy banks "
                        f"load on install); will re-locate per experiment")
                else:
                    raise SystemExit(
                        f"{alias} ({path.name}) image NOT found in RAM")
            dats[alias] = dat

        framestep.freeze(d)
        runner = MoveRunner(d, p, log=log)
        runner.player.resolve()
        bag = None
        if bag_kind is not None:
            from shared.ingame.gamestate import Bag
            bag = Bag(d, port=1)
            if not bag.resolve():
                raise SystemExit("bag player never spawned (port 1 ft is null)")
            log(f"bag resolved on port 1: {bag.snapshot()['state_name']}")

        current_copy = None
        for exp in spec.experiments:
            want_copy = exp.kirby_copy or spec.kirby_copy
            if want_copy and want_copy != current_copy:
                log(f"{exp.name}: installing Kirby copy ability "
                    f"'{want_copy}' (KO -> rebirth)...")
                hat = match_setup.install_kirby_copy_via_rebirth(
                    d, match_setup.KIRBY_COPY_FTKIND[want_copy],
                    port=0, log=log)
                runner.player.resolve()
                if bag:
                    bag.resolve()
                safe_reset(runner)          # drops off the rebirth halo
                if hat != match_setup.KIRBY_COPY_FTKIND[want_copy]:
                    log(f"{exp.name}: COPY INSTALL FAILED (hat.kind={hat}); "
                        f"skipping this experiment")
                    continue
                current_copy = want_copy
                log(f"{exp.name}: copy '{want_copy}' installed "
                    f"(hat.kind=0x{hat:02X}); copied neutral-B state expect "
                    f"{match_setup.KIRBY_COPY_STATES[want_copy]}")

            missing = False
            for pk in exp.pokes:
                dat = dats[pk.dat_alias]
                if not dat.bases and not locate_dat(pk.dat_alias, dat):
                    log(f"{exp.name}: {pk.dat_alias} STILL not in RAM after "
                        f"the copy install; skipping this experiment")
                    missing = True
                    break
            if missing:
                continue

            applied = []   # (dat_alias, poke, hit_count)
            for pk in exp.pokes:
                dat = dats[pk.dat_alias]
                n = apply_poke(dat, pk)
                ok = verify_poke(dat, pk)
                log(f"{exp.name}: {pk.describe()} -> poked {n} "
                    f"| readback {'OK' if ok else 'FAILED'}")
                applied.append((dat, pk))

            for move in exp.moves:
                frames = spec.moves[move]
                try:
                    run_move_and_capture(runner, boot, shot, d, out_dir,
                                         move, frames, exp.name,
                                         sched=spec.move_inputs.get(move),
                                         bag=bag,
                                         bag_dx=spec.bag["dx"] if bag else 8.0,
                                         bag_dy=spec.bag["dy"] if bag else 0.0,
                                         bag_pin=spec.bag["pin"] if bag else False)
                except MoveError as e:
                    # one bad recipe (e.g. a char-specific grab state) must
                    # not kill the whole boot -- log, recover, continue
                    log(f"{exp.name}: MOVE FAILED ({move}): {e}")
                    try:
                        runner.p.neutral()
                        safe_reset(runner)
                    except Exception:
                        pass

            for dat, pk in applied:
                restore_poke(dat, pk)
            if applied:
                log(f"{exp.name}: restored {len(applied)} poke(s)")

        log(f"done -> {out_dir}")
    finally:
        try:
            if p:
                p.close()
        except Exception:
            pass
        boot.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
