# Test In Game

**Test in Game** opens your mod in an offline match so you can run around and try it yourself.

Nucleus builds a temporary ISO containing the selected mod and opens it in Slippi Dolphin.
Character and costume tests load the selected fighter on **Battlefield**.
Stage tests load **Mario** on the selected stage or stage skin.
Use the controller configured for **port 1** in Slippi.

## Where It Appears

The button shows up on things that can be match-tested:

- a costume's edit modal (vanilla-character skins)
- custom characters and their individual skins
- custom stages
- DAS stage variants
- pause-screen mods (as a live capture preview)

There is also a whole-build test after export, which exercises several mod types in as few matches as possible.

In builds with Randall enabled, you can also ask in chat: **“Let me play this
costume”** or **“Test this imported model in game.”** Randall opens a live game
card with build progress and Stop. An exported model costume can be tested before
saving it to your vault. Custom characters, their costume slots, custom stages
and saved tournament-stage variants are supported too.

Use your port 1 controller to play. Reopening the conversation reconnects to the
same test; it does not launch another copy. Closing the chat leaves the game
running, and you can return to its card to stop it. Stop in the chat composer
stops Randall's reply; Stop on the game card ends the game. Randall cannot watch
the live video or judge the result for you.

## What Actually Happens

1. Nucleus checks that another test or Dolphin emulator is not already running
2. it builds a small test ISO: vanilla plus just this mod (a whole-build test uses your exported ISO).
   The first test after you set your Melee ISO first prepares a clean test base from it,
   which can take about 3 minutes and shows **Preparing the test base from your Melee ISO**
   with a running timer. Later tests reuse that base and start with copying it, so the
   build takes well under a minute. Each test still gets its own fresh copy
3. it launches an **isolated** copy of your Slippi Dolphin — a temporary config folder, so your real netplay setup is never touched
4. it navigates to the offline VS character select screen by reading the game's state, not by blind timing
5. it selects the modded character/costume/stage and starts a solo match
6. it leaves the match open for you to play, with no opponent and no time limit

Click **Stop** when you are finished, or close the Dolphin window. You can pause
or stand still without a test timer ending the session. Stopping during an ISO
build skips launching Dolphin. Preparing the test base, copying it and exporting
the ISO stop right away; installing the mod into the copy finishes that step
first. A test base that was still being prepared is discarded, and the next test
prepares it again. The temporary test files are cleaned up after the session ends.

Your port-1 controller mapping is kept from Slippi; Nucleus does not auto-detect
or switch controller ports. If controls are not configured, set up port 1 in
Slippi first. Other controller ports do not control the test fighter.

On Windows, a live video preview appears inside the app while the test runs.
Use **Open Dolphin window** to watch in a separate window. If the live preview
cannot start or loses its connection, the test can continue in Dolphin's window.
Dolphin still runs separately behind Nucleus; very small app windows may leave
part of it visible.

## If Dolphin Is Already Open

Close the Dolphin emulator window, then start the test again. Nucleus checks
before building the test ISO and explains the conflict immediately. You can
leave the Slippi Launcher open; it is the emulator window that matters.
Nucleus does not close your running game for you.

If you open Dolphin after the test begins building, the test can still pause
at **Waiting for Dolphin**. Close that other emulator window to let the test
continue. While waiting, the panel shows the explanation instead of a percentage
or an empty game preview. A wait can time out if the other window stays open.

## Automated Checks And Errors

Manual previews show **Session ended** when you stop or close them; this is not
an automatic verdict on the mod. Whole-build checks and screenshot captures
remain automated. Whole-build checks can report:

- **PASS** — the match loaded and ran healthy, with screenshots as proof
- **CRASH** — the game died (with a screenshot of where)
- **HUNG** — the game froze
- **ERROR** — setup or menu navigation failed, so the requested checks could not run

If Dolphin cannot initialize its graphics renderer, Nucleus reports that failure
instead of continuing to wait for the menus. Check the video backend in Slippi's
graphics settings and retry. A Direct3D error mentioning graphics-card support
does not by itself mean your card is unsupported. A game that never reaches the
offline character-select screen cannot receive PASS from advancing frames alone.

Character select must finish loading before the preview selects your fighter.
If that loading step or the move to stage select fails, Nucleus reports which
step stopped. Retry the preview; if it repeats, use **Open Dolphin window** to
check where the game is waiting.

## Stage Screenshot Capture

Stage variants have a related flow: **Capture Screenshot** boots the stage alone with a free camera and grabs a clean whole-stage preview image for the vault.

For many variants at once, use **Bulk Render Screenshots** on the vault's Stages tab instead. It draws each stage offline — no test build, no Dolphin, and no vanilla ISO or Slippi path needed — in about a second per variant. See [Stage Mod Workflow](Stage-Mod-Workflow.md).

## Ground Rules

- **Windows only** (it drives the Dolphin window directly)
- **one test at a time**, and Nucleus asks you to close any running Dolphin first — two emulators would fight over the controller pipe
- it **never goes online**: the harness only proceeds on the offline character select and backs out if it ever sees the online menus

## Related Pages

- [Custom Characters](Custom-Characters.md)
- [Custom Stages](Custom-Stages.md)
- [Stage Mod Workflow](Stage-Mod-Workflow.md)
