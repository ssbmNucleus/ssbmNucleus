# L-load alternate fighters: how ACE 2.0 does it, and a Nucleus design

*Investigation write-up (2026-10-15) and the design as built the same day.
The ACE half describes ACE Build 2.0.0 as extracted on this machine and is not
maintained. The Nucleus half describes the code in `app/backend/projects/lload/`
and the CSS layout editor; keep it current.*

## Summary

- **Where ACE's L-load lives.** It is **not** in `MxPt.dat`, m-ex data or the
  DOL. It is one extra file on the disc, `AltSlippiCSS.dat` (3,794 B of
  compiled C), plus three ACE-only Gecko codes. The codes load the file when
  the character select screen (CSS) opens and run it every CSS frame.
- **What ACE does.** Once a player's coin is placed on one of six base
  fighters, a **tap** of L rewrites the selection to a hard-coded alternate.
  Match load just sees a normal pick of the alternate. In ACE 2.0 every
  alternate also has its own visible icon, so L is a shortcut there.
- **ACE's flaws, seen in game.** The coin jumps to the alternate's icon. The
  portrait does not change until you press a costume button. There is no way
  back.
- **Licence.** Nobody is credited for the code, and neither ACE nor m-ex has a
  licence. We copy nothing; our own clean-room code is 408 B.
- **Built in Nucleus**, all proven in game:
  - L **scrolls** through an ordered list per base fighter (Luigi → Luigi &
    Boo → Dr. Luigi → Daisy → Luigi).
  - The portrait switches instantly and the coin stays put.
  - The alternates need **no visible icon**: each keeps a "tucked" icon
    hidden behind its base's icon.
  - Lists are stored by fighter name, resolved at export and baked into one
    generated Gecko code.

## How ACE 2.0 does it

Source: the extracted ACE 2.0.0 project the app already holds
(`<data root>/projects/ace_2.0`, ISO patched from the
[v2.0.0 release](https://github.com/Chri222k/ACE-BUILD-PUBLIC-/releases/tag/v2.0.0)).
The release notes say "Luigi and Boo have been added as L press for luigi"
and Giga Bowser "for L press" on Bowser.

### The pieces

| Piece | Where | Role |
|---|---|---|
| `AltSlippiCSS.dat` | disc root, 3,794 B | HSD archive with two roots. `altcssFunction` is a MexTK relocatable function blob (0x7F4 B of code, 25 relocations): function 0 `AltCharSelect_Init`, function 1 `AltCharSelect_Think`. `mnFunction` is an unused earlier prototype (below). |
| `$Alt Slippi CSS Init` | C2 at `0x802669DC`, inside `mnCharSel_8026688C_OnEnter` (CSS scene enter) | If the instruction at `0x801BFA20` is no longer vanilla `lbz r3,4(r31)`, calls m-ex `MEX_LoadRelArchive` (`0x803D709C`) with `"AltSlippiCSS.dat"`, a two-word table and `"altcssFunction"`, then calls table[0] (Init). |
| `$Alt Slippi CSS Think` | C2 at `0x80263334`, inside `fn_80262F44` (a CSS GObj proc, runs every CSS frame) | Finds Init's table by decoding the branch at `0x802669DC`, calls table[1] (Think) when it is set. |
| `$TEMP \| L Press function Alt fighters` | C2 at `0x801BFA20`, inside `gm_801BF9A8` | Despite the name, this is the "boot to CSS" line of the Netplay Community Settings code (`li r3,2` = VS mode). The code's own comment says it was cut down from that code as "a temporary fix while the actual function is being made". Init uses its presence as the on-switch. |

`MxPt.dat` holds only `patch_loader`, `clone_engine` and `allstar`; `MxDt.dat`,
`mexSelectChr.dat` and `main.dol` contain nothing alt-related. The three codes
are in ACE's `codes.ini` and compiled `codes.gct` (328 B together); our pinned
`codes.gct` and `seed_codes.ini` have none of them. They are probably most of
the 448 B of "ACE-only codes" counted in `app/CLAUDE.md`; that count was not
re-checked here.

`AltCharSelect_Init` is two instructions (`li r3,2; b MEX_GetData`) and does
nothing useful. All behaviour is in `AltCharSelect_Think`.

### What one L press does

Every CSS frame, for each port `p`:

1. Read `HSD_PadCopyStatus[p].trigger` (`0x804C20BC + 0x44*p + 8`). Continue
   only if L (`0x40`) was newly pressed this frame.
2. Read the player's selected fighter, `CSSData->players[p].c_kind`
   (`*0x804D6CB0 + 0x70 + 0x24*p`, an **external** fighter id).
3. If it matches a base fighter in the switch below:
   - write the alternate's external id to `c_kind`;
   - write the alternate's icon number to
     `mnCharSel_803F0DFC.doors[p].sel_icon` (`0x803F0DFC + 0x24*p + 0xE`);
   - overwrite the port's trigger with `0x800`, a fake **Y** press meant to
     run vanilla `mnCharSel_CostumeChange` and redraw the portrait;
   - play sound `0x7C866` (510054) through `Ground_801C53EC`.

Vanilla re-derives `c_kind` from `icons[sel_icon].char_kind` when the hand
picks up or drops the coin (`mnCharSel_CursorThink` in the decomp's
`mncharsel.c`), and the portrait redraw reads the icon's fighter too. That is
why the selected icon has to move along with `c_kind`.

### The pair table (hard-coded)

| Base (external id) | Alternate (external id) | `sel_icon` written |
|---|---|---|
| Mario (0x08) | Metal Mario (0x2D) | 0x37 = icon 55 |
| Luigi (0x07) | Luigi & Boo (0x2B) | 0x35 = icon 53 |
| Bowser (0x05) | Giga Bowser, ACE's playable one (0x39) | 0x36 = icon 54 |
| Wolf (0x1A) | Wolf SSBU (0x33) | 0x34 = icon 52 |
| Sonic (0x1E) | Sonic BM (0x2A) | 0x33 = icon 51 |
| Lucas (0x1D) | Lucas TDX (0x24) | 0x32 = icon 50 |

Icons 50 to 55 (in `css.json` each icon's `fighter` is an external id) are
exactly these six alternates. They sit visibly on ACE's bottom grid row.

### What it looks like in game (2026-10-15)

From an ISO exported from a copy of the ACE project, in the harness:

- **Only after the coin is placed.** While the coin is still in the hand,
  `c_kind` is empty (66), so L does nothing.
- **Correct pick.** On a placed Mario, L sets `c_kind` 45 (Metal Mario) and
  `sel_icon` 55. START works, and the match loads fighter kind 46 (Metal
  Mario).
- **The coin jumps** to the alternate's icon on the bottom row.
- **The portrait does not change.** It still shows "Mario" until a costume
  button (X) is pressed. The fake Y only redraws when the costume number
  actually changes.
- **No way back.** An alternate's id is not a case in the switch, so a second
  L does nothing.

### Other details

- **A latent ACE bug (from the disassembly, not seen in game).** The compiled
  code has a second, unrolled path for ports 2 to 4, taken when
  `CSSData->unk_0x0` is non-zero. That path writes port 1's `sel_icon`
  (`0x803F0E0A`) instead of its own port's.
- **m-ex dependencies.** It needs m-ex's `MEX_LoadRelArchive` (`0x803D709C`)
  and calls `MEX_GetData` (`0x803D7094`) from Init. Both are m-ex standalone
  functions present in our `codes.gct` too.
- **The boot code doesn't boot to the CSS in practice.** ACE still started at
  the normal menus. It works only as the switch Init checks.
- **The unused prototype.** The `mnFunction` root is an earlier attempt: a
  minor scene (prints `CSS_load`, `hello`, `CSS_exit`) with a table
  `alt_cs_icons` of `{icon, fighter, fighter-with-L, button mask}` entries
  (Mario and Metal Mario only). Its think rewrote the icon's own fighter while
  L was **held**. Nothing loads this root.

### Provenance and licence

- The ACE repository ([Chri222k/ACE-BUILD-PUBLIC-](https://github.com/Chri222k/ACE-BUILD-PUBLIC-))
  holds 1.0.1 project data only (no 2.0 data, no source for this file) and has
  no licence file. Its credits document lists character coders (for example
  Mrmariobros222 for Metal Mario; PigsSSBM and Fennel for Luigi & Boo) but not
  the author of the L-press code. The codes in `codes.ini` carry no author tag.
- `AltSlippiCSS.dat` was built with MexTK from [akaneia/m-ex](https://github.com/akaneia/m-ex),
  which also shows no licence file.
- The cut-down boot code comes from the Netplay Community Settings code that
  Slippi distributes.
- With no licence, the default is all rights reserved. Our code is a clean
  re-implementation from the decomp's structures and copies no ACE bytes.
  Credit ACE in the changelog as the prior art for the idea.

## The Nucleus design (built)

The idea is ACE's; the implementation is ours. Store an ordered list of
alternates per base fighter by name, turn the lists into ids at export, and
generate one Gecko code from them. Nothing changes in `MxPt.dat`, the DOL or
any fighter package.

### What the player does

Place the coin on a base fighter and **tap L** to scroll through its list.
With Luigi → [Luigi & Boo, Dr. Luigi, Daisy], each L moves one step:
Luigi → Luigi & Boo → Dr. Luigi → Daisy → Luigi. With one alternate it is a
toggle. The portrait and name switch on the same frame, the coin stays on the
base's cell, and X/Y cycle the current fighter's own costumes. This was the
owner's choice in review ("just scrolling with L, like luigi has 3").

The vanilla CSS code never checks L or R. R could scroll backwards later; it
is not in v1.

### Where the alternates' icons live: tucked icons

The CSS takes the portrait and the costume count from the selected icon's
fighter, not from `c_kind`. An alternate therefore needs an icon slot, but
not a visible one. Each alternate gets a **tucked icon**:

- **Placement:** the same position and scale as its base's icon;
- **No hit box:** a collision size of 0, so the hand can never hover it;
- **Draw order:** listed **immediately before** the base's icon in the icon
  list. Later icons draw on top, so the base covers it. Depth (z) does not
  decide this; list order does.

In game, the grid shows only the base, L's portrait switch is instant, and
the coin does not move, since the tucked icon sits under the base's cell.
This needs no m-ex code change.

Rejected after testing:

- **Visible alternate icons** (ACE's layout). The coin jumps to the
  alternate's cell, and the grid spends a slot per alternate.
- **No icon at all**, with only `c_kind` changed. The match loads the
  alternate, but the CSS keeps showing the base's portrait and name, and X/Y
  cycle the base's costumes.

### Project data

`<project>/nucleus_lload.json`, written atomically like `nucleus_menus.json`:

```json
{"groups": [{"base": "Luigi", "alts": ["Luigi & Boo", "Dr. Luigi", "Daisy"]},
            {"base": "Mario", "alts": ["Metal Mario"]}]}
```

- **Fighter names, not ids.** External ids shift when a fighter is removed;
  this is the convention `vault/climbers/pairs.find_by_name` and the FSM bake
  already follow.
- **Rules:**
  - A fighter is in at most one group, either as the base or as an
    alternate, never both.
  - The base keeps a normal visible icon.
  - Popo, Nana, Sheik, the specials and the NONE placeholder cannot be
    alternates.
- **Not `subCharacter`.** That field describes how a pair spawns in a match,
  not the CSS.

### UI

- **CSS layout editor's icon list** (`CssLayoutEditor.jsx`,
  `CssLloadAlternates.jsx`): every eligible fighter's row has a **+ L**
  picker on the same row. A fighter's alternates show as indented rows under
  it (L1, L2, ... with their icon, ▲▼ to reorder, × to remove), and **+ L**
  stays on the row to add more. Each change saves at once, then the grid
  re-fits over the visible icons; a "Saving L alternates..." line shows
  meanwhile. Base icons carry a small "L" badge on the canvas and in the list,
  and the editor never draws tucked icons. `IconReorderList` gained two
  optional hooks for this (`renderRowAction`, `renderAfterRow`); the SSS
  editor does not use them.
- **Later:** a "install as L alternate of ..." choice on install.

### What install and export write

- **Editing a group:** writes `nucleus_lload.json`.
- **Export** (`projects/install/export_job.py`, right after the Any Climbers
  block): a new module shaped like `vault/climbers/engine_code.ensure_code`.
  1. Resolve names to external ids (`groups.normalize`, the one place that
     decides which groups are in effect). Drop entries whose fighters are
     gone, and groups whose base has no CSS icon. Each drop becomes a warning
     in the export result.
  2. **Tuck:** make sure each alternate has exactly one icon. That icon gets
     its base's position and scale, a zero hit box, and a place immediately
     before the base in the icon list. Write it with `set-css-layout`, and
     only when something changed.
  3. Take the final icon numbers from the tucked list itself.
  4. Build the C2 code: fixed instruction words (assembled once with
     devkitPPC and committed, like `gen_engine_code.py`) plus the group
     table. No assembler runs at export.
  5. `add-code` if missing; rewrite and `sync-codes` if stale (add-code skips
     an existing name); remove it when there are no groups, and untuck the
     former alternates. If the step fails, the export says so in its
     warnings.
- **Grid reflows, without a fork change:** MexCLI's `Template.Apply`
  (add/remove/duplicate fighter) places every icon, tucked ones included, and
  resets hit boxes. So alternates are recognised by group membership, never
  by hit box. Every `POST /menus/css/layout` re-tucks them, and the editor's
  auto-grid (`computeAutoCssLayout`) lays out only visible icons. A reflow
  therefore never leaves an alternate showing or a hole where one sat.
- **Test-in-game builds** don't run the step: they use a fresh temporary
  project with one mod, which never has groups.
- **Removing a fighter** drops it from its group (or the whole group, if it
  was the base), independently of the icon repair below.
- **Locking:** both layout writes (`POST /menus/css/layout` and
  `/menus/css/lload`) take the project's build session, so they wait for a
  running export. The L code bakes icon numbers in at export, so a layout
  change can't slip in between.

### The runtime code

One C2 at `0x80263334`, the same CSS proc hook ACE uses. Our pinned m-ex
codes don't hook that address; they hook the same proc at `0x80262FFC` and
`0x80263050`. Every CSS frame, for each open door:

1. Continue only if L was newly pressed.
2. Find the group that contains `c_kind` and take the next entry, wrapping to
   the base.
3. Write that entry's external id to `c_kind` and its icon to `sel_icon`.
4. Reset the costume to 0 and step past taken costumes with the CSS's own
   duplicate check (`0x8025DAA0`), bounded by the fighter's costume count.
5. Call the CSS's own portrait redraw (`0x8025DB34`), play
   `lbAudioAx_80024030(2)`, and clear the L bit.

Notes:

- **Why not ACE's fake Y.** m-ex hooks inside both of those CSS functions,
  so calling them directly is m-ex-aware. The fake Y redraws only when the
  costume number changes (seen in game).
- **Costume.** The match takes it from `players[p].color`, which the CSS
  copies from the door when it exits.
- **Table.** Groups are `{count, then count × {external id, icon}}`, ending
  with a count of 0.
- **Size.** The clean-room code with two groups (five entries) assembles to
  408 B.

On a project made from an existing m-ex build such as ACE, the source build's
whole `codes.gct` is adopted as the "m-ex core", and its `codes.ini` entries
are disabled for reference. ACE's L codes therefore cannot be removed through
`codes.ini`. Our code comes later in `codes.gct` at the same address, so it
replaces ACE's Think hook, and only ours runs. This was verified in game on
the ACE base.

### How it meets existing features

- **Clones.** Nothing new. The alternate loads exactly as a direct pick, and
  the item-only clone patch is per fighter. Metal Mario ran without Mario in
  the match.
- **Custom characters and ACE imports.** ACE 2.0's alternates import as
  ordinary characters. The scan cannot read pairings out of compiled code.
  Optional, later: a hand-checked table of ACE 2.0's six pairs that pre-fills
  "suggested L groups" when the scan recognises ACE 2.0.
- **Ice Climbers and Any Climbers pairs.** L changes only the CSS selection.
  The partner spawns at match load from the chosen fighter's own
  `subCharacter`, so scrolling to or from a climber pair is the same as
  picking its icon. Not yet tested in game.
- **Zelda and Sheik.** Unaffected; Sheik is chosen by holding A as the match
  starts.
- **Random select.** Not tested. If m-ex's random pick can land on a tucked
  icon, random could choose an alternate. That would be acceptable, but it
  should be checked.
- **Memory and roster size.** The CSS loads every fighter's portraits whether
  or not it has a visible icon, so an alternate costs the CSS heap and counts
  toward the Slippi roster advisory exactly as today.
- **Replays and Tracker.** The replay records the alternate's id, as for a
  direct pick.
- **Slippi online.** Not covered by v1. Both players need the same build, and
  the online CSS is untested.

### Remove-fighter icon bug: worked around in Nucleus

In the `ssbmNucleus-mex` fork, `MexProject.RemoveFighter` points the removed
fighter's icons at external id 0 (Captain Falcon). `RemoveFighterCommand` then
deletes the **last** icon whose fighter is 0. If Falcon's icon comes later in
the list, Falcon's real icon is deleted and the removed fighter's icon stays,
now showing Falcon. Removing a fighter with no icon always deletes Falcon's.

`remove-from-project` now snapshots the icons before `remove-fighter` and
restores them afterwards (`export.repair_after_remove`): the snapshot minus
the removed fighter's icons, with higher ids shifted down by m-ex's own rule.
It also drops the fighter from its L group.

Checked with a real removal on the ACE copy. Removing Daisy, a tucked
alternate, made MexCLI delete Falcon's icon (index 39) and leave Daisy's slot
pointing at Falcon. The repair put Falcon's icon back in place. The fork
itself is unchanged.

## In-game results (2026-10-15)

All runs were port 1 only, with no CPU. They used the CSS cursor path, the
documented exception for CSS UI tests, then pressed START and picked FD with
`force_select`. Scratch builds and run outputs are in
`randall-runs/lload-2026-10-15/`. The probe scripts are scratch and are not
kept in the repo.

| Build | What was pressed | RAM | Screen | Match |
|---|---|---|---|---|
| ACE 2.0 as shipped | hover Mario, L | `c_kind` stays empty (66) | nothing | – |
| ACE 2.0 as shipped | lock Mario, L, X, L | 8 → 45, `sel_icon` 2 → 55; second L no change | coin jumps to M.MARIO; portrait stays Mario until X | Metal Mario (kind 46) |
| Vanilla + our code, Mario→Luigi on Luigi's visible icon | lock Mario, L, L | 8 → 7 → 8 | portrait switches instantly; coin moves to Luigi's cell | – |
| Vanilla + our code, Bowser→Peach with no Peach icon used | lock Bowser, L, X, B, re-lock, L | 5 → 12; picking up the coin keeps 12; re-lock gives 5 | portrait stays Bowser; X cycles Bowser's colours | Peach (kind 9) |
| ACE copy, Metal Mario icon deleted, our code | lock Mario, L (and a run with X, X) | 8 → 45, `sel_icon` stays 2 | portrait stays Mario | Metal Mario |
| ACE copy, Metal Mario icon tucked under Mario, our code | lock Mario, L, L, L, X | 8 → 45 → 8 → 45, colour 1 | no visible Metal Mario icon; portrait switches instantly both ways; X gives red Metal Mario | red Metal Mario |
| ACE copy, scroll groups, all alternates tucked | lock Luigi, L ×6 | 7 → 43 → 46 → 35 → 7 → 43 → 46 | Luigi → Luigi & Boo → Dr. Luigi → Daisy → Luigi, instantly; grid shows only Mario and Luigi | Dr. Luigi (kind 47) |
| ACE copy, groups saved and exported by the app's own `projects/lload` code | lock Luigi, L ×6 | same as above | same as above | Dr. Luigi (kind 47) |

Practical notes:

- **Use an ISO.** The Slippi Dolphin build exits at once when asked to boot an
  extracted folder (`sys/main.dol`), so every run used an exported ISO.
- **No other Dolphin.** On Windows the harness waits while any other Dolphin
  is open, including the owner's own Slippi.

Not yet covered: ports 2 to 4, teams mode, an Ice Climbers group, random
select, and a grid reflow after tucking.

## Decisions

Settled:

- L scrolls a list per base fighter.
- Alternates need no visible icon (tucked icons).
- Reflows need no fork change.

Still open:

- Should scanning ACE 2.0 suggest its six pairs as L groups?
- Should R scroll backwards?
