# Replays

Open **Replays** in Tracker to browse every game Nucleus has indexed from your
Slippi replay folder. Games are grouped by month, newest first. Use the
character, opponent, stage, result, and singles/doubles filters to narrow the
list. When an online replay's metadata has no names, Tracker reads player names and
connect codes from the start of the game.

Each row has:

- **Lite**: an instant in-app preview, with no Dolphin needed (1v1 games only).
- **▶ Watch**: plays the game in Slippi's playback Dolphin, embedded in the
  app. You can dress the players and stage with skins from your vault, record
  the game to a video, switch to widescreen, hide the player names, or turn
  off the music.

**No music** mutes the stage and menu music and keeps everything else: sound
effects, character voices, and the announcer. Like **Widescreen (16:9)**, it
applies whether you only watch or also record, and it changes nothing about
how the game plays back. Both options are in the single-game Watch popup and
in the playlist popup (Replays and Combos tabs).

## Watching or recording several games at once

The controls are at the top right of the filters, like the Combos tab's
playlist.

- **Latest games:** set the number next to **▶ Play** (25 by default) and
  click it. This queues your most recent games that match the current filters.
- **Pick exact games:** tick the checkbox at the left of each game you want.
  Your selection stays when you change pages, open other months, or change
  filters. The button becomes **▶ Play N selected**. Shift-click a checkbox to
  tick (or untick) every game between it and the last one you clicked.
  **Select shown** adds every game on the open pages, and **Clear** empties the
  selection.

The games play back to back, **start to finish**: ticked games in the order
you ticked them, the latest-games button oldest first. As with a
combo playlist, you can pick one skin per character and one variant per stage.
Nucleus builds a single ISO that dresses every game in the queue.

Tick **Record to video** to save **each game as its own video file**. The
popup shows the folder the videos go to; click **Change…** before you start
to pick another one. Files are named `playlist_<date-time>_<number>_<replay
name>.mp4`, so they sort in the order they played. The recording takes as long
as the games themselves. The progress line shows which game is recording
("Recording game 3 of 12"), and **Stop recording** ends the batch after saving
the game in progress. Every game already saved is kept. **Compress for
Discord** compresses each game's video separately, so each one fits under
Discord's 10 MB limit. Long games are saved at a lower resolution to fit. If
every selected game is a 1v1, **Watch Lite** steps through them in the app
instead.

A combo playlist (from the Combos tab) still records as one video.

If Dolphin produces no audio or video encoding fails, recording reports an
error. It does not save a silent fallback video. Videos already completed in a
playlist remain available.

A single playlist holds up to 2,000 games. If you select more, only the first
2,000 are played.

## Related Pages

- [Combos](Combos.md)
- [Stats And Tournaments](Stats-And-Tournaments.md)
- [First-Run Setup](First-Run-Setup.md)
