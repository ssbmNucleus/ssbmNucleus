# Vault Backup And Restore

Vault backup and restore is the library-level preservation workflow.

## Vault Organization

The vault is not just a dump folder. It is a managed library.

Current storage-side workflows include:

- renaming items
- reordering items
- moving skins to top or bottom
- organizing costumes into folders
- deleting items from storage

Those actions are about the library itself, not the active project build.

Click a costume or stage-variant card to open its editor. You can also focus
the card and press Enter or Space. Dragging a card still reorders it when
custom sorting is selected, without opening the editor when you drop it.

Deleting a costume closes its editor and preview. If you open another costume
while deletion finishes, that newer selection stays open. Concurrent imports
of the same costume keep separate library entries and files.

## Vault Backup And Restore

Nucleus can back up the Vault's storage directory as one ZIP.

**Export Vault** first asks where to save the backup, suggesting
`SSBM-Nucleus-Vault-<date>.zip`. If you cancel, no backup is made. Temporary
mod-export ZIPs are cleaned up when downloads finish or are cancelled; if you
cancel one, export again to retry.

That backup includes its files and current catalog, including effects, menu mods,
and codes. It leaves out the Tracker's replay-viewer animations (about 90 MB):
Nucleus downloads them again whenever they are missing. Saved portrait poses currently live outside this directory and are
not included. If Nucleus detects changes during a backup, finish active edits
and retry the backup. Randall's chat history and task records are saved as a
consistent copy taken while the app runs, so using Randall during a backup does
not spoil it. Older backups that hold them as raw files still restore.

A backup leaves out your sign-in, this computer's AI-client settings and its
folders, and keeps everything else. Its copy of the Tracker data (`nucleome.db`:
your replay index, combos, stats and Tracker settings) has the sign-ins taken out
(your Patreon link for cloud sync and your Discord sign-in), and so are the replay
and recording folders. The AI connection settings (`assistant/mcp.json`), My game
(`assistant/settings.json`: your project, game copies and Slippi Launcher or Dolphin),
the records of what Randall delivered to your game (`assistant/deliveries/`, which
"undo" uses to put your game back) and where your clean ISO is (`vanilla_iso.json`)
stay out, so sharing a backup does not share your account or point another PC at
your folders.
A restore never takes any of these from a backup; you keep your own, and on a new PC
you choose them again. Nor does a restore take a network path (`\\server\share`)
from a backup: games, replay records and Tracker settings that name one are left out.
Replace brings back the backup's Tracker data; merge adds the games and settings
you don't have yet and keeps yours. After a replace, the next cloud sync checks
again which replays your cloud library already has.
A backup whose catalog names a file outside the Vault is refused before anything changes.

Restore supports two basic mindsets:

- **replace**, where the backup is validated before becoming your active Vault
- **merge**, which adds missing items and keeps your existing versions, including
  their files, effects, menu mods, and codes

The restore dialog opens on **Replace All** with no file chosen every time, so
pick **Merge** again for each restore that should merge.

After a replacement, Nucleus shows where it retained your previous Vault for
recovery. That copy continues to use disk space. Keep it until you have checked
the restored library, then choose **Open Restored Vault** to refresh the app.
If validation fails, your current Vault stays in place. If switching libraries
fails, Nucleus attempts to put the previous Vault back and reports its location
if it cannot.

Once the app accepts an upload, reopening Settings or reconnecting recovers
the restore's progress and result. Uploads still in transit cannot resume after
a reload. If the backend stops mid-restore, inspect the Vault and retained
previous directory before retrying. A merge publishes several files and catalogs;
an interrupted merge can leave some additions completed.

This is about preserving your library state, not exporting an ISO or rebuilding a patch.

## Separate Workflows

These are separate workflows:

- normal ISO export settings
- CSP compression
- patches
- texture-pack mode

Those are separate workflows now.

## Summary

The vault is your long-term library.

Vault backup and restore is the workflow for saving or recovering that library as a whole.
