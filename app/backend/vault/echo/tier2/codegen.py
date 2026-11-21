"""Scaffold a donor-specific MexTK C project.

    files = scaffold(fighter_json, dol_bytes, pl_bytes=None, symbols=None)
    -> {"fighter.h": ..., "fighter.c": ..., "moves.c": ...}

What the agent gets:
* `fighter.c`  -- the donor's special-state table (`move_logic[]`, read from
  the DOL, each callback annotated with its decomp symbol) and the boilerplate
  that chains the donor's own OnLoad / OnDeath / attributes / eye-texture
  slots, installs the common-state wrapper and the HUD line, and forwards to
  the hooks in moves.c. Edit table entries to point states at your callbacks.
* `moves.c`    -- the hooks (`Moves_OnLoad`, `Moves_PostPhysics`,
  `Moves_DamageTakenMult`, ...) with worked examples, all no-ops by default.
* `fighter.h`  -- state / action enums for the donor's specials, fighter_var
  slot macros, hook prototypes.

Engine facts behind every line are in tier2/README.md.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

# vanilla move-logic table sizes by DOL address (mexLib SourceGenerator.cs)
MOVE_LOGIC_COUNT = {
    0x803C7120: 12, 0x803C7788: 35, 0x803C72B8: 23, 0x803CB838: 46, 0x803C8368: 203,
    0x803CEDC0: 23, 0x803C7E18: 21, 0x803CC060: 24, 0x803CC650: 36, 0x803CCCB8: 30,
    0x803CD2D0: 26, 0x803CD838: 26, 0x803CDD78: 26, 0x803CE2D0: 18, 0x803CE6D0: 28,
    0x803CFEF0: 32, 0x803D0B00: 20, 0x803D0628: 20, 0x803CF420: 32, 0x803CFA58: 18,
    0x803D0FA0: 21, 0x803D1498: 10, 0x803D1848: 35, 0x803D1EA8: 26, 0x803D23E8: 40,
    0x803D29F8: 23, 0x803D2E80: 32, 0x803D3A30: 50, 0x803D41F8: 49, 0x803D35E8: 24,
    0x803D3998: 1, 0x803C7260: 2, 0x803CA04C: 4, 0x803D0868: 2, 0x803D38C8: 1,
}
FIRST_SPECIAL_STATE = 341
CAMERA_BOX = 0x800761C8   # Fighter_UpdateCameraBox

# Pl prefix -> MexTK FTKIND_* (include/fighter.h enum) for MexCPU_InitSpoofData
FTKIND = {
    "Mr": "FTKIND_MARIO", "Fx": "FTKIND_FOX", "Ca": "FTKIND_FALCON", "Dk": "FTKIND_DK",
    "Kb": "FTKIND_KIRBY", "Kp": "FTKIND_BOWSER", "Lk": "FTKIND_LINK", "Sk": "FTKIND_SHEIK",
    "Ns": "FTKIND_NESS", "Pe": "FTKIND_PEACH", "Pp": "FTKIND_POPO", "Nn": "FTKIND_NANA",
    "Pk": "FTKIND_PIKACHU", "Ss": "FTKIND_SAMUS", "Ys": "FTKIND_YOSHI", "Pr": "FTKIND_JIGGLYPUFF",
    "Mt": "FTKIND_MEWTWO", "Lg": "FTKIND_LUIGI", "Ms": "FTKIND_MARTH", "Zd": "FTKIND_ZELDA",
    "Cl": "FTKIND_YOUNGLINK", "Dr": "FTKIND_DRMARIO", "Fc": "FTKIND_FALCO", "Pc": "FTKIND_PICHU",
    "Gw": "FTKIND_GAW", "Gn": "FTKIND_GANONDORF", "Fe": "FTKIND_ROY",
}

ATKKIND = {18: "ATKKIND_SPECIALN", 19: "ATKKIND_SPECIALS", 20: "ATKKIND_SPECIALHI",
           21: "ATKKIND_SPECIALLW"}


# ---------------------------------------------------------------------------
# DOL + symbols
# ---------------------------------------------------------------------------
class Dol:
    def __init__(self, data: bytes):
        self.data = data
        offs = struct.unpack(">18I", data[0:0x48])
        addrs = struct.unpack(">18I", data[0x48:0x90])
        sizes = struct.unpack(">18I", data[0x90:0xD8])
        self.sections = [(o, a, s) for o, a, s in zip(offs, addrs, sizes) if s]

    def read(self, addr: int, n: int) -> bytes:
        for o, a, s in self.sections:
            if a <= addr < a + s:
                return self.data[o + addr - a:o + addr - a + n]
        raise KeyError(f"address 0x{addr:08X} not in the DOL")


def read_dol_from_iso(iso_path) -> bytes:
    """main.dol straight out of a GC disc (header word 0x420 = DOL offset)."""
    with open(iso_path, "rb") as f:
        f.seek(0x420)
        dol_off = struct.unpack(">I", f.read(4))[0]
        f.seek(dol_off)
        hdr = f.read(0xD8)
        offs = struct.unpack(">18I", hdr[0:0x48])
        sizes = struct.unpack(">18I", hdr[0x90:0xD8])
        end = max((o + s for o, s in zip(offs, sizes) if s), default=0)
        f.seek(dol_off)
        return f.read(end)


def load_symbols(path) -> dict[int, str]:
    """decomp config/GALE01/symbols.txt -> {addr: name} (functions only)."""
    out = {}
    rx = re.compile(r"^(\S+)\s*=\s*\.\w+:0x([0-9A-Fa-f]{8});.*type:function")
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = rx.match(line)
        if m:
            out[int(m.group(2), 16)] = m.group(1)
    return out


def find_symbols_file() -> Path | None:
    for c in (Path.home() / "projects" / "melee" / "config" / "GALE01" / "symbols.txt",):
        if c.is_file():
            return c
    return None


# ---------------------------------------------------------------------------
# move-logic table
# ---------------------------------------------------------------------------
def read_move_logic(dol: Dol, table_addr: int) -> list[dict]:
    count = MOVE_LOGIC_COUNT.get(table_addr)
    if count is None:
        raise KeyError(f"move-logic table 0x{table_addr:08X} is not a known vanilla table")
    out = []
    for i in range(count):
        e = dol.read(table_addr + i * 0x20, 0x20)
        action_id, flags = struct.unpack(">iI", e[:8])
        cbs = struct.unpack(">5I", e[12:32])
        out.append({"state": FIRST_SPECIAL_STATE + i, "action_id": action_id, "flags": flags,
                    "move_id": e[8], "bitflags1": e[9], "animation_callback": cbs[0],
                    "iasa_callback": cbs[1], "physics_callback": cbs[2],
                    "collision_callback": cbs[3], "camera_callback": cbs[4]})
    return out


def _c_ident(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", s).upper()


def _cb(addr: int, symbols: dict[int, str] | None) -> str:
    if addr == CAMERA_BOX:
        return "Fighter_UpdateCameraBox"
    if addr == 0:
        return "0"
    name = symbols.get(addr) if symbols else None
    return f"0x{addr:08X}" + (f" /* {name} */" if name else "")


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------
def scaffold(fighter_json: dict, dol_bytes: bytes, pl_bytes: bytes | None = None,
             symbols: dict[int, str] | None = None, name: str | None = None) -> dict[str, str]:
    fn = fighter_json.get("functions") or {}
    files = fighter_json.get("files") or {}
    pl_name = files.get("fighterDataPath") or files.get("FighterDataPath") or "Pl??.dat"
    prefix = pl_name[2:4] if pl_name.startswith("Pl") else "??"
    ftkind = FTKIND.get(prefix, "FTKIND_MARIO")
    donor = fighter_json.get("name") or fighter_json.get("Name") or prefix
    char = name or f"{donor} Clone"
    dol = Dol(dol_bytes)
    table_addr = int(fn.get("moveLogicPointer") or 0)
    entries = read_move_logic(dol, table_addr)

    motions = {}
    if pl_bytes:
        from ..subactions import FighterDat
        fd = FighterDat(pl_bytes)
        motions = {a.index: (a.motion or f"action{a.index}") for a in fd.actions}

    def addr(key):
        v = int(fn.get(key) or 0)
        return f"0x{v:08X}" if v else "0"

    # -- fighter.h ----------------------------------------------------------
    enum_actions, enum_states, seen = [], [], set()
    for e in entries:
        mname = motions.get(e["action_id"], f"ACTION{e['action_id']}")
        ident = _c_ident(mname)
        if ident in seen:
            ident = f"{ident}_{e['state']}"
        seen.add(ident)
        enum_actions.append(f"    ACTION_{ident} = {e['action_id']},")
        enum_states.append(f"    STATE_{ident} = {e['state']},")
    h = f"""#ifndef FIGHTER_HEADER_FILE_
#define FIGHTER_HEADER_FILE_
// {char} -- scaffolded from {donor} ({pl_name}) by echo.tier2.codegen
#include "../mex.h"

// The donor's own callbacks (DOL addresses; chained by the boilerplate).
#define DONOR_ONLOAD            {addr('onLoad')}
#define DONOR_ONDEATH           {addr('onRespawn')}
#define DONOR_RESET_ATTRIBUTES  {addr('resetAttribute')}
#define DONOR_EYE_DAMAGED       {addr('eyeTextureDamaged')}
#define DONOR_EYE_NORMAL        {addr('eyeTextureNormal')}
#define DONOR_FTKIND            {ftkind}

// Special action states: action ids index the Pl action table (animations
// + subaction scripts), state ids are what fd->state_id reports in-game.
enum FIGHTER_ACTIONS
{{
{chr(10).join(enum_actions)}
}};

enum FIGHTER_STATES
{{
{chr(10).join(enum_states)}
}};

// fighter_var slots (ft + 0x222C .. 0x22F8) persist across frames and state
// changes. The donor uses the low ones for its own specials; hud.c uses
// ft_var49. Put character state here, never in C statics (statics are shared
// by every instance of the fighter in the match).
#define VAR_A  fighter_var.ft_var52   // 0x22F8
#define VAR_B  fighter_var.ft_var51   // 0x22F4
#define VAR_C  fighter_var.ft_var50   // 0x22F0

// Hooks implemented in moves.c
void  Moves_OnLoad(GOBJ *gobj, FighterData *fd);      // after the donor's OnLoad, once per fighter
void  Moves_OnRespawn(GOBJ *gobj, FighterData *fd);   // every death/respawn
void  Moves_ResetAttributes(GOBJ *gobj, FighterData *fd);
void  Moves_OnFrame(GOBJ *gobj, FighterData *fd);     // top of the think proc (BEFORE subactions run)
void  Moves_PostPhysics(GOBJ *gobj, FighterData *fd); // after the state's physics, BEFORE hit detection
float Moves_DamageTakenMult(GOBJ *gobj, FighterData *fd); // 1.0 = unchanged; applied on every hit taken

#endif
"""

    # -- fighter.c ----------------------------------------------------------
    rows = []
    for e in entries:
        mname = motions.get(e["action_id"], "")
        rows.append(
            f"    {{ /* state {e['state']}{' ' + mname if mname else ''} */\n"
            f"        /*.action_id          =*/ {e['action_id']},\n"
            f"        /*.flags              =*/ 0x{e['flags']:08X},\n"
            f"        /*.move_id            =*/ {ATKKIND.get(e['move_id'], str(e['move_id']))},\n"
            f"        /*.bitflags1          =*/ {e['bitflags1']},\n"
            f"        /*.animation_callback =*/ {_cb(e['animation_callback'], symbols)},\n"
            f"        /*.iasa_callback      =*/ {_cb(e['iasa_callback'], symbols)},\n"
            f"        /*.physics_callback   =*/ {_cb(e['physics_callback'], symbols)},\n"
            f"        /*.collision_callback =*/ {_cb(e['collision_callback'], symbols)},\n"
            f"        /*.camera_callback    =*/ {_cb(e['camera_callback'], symbols)},\n"
            f"    }},")
    c = f"""// {char} -- fighter.c (scaffolded from {donor}; edit the table + moves.c)
#include "fighter.h"
#include "cpu.c"      // MexCPU spoof -- without it CPU-controlled copies crash
#include "hud.c"      // HUD_Create / HUD_Printf
#include "ftwrap.c"   // FtWrap_Install: per-frame hook after physics, before hit detection
#include "moves.c"    // your hooks + state callbacks

// ---- special-state table (from the DOL: 0x{table_addr:08X}, {len(entries)} states) ----
// Replace a callback with your own function to take a state over. A no-op
// animation callback holds the clip's last frame (the donor's usually hands
// off to the next state when the clip ends). Keep the rest as the donor's.
__attribute__((used)) static struct FtState move_logic[] = {{
{chr(10).join(rows)}
}};

// ---- boilerplate: chains the donor, installs the hooks --------------------
void ResetAttributes(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (DONOR_RESET_ATTRIBUTES)
        ((void (*)(GOBJ *))DONOR_RESET_ATTRIBUTES)(gobj);
    Moves_ResetAttributes(gobj, fd);
}}

void OnRespawn(GOBJ *gobj)   // m-ex slot 1 (onDeath in the core's naming)
{{
    if (DONOR_ONDEATH)
        ((void (*)(GOBJ *))DONOR_ONDEATH)(gobj);
    Moves_OnRespawn(gobj, gobj->userdata);
}}

void OnFrame(GOBJ *gobj)     // top of the think proc: BEFORE this frame's subaction commands
{{
    Moves_OnFrame(gobj, gobj->userdata);
}}

static void PostPhysics(GOBJ *gobj)
{{
    Moves_PostPhysics(gobj, gobj->userdata);
}}

// m-ex slot 21 ("eyetexturedamaged") = the core's onKnockbackEnter: called on
// every hit taken, from the damage state's enter, AFTER the percent was added
// and while fd->dmg.percent_temp still holds this hit's amount. Knockback was
// computed from the full amount; the refund below adjusts percent only.
void EyeTextureDamaged(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (DONOR_EYE_DAMAGED)
        ((void (*)(GOBJ *))DONOR_EYE_DAMAGED)(gobj);
    float mult = Moves_DamageTakenMult(gobj, fd);
    if (mult != 1.0f && fd->dmg.percent_temp > 0.0f)
    {{
        float refund = fd->dmg.percent_temp * (1.0f - mult);
        ((void (*)(FighterData *, float))0x8006CC7C)(fd, -refund);   // Fighter_TakeDamage: adds + syncs the HUD
    }}
}}

void OnLoad(GOBJ *gobj)
{{
    FighterData *fd = gobj->userdata;
    if (DONOR_ONLOAD)
        ((void (*)(GOBJ *))DONOR_ONLOAD)(gobj);
    ResetAttributes(gobj);
    fd->ftstates_special = move_logic;
    FtWrap_Install(fd, PostPhysics);
    MexCPU_InitSpoofData(gobj, DONOR_FTKIND);
    Moves_OnLoad(gobj, fd);
}}
"""

    # -- moves.c ------------------------------------------------------------
    m = f"""// {char} -- moves.c: your hooks and state callbacks. Everything here is
// optional; the defaults leave the donor untouched.
//
// Cheat sheet (all proven in-game, see tier2/README.md):
//   fd->state.frame                       current frame of the state's clip
//   fd->input.held / fd->input.down       HSD_BUTTON_A/B/X/Y/Z/L/R, HSD_BUTTON_DPAD_*
//   fd->input.lstick.X / .Y               -1..1
//   fd->phys.self_vel.X = 2.0f * fd->facing_direction;
//   ActionStateChange(startFrame, animSpeed, blend, gobj, STATE_..., 0, 0);
//   Fighter_EnterWait(gobj); Fighter_EnterFall(gobj); Fighter_EnterSpecialFall(gobj, landing_lag)
//   fd->hitbox[i].active / .dmg / .dmg_f   live hitboxes (scale in Moves_PostPhysics)
//   fd->attr.*                             this instance's attributes (walk/run/jump/gravity...)
//   HUD_Create(fd, x, y, w, h); HUD_Printf(fd, "fmt %d", a, b);

void Moves_OnLoad(GOBJ *gobj, FighterData *fd)
{{
    // HUD_Create(fd, 40, 60 + 24 * fd->ply, 20, 1);
    // HUD_Printf(fd, "{_c_ident(char)[:12]}", 0, 0);
}}

void Moves_OnRespawn(GOBJ *gobj, FighterData *fd)
{{
}}

void Moves_ResetAttributes(GOBJ *gobj, FighterData *fd)
{{
    fd->VAR_A = 0;
    fd->VAR_B = 0;
}}

void Moves_OnFrame(GOBJ *gobj, FighterData *fd)
{{
}}

void Moves_PostPhysics(GOBJ *gobj, FighterData *fd)
{{
    // Example: scale every freshly created hitbox while VAR_A is set.
    // int seen = fd->VAR_B;
    // for (int i = 0; i < 4; i++) {{
    //     ftHit *hb = &fd->hitbox[i]; int bit = 1 << i;
    //     if (hb->active != 0) {{
    //         if (!(seen & bit)) {{ seen |= bit; if (fd->VAR_A) {{ hb->dmg *= 2; hb->dmg_f = (float)hb->dmg; }} }}
    //     }} else seen &= ~bit;
    // }}
    // fd->VAR_B = seen;
}}

float Moves_DamageTakenMult(GOBJ *gobj, FighterData *fd)
{{
    return 1.0f;   // e.g. return fd->VAR_A ? 0.5f : 1.0f;
}}

// Example state callback (point a move_logic entry's iasa_callback at it):
// void MySpecial_IASACB(GOBJ *gobj)
// {{
//     FighterData *fd = gobj->userdata;
//     if (fd->state.frame >= 12.0f) Fighter_EnterWait(gobj);
// }}
"""
    return {"fighter.h": h, "fighter.c": c, "moves.c": m}
