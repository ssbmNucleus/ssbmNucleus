# Tier 2 - compiled move logic for cloned fighters (PROVEN in-game 2026-09-03)

A cloned fighter whose specials, per-frame behaviour, damage dealt, damage
taken and on-screen indicator are written in C, compiled with MexTK, shipped
inside the fighter package's `Pl*.dat`, and built/booted through the ordinary
Echo path (`echo.json` through `package.materialize`, or `python -m vault.echo.tier2`). Every claim below
was measured with the harness on the "Shulk Probe" character (Marth clone).

## The workflow an agent runs

```
python -m vault.echo.tier2 info                                   # MexTK / devkitPPC / DOL / symbols present?
python -m vault.echo.tier2 scaffold --donor Marth --out work/     # fighter.h fighter.c moves.c (+ hud.c ftwrap.c)
# edit moves.c (hooks + state callbacks); point move_logic[] entries at them in fighter.c
python -m vault.echo.tier2 compile work/                          # compiler errors -> exit 1 + message
python -m vault.echo.tier2 build PlMs.dat work/ PlMs.out.dat      # Pl + appended ftFunction root
```

or hand the same sources to the package: `echo.json` with `"code": {"entry":
"fighter.c", "files": {"fighter.c": "...", "fighter.h": "...", "moves.c": "..."}}`
-- `materialize()` compiles and splices after value, script and animation ops
(`build.check_files` compile-checks them alone). The character then installs
and exports like any custom character.

What the scaffold gives you (`codegen.py`):

* `fighter.c` -- the donor's special-state table `move_logic[]` read from the
  DOL (`ftData_CharacterStateTables` -> `moveLogicPointer`, counts from
  mexLib's `SourceGenerator`), every callback annotated with its decomp symbol
  (`ftMs_SpecialNStart_Anim`...), plus boilerplate that chains the donor's
  OnLoad / OnDeath / attribute / eye-texture slots, installs the common-state
  wrapper and forwards to the hooks. Replace a callback with your function to
  own a state; leave the rest as the donor's.
* `moves.c` -- the hooks: `Moves_OnLoad`, `Moves_OnRespawn`,
  `Moves_ResetAttributes`, `Moves_OnFrame`, `Moves_PostPhysics`,
  `Moves_DamageTakenMult`, with a cheat sheet and worked examples.
* `fighter.h` -- `ACTION_*` / `STATE_*` enums for the donor's specials (named
  from the Pl action table), donor addresses, `VAR_A/B/C` fighter_var slots.
* `hud.c`, `ftwrap.c` -- helpers, copied beside the sources.

The `probe/` proof character on this scaffold (sources plus an authored-script op) was archived on 2026-10-02 to `ssbmNucleus-archive\echo-tier2-probe.zip`; the write-up is in `ssbmNucleus-archive/echo-fixedpack.zip`.

## Proof runs (harness `boot_match` + `do_move` + RAM reads)

| what | measured |
|---|---|
| stance toggle (compiled special, state 341 -> Wait at frame 12) | flag at `ft+0x22F8` flips; HUD "STANCE ON  x2" |
| damage dealt x2 (`Moves_PostPhysics` hitbox scale) | Marth ftilt 9.0% -> **18.0%** |
| authored script (`set_script`: 25-dmg hitbox at frame 3) | bag DamageFlyN on move frame 4; **50.0%** on / **22.75%** off |
| damage taken x0.5 (`Moves_DamageTakenMult`) | DK ftilt 10 -> **5.0%** on / **9.1%** off (probe as the bag) |
| HUD text from fighter code | `probe5-hud-*.png`, `probe7-hud-clean.png` |

Screenshots: `tests/artifacts/mcp/20260903-165953/`.

## Engine facts that decided the design (all verified live)

* **`OnFrame` (slot 23) runs inside the fighter think proc BEFORE the
  animation step that executes subaction commands** (`Fighter_8006A360`,
  hook @ `0x8006AA28`, replacing `ftData_UnkMotionStates3[kind]`). A hitbox
  created this frame is not visible to it until next frame, and hit
  detection has already used the base damage.
* **The per-state physics callback runs after that step and before hit
  detection** (`Fighter_procUpdate` -> `fp->phys_cb`). Common states live in
  the shared `ftData_MotionStateList` (`0x803C2800`, 341 x 0x20).
  `Fighter_Init` sets `fd->ftstates_common` (+0x1C) and `common_state_num`
  (+0x18) BEFORE the character's OnLoad (fighter.c:734 vs :883), so
  `ftwrap.c` copies the table into the DAT, routes every `physics_callback`
  through a wrapper and points +0x1C at the copy. Callbacks are cached per
  state at `ActionStateChange`; install at load, never later.
* **Damage taken:** slot 21 (`eyetexturedamaged` in `ftFunction.txt`) is the
  core's `onKnockbackEnter` (`Header.s` +0x54, hook @ `0x8007F830` inside
  `ftCommon_8007F824`), called from the damage state's enter, AFTER
  `Fighter_UnkTakeDamage` added `fd->dmg.percent_temp` (0x1838) to the
  percent and BEFORE `Fighter_ProcessHit` zeroes it. The boilerplate refunds
  `percent_temp * (1 - mult)` through `Fighter_TakeDamage_8006CC7C`
  (0x8006CC7C, accepts negatives, syncs the HUD). Knockback was computed from
  the full amount; scale `dmg.kb_mag` there if the design needs it.
* **DOL / MEM1 pointers are negative as signed 32-bit ints.** `(int)ptr > 1`
  never fires; the wrapper skipped every original physics and the fighter
  hung on the spawn platform. Compare unsigned (`ftwrap.c` does).
* Marth's SpecialN start animation callback hands off to the swing when the
  clip ends, before a frame-12 IASA check fires. Own the animation callback
  too (a no-op holds the last frame) when a state should outlive the donor
  clip.
* Statics: `__attribute__((section(".data")))` on zero-initialised arrays and
  small pointers; gcc would put them in `.bss`/`.sdata`, which MexTK does not
  carry. Statics are shared by every instance of the fighter -- per-instance
  state goes in `fighter_var` (`ft+0x222C..0x22F8`, persists across frames
  and state changes; the donor uses the low slots).
* `memcpy` (`0x800031F4`), `Fighter_EnterWait`, `ActionStateChange`,
  `Fighter_UpdateCameraBox`, `HSD_MemAlloc`, `DevelopText_*` are in
  `melee.link`; `DevText_HideCursor` (0x80302AB0) and `Fighter_TakeDamage`
  (0x8006CC7C) are called by address.
* **Never MexTK `-dat` / HSDRaw-Save a Pl file.** Compile standalone and
  append the root with `vault/echo/datroot.py` (target bytes asserted verbatim).
* Harness: `do_move` re-parks the bag and RESETS its percent, so every hit
  reads from 0 while the stale-move queue still counts uses (x0.91 on the
  second use). `boot_match char=dk bag=0x1A` puts the clone on the receiving
  end; its fighter_var slots can be poked directly (`bag_ft + 0x22F8`).

## Subaction script authoring (`set_script` / `insert_command` / `delete_command`)

`FighterDat.encode_script` is the exact inverse of the walker (all 27 vanilla
Pl DATs re-encode byte-for-byte, incl. NULL `go_to` words), and
`FighterDat.replace_script` appends the authored stream as a new struct
(`Dat.append_struct`) and repoints the action-table slot. Ops in
`vault/echo/ops.py`, same plan/preview/create path. Not in v1: pointer commands
that target the authored script itself (use `set_loop` / `execute_loop` or
point at an existing struct); `diff()` still refuses files whose script layout
changed -- recover ops from `echo.json`.

## Toolchain

MexTK release + `akaneia/m-ex/MexTK/` headers in a local `MexTK` folder
(`MEXTK_DIR`; `build.find_mextk()` also looks in `app/utility/MexTK`),
devkitPPC 16.1.0 at `C:\devkitPro\devkitPPC` (hard-coded path in MexTK).
Decomp symbols for the table annotations: `~/projects/melee/config/GALE01/symbols.txt`.
The DOL for scaffolding comes from `--dol`, any `projects/*/sys/main.dol`, or
the recorded vanilla ISO. A compile takes about a second; a full rebuild +
ISO export about two minutes.
