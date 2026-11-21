# Sound Mods

Nucleus handles two kinds of audio modding: **character sound packs** (voice/effect banks) and **music playlists** (stage and menu music).

Character sound packs follow the vault-vs-project pattern: packs live in the vault, and installing writes into the open project. Music playlists are edited directly in the open project.

## Character Sound Packs

Every character has a sound bank (their voice lines and sound effects). Nucleus lets you keep multiple packs per character and swap them.

From a character's sound-bank browser you can:

- create a new pack (it starts as a copy of the vanilla bank)
- browse every sound in the bank and **preview** it
- **replace** any individual sound with an audio file — normal formats are converted automatically
- **revert** one sound, or all of them, back to the pristine originals
- rename and delete packs
- **install** a pack into the open project, or **uninstall** back to the character's original sounds

A pack stays lossless where you have not touched it: unreplaced sounds keep their original game audio untouched.

### Notes

- Zelda and Sheik share one sound bank — a pack for one is a pack for both.
- Custom characters have sound banks too, browsable from their detail view.

## Stage Music

Each of the six tournament stages (Battlefield, Final Destination, Yoshi's Story, Dream Land, Pokémon Stadium, Fountain of Dreams) has its own music playlist in the open project. On the Install page's stage view, the music note button on the stage's panel opens its editor:

- the list always shows what the stage currently plays — on an untouched stage that's its vanilla music (for example Battlefield's theme with its rare Multi-Man Melee alternate at 12%)
- add songs in normal audio formats — they are converted to the game's HPS format automatically (stereo preserved); the vanilla songs stay in the rotation until you remove them
- **Add Songs** takes as many files as you want at once — select any number of them in the picker and Nucleus works through them in order, adding each to the list as it finishes
- drag each song's slider to set how often it plays — shares always total 100%, so raising one song lowers the others proportionally
- preview and remove songs
- **Restore Vanilla Music** puts the stage back to exactly its default soundtrack

The playlist plays across the stage's variants; it is independent of which stage skin is loaded.

## Menu Music

Melee plays one shared playlist on every menu (vanilla is two songs at 75% / 25%). On the Install page, the music note button next to the Fighters / Stages / Menus tabs opens the Menu Music editor — it works exactly like a stage playlist, with one difference: the playlist always keeps at least one song, because there is no vanilla fallback for menus.

Both editors apply directly to the open project; there are no vault packs for music.

### Choosing where a song loops

Click **Edit loop** beside a song in Stage Music or Menu Music. The **Listen**
controls let you play/pause, restart, seek using the waveform or playback
slider, and adjust volume. Seeking changes only where you listen.

Previews refresh when the song changes. If audio preparation fails, the player
shows an error; reopen the editor to retry.

Under **Adjust loop**, drag the loop-start slider, enter a time in seconds, or
click **Use playhead** to use the current listening position. Adjustments keep
playback running. The intro plays once; the song then repeats from that point.
**Preview repeat** starts near the end so you can hear the transition immediately.
Use **Songs** to return to the playlist. Click **Save loop** to
apply it. The saved time can move slightly to the nearest supported audio
boundary; the editor shows the actual saved time.

Loop changes apply everywhere that song is used in the current project,
including other stage and menu playlists. Saving enables looping and preserves
the full song. Your original imported file is unchanged. Replacing a playlist
or restoring its vanilla selection does not undo edits to a song's loop.

### Adding several songs at once

Adding a batch is one selection, not one click per file. A song that can't be converted — a corrupt file, or a format the game can't use — doesn't stop the batch: the rest are still added, and the editor tells you afterwards how many landed and which files were skipped, with the reason for each. Bigger batches take proportionally longer, since each song is converted and saved into the project in turn.

## What Ships In A Build

Installed sound packs and music playlists are part of the project, so they ride along in ISO exports, patches, and bundles like any other installed mod.

## Related Pages

- [Custom Characters](Custom-Characters.md)
- [Stage Mod Workflow](Stage-Mod-Workflow.md)
- [Vault Vs Project](Vault-Vs-Project.md)
