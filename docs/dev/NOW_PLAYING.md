# Now Playing: the song name at match start

*Written 2026-10-19, restyled 2026-11-20 (then moved clear of the match clock
and hidden while paused, the same day). The ACE half describes ACE Build
1.0.1 as extracted on this machine and is not maintained. The Nucleus half
describes `app/backend/projects/nowplaying/`; keep it current.*

## Summary

- **What it does.** When a match starts, a banner slides in at the top left:
  the song's name in white on a dark translucent bar, sized to the name, with a
  thin gold rule under it. It holds for four seconds and slides back out. There
  is no "Now Playing" label (owner, 2026-11-20). It sits above a timed match's
  clock with a gap, and it is hidden while the game is paused. The first
  version (2026-10-19) was the bare name with a drop shadow for five seconds;
  the owner found it much plainer than ACE's banner.
- **Where the idea comes from.** The ACE Build shows the song in a small animated
  banner. That is an m-ex *plugin*, `plugins/bgm_display.dat`, not a Gecko code
  and not part of `codes.ini`.
- **Why Nucleus does not ship ACE's file.** The plugin only runs under ACE's own
  plugin loader, and neither ACE nor m-ex has a licence. Nucleus has its own
  clean-room code instead, like L-load (`L_LOAD.md`). It copies no ACE bytes.
- **Who gets it.** Projects created from the Projects page or by Randall start
  with it enabled. An existing project that still has an earlier version of the
  code, exactly as shipped, is moved to the current one when it is exported
  (`upgrade.py`, under "Existing projects" below); nothing else in it changes,
  and a project without the code never gets it. It is an ordinary code that
  users can untick or remove.

## How ACE 1.0.1 does it

| Piece | Role |
|---|---|
| `plugins/bgm_display.dat` (4,289 B) | HSD archive with two roots. `function` is a MexTK function blob (0x78C B of code, one hook: `CreateHUD_b802f3a60`). `bgm` is a joint and animation for the banner. |
| `MxPt.dat` root `patch_loader` | ACE's loader. At boot it loads each `plugins/*.dat` it has enabled in ACE's own save data (`aksave`) and stores the archive pointer in the plugin's `plugin` struct. |

At `0x802F3A60` (the final `blr` of `ifAll_802F390C`, the in-match HUD setup)
the hook creates a GObj with the `bgm` banner model. The GObj's proc waits
until `Ground_801C5A94()` (`stage_info.x98`, the current BGM id) is not -1. It
then reads `MEX_GetData(MXDT_MEXDATA)->music->labels[id]`, draws the label with
the SIS text library, and makes the text follow one of the banner's joints. When
the banner animation ends, the text and GObj are destroyed. It also moves the
banner left when a widescreen code has patched `0x8036A4A8`.

Without `patch_loader` the archive pointer is never set, so the file does not
work on a vanilla-based Nucleus build. Porting the loader would also bring in
ACE's save data, its music override and its results-screen patch.

## The Nucleus code

One Gecko C2 at the same hook, `0x802F3A60`. Source:
`app/backend/projects/nowplaying/now_playing.s`. The words are assembled once
with devkitPPC into `code_words.py` (`python -m projects.nowplaying.gen_code`
from `app/backend`). No assembler runs at create or export.

- **Hook.** Creates a UI GObj (`GObj_Create(14, 16, 0)`), allocates a
  0x60-byte state block (`HSD_MemAlloc`, freed with the GObj through
  `GObj_InitUserData(..., HSD_Free, ...)`) and attaches the proc. The
  replaced `blr` is the code's own last instruction. p_link 16 is the one the
  game's own match clock and pause-camera UI use; unlike 15, the HUD's, its
  procs keep running while a match is paused (see "Pause" below).
- **Proc, waiting.** Polls `Ground_801C5A94()`. It gives up after 600 frames,
  or when the id is out of range (`metadata->bgm_count`), or there is no label.
  It then copies the label (see "The name" below).
- **Drawing.** It creates its own canvas, `HSD_SisLib_803A611C(4, NULL, 9, 13,
  0, 14, 0, 11)`: a 640x480 ortho camera drawn after the HUD, with the
  parameters the game uses for its in-match camera-mode text (`gmcamera.c`).
  SIS slot 4 is one the game never loads, so no game code can clear the canvas,
  and its glyphs come from the built-in font. Slot 2 (HUD/nametags/prizes) is
  cleared by `ifprize`, and `ifprize` assumes it owns canvas 0. On it go two
  texts, both pure SIS, no model:
  - **The bar** is the name text itself. A SIS text draws a quad from `pos` to
    `pos + box_size * font_size` in `bg_color` before its glyphs when the
    colour's alpha is not 0 (`HSD_SisLib_803A84BC`; read in its disassembly,
    the decomp of that function is non-matching). The bar is RGBA
    `0C0E18C8`, 28 px tall from y 18, flush with the screen's left edge. The
    name is one subtext at (18, -10) from the bar's top, scale 0.56 x 0.54,
    white, kerning on. Subtext y is the top of a 32-unit line with the glyph
    at its bottom, so the glyphs land at y 22.7 to 40.
  - **The rule** is a second text with no glyphs and a gold (`FFC83C`) 2 px
    background box under the bar, y 46 to 48.
  - **The clock.** A timed match's clock has its digits from y 55 (640x480),
    starting about x 245, so a name over about 19 glyphs runs over it
    horizontally. The first restyle had the bar at y 24 and the rule ending
    at 54, touching the digits; the banner now ends 7 px above them for any
    name. Its top, y 18, stays below the overscan line (about y 14).
  - **Width.** The renderer leaves the end of the last line it drew in
    `HSD_Text.current_width`. The texts are made off-screen, drawn once, and
    from the next frame on both boxes are that width (at least 64) plus 16.
  - The label is passed as a `%s` argument, so a `%` is never a format.
- **Animation.** Frame `s` counts from the frame the banner is made. Both
  texts' `pos_x` is `-width * ease[i]`, where `ease` is a 14-entry table of
  `(1 - i/13)^3`: `i = s - 1` for `s` 1..14 (slide in, ease-out), the last
  entry (0, fully in) for `s` 15..254 (four seconds), and `268 - s` for `s`
  255..268 (the same curve backwards, so it accelerates out to the left).
- **Pause.** A player's pause (`fn_8016CA68`, decomp `gm/gm_16AE.c`) hides the
  HUD (`ifAll_802F3394`) and sets a bit in the scene's pause bits,
  `gm_80479D58.unk_10.x0` at `0x80479D68` (the byte `gm_801A45E8(bit)`
  tests): bit 1 in a match, bit 2 in Training. The free camera (`gmcamera.c`)
  sets bit 3 and hides the HUD too; bit 0 is the debug freeze the harness's
  frame stepping uses. While bit 1 is set the scene loop stops every proc on
  the p_links in `gm_803DA888[1]` (`0x82FFFA`), 15 among them, which is why the
  first restyle sat frozen on screen over the pause view's corner bracket. The
  proc, on p_link 16, runs on: while any of bits 1 to 3 is set it moves both
  texts to x -1000, where they wait to be measured, and does not count the
  frame (in the waiting phase it only skips the count). On unpause the slide
  picks up at the same `s`, and the next frame puts both texts back. Parking
  the texts off-screen, rather than setting `hidden`, keeps them drawn, so
  `current_width` stays measured, and leaves `hidden` meaning "done".
- **Done.** At `s` 269 it sets both texts' `hidden` flag and frees the GObj.
  It does not call `Text_Destroy`. The SIS heap is reset with the scene, which
  frees the texts and canvas, and this avoids a double free if anything ever
  clears slot 4 first. The same path hides whatever was made when the second
  text cannot be created.

**The name.** The game's ASCII-to-SIS encoder (`HSD_SisLib_803A67EC`, read in
its disassembly) handles letters, digits, space and `" ' , - . :` itself. Any
other byte is taken as the first half of a Shift-JIS pair with the byte after
it, which swallows that byte, or the terminator, after which it reads stack
garbage. Its output goes to a 128-byte stack buffer in `Text_AddSubtext` with
no bounds check: 3 bytes a letter, and 7 for a space or digit after a letter.
The first version copied printable ASCII up to 63 characters and turned other
bytes into `?`, so a long label overran that buffer (212 bytes for the long
test label below) and `(`, `!`, `?` and the like each ate the next letter.
m-ex makes this worse: it stores labels in Shift-JIS, with ASCII punctuation as
full-width pairs (`100%` is `100` `81 93`; accents dropped, emoji as `??`).
The copy now writes the label in a form where every glyph is 3 encoded bytes:

- letters as they are;
- digits as their `82 4F`..`82 58` pair;
- space and every other printable ASCII symbol as its full-width `81xx` pair
  (table `d_pairs`; `\` shows as `/` and `` ` `` as `’`, which the font has);
- a Shift-JIS lead byte with a valid second byte (what m-ex writes) as is, so
  full-width punctuation and kana show;
- anything else (a control character, a stray high byte) as a full-width `?`.

With kerning on, the renderer ignores the spacing opcodes the encoder adds for
spaces and digits, so a pair looks the same as the plain character. A pair the
font has no glyph for (m-ex's `〈` `〉` for `<` `>`, `＼`) encodes to one byte
and draws nothing. Every glyph the font maps is in the built-in set (codes
`0x2000`..`0x211E`). Over 32 glyphs the name is cut to 29, a trailing space is
dropped, and `...` is added: at most 96 encoded bytes, 64 input bytes, and
about 370 px of bar.

Song names come from the build's music list (`data/music.json` names, which
m-ex exports as the `MxDt` music labels), so custom songs show the names users
gave them.

## How projects get it

- `projects/install/required_codes.py`: `new_project_gecko_codes()` and
  `add_new_project_gecko_codes(project_file, source_iso)`. The second runs
  `mexcli add-code` for each code. The code lands enabled (`$!`) in
  `files/codes.ini`, like any other code.
- **Callers.** `POST /api/mex/project/create` when the body has
  `starterCodes: true`; the Projects page sends it. Randall's `apply_create`
  always calls it. The throwaway projects created by replay playback, combo
  videos, the e2e/test-build harnesses and first-run extraction don't send the
  flag, so their output has no overlay.
- **ACE packs.** A project created from a pack that has
  `plugins/bgm_display.dat` (the ACE Build, whose engine is adopted) is
  skipped, so the name is not drawn twice.
- **Not `REQUIRED_GECKO_CODES`.** That list is re-added on every export when
  missing, so it would reach every existing project. Using it for Now Playing
  would be a separate decision.

**Existing projects.** A project keeps the hex it was created with, so
`projects/nowplaying/upgrade.py` moves it to the current code. Every ISO export
and `save` runs through `mexcli.project.MexManager`, which calls
`upgrade_project` just before MexCLI compiles `files/codes.ini` into
`codes.gct`. An entry whose hex lines are exactly an earlier version
(`previous_versions.py`; case, spacing and `#` comments aside) gets the current
hex. Its header, so its name and enabled state, its description, its place in
the file and every other byte of `codes.ini`, line endings included, stay as
they were. A log line names the file. An edited entry, a project without the
code and a build with `bgm_display.dat` are left alone; nothing is ever added.
When `code_words.py` changes, add the outgoing `source()` to
`previous_versions.py`. It holds `V1_2026_10_19` (the drop-shadow name, commit
`3d7697196`) and `V2_2026_11_20` (the first restyle, main at `9493e4af5`, made
from `git show 9493e4af5:` copies of `code_words.py` and `code.py`), oldest
first. Tests: `tests/backend/test_now_playing_upgrade.py`.

## Verification

- `tests/backend/test_now_playing_code.py`: the committed words match the
  assembly source; the C2 is valid; the name budget fits the encoder's
  128-byte buffer and the state block; the bar and rule end at least 5 px
  above the clock's digits and below the overscan line, with the glyphs inside
  the bar at the approved size; the GObj's p_link is not one a match pause
  stops, and the proc reads the pause bits (1 and 2, not the debug freeze);
  `d_pairs` covers every printable ASCII symbol once; the helper runs
  `add-code`, and skips ACE packs.
- `tests/backend/test_now_playing_upgrade.py`: V1 and V2 entries both move to
  the current code, edited ones of either are left alone.
- 2026-10-19: a project created with `mexcli create`, given the code by
  `add_new_project_gecko_codes`, and exported has the C2 in its `codes.gct`.
  The ACE 1.0.1 ISO is detected and skipped.
- In game: see the status line at the end of this section.

**In-game status, clock and pause (2026-11-20, current code):** checked on an
ISO exported the app's way (`app/scratch/nowplaying-timer-fix/build.py`:
`mexcli create` from the vanilla ISO, the code added as the V2 hex, Final
Destination's songs labelled with a long name and Battlefield's with
`Battlefield`, then `MexManager.export_iso`). The export upgraded the V2 entry
and `codes.gct` holds the new C2, not V2. The drivers (`ingame.py`,
`ingame2.py`, the harness pieces `Session.start` uses) set Stock, 4 stocks,
8:00, with Fox and a DK bag (two human ports, no CPU).
- **Clock.** In the hold, with the clock counting, the rule runs y 46 to 48 and
  the clock's digit ink starts at y 55, a 7 px gap for the cut long name
  (`Final Destination Theme (Exte...`, 362 px of bar, across the clock) and
  for the short one. Before, it was 1 px (`gap.json`).
- **Pause.** Paused during the hold, both texts sit at x -1000 and `s` stays
  put: through frozen steps, through 4 s of the game's own pause, and through
  2 s of a pause and unpause pressed in real time. On unpause the bar is back
  at x 0 at once, `s` carries on from where it stopped, and the slide out and
  the hide at `s` 269 follow as before. The pause view's corner bracket is
  clear.
- **Second match.** After L+R+A+START back to the CSS, Battlefield shows the
  banner again; it slides in, holds, slides out in real time and is hidden.
  The game kept running (health checks) and the Dolphin log has no assert.
- **Evidence.** `app/scratch/nowplaying-timer-fix/sheet.png` (frames, zooms of
  the gap and of the paused corner next to the same crops from before),
  `frames/`, `ingame-result.json`, `ingame2-result.json`.
- **Not checked.** Training mode's pause (bit 2) and the free camera (bit 3)
  in game, a CRT, widescreen codes, kana labels.

**In-game status, first restyle:** the banner was verified 2026-11-20 with the harness
(`boot_match`, Fox solo, no CPU). The test ISO,
`app/scratch/nowplaying-restyle/nowplaying-restyle-test.iso`, was built with
`mexcli` from the vanilla ISO and given custom music labels: a 95-character
name, `Déjà Vu 🎵 100% Rock & Roll! (Live) #1?`, and a name made of every
awkward ASCII symbol.
- **Stages.** It ran on Battlefield, Dream Land, Final Destination, Pokémon
  Stadium and Yoshi's Story (whose label is vanilla). On each, the banner
  starts at in-game frame 1, and the name in RAM matches a Python model of the
  copy.
- **Slide.** The harness freezes 200 frames into the match, so the slide-in was
  replayed by setting the frame counter back to 0, then stepping.
- **Frames and sheet.** The frames are in `app/scratch/nowplaying-restyle/frames/`
  and the sheet is `contact-sheet.png`. They show the slide in (frames 1-14),
  the hold, the slide out (frames 255-268) and the banner gone (frame 269),
  plus the cut long name, the m-ex-mangled name and the symbol name.
- **Not checked then** (the clock, the pause and an app-exported ISO are
  covered above): widescreen codes, kana labels.
