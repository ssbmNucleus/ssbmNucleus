"""Build an "Any Climbers" pair: two fighters sharing one CSS slot.

Melee already models a character as *up to two* fighters -- that is how the Ice
Climbers and Zelda/Sheik work -- and m-ex exposes it per fighter as
`subCharacter` + `subCharacterBehavior` (0 = spawn together). So a pair needs no
new engine concept: duplicate the leader into a fresh slot and point its
sub-fighter at the partner.

What the stock engine will *not* do is give the partner Nana's follow-the-leader
AI, because that selection is hardcoded to `fp->kind == FTKIND_NANA`. The
`Any Climbers` Gecko code in `echo/climbers/any_climbers.ini` generalises it;
`ensure_engine_code` puts it in the project.

A pair is built as an ordinary fighter package (the same zip `export-fighter`
produces) so it lands in the vault as a normal custom character and inherits the
whole existing card / install / delete / export pipeline.
"""
from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from pathlib import Path

from vault.climbers import colors as color_match
from vault.climbers import roster
from vault.climbers.portraits import composite

logger = logging.getLogger(__name__)

# Fighters that cannot lead a pair. Popo's up-B (Belay) and down-B (Squall
# Hammer) call into ftNn_* expecting the partner to be in Nana's motion states,
# so an Ice Climbers leader gets a broken special. Zelda and Sheik already own
# a sub-fighter (each other) and a transform that would fight the pairing.
_BLOCKED_LEADERS = {"ice climbers", "popo", "nana", "zelda", "sheik"}

# Fighters that cannot be a partner. The engine code identifies a follower as
# "second entity, and not one of the transform kinds" -- kinds 7 (Sheik) and 19
# (Zelda) are deliberately excluded there, so they can never follow. Popo's
# specials need a Nana, and only the picked fighter's sub-fighter ever spawns.
_BLOCKED_PARTNERS = {"ice climbers", "popo", "zelda", "sheik", "nana"}

# The last six internal slots are always the non-selectable specials (hands,
# wireframes, Giga Bowser, Sandbag); m-ex inserts added fighters before them.
_SPECIAL_SLOT_COUNT = 6


def _assets_dir(project_path) -> Path:
    return Path(project_path).parent / "assets"


def load_fighters(project_path) -> list[dict]:
    """Every fighter in the project, indexed by internal id (list position)."""
    out = []
    from mexcli.project import fighter_files
    for path in fighter_files(project_path):
        with open(path, encoding="utf-8-sig") as fh:
            out.append(json.load(fh))
    return out


def _asset_png(project_path, ref: str | None) -> bytes | None:
    """Resolve a fighter.json asset reference ('csp\\csp_011') to PNG bytes."""
    if not ref:
        return None
    path = _assets_dir(project_path) / (ref.replace("\\", "/") + ".png")
    return path.read_bytes() if path.exists() else None


def candidates(project_path=None) -> list[dict]:
    """Selectable fighters plus why each is or isn't usable on either side.

    Works with **no project open** — the vault is project-independent and so is
    this picker. With a project it uses that roster instead, so added m-ex
    fighters appear and costume counts match what will actually be built.
    """
    if project_path is None:
        return roster.vanilla_candidates()

    fighters = load_fighters(project_path)
    playable_count = max(0, len(fighters) - _SPECIAL_SLOT_COUNT)

    out = []
    for internal_id, fighter in enumerate(fighters):
        if internal_id >= playable_count:
            continue
        name = fighter.get("name", f"Fighter {internal_id}")
        if not roster.is_selectable(name):
            # Same exclusion the no-project path applies. Nana is a real
            # fighter with a real roster slot, but she only ever exists as the
            # Ice Climbers' follower and ships no css_icon.png -- listing her
            # put a broken, permanently-blocked tile in the picker.
            continue
        key = name.strip().lower()
        costumes = fighter.get("costumes") or []
        paired = fighter.get("subCharacter", -1) not in (-1, 255)

        leader_block = None
        if key in _BLOCKED_LEADERS:
            leader_block = f"{name} can't lead a pair"
        elif paired:
            leader_block = f"{name} already has a sub-fighter"

        # A partner's own sub-fighter is no reason to refuse it: the game reads
        # `subCharacter` from the picked fighter alone (ftMapping_list), so a
        # pair of two clones points at a partner built as a pair, whose own
        # partner never spawns. A transform (behaviour != 0) can't follow.
        partner_block = None
        if key in _BLOCKED_PARTNERS:
            partner_block = f"{name} can't be a partner"
        elif paired and fighter.get("subCharacterBehavior", 0) != 0:
            partner_block = f"{name} transforms, so it can't follow"

        out.append({
            "internalId": internal_id,
            "name": name,
            "costumeCount": len(costumes),
            "canLead": leader_block is None,
            "canPartner": partner_block is None,
            "leaderBlockedReason": leader_block,
            "partnerBlockedReason": partner_block,
        })
    return out


def find_by_name(fighters: list[dict], name: str) -> int | None:
    """Internal id of the fighter called `name`, or None.

    Pairs are stored by NAME rather than internal id: the id of a given fighter
    shifts as m-ex fighters are added, and a vault pair has to survive being
    installed into a project it was never created against.
    """
    wanted = name.strip().lower()
    for internal_id, fighter in enumerate(fighters):
        if fighter.get("name", "").strip().lower() == wanted:
            return internal_id
    return None


def _no_swap_path(project_path) -> Path:
    """Beside the .mexproj, not in `data/`: fighter.json can't carry this,
    because MexCLI rewrites those files with only the fields it knows."""
    return Path(project_path).parent / "climbers.json"


def no_swap_pairs(project_path) -> list[str]:
    """Names of the project's pairs that keep their leader all match."""
    path = _no_swap_path(project_path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("noSwap", [])


def set_no_swap(project_path, name: str) -> None:
    """Turn the D-pad swap off for one pair; the next export carries it."""
    names = sorted({*no_swap_pairs(project_path), name})
    _no_swap_path(project_path).write_text(json.dumps({"noSwap": names}, indent=2), encoding="utf-8")


def fighter_art(name: str, color: int, kind: str, project_path=None) -> bytes | None:
    """Art for one fighter's colour slot, preferring the open project's copy."""
    if project_path is not None:
        fighters = load_fighters(project_path)
        internal_id = find_by_name(fighters, name)
        if internal_id is not None:
            fighter = fighters[internal_id]
            if kind == "icon":
                art = _asset_png(project_path, (fighter.get("assets") or {}).get("cssIcon"))
                if art:
                    return art
            else:
                costumes = fighter.get("costumes") or []
                if costumes:
                    costume = costumes[min(color, len(costumes) - 1)]
                    art = _asset_png(project_path,
                                     costume.get("csp" if kind == "csp" else "icon"))
                    if art:
                        return art
    return roster.vanilla_art(name, color, kind)


def costume_code(filename: str) -> str:
    """The `PlXxYy` code from a costume's DAT filename.

    Melee's own data is not consistently clean: Captain Falcon's red costume is
    recorded as `PlCaRe.` -- a bare trailing dot, which `Path.stem` leaves in
    place because a trailing dot is not a suffix -- so the colour code used to
    parse as `e.` and the costume matched nothing.
    """
    stem = Path(filename or "").stem.rstrip(".")
    match = re.match(r"^(Pl[A-Za-z]{2}[A-Za-z]{2})", stem)
    return match.group(1) if match else stem


def _costume_zip_name(costume: dict) -> str:
    """Costume zips inside a fighter package are named after their DAT."""
    return costume_code((costume.get("file") or {}).get("fileName") or "") + ".zip"


def build_pair_zip(project_path, leader_zip: bytes, leader: dict, partner: dict,
                   partner_internal_id: int, name: str) -> tuple[bytes, dict]:
    """Turn an exported leader package into a pair package.

    Returns (zip bytes, info). The package keeps the leader's fighter data
    wholesale -- it *is* the leader, mechanically -- and only changes three
    things: the name, the sub-fighter fields, and the per-costume art.

    Colours: the pair keeps **every** one of the leader's costumes. The engine
    forces the partner's costume id to equal the pair's slot index and clamps it
    to 0 past the end of the partner's list, so a short partner simply repeats
    its default rather than costing the leader colours -- which is what makes a
    one-costume partner like Mr. Game & Watch usable at all.

    Because that id is forced, matching the two fighters' colours means
    reordering the *leader's* costumes, which this package owns. See
    `vault.climbers.colors`; `color_plan` decides the order.
    """
    leader_costumes = leader.get("costumes") or []
    partner_costumes = partner.get("costumes") or []
    if not leader_costumes or not partner_costumes:
        raise ValueError("both fighters need at least one costume")

    plan = color_plan(leader.get("name") or "", partner.get("name") or "",
                      project_path)
    lead_for, part_for = plan["leaderForSlot"], plan["partnerForSlot"]
    if len(lead_for) != len(leader_costumes):
        # The plan is built from the project roster by name; if that disagrees
        # with the exported package, trust the package and keep slot order.
        logger.warning("climbers: colour plan is %d slots for %d costumes, "
                       "falling back to index order",
                       len(lead_for), len(leader_costumes))
        lead_for = list(range(len(leader_costumes)))
        part_for = [color_match.partner_slot(s, len(partner_costumes))
                    for s in range(len(leader_costumes))]

    # Pair slot order, as costume-zip names. `slot_of` inverts it so a zip entry
    # can find which slot -- and so which partner costume -- it ended up at.
    ordered = [_costume_zip_name(leader_costumes[i]) for i in lead_for]
    slot_of = {zip_name: slot for slot, zip_name in enumerate(ordered)}

    src = zipfile.ZipFile(io.BytesIO(leader_zip))
    buf = io.BytesIO()
    composited = 0

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename == "fighter.json":
                data = json.loads(src.read(item.filename))
                data["name"] = name
                data["subCharacter"] = partner_internal_id
                data["subCharacterBehavior"] = 0  # SpawnSimultaneously
                costumes = data.get("costumes") or []
                if len(costumes) == len(lead_for):
                    data["costumes"] = [costumes[i] for i in lead_for]
                    # Team colours point at costume indices, which just moved.
                    where = {old: slot for slot, old in enumerate(lead_for)}
                    for field in ("redCostumeIndex", "blueCostumeIndex",
                                  "greenCostumeIndex"):
                        data[field] = where.get(data.get(field, 0), 0)
                dst.writestr(item, json.dumps(data, indent=2))
                continue

            if item.filename == "icon.png":
                partner_icon = _asset_png(
                    project_path, (partner.get("assets") or {}).get("cssIcon"))
                # The badge is drawn from the partner's stock icon when we have
                # one -- it is the asset meant to read at 20px.
                partner_stock = _asset_png(
                    project_path, (partner_costumes[part_for[0]] if part_for else {})
                    .get("icon")) if partner_costumes else None
                dst.writestr(item, composite(src.read(item.filename), partner_icon,
                                             kind="icon", partner_stock=partner_stock))
                continue

            slot = slot_of.get(item.filename)
            if slot is not None:
                dst.writestr(item, _composite_costume_zip(
                    project_path, src.read(item.filename),
                    partner_costumes[part_for[slot]]))
                composited += 1
                continue

            dst.writestr(item, src.read(item.filename))

        # The leader is a DUPLICATE fighter with a new internal kind, and
        # Melee's shared character code asks "which character am I?" by kind:
        # `ftMr_SpecialN_ItemFireSpawn` reads `fp->kind == FTKIND_MARIO` and
        # sends everyone else down Dr. Mario's branch, so a Mario pair threw a
        # Megavitamin -- and HUNG the game outright when Dr. Mario wasn't in the
        # match to register that article ("error: item not initialized").
        #
        # That is now handled by the kind alias in the engine code (see
        # `engine_code.project_aliases`): from its first frame the leader
        # answers every such check as its donor, so its articles, effects and
        # sounds resolve exactly like the donor's. Pairs used to ALSO bundle
        # m-ex's `clone_engine` function patch (`patches/clone_engine.dat`) for
        # this, but that patch re-routes every fighter's effect spawns through
        # the spawning fighter's own effect bank, which breaks Kirby's copied
        # specials for the whole build (Falcon Punch drew Kirby's Final Cutter
        # slash, Warlock Punch crashed at its end). With the alias in place the
        # patch is redundant, so a pair no longer ships it and
        # `engine_code.ensure_code` strips a stale copy on export.

    return buf.getvalue(), {
        "costumes": len(ordered),
        "leaderCostumes": len(leader_costumes),
        "partnerCostumes": len(partner_costumes),
        "compositedCostumes": composited,
        "leaderForSlot": lead_for,
        "partnerForSlot": part_for,
    }


def costume_slots(name: str, project_path=None) -> list[dict]:
    """A fighter's colour slots as [{'code', 'name'}], project first."""
    if project_path is not None:
        fighters = load_fighters(project_path)
        internal_id = find_by_name(fighters, name)
        if internal_id is not None:
            out = []
            for i, costume in enumerate(fighters[internal_id].get("costumes") or []):
                filename = (costume.get("file") or {}).get("fileName") or ""
                out.append({
                    "code": costume_code(filename) or f"Color{i}",
                    "name": costume.get("name") or f"Color {i + 1}",
                })
            if out:
                return out
    codes = roster.vanilla_costume_codes(name)
    return [{"code": c, "name": roster.color_label(c, i)} for i, c in enumerate(codes)]


_PLAN_CACHE: dict[tuple, dict] = {}


def color_plan(leader: str, partner: str, project_path=None) -> dict:
    """How the pair's colour slots map onto the two fighters' costumes.

    `leaderForSlot[s]` is the leader costume shown at pair slot *s* and
    `partnerForSlot[s]` is the partner costume the engine will load there. The
    pair gets one slot per leader costume; see `vault.climbers.colors` for why only
    the leader's order is ours to choose and why the partner may be short.

    Cached because the picker asks for a preview on every swatch click and the
    plan reads every costume CSP of both fighters to compute it.
    """
    key = (leader.lower(), partner.lower(), str(project_path))
    if key in _PLAN_CACHE:
        return _PLAN_CACHE[key]

    lead_slots = costume_slots(leader, project_path)
    part_slots = costume_slots(partner, project_path)
    order = color_match.plan(
        [fighter_art(leader, i, "csp", project_path) for i in range(len(lead_slots))],
        [s["code"] for s in lead_slots],
        [fighter_art(partner, i, "csp", project_path) for i in range(len(part_slots))],
        [s["code"] for s in part_slots])

    plan = {
        "leaderForSlot": order,
        "partnerForSlot": [color_match.partner_slot(s, len(part_slots))
                           for s in range(len(order))],
        "leaderSlots": lead_slots,
        "leaderCount": len(lead_slots),
        "partnerCount": len(part_slots),
    }
    _PLAN_CACHE[key] = plan
    return plan


def write_vault_assets(char_dir, leader: str, partner: str, pair_name: str,
                       colors: int, project_path=None) -> list[dict]:
    """Write the display assets the Custom Characters vault reads.

    A pair is stored as a recipe, but the vault card and detail page still need
    real files on disk: `css_icon.png` for the card, `csp_<i>.png` /
    `stock_<i>.png` per colour, and a `fighter.json` listing the colours. Without
    these the entry renders as a broken image with no costumes. The actual
    fighter package is still built later by `materialize`.
    """
    char_dir = Path(char_dir)
    char_dir.mkdir(parents=True, exist_ok=True)

    (char_dir / "css_icon.png").write_bytes(composite(
        fighter_art(leader, 0, "icon", project_path),
        fighter_art(partner, 0, "icon", project_path), kind="icon",
        partner_stock=fighter_art(partner, 0, "stock", project_path)))

    # Follow the same colour plan the built pair will use, or the vault preview
    # would advertise pairings the game never shows.
    plan = color_plan(leader, partner, project_path)
    lead_for, part_for = plan["leaderForSlot"], plan["partnerForSlot"]
    all_slots = plan["leaderSlots"]

    slots = []
    for i in range(min(colors, len(lead_for))):
        lead_i, part_i = lead_for[i], part_for[i]
        slots.append(all_slots[lead_i])
        (char_dir / f"csp_{i}.png").write_bytes(composite(
            fighter_art(leader, lead_i, "csp", project_path),
            fighter_art(partner, part_i, "csp", project_path), kind="csp"))
        (char_dir / f"stock_{i}.png").write_bytes(composite(
            fighter_art(leader, lead_i, "stock", project_path),
            fighter_art(partner, part_i, "stock", project_path), kind="stock"))

    # Minimal fighter.json: the detail view keys costumes off this file, and
    # the real one only exists once the pair is materialized into a project.
    (char_dir / "fighter.json").write_text(json.dumps({
        "name": pair_name,
        "climbers": {"leader": leader, "partner": partner},
        "costumes": [{"name": s["name"], "file": {"fileName": f"{s['code']}.dat"}}
                     for s in slots],
    }, indent=2), encoding="utf-8")

    return slots


def materialize(entry: dict, char_dir, project_path) -> Path:
    """Build a stored pair's fighter package against the project being installed into.

    A pair vault entry is a *recipe* — two fighter names and the composited art —
    not a baked package, because creating one must not require a project open
    (the vault never does) and because the pair should be built from whatever
    the target project actually contains. This runs at install time, when a
    project necessarily exists, and writes the usual `fighter.zip` so the rest
    of the install path is unchanged.
    """
    import subprocess
    import tempfile

    from core.config import MEXCLI_PATH, PROJECT_ROOT, get_subprocess_args
    from core.state import mexcli_lock

    pair = entry.get("climbers") or {}
    leader_name = pair.get("leader")
    partner_name = pair.get("partner")
    if not leader_name or not partner_name:
        raise ValueError("pair entry is missing its leader/partner names")

    fighters = load_fighters(project_path)
    leader_id = find_by_name(fighters, leader_name)
    partner_id = find_by_name(fighters, partner_name)
    if leader_id is None:
        raise ValueError(f"this project has no fighter called {leader_name!r}")
    if partner_id is None:
        raise ValueError(f"this project has no fighter called {partner_name!r}")

    char_dir = Path(char_dir)
    tmp_dir = tempfile.mkdtemp(prefix="climbers_install_")
    try:
        leader_zip = Path(tmp_dir) / "leader.zip"
        with mexcli_lock:
            result = subprocess.run(
                [str(MEXCLI_PATH), "export-fighter", str(project_path),
                 str(leader_id), str(leader_zip)],
                capture_output=True, text=True, timeout=600,
                cwd=str(PROJECT_ROOT), **get_subprocess_args())
        if result.returncode != 0 or not leader_zip.exists():
            raise ValueError(
                f"could not export {leader_name}: {result.stderr or result.stdout}")

        data, info = build_pair_zip(
            project_path, leader_zip.read_bytes(), fighters[leader_id],
            fighters[partner_id], partner_id, entry.get("name") or leader_name)
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    dest = char_dir / "fighter.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    logger.info(f"materialized pair {leader_name}+{partner_name}: {info}")
    return dest


def _composite_costume_zip(project_path, costume_zip: bytes,
                           partner_costume: dict) -> bytes:
    """Replace one costume zip's csp/stock with leader+partner composites."""
    partner_csp = _asset_png(project_path, partner_costume.get("csp"))
    partner_stock = _asset_png(project_path, partner_costume.get("icon"))

    src = zipfile.ZipFile(io.BytesIO(costume_zip))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            base = item.filename.split("/")[-1].lower()
            if base == "csp.png":
                dst.writestr(item, composite(src.read(item.filename),
                                             partner_csp, kind="csp"))
            elif base == "stc.png":
                dst.writestr(item, composite(src.read(item.filename),
                                             partner_stock, kind="stock"))
            else:
                dst.writestr(item, src.read(item.filename))
    return buf.getvalue()
