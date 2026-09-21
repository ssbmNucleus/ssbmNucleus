# Changelog

All notable changes to SSBM Nucleus are documented here.

## 0.8.9 — 2026-09-21

### Fixes

- **Export buttons download again.** Exporting a skin or stage from the Edit
  window, exporting a custom character or custom stage, downloading a vault
  bundle, and every Export button on the Menus page silently did nothing. The
  download link was missing the app's local access token.
- **The CSS layout editor shows character icons again** instead of plain white
  boxes (same cause). The Game & Watch colour creator's preview is fixed too.
- **Icon packs keep custom characters' icons.** A pack of `=name.png` icons
  dropped every non-vanilla character's icon, and a `mexSelectChr.dat` without
  its `MxDt.dat` imported nothing. Unnamed icons are kept as "Extra Icon N" so
  you can rename them.
- **Giga Bowser can be set up again after you delete him.** Building him threw
  away the files needed to rebuild him, so after a delete he could not be
  rebuilt and Giga Bowser skins were refused. If this already happened to you,
  re-run first-time setup from Settings once.
- **Jigglypuff's hats stay on her head** in the skin editor and the animation
  viewer.
- **A failed replay recording no longer leaves replay playback stuck at 4:3.**

### ACE build characters

Re-scan your ACE ISO once after updating so characters you already imported
pick up these fixes.

- **ACE characters work on projects that were not made from the ACE patch.**
  Metal Mario's side-B cape, and other clones whose specials use a vanilla
  character's items, froze the game; the item part of m-ex's clone patch now
  travels inside those characters' files. Raichu and Skull Kid froze while the
  match loaded because files their code loads were never packed; they are now
  included. Meta Knight froze on every project because our build tool dropped
  two bones from his skeleton; that is fixed.
- **ACE's playable Giga Bowser imports** as "Giga Bowser (ACE Build)" instead of
  being skipped.
- **Custom characters say the right name.** Every imported ACE character was
  announced as one other character (usually Lucas TDX), because the install
  reused the source build's sound number, which means something else in your
  project. Announcer lines are now matched by the audio itself: a character
  that uses a vanilla name points at it, its own custom line is added once
  and shared, and a character with no line of its own says "Bonus Character"
  (made from your own ISO's narrator clips).

### Replays

- **Widescreen.** Watch with mods and playlists have a "Widescreen (16:9)"
  option that shows more of the stage instead of stretching the picture;
  recordings are saved as 16:9 video.
- **Playlists of whole games.** On the Replays tab, "▶ Play [N] games" queues
  your latest games, or tick games to pick exactly which (shift-click ticks a
  range). Ticked games play in the order you ticked them.
- **One video per game.** Recording a playlist saves each game as its own
  video in the folder shown in the popup, and "Compress for Discord" compresses
  each one to fit 10 MB. Long single recordings that used to go over 10 MB now
  fit.

### Cloud sync

- **Uploading your games is about 5x faster**, newest games first, so recent
  games show up on your phone right away. Games already uploaded are not sent
  again.

## 0.8.8 — 2026-09-15

- **Building an ISO works again.** 0.8.7 could not export at all: every build
  ended in "Export failed", including a project with nothing added. 0.8.7 added
  a final disc-padding step to the export so the game's last file read stays
  inside the image; that step reopened the finished ISO for itself while the
  export was still holding the file open, so it failed every time. The padding
  now runs after the export lets go of the file, and it still does its job.
  Nothing in your project was harmed by the failed builds -- update and rebuild.
- **Export failures now report the actual error.** The failure above filled the
  Export Failed box with internal debug text about portrait compression and
  never mentioned the cause, because the app could only read an error message
  that arrived on a single line. It now reads the whole message either way.

## 0.8.7 — 2026-09-14

### Any Climbers

- **Dying after switching characters now costs a stock and respawns the pair
  together.** Previously the newly controlled partner could die without losing
  a stock, while the other fighter lingered on the respawn platform. This also
  fixes dying again before that delayed partner returned. Rebuild your ISO to
  apply the fix to an existing project.
- **A pair's leader now plays exactly like the character it was built from.**
  The leader is a copy with its own identity, and Melee's character code asks
  "which character am I?" in about a hundred and thirty places before it lets a
  move happen. Those checks failed for every pair: Link and Young Link could
  never fire the hookshot in the air, Kirby's inhale could not copy an ability,
  Captain Falcon's and Ganondorf's dives lost their flame, and the same held for
  Fox, Falco, Marth, Roy, Pikachu, Pichu and the rest wherever the game checks.
  The build now tells the game the leader's original character from the first
  frame of the match, so all of those checks pass.
- **The swap fix from 0.8.6 now reaches projects made before it.** Each export
  only ever added the pair engine code if it was missing, so a project first
  built on 0.8.5 kept the 0.8.5 code, and swapping to a dead partner could
  still lock you out. Exports now replace an older copy of the engine code.
- **Kirby can copy a pair's leader.** Inhaling and swallowing the leader used
  to freeze the game the moment the ability was granted, because the game
  loads copy abilities at the start of a match for the characters it finds
  there, and a pair's leader was not one it knew. The build now loads the
  original character's ability for a pair, so Kirby copies it exactly as he
  would from that character.
- **Kirby's copied specials no longer draw his Final Cutter sword in a build
  that contains a pair.** Pairs used to bundle an extra m-ex function patch
  whose effect hook sent every fighter's effects through the spawning
  fighter's own effect bank, so a Kirby wearing any hat drew Kirby's effects
  (Falcon Punch showed the sword, Warlock Punch crashed at its end). The pair
  fixes above already cover what that patch did, so pairs no longer ship it
  and rebuilding your ISO removes it from an existing project.

### Elsewhere

- **Hidden the unfinished Agent tools settings in release builds.** The panel
  was visible even though its backend was disabled, so it displayed a 404 error.
- **Menu files import under any name.** A character-select, stage-select,
  pause or HUD file is now recognised by what is inside it, so a background
  downloaded as "Halo3CSS.dat" imports from the main Import button instead of
  failing with "unsupported file type". Only a file called MnSlChr was
  recognised before.
- **Giga Bowser and wireframe skins no longer create phantom characters.** A
  bulk pack containing a Giga Bowser costume used to add a nameless "G" card
  to the Characters grid, and wireframe costumes were filed under Young Link
  because the file reader had the two mixed up. Giga Bowser costumes now go
  to the built-in Giga Bowser (set him up first), wireframe costumes are
  named correctly and refused with a message until wireframe fighters are
  supported, and an existing phantom card is hidden from the grid.
- **The Menus tab remembers what is installed.** The "Currently in MEX" panel
  for backgrounds, doors, icon grids, pause screens and fonts forgot its
  contents as soon as you left the tab and showed the default again. Installs
  are now recorded with the project and shown when you come back.
- **Exported discs no longer end exactly where the last file does.** Melee
  reads files in 32-byte steps, and an image that stopped on the last byte of
  its final file could send that last read past the end of the disc. Every
  export now finishes with padding and on a sector boundary.
- **The user guide was refreshed** with current screenshots and updated
  pages for the vault, Install tab, tracker and settings.

## 0.8.6 — 2026-09-13

### Any Climbers

- **Test in game works on a pair you have not installed yet.** Pressing it
  straight after creating a pair failed with "Custom character archive not
  found". A pair is stored as a recipe rather than a built fighter, and the
  test build was the one path that never built it. It now builds the pair
  against its own throwaway project.
- **You can no longer swap to a partner who cannot act.** Swapping to a dead
  character left you unable to swap back or pause, and swapping while your
  partner was still respawning crashed the game. The D-pad press is now ignored
  unless both fighters are in a state they can be driven from.
- **Nana no longer appears in the partner picker** while a project is open.
  She was listed as a broken tile and could not be chosen anyway.

### Elsewhere

- **Reordering skins in the ISO editor no longer opens the import dialog.**
  Dragging a card also dragged its portrait as a file, and the app tried to
  import its own thumbnail. Images and links can no longer start a native drag
  anywhere in the app, and the version number in the header is no longer
  selectable text.
- **Bug reports from macOS and Linux are verified end to end.** Nothing was
  broken, but until now every report had come from Windows. The build now
  checks the report path on each platform.

## 0.8.5 — 2026-09-13

### Any Climbers

- **Build an Ice Climbers pair out of any two fighters.** A **New Climbers**
  card in Custom Characters opens a character select: pick a leader and a
  partner from their icons, and Nucleus builds the two of them into one CSS
  slot that plays the way the Climbers do — you control the leader, the partner
  follows you. Melee already treats a character as up to two fighters, which is
  how the Climbers and Zelda/Sheik work, so none of this is faked. The one
  thing the stock game will not do is hand a partner Nana's follow-the-leader
  AI, because it checks specifically for Nana; Nucleus adds the code that
  generalises it. Combinations the engine cannot manage are shown dimmed with
  the reason rather than hidden — the Ice Climbers cannot lead, and Zelda and
  Sheik cannot follow. The finished pair arrives in your vault as an ordinary
  custom character, so it installs, exports and deletes like any other.

### Skins and portraits

- **Skin Creator: layers.** A Layers tab beside the color palette stacks your
  edits the way paint.net does — add, duplicate, reorder, hide, merge down, set
  each layer's opacity and blend mode (Multiply, Screen, Overlay, Additive and
  the rest), and paint on whichever layer is selected. Erasing on an upper layer
  reveals the one below instead of punching a hole in the texture, and a PNG
  import lands on the selected layer so you can dial it back instead of
  overwriting everything. Layers last for the editing session: the game only
  ever takes a flat texture, so saving writes the flattened result.

- **Selecting an area behaves like a real editor.** The selection box can be
  moved by dragging its middle and resized by its edges and corners, Shift
  squares off a new one, and Ctrl+A / Ctrl+D select all and clear. Its outline
  is now drawn a couple of pixels thick on screen instead of being scaled up
  with the pixel grid, which made the dashes enormous when zoomed in.

- **Undo no longer misses clicks.** Finishing a stroke briefly handed the canvas
  back to the texture loader, and painting and undo are both disabled while that
  happens — so an undo click (or the start of the next stroke) in that moment
  did nothing at all.

- **Export a portrait, stock icon or stage screenshot as an image.** Hovering
  any of them in a costume's or stage's edit window now offers an Export button
  along the top, opposite the buttons that replace them.

- **Watching replays finds Slippi's playback build on Linux again.** Nucleus
  only knew the netplay AppImage's filename, so on a perfectly good install it
  reported "Slippi playback Dolphin not found" and refused to play anything.

- **You choose which kind of stock icon to generate.** The icon tile in a
  costume's edit window now offers both looks instead of picking one for you:
  recolor the vanilla pixel icon, or render this model's head in 3D. Whichever
  you press is what you get; if that look cannot be built for a skin, it says
  so and points at the other one.

- **Skin Creator: replace one color everywhere.** The new replace tool recolors
  every pixel of the color you click across the whole texture, not just the
  patch under the cursor like the bucket. A Match slider widens what counts as
  the same color for shaded and photographic textures.

- **Skin Creator: select an area to paint inside.** Drag out a selection and
  every tool — pencil, eraser, bucket, replace — stops at its edge, so a change
  cannot bleed into the part of the sheet next door.

- **Skin Creator: work from a reference picture.** A new Reference tab holds the
  image you are matching. Click it to eyedrop any color straight into your
  brush, or pull out its palette and paint from those swatches.

- **Skin Creator: see where a texture lands on the model.** Picking a texture
  now flashes it on the 3D preview, so you can tell at a glance which part of
  the character a sheet actually paints. The target button beside the texture
  name repeats the flash. It is only a flash — your pixels go back untouched,
  and it counts as neither an edit nor an undo step.

### Friends

- **A message reaches you wherever you are in the app.** Notifications used to
  fire only while the Friends tab was the tab you were looking at — so a message
  that arrived while you were browsing skins, editing a costume, or had the
  window minimised mid-game never said anything. They now come from the app
  itself: any tab, either mode, and while minimised. Nucleus mode shows how many
  people are waiting beside the wordmark, the Friends tab carries an unread
  count, an unfocused window flashes in the taskbar, and clicking a notification
  brings Nucleus up on that conversation. Still messages and friend requests
  only — nobody needs a popup because a friend came online, and a pile of
  messages waiting for you arrives as one "12 new messages" notification rather
  than twelve of them.

- **Play invites wait for a friend who is offline.** Typed messages have been
  held for up to 30 days since 0.8.3, but an invite sent to someone who was not
  online was simply dropped. It now waits with the rest and arrives the next
  time they open Nucleus.

### Tracker

- **The app stays responsive while your library updates.** Indexing replays and
  finding combos now happen in a separate background process that yields to
  whatever you are doing, instead of competing with the window for the same
  CPU. This build re-reads every game you have to pick up the new combo timing,
  so the pass is a long one — before, it made everything else crawl, and
  clicking **Watch** could leave the popup sitting on "Loading…" for a long
  time. Nothing about the passes themselves changed: they are still
  incremental, still resumable, and the Sync panel still reports them.

- **Watching a replay with a custom skin or stage works again.** Picking any
  skin failed after about a minute with "build worker never became ready",
  while an unmodded replay played fine. Nucleus builds the cosmetic ISO for
  that one replay in a second, hidden copy of itself, and since 0.8.0 it could
  no longer log in to that copy, so the build never started. Behind that sat a
  second fault: the finished ISO was looked for under the wrong name, so a
  build that worked would still have timed out after fifteen minutes. The
  progress now counts up while the ISO builds, and a build that fails says why
  instead of running to the timeout.

- **Watching a modded replay no longer discards an export you have not saved
  yet.** The hidden copy ran the startup sweep of the output folder, which is
  where a finished ISO waits for you to press Save.

## 0.8.4 — 2026-09-10

Scanning a modded ISO is the centre of this release: stage previews are
rendered without building an ISO, the results screen was redesigned, .rar
archives import, and a build's own stock icons come across. Music gains real
listening controls, and several editing screens keep up with what you just did.

### ISO scanning and importing

- Fixed ISO imports doing nothing when selected through **Import** or dragged
  into the vault. Windows builds now test both entry points before packaging.

- **.rar archives now import.** Drop one on the window or pick it with Import,
  the same as a .zip or .7z, including .rar files found inside a container
  archive. An archive that cannot be opened says so instead of reporting that
  no mods were found.

- Redesigned ISO scan results with content categories, image cards, clearer
  skin selection, and separate counts for added items and skins ready to import.
  Partial failures retain successful additions. Removed the large summary header
  and vanilla-file counts; already-imported content shows its saved vault images.
  Flat rectangular category tabs replace the summary cards, with simpler image captions
  and no repeated section titles.
  Portraits and icons use uniform sizes and preserve the full artwork.
  Result images and names share a bordered card, without repeated “Added” badges.
  Categories use Character skins, Stage variants, Custom characters and Custom
  stages throughout the menu, in that order. Result columns expand to fill the window.

- Simplified ISO import completion: **Import & finish** saves selected character
  skins, plays the success sound and returns to the vault. Closing no longer waits
  for temporary-file cleanup or silently discards a selection on an outside click.
  Partial failures keep their cards and errors visible; refresh failures can be
  retried without importing twice. **Done** confirms already-saved content.

- **ISO scanning now keeps a build’s real stock icons.** Modded discs store
  their icons in the m-ex table, which the scanner skipped outright — so every
  skin imported from one arrived with a stand-in icon. Added costumes beyond
  the vanilla slots are included.

- Reduced ISO preview preparation time: rendering starts as workers become ready,
  reuses warm workers and launches fewer renderers by default.

- ISO scanning no longer requires Wiimms tools when the built-in reader is
  available. Missed progress events and temporary connection failures recover
  automatically; unreadable ISOs produce an error or a partial-results warning.

- Fixed empty ISO scans waiting for unused thumbnail workers. Scanning now uses
  a compact square panel with the shine animation, less text and working cancellation.

- The scan card no longer looks like it crashed during the custom-content
  step. That step runs quietly for minutes at a time, so instead of counting
  how long nothing has happened it now says it is still working. Dropped the
  "ISO SCAN" label above the disc name.

- Redrew the import questions — the Slippi safety warning, the duplicate prompt
  and "What is this?" — so they match the rest of the app instead of using their
  own grey panels. Cancel now reads as the quiet option rather than looking like
  a third choice, Escape closes them, and the Slippi warning counts correctly
  when more than one costume in an archive is unsafe.

### Stages

- ISO stage variants now get rendered previews without building an ISO or
  launching Dolphin. Rescanning fills in missing previews for older imports.
  Fixed Pokémon Stadium's missing floor and platforms in the stage renderer.
  Fixed ISO extraction skipping variants with ordinary names inside stage folders.

- **Bulk stage screenshots are now rendered, not played.** The vault's stage
  screenshot button draws every selected variant with the same renderer, about
  a second each, so it no longer builds test ISOs, boots Dolphin, or needs a
  vanilla ISO and Slippi path at all. Shots appear as they finish, you can stop
  part-way and keep what is done, and each variant that cannot be drawn says
  why. Stages outside the six competitive ones have no camera yet and are shown
  as such.

### Costumes and portraits

- Retaking a costume’s portrait now keeps the new render on screen once you
  accept it, instead of showing the previous portrait again until the costume
  was reopened. Removed the caption above **Use it** / **Discard**.

- Fixed **"The selected costume does not match ..."** when replacing a
  vanilla slot with a mod whose colour that fighter never shipped — Bowser
  has only Normal, Red, Blue and Black, so `PlKpWh` and `PlKpYe` costumes
  were refused. Costume files are also matched regardless of their casing.

### Music

- Separated music listening controls from loop adjustments. Added pause/resume,
  seeking, volume and **Use playhead**; adjusting a loop no longer stops playback.

- Simplified Stage Music, Menu Music and loop-editor text.
- Development launches now update MexCLI automatically. Release packaging tests
  music import, preview and loop saving against the bundled helper before proceeding.

### Elsewhere

- Patreon status now just says **Not linked**. Replay-sharing prompts explain
  that you need to follow or join SSBM Nucleus on Patreon for free and link your account.

- Startup failures now save copyable error details with the app version and
  system information. Windows packaging checks the bundled native runtime
  without development tools on its search path.

- Removed the separate logs ZIP button. The yellow **Report a Bug** button
  opens the report form, which attaches logs automatically.

- Foreign SMD imports preserve small weighted body parts; Melee's hidden and
  parked mesh filter now requires an explicitly identified Melee source.
  DAE conversion verification excludes Blender's generated bone-display mesh.
- Artist revisions also preserve native mesh slot order and single-material
  grouping. Reordered or missing groups are rejected before they can shift
  costume visibility indices in-game.

- Model fitting returns drafts for per-model artist assessment. New artist
  revisions preserve authored mesh/weight changes, retain per-asset recipes and
  regenerate animation previews without automatic refitting. Every revision
  requires fresh independent visual review.

- Model fitting now supports optional DAE conversion, more source bone naming
  conventions, automatic orientation from named anatomy, and SMD texture
  companions. Multi-material SMDs retain separate export groups.
- Faster sampled animation checks preserve separate vertex weights and resolve
  numbered/shared fighter animation names. A repeatable model corpus benchmark
  reports latency and incomplete pose coverage separately from visual quality.

- Development preview: bounded multi-character model fitting accepts models or
  ZIPs, preserves named anatomy and material colors, compares cached poses
  against vanilla, and exports the chosen fit without rerigging. New diagnostics
  flag weight, head, torso and ground-reach issues; visual acceptance remains separate.
- Model exports preserve material-animation layout and restore required neutral
  blink tracks. Unsupported material-walk layouts report a repair requirement.

- Development preview: model matching ranks vanilla characters using shape,
  proportions and named source bones, and can propose a separate reposed working
  mesh. Pose adjustment and rigging remain experimental and require independent
  visual review across animation before native acceptance.
- Model import preserves scene instances/transforms and source bone weights
  through simplification. Corrected Zelda's vanilla model prefix.
- Development preview: external agents can use Randall MCP for model rigging,
  character and stage imports/installation, project builds, live editors,
  website downloads, menu/sound/extra management and Dolphin testing. Added
  isolated two-client netplay tests and paired replay reports. Native acceptance
  and a compatible public installer are still pending.
- Queued ISO exports retain the project selected when export was requested.

## 0.8.3 — 2026-09-09

A cleaner editing workflow throughout Nucleus, with Stage Creator,
non-tournament vanilla stage support, extras improvements, and Friends text
and global chat.

### Stage and skin editing

- **Stage Creator:** create reskins from vanilla stages or edit an existing
  stage skin with a live 3D preview, texture painting, recoloring, and animation
  playback. Save the result as a new vault mod with its own preview.
- Skin Creator and Stage Creator have a more compact workspace, resizable
  panels, a searchable texture browser, and improved texture zoom and panning.
- Edit material colors, opacity, shininess, and texture-blending colors.
  Palette adjustments can affect textures, materials, or both, with controls
  to reset your changes.
- **More Stages:** import and install skins for all 23 non-tournament vanilla
  stages. Replace the original stage skin, restore vanilla, or add the skin as
  a separate stage-select entry. The six tournament stages retain their
  alternate-stage workflow.

### Simpler menus and vault screens

- Costume and stage edit menus use compact actions and apply names, portraits,
  stock icons, and screenshots directly. Slippi status and retests update in
  place.
- **Portraits:** choose the active portrait from one grid, manage alternates,
  and retake portraits across characters in one batch. Retakes save both normal
  and HD portraits. Costume installs now use the portrait you selected.
- **Menus:** browse icon grids, backgrounds, doors, pause screens, percent
  fonts, and Ready / Go / Game graphics from one sidebar. Create or import mods
  directly from their category, with editing and card actions kept together.
- Menu mods and effects use the main **Import** button. When a file has more
  than one possible use, a compact choice dialog lets you choose its destination.
- Sound packs open immediately after creation and can be renamed in place.
  Vault browsing, sorting, folder actions, and Settings also receive layout
  and consistency improvements.

### Extras improvements

- **Live pictograms:** click a shape to edit just that part's colors and see
  the drawing update immediately. The game reference stays visible, with the
  selected part highlighted where mapped. A compact selector reaches
  overlapping parts and different phases.
- Related effects are grouped by move and recognizable parts, including Up-B
  startup and flight. Whole-effect recoloring and presets remain available.
- Added Fox's Up-B charging flames and wisps, plus separate controls for the
  rotating swirl in Samus's Screw Attack.
- **Image shines:** import a picture for Fox or Falco's reflector, including
  supported image shines from the website. Transparency is preserved, and
  flash and sparkle colors can be edited separately.
- Improved effect imports, saved-recipe editing, and Restore Vanilla behavior.
  Effects shared across large groups now say "Shared with many characters."

### Friends

- Send typed private messages to friends, with offline delivery, or join the
  global chat beside the player list.
- Patrons get profile borders.
- New profile privacy controls and fixes for connect codes claimed on another
  computer.

### Other improvements and fixes

- **Music loops:** stage and menu music have a waveform editor for choosing
  where the intro ends and previewing the transition into the repeating section.
- **Test in Game:** sharper previews that fill the panel, and Stop cancels an
  in-progress test build immediately.
- Replace a vanilla costume directly from its Install slot while retaining
  team assignments. Improved Falcon slot compatibility, Jigglypuff hats and
  cloth physics, and Kirby copy-costume colors.
- Fixed red Captain Falcon missing from Skin Creator after setup, and improved
  viewer startup errors and material animation playback.
- Upload now recognizes Discord sign-in.

Randall and the other unreleased features remain gated. This update does not
expand AI access.

## 0.8.2 — 2026-09-06

### Added
- Test in Game lets you play with controller port 1 until you stop: characters
  and costumes load on Battlefield, and stages load with Mario.
- Settings groups its existing cards into vertical categories, keeping edits
  and running operations when you switch sections. Help and updates live in
  General, Account in Files & setup, and HD portraits in Storage & backups.
  Tracker keeps a separate Cloud category. Cards stack without empty gaps
  beneath shorter neighbours.
- A mobile setup guide in Settings → Cloud vault explains Home Screen
  installation, phone pairing and replay upload progress.
- Paint Popo and Nana together in one preview, with labeled texture sets,
  separate undo histories and paired saves.
- Choose a data drive in Settings for Vault downloads, projects, build output
  and temporary files. Nucleus copies and verifies existing data on the next
  full launch and keeps the original folder for recovery.

### Fixed
- Settings no longer shows an empty Modding tab when AI Studio is disabled.
  Its optional setup card lives in Files & setup.
- Playable Test in Game waits for character select to finish initializing
  before selecting the fighter, preventing early menu-transition writes from
  being discarded. Loading and stage-select failures identify the failed step.
- Update checks retry after temporary connection failures and refresh when due
  after returning to the app or waking the computer. Manual checks and the
  update banner stay synchronized, and stable releases supersede their previews.
- Windows Test in Game shows a live video preview inside Nucleus, with an
  Open Dolphin window fallback. Its render window is left alone during startup.
- Test in Game reports Dolphin graphics startup errors promptly. Failed menu
  navigation cannot report PASS just because game memory is still advancing.
- Click a Vault costume or stage-variant card to edit it, without an extra
  hover pencil. Dragging still reorders; Enter or Space opens the focused card.
- Stats and Tourneys keep their chart layout after opening Settings; storage
  statistics no longer override their column sizes.
- Combos keeps its header controls in place while library details load, with
  Retry for failed details. Short sequences explain why sharing is unavailable,
  and invalid combo selections are rejected before starting an upload.
- Custom-character header icons, including Giga Bowser's, load with the required
  authentication. Repeating a completed Giga Bowser setup recognizes the installed
  character instead of asking you to run setup again.
- Stats shows its summary before rating history and other secondary data,
  reduces replay aggregation work, and keeps newer filter results protected
  from late responses. Failed loads offer Retry.
- Tourneys shows cached results and the first history page while older sets
  continue syncing. Brackets and replay playback load when opened, and
  outdated account or event requests cannot replace the current view.
- Ice Climbers animation lists include shared movement, attacks and damage
  motions, with Nana's own special-move overrides when available.
- Test in Game asks you to close an already-open Dolphin before building a
  test ISO. If Dolphin opens later, the waiting screen explains the pause
  without showing an empty preview or a stuck percentage.
- Friends keeps a full loading layout, prepares the first visible avatars and
  fades decoded pictures in over stable fallbacks. Profiles retain roster
  pictures, reuse recent details and offer Retry when details fail to load.
- The floating Import button stays anchored to the window when switching
  between Nucleus and Tracker instead of jumping with the page animation.
- Ice Climbers show Popo and Nana together in every costume preview, including
  when opening Nana, with synchronized animation and preserved custom partners.
- Viewer rendering avoids offscreen window presentation and redundant resizing
  on Windows. Mac and Linux wait for frame deadlines with immediate command
  wakeups, reducing polling and unnecessary delays between frames.
- Data location uses the Settings button/path styles, wraps long folders, and
  clearly separates pending moves, progress and errors.
- Combos prioritizes its first page, loads playback tools when opened, and
  avoids sorting full replay payloads before pagination. Failed loads offer
  Retry, and outdated requests cannot replace newer filter results.
- Fixed a preview startup error that prevented the desktop bridge from loading,
  causing Settings verification to report Unauthorized and native controls to fail.
- The Windows 3D preview now draws inside the app, so it clips and layers with
  panels and dialogs. Hidden previews pause, and slow frames cannot accumulate.
- Failed backend startup reports its actual error instead of opening every
  screen against a guessed backend address.
- The Windows development launcher checks dependencies and Vite readiness,
  reports launch failures, and preserves other running applications.
- Ice Climbers texture painting keeps separate Popo and Nana edits and saves
  both costume files together. Existing custom Nana partners are preserved.
- Friends no longer lets old requests overwrite newer actions or another
  account's state. Chat history paging retains messages with identical timestamps,
  and failed friend/profile actions report errors instead of looking successful.
- Temporary connect-code registration failures retry, so a signed-in user does
  not remain unfindable until restarting. Lobby Join can retry after its cooldown,
  and failed Accept/Leave sends preserve the action for retry.
- Patch downloads include authentication and report failed download checks with
  a retryable error instead of silently doing nothing.
- ISO verification distinguishes an invalid disc from a failed verification
  request, with Retry for unavailable verification.
- ISO export recovers missed completion events from artifact status. The exporter
  drains both output streams and reports timeout or pipe failures instead of hanging.
- Vault merges include effects, menu mods, and codes while preserving existing
  items. Backups read the active catalog and reject detected changes during copying.
- Short Vault edits preserve concurrent changes; unreadable catalogs fail without
  replacing their contents. Costume ZIP edits publish validated replacements atomically.
- Accepted restores recover their status after reconnecting or reopening Settings.
  An interrupted backend reports an uncertain restore instead of silently restarting it.
- File-serving, bundle, stage-package, and ISO output paths are confined to their
  intended locations. Preview audio, menu images, and door exports include authentication.
- ISO Save and Download select a specific completed export. Patch and bundle Play
  caches distinguish different content and ignore incomplete builds.
- Replay analysis retries failures and invalidates stale results. Tournament matching
  reads every replay page, resumes capped synchronization, and refreshes after rescans.
- Account token changes are validated and cancel subsequent cloud-upload work.
- Backend startup handles split port announcements. Viewer startup and portrait
  generation failures have bounded waits and clean up their owned workers.
- Setup progress recovers after reconnects, and duplicate starts are rejected.
- Costume exports retain G&W palettes; Stadium exports retain complete
  transformation sidecars. Packaged xdelta tools resolve consistently across platforms.
- Cold launch links wait for the renderer to accept them. Shutdown no longer uses
  process-name kill fallbacks. Update installation keeps its selected manifest and
  handles failed macOS opening and Linux single-instance handoff.
- Vault replacement restores now validate the backup and prepare the database
  before switching libraries, retaining the previous Vault for recovery.
  Backup downloads and restore uploads now include the required authentication.
- Restore progress accepts completion that arrives before the upload response.
- Fixed progress-socket connections with the pinned Flask version and restored
  token checks that a duplicate connection handler had bypassed.
- Failed queued imports can now retry, skip to the next item, or cancel the
  remaining queue.
- Fixed Skin Creator exports getting stuck because an old request's timer
  cleared a newer save or download.
- Cloud sync now reports metadata commit timeouts and keeps affected replays
  pending for retry instead of marking them backed up.
- Fixed Pokemon Stadium's variant list getting stuck loading on Windows when
  checking an existing vanilla variant. Name collisions now preserve both
  variants and their transformation skins.
- Fixed incremental replay rescans sometimes associating player identities
  and characters with the wrong replay.

### 🔒 Waiting

Built, but held out of 0.8.0 until each is proven end to end.

- **Share a build with a friend — and play it from the message.** Pick a vault
  Patch (an xdelta against the vanilla ISO), send it as a card, and your friend
  hits Play: the patch lands in their Vault → Patches, the ISO is built against
  their own vanilla copy, and Slippi launches. Also reachable as a
  `nucleus://play?build=…` link.
- **Sending a replay or combo to a friend.** Copy link works; handing one
  straight to a friend in chat is held back until a delivery that goes missing
  can explain itself.
- **Group chats.** The rooms exist, but the presence hub could not relay a
  message to them; fixed on the server, held here until one is seen to land.
- **Any emoji you like** (the patron perk). The curated palette sends for
  everyone.

## 0.8.0

### 🎁 Now free
- **Everything Tracker does on your PC is free.** The Stats suite, Watch Lite,
  and Watch with mods are no longer Patreon features — they open for everyone.
  Nothing that runs purely on your machine asks for an account at all.
- **Sharing a replay is free**, and no longer needs your library uploaded
  first: hit share on any game and Nucleus uploads that one game, then hands
  you the link. You do need to be signed in with Patreon for it — a **free
  ($0) account is enough**.
- What's still part of the $5 tier: **the phone app**, and the whole-library
  sync that fills it. That sync only ever pays off on a phone, so there's no
  longer any reason to push your whole library without one.

### ✨ New
- **Friends.** Tracker mode has a Friends tab: sign in with Discord, add
  friends by connect code, and see who's online and who's in game — the
  moment they're in one. Click a friend to open your conversation: preset
  messages, emotes and play invites live in a chat that keeps its history.
  Notifications fire for messages and friend requests only — never for someone
  just coming online. Completely free — no Patreon required.
- **A looking-for-games lobby.** List yourself for Singles or Doubles with a
  region you type yourself (share as much or as little as you like — it's
  remembered for next time). Singles listings show your Slippi rank; grab
  anyone's connect code with one click.
- **Put your best combo on your profile.** Pin any shared combo to your player
  card and it plays right there for anyone who opens it — no download, and it
  works even for people who have never seen that replay. Pinning needs the
  vault (a free Patreon account is enough); watching is free for everyone.
- **A heads-up before your first share link.** The first time you share a
  replay, Nucleus says plainly what that means: the replay and its thumbnail
  go to ssbmnucleus.net, anyone with the link can watch it without an account,
  and the link is permanent. Confirm once and it won't ask again.
- **Share sheet on replays and combos.** The share button mints the permanent
  ssbmnucleus.net link and copies it — for a game or for one combo.

### 🔧 Fixed
- **Friends tells you when it can't reach the network.** A dropped connection
  used to look exactly like being online, with nothing but an unlit dot to say
  otherwise — so you could sit there invisible to everyone, wondering why
  nobody was ever on. It now says so plainly, and says what to check.
- **Connecting to the friends network on a fresh Windows install.** The
  handshake verified against the machine certificate store, which on some
  machines is missing the issuer it needs; presence would silently never
  connect while everything else worked. It now trusts the same bundle the rest
  of the app uses.
- **Opening the Friends tab no longer flashes the signed-in-out page**, and
  friend requests show up in seconds instead of up to a minute.
- **Cloud combo refresh no longer restarts from scratch.** The one-time
  cloud repair that follows a combo re-scan now remembers how far it got:
  if a batch fails partway (bad connection, busy server), the next attempt
  continues from that point instead of re-sending the whole library. Big
  libraries previously re-sent everything on every retry, which could hammer
  the sync service for hours.
- **Texture-pack installs on a clean machine.** A hashing dependency was only
  ever present by accident on the development PC; every other install shipped
  without it and would have failed on the first install.

## 0.7.2

### ✨ New
- **The cloud vault is live for patrons.** The feature the download page has
  been describing finally exists in the shipped app: in Tracker mode, open
  Settings → **Cloud vault** to pair your phone (QR code), push your replay
  library, and browse it at tracker.ssbmnucleus.net. Link Patreon in the
  Account section first — the card explains the rest. Automatic processing
  (index → combos → sync) works in shipped builds too.
- **Report bugs from Settings.** Settings → Bug Report: describe what broke
  and hit Send — your logs come along automatically (usernames and tokens are
  scrubbed first) and the report goes privately to the developer, not to the
  public Discord. If you're on an old version the form asks you to update
  first, since your bug may already be fixed.
- **You'll know when an update drops.** The app now checks for releases in
  the background: a gold dot appears on the Settings tab and a one-time
  banner offers to take you to the updater — no more clicking "Check for
  Updates" to find out.

### 🔧 Fixed
- **The Windows build pipeline broke on the frontend rename** — fixed before
  it could bite a release.
- The installer no longer ships source maps.
- Large internal reorganization (backend packages, frontend service layer,
  one release-gate table) — no user-visible changes, a much cleaner base.

## 0.7.1

### ✨ New
- **Share links in Tracker mode.** Every synced replay — and every combo big
  enough to have a public page — now has a Share button that mints its
  permanent public link (the same pages the mobile vault shares), complete
  with a preview thumbnail for Discord embeds. Games that haven't synced yet
  don't show the button; sync first.
- **The vault keeps itself fresh.** Automatic processing (index → combos →
  sync) now runs every 10 minutes while Nucleus is open, not just at launch —
  tonight's games are there when you switch to Tracker mode, without a
  restart.

### 🐛 Fixed
- **Closing the app no longer truncates a saving ISO.** Exported ISOs are now
  saved through a native "Save As" dialog with a safe copy that lands complete
  or not at all — and quitting the app waits for any in-flight export, save,
  or download to finish before the backend exits. Previously, closing the
  window seconds after clicking Download could cut the 1.5 GB copy short, and
  the partial ISO would boot to a black screen in Dolphin.
- **Falcon costumes are neutralized again in installed builds.** The
  install-time Falcon neutralizer (added in 0.7.0 to kill per-color Slippi
  desyncs) looked for its reference skeleton in a folder that packaged builds
  ship empty, so it silently skipped every install outside a dev checkout. It
  now resolves the reference from the tables derived from your own ISO.
- **Downloaded effect colors now actually install.** Color effects
  downloaded from the website (lasers, side-B trails, shines and friends)
  used to report "installed" while leaving the game untouched — the
  downloaded file's colors were never read. Nucleus now reads the colors out
  of the downloaded mod and installs them through the same system as effects
  created in the app. Already-imported effects heal automatically the next
  time you install them or export an ISO. (Image-based shines — the ones
  with a picture inside the hexagon — are a different kind of mod and still
  aren't supported; they now say so instead of pretending.)
- **Effect thumbnails show up in the Upload page.** Downloaded effects'
  preview images pointed at a folder that doesn't exist, so their cards in
  the publish flow rendered without a picture.

## 0.7.0

### ✨ New
- **SSBM Nucleus on Linux.** The whole app ships as an AppImage: vault,
  installs, ISO export, Slippi integration, CSP rendering, HD texture packs —
  validated end to end on real hardware. In-app auto-updates work on Linux
  from this release forward.
- **SSBM Nucleus on macOS.** Apple Silicon Macs get a signed DMG with the
  same feature set: vault, installs, ISO export, Slippi integration, CSP
  rendering and HD texture packs — validated end to end on real hardware.
  (The build is Apple Silicon only; Intel Macs aren't supported.)
- **Tracker mode.** Nucleus gets a sibling mode for your replays — click the
  logo to switch. Browse and filter every Slippi replay you've ever played,
  search every combo you've landed, and pull your bracket history from
  start.gg — all free. Watching replays (with your installed mods, or
  instantly in Watch Lite) and the full Stats suite are for Patreon
  supporters: Tracker mode is the supporter project that funds Nucleus, and
  Nucleus itself stays free, forever.
- **Stats time machine.** The Stats tab has adjustable start and end dates,
  so you can scope every chart to a season, a year, or last week.
- **Sort your skins and stages.** The vault's character and stage pages have
  a sort row: A–Z, date added, and (for skins) costume color — ascending or
  descending. Your own drag-arranged order is the "Custom" sort and stays the
  default; other sorts are view-only, so switching back to Custom always
  brings your arrangement back untouched.
- **Gecko codes.** A new **Codes** button on the Install tab manages the
  codes in your build: apply, disable, or remove per build, then export the
  ISO to play with them. Your code vault comes pre-loaded with the community
  library (UCF, Better Camera, Unlock Everything, and 46 more) in collapsible
  groups, and **+ Paste codes** takes anything — raw hex, an INI block, or a
  loose forum copy-paste — and figures it out. One click on **Add m-ex
  defaults** stages the full stock-MexManager code set (Skip Memcard Prompt,
  Unlock Everything, Neutral Spawn, …) that Nucleus builds never had. The
  manager also shows the codes your Slippi Dolphin injects at launch, so the
  full picture of what runs in-game is finally in one place.

### 🚀 Improvements
- **First-time setup is faster — Giga Bowser now sets himself up on demand.**
  Setup used to render his portraits, recolored costumes and stock icons before
  it would finish, which added minutes for a character most people never open.
  He now waits in Custom Characters as a greyed-out card; click him and he
  builds right there, showing progress on the card, then behaves like any other
  custom character.

### 🐛 Fixed
- **Captain Falcon skins no longer desync online.** Falcon is the one
  character whose vanilla skeleton genuinely differs per color slot, so any
  skin built on a non-neutral color could desync on Slippi netplay — and the
  safety check couldn't catch it. Nucleus now normalizes every Falcon skin to
  the neutral color as it's installed: same look, netplay-safe skeleton. Your
  vault files are never modified — only the copy that goes into the build.
- **Watch Lite now shows Nana.** Ice Climbers games rendered only Popo — the
  replay parser never read the follower data Slippi records for Nana, so she
  simply didn't exist in the in-browser player. She now fights alongside Popo
  in every Watch Lite clip (and disappears correctly while she's KO'd), on
  desktop and mobile.
- **Portraits no longer come out full of holes on some imported skins.** A
  skin that re-exports with the translucent-pass flag set on its root bone
  had chunks cut clean out of its portrait — cape, face and tunic all
  perforated (reported on Skull Kid Link). The low-poly meshes Nucleus hides
  behind the visible ones stopped being safely hidden and started deleting
  real geometry instead. Nucleus now corrects that flag while rendering the
  portrait; your costume file and the ISO it builds are never touched.
- **"Fix" on a Slippi-unsafe skin actually fixes it now.** Clicking Fix could
  come back reporting success while leaving the costume byte-for-byte
  unchanged — and a skin whose file was already correctly named was never
  checked at all. Both are corrected, and a check that can't run now says so
  instead of quietly labelling the skin unsafe: the old behaviour offered a Fix
  that had nothing to fix, so clicking it did nothing and reported nothing.
  Costumes marked unsafe by a failed check are worth retesting.
- **Duplicate Slippi-fix code no longer piles up.** Every export quietly
  re-added the required "Skip Slippi SSS" code instead of noticing it was
  already there — long-lived projects had accumulated a dozen copies. New
  exports add it once; opening the code manager and hitting Apply cleans up
  existing duplicates.
- **Saving texture edits on some third-party skins no longer hangs.**
  Painting or importing textures onto certain imported models (big
  palette-format textures with color-rich art) could freeze the 3D viewer for
  minutes and make Save to Vault time out. The palette encoder is orders of
  magnitude faster now, and if the viewer ever does stall, the editor says so
  instead of silently timing out.
- **Kirby stock icons stop wearing every copy ability at once.** Generating a
  stock icon for a heavily-modified Kirby costume could render his stone and
  copy-hat models stacked on top of him. The stock render now hides the same
  prop meshes the CSP render always has.
- **CSS and SSS backgrounds coexist.** Importing a background for one select
  screen looked like it removed the other's — it never did, but the Install
  page showed them sharing one "Currently in MEX" slot. Each screen now
  tracks its own background, each vault page lists only its own kind, and a
  pack containing both menu files extracts the one for the screen you
  imported it from.
- **The build title on the Install page is no longer editable in place** —
  click the banner to edit everything in one spot instead of two.

## 0.6.4

### ✨ New
- **Add many songs at once.** Stage Music and Menu Music now take a
  multi-file selection — pick every song in one go instead of one file per
  click. Each song shows up in the list as it converts, and if a file won't
  convert the rest still land, with a summary naming what failed and why.

### 🐛 Fixed
- **Added songs actually play.** Adding a song to Menu Music or Stage Music
  put "All-Star Rest Area" in the playlist instead of the uploaded track.
  The upload itself was fine — the playlist just pointed at the wrong song.
  Re-adding your song (or picking it from the existing list) now works.

## 0.6.3

### ✨ New
- Costume drag-reorder is instant (was ~45s).
- MP3, OGG, M4A and FLAC work in music and sound slots.
- New animated logo and hi-res app icon.
- Click anywhere on a costume card to open it.
- Credits & Licenses panel in Settings.
- **Upgrading from 0.6.2 runs first-time setup once more.** The download no
  longer contains any Nintendo game data — Nucleus now pulls what it needs
  (fighter data and the retail costume models used as portrait references)
  straight from your own copy of the game. One extra setup pass, then it's
  business as usual.

### 🖼️ CSP improvements
- Lighting retuned to match vanilla (7 characters).
- Game & Watch gets his drop shadow back.
- Ice Climbers portraits include Nana.
- Bulk portrait retakes no longer come back blank.
- Jigglypuff and Kirby stock icons use the whole body.

### 🐛 Fixed
- Imported Jigglypuff costumes keep their hats.
- Uploaded songs loop; corrupt files rejected up front.
- Failed sound edits roll back cleanly.
- Accented mod names no longer break HD portraits.
- Clearing the vault clears its database too.
- "Skip" on a duplicate now works for stages, patches and effects, and reports
  what it skipped.
- Test in Game gets past Melee's save-data prompt.
- Screenshots capture the game, not the emulator or your desktop.
- Stuck screenshot batches stop early and say why.
- Packaged builds show the right icon.
- Modals no longer open under the header.
- Assorted import fixes for custom characters, stages, sound banks and
  playlists.

## 0.6.2

- **Mr. Game & Watch color creator** — G&W can finally have custom colors:
  "Create New Color" on his character page makes fill/outline color mods, and
  added color slots stay correct through add, remove, and reorder.
- **Duplicate-detection fix** — vault entries whose stored zip was deleted no
  longer "ghost-block" re-importing the same mod.
- **Giga Bowser stock icon** — the generated stock icon now crops around the
  face correctly.
- **Upload page polish** — the review step previews the post exactly as the
  website will show it, and "Upload another mod" resets the form cleanly.

## 0.6.1

- **Uploading fix** — publishing from the Upload tab to ssbmnucleus.net now
  works.
- **Stage music improvements** — stage and menu music are edited as weighted
  playlists.

## 0.6.0

### ✨ New
- **Classic mexTool character packages import directly as custom characters.**
  The `fighter.yml` package format most community fighters ship in — Shadow,
  Deoxys, Slippy, and hundreds of others — can now be dropped straight into
  the import button. The package is converted on the fly: costumes, CSS icon,
  sound bank, announcer call, victory theme, and the character's embedded
  move-logic tables (specials, taunts) all carry over. Packages nested inside
  a post's outer zip are found automatically, the best icon art shipped
  alongside the package is harvested (or one is generated from the first
  costume's portrait so the roster never shows a blank slot), and team-battle
  costume slots authored against a dev build are clamped so team mode can't
  break.
- **Vanilla-stage mods import as new custom stages.** A raw stage file for any
  non-tournament stage — Green Greens, Peach's Castle, Big Blue, Temple,
  Onett, and the rest — can now be dropped straight into the import button (or
  added from the website). Instead of replacing the original stage, the mod is
  added as a brand-new stage with its own stage-select entry, carrying the
  real stage's icon, music, sound effects, and stage logic (hazards, moving
  platforms, Banzai Bills...). The six tournament-legal stages still import as
  stage skins, exactly as before.
- **Sign in with your ssbmnucleus.net account.** The new Settings › Account
  card signs into the same community account used on the website (username or
  email), shows your avatar, and keeps you signed in between sessions. One
  account now works in both places.
- **Upload tab: build a website post from your vault.** A three-step flow for
  packaging mods for ssbmnucleus.net: pick mods straight from your vault (or
  drag in any files), fill in post details with category options derived from
  what you selected, and review the finished post. Actually publishing to the
  site goes live in an upcoming update — for now the flow is a full offline
  preview.
- **Menu music playlist editor.** The music button on the Fighters, Stages,
  and Menus screens now also edits the project-wide menu playlist — add any
  songs you like and weight how often each plays (vanilla is two songs at
  75%/25%).
- **Shield texture extras.** A new kind of effect mod that replaces the
  shield-bubble texture itself. Shield color still comes from the engine, so
  one texture mod restyles every player's shield without touching the tints.
- **Model Studio: real skin weights and a rig check.** AI-generated models are
  now rigged with Blender's bone-heat solver for much better deformation, and
  a rig-quality gate flags bad rigs before you waste time exporting them.

### 🚀 Improvements
- **The app now scales to your display.** The UI was designed on a 1440p
  monitor and looked off elsewhere; the window now picks a zoom factor from
  your display's resolution, and re-adapts when you drag it to another
  monitor. The embedded 3D viewers and the in-app Dolphin window stay
  pixel-aligned at every zoom level.
- **Vault layout polish.** The Stages home is a honeycomb of hexagons instead
  of a plain grid, all four mode homes line up at the same height, the
  character grid fills the page with bigger icons, and Upload-page costume
  rows show each costume's slot color as a named dot.
- **Settings page stability.** Sections live in fixed columns so expanding one
  card no longer reshuffles the whole page, and the danger zone is clearly
  marked.

### 🐛 Fixes
- **Big zip imports no longer silently drop most of their files.** A zip
  containing other archives (a whole character pack, an overnight batch)
  used to import only the loose files at the top level and ignore everything
  nested — now inner archives are unpacked two levels deep, with a summary of
  what was imported, auto-fixed, and skipped. Also fixed in the same pass:
  `.7z` archives import instead of erroring, "skip duplicates" actually skips
  for stages/patches/effects, and a file that tripped two confirmation
  dialogs at once (e.g. Slippi fix + duplicate) imported instead of silently
  failing.
- **Ice Climbers costumes from the website import correctly.** Website
  exports pair Popo and Nana in non-vanilla color combinations (say, Green
  Popo with Aqua Nana), which the importer refused to match up — a zip with
  exactly one of each now pairs them regardless of color.
- **Character detection works on more files.** The DAT parser misread any
  file that contains reference nodes, which silently defeated content-based
  character and color detection for those imports.
- **Patch files no longer balloon on rebuilt ISOs.** Creating an xdelta patch
  against a rebuilt ISO could degenerate to nearly the size of the full
  image; patches are now created with a full-image search window.
- **Hand-edited recolors render clean portraits again.** A re-exported skin
  that dropped a couple of model parts could defeat low-poly hiding, drawing
  the low-detail mesh on top of its CSP.

## 0.5.2

### 🐛 Fixes
- **m-ex builds no longer crash on the stage-select screen with current
  Slippi.** Slippi's October 2025 update made m-ex ISOs require the "Skip
  Slippi SSS" gecko code — without it, the game crashed the moment you opened
  the stage-select screen. Every exported ISO now bakes this code in
  automatically, so there's nothing to set up by hand.
- **Pokemon Stadium alternate stages no longer crash on load.** Dynamic
  Alternate Stage variants for Pokemon Stadium could crash the game the instant
  the stage loaded, depending on your Melee save's language — Pokemon Stadium
  is the one stage whose file the disc loads differently for English vs.
  Japanese saves, and a variant was only ever packed for one of them. Exported
  ISOs now include every Stadium alternate for both, so they load no matter
  which language your save uses. Existing projects fix themselves on the next
  export.
- **Effect recolors (Extras) now work reliably on any install.** Extras that
  recolor a texture — Mario's coins, Fox/Falco's Firefox charge fire, Bowser's
  fire breath, and others — could fail with a "no vanilla reference" error, and
  installing one effect mod on top of another could silently keep the old
  colors for some layers ("N layers could not be safely written"). The app now
  pulls the small reference files it needs straight from your saved vanilla
  ISO, so these installs apply cleanly everywhere.

### ✨ New
- **Bowser "Fire Breath Texture" extra.** With a recolored fire breath, the
  flames landing on the stage stayed orange, because sustained ground fire is
  drawn from a texture the color mod didn't touch. The new texture recolor
  brings the flame body itself in line with your color, so Bowser's fire is one
  consistent color from breath to ground.

### 🚀 Improvements
- **Settings › Updates polish.** The update indicator is now the same hexagon
  loader used throughout the rest of the app, and it holds its position instead
  of shifting when an update is found or while one downloads.

## 0.5.1

### 🐛 Fixes
- **Extras install no longer fails with "No module named 'ptcl_parse'"** in the
  installed app — the offset-relocation module was imported dynamically and
  never got bundled into the packaged backend, so any extra whose install hit
  the relocation guard (e.g. Bowser's Fire Breath on an already-modified
  effect file) errored out.
- **Installing an extra on top of another one now works.** The offset-safety
  guard only accepted untouched vanilla bytes, so a second install over a
  previous mod (or re-installing an edited mod, or restore-vanilla) silently
  skipped most layers. The guard now proves the write location structurally
  (neighborhood context + particle-bank identity) instead of by vanilla color
  value.
- **Fox/Falco Firefox tip and body colors no longer get stuck** — their
  matrix-format layers matched only the vanilla color, so they could be
  recolored exactly once and never restored.
- **The install page's "Currently in MEX" preview shows the actually-installed
  colors** — it previously fell back to a hardcoded white/blue pictogram for
  the fan-out effect extras.
- **Extras installs are atomic** — patches are applied to an isolated copy and
  swapped in only after every layer succeeded, so a mid-install failure can't
  leave a half-patched effect file.
- Skipped layers (unrecognizable file layout) are now reported to the user
  instead of the install silently claiming success.

## 0.5.0

### ✨ New
- **Recolor nearly every character's in-game effects.** The Extras system now
  covers the whole cast with 55 effect mods: lasers, Shine, and Firefox
  (Fox/Falco — including the charge-phase fire), Falcon Punch/Kick/Raptor
  Boost, Mario & Doc fireballs/cape/tornado/coins, Luigi, Samus screw
  attack/missiles/charge shot, Ness PSI/PK Thunder/PK Fire, Pikachu & Pichu
  thunder and jolts, Mewtwo, Zelda & Sheik, Bowser's fire breath, Jigglypuff's
  sing notes, Ganondorf's warlock/wizard's foot/gerudo, Ice Climbers,
  Link & Young Link spin attacks, Kirby stone + five copy-ability recolors,
  Marth/Roy/Link sword trails, and cast-shared common fire/flash/electric.
  Every mod was verified in-game frame-by-frame.
- **Redesigned extras editor.** Simple mode recolors the whole effect with one
  picker while preserving each layer's brightness; Advanced mode shows a card
  per effect element (Main Colors, Trail, Dots, ...) with in-game-cropped
  pictograms — no more cryptic offset names. One preset row, clickable color
  swatches, and live previews that match what actually renders in game.
- **Fox and Falco laser mods can now recolor the beam's white center line.**
  The laser editor gained "Center Line" and "Center Tip" pickers (the preview's
  center line — previously always white — now follows your color). Existing
  saved laser mods keep their behavior: the line stays vanilla white unless
  you set it.
- **Bulk CSP generation** — regenerate portraits for every costume of a
  character in one click.
- **Wiki overhaul: 7 new pages** covering previously undocumented features
  (Custom Characters, Custom Stages, Menus & Select Screen Mods, Sound Mods,
  Skin Creator, Test In Game, ISO Scanning), plus stale pages brought up to
  date with current behavior.
- **Boot-time setup health check.** The app now validates your saved vanilla
  ISO path on startup (exists, right size, GALE01 header) and shows a
  dismissable "re-run setup" notice if something's off.

### 🚀 Improvements
- **The vault now runs on a real database.** The vault index (costumes, stages,
  custom content, bundles) moved from the single `storage/metadata.json` blob
  to SQLite (`storage/vault.db`) — concurrent writes are safe across processes,
  and it lays the groundwork to eliminate list-position ordering bugs. Migrated
  automatically on first launch with a backup and a round-trip-validation check
  (falling back to JSON if anything looks wrong); `metadata.json` is kept in
  sync as a live backup and remains the portable format for vault
  backups/exports. Set `NUCLEUS_VAULT_DB=0` to stay on JSON. See
  `docs/VAULT_SQLITE_MIGRATION.md`.
- **Much faster portrait generation.** Headless CSP renders go through a
  persistent worker pool instead of spawning a fresh renderer per portrait —
  around 9.5x faster on batch renders, byte-identical output.
- The skin creator's costume-select step now renders as a normal in-app page
  under the header instead of a fullscreen takeover.

### 🐛 Fixes
- **Custom Firefox/Firebird mods now apply ALL their layers when installed.**
  Newer up-B color layers (small trail, dots, charge lines, flare) were
  silently skipped during install/export when the app's dynamic offset
  detection was active — mods saved with those colors only partially applied.
- **CSP/portrait generation no longer steals your keyboard focus.** Every
  headless render (generating CSPs, stock icons, HD portraits, the skin-lab
  viewer) used to yank the foreground away from whatever you were typing in —
  making the app unusable for writing AI prompts while portraits generated.
  The renderer's internal OpenGL window force-focused itself on creation; it
  is now blocked from activating at all (with an instant hand-back safety net),
  and the full CSP regression suite confirms renders are pixel-identical.
- **Sword trail extras (Marth, Roy, Link, Young Link) now recolor the trail
  correctly.** The editor previously offered three colors (Main / Secondary /
  Edge), but the game's trail is actually a two-color ribbon — one color along
  each edge of the arc, fading out toward the tail — and two of the old
  "color" bytes were really the trail's transparency settings, so custom
  trails could come out with a reversed fade and mostly-wrong colors
  (vanilla Marth's trail is cyan-to-white, not red/yellow/white). The editor
  now has Inner Edge / Outer Edge pickers and the preview matches what
  actually renders in game. Verified frame-by-frame in-game on Marth.
- **The character page's "Available to Import" list now matches the vault's
  order.** Costumes you filed into a folder (e.g. an "Animelee" folder) were
  grouped together in the vault but showed up scattered in raw import-order on
  the character page, so the two screens disagreed. The import list now orders
  costumes exactly like the vault — folder members grouped where the folder
  sits — just as a flat list, without the folder headers. Ordering only; no
  costumes are added, removed, or changed on disk.
- **Mr. Game & Watch portraits and stock icons recolor correctly.** Team-color
  and custom G&W costumes get his signature outline rebuilt in the portrait
  pipeline (it used to project as a gray blob), and his stock icons are
  recolored from the vanilla icon instead of rendered.
- **Some imported costumes no longer render with flat-grey armor or
  near-black bodies in portraits.** A color-mixing operation (RGB_MASK) in the
  CSP shader was implemented wrong; costumes using it (e.g. Marth "Lyn",
  some Mario imports) now match the game. Re-render CSPs to refresh existing
  portraits.
- **Reordering Ice Climbers costumes no longer desyncs Popo and Nana** — and
  reordering Peach no longer silently corrupts Nana's costume order (the
  pairing logic pointed at the wrong character slot).
- **Exported ISOs are always valid even if a Stadium stage folder still has
  legacy `.usd` alt files** — they're healed to `.dat` names at ISO pack time
  so the in-game alt loader accepts them.
- **Bundle/patch export fixes** for modded-vanilla content: Red Falcon,
  Fox's blaster, Pichu multi-slot costumes, and Ice Climbers costumes with a
  modded Nana.
- Fixed a race that could briefly leave the vault index partially written
  during imports.

### ⚙️ Internal
- Added a backend pytest suite + GitHub Actions CI that runs it.
- Docs audit (ARCHITECTURE/API_REFERENCE now cover all blueprints and hooks;
  stale claims removed; `docs/DOCUMENTATION.md` defines the doc tiers and ship
  checklist) and a dead-code sweep (17 finished one-off probe scripts, orphan
  component, 93 tracked debug PNGs).
- One-shot release script (`scripts/build/release.bat`): tests → build → CSP
  regression → tag → publish to R2 + GitHub.

## 0.4.3

### 🐛 Fixes
- **Character-select portraits render imported costumes correctly.** Costumes whose
  eyes were drawn black/empty (Sonic, Wario and similar imports) now composite their
  eye textures properly, and replaced-model costumes no longer show low-poly geometry
  poking through. Regenerate CSPs to refresh existing portraits.
- **Costume accessories show up in portraits.** Attached hats and hair now sit on the
  model — e.g. Jigglypuff's nurse hat and the Falco-slot's long hair.
- **Pokémon Stadium custom stages no longer crash on boot** (caused by legacy
  alt-file extensions).
- **Reordering DAS stage variants no longer fails** with "Invalid fromIndex or
  toIndex" when an on-disk variant wasn't in the vault metadata.

### 🚀 Improvements
- **Fox and Falco's blaster renders as the real 3D model in portraits.**
- **Faster texture-pack exports.** HD portraits now render in parallel, sized to your
  machine's CPU, instead of one at a time.
- **Automatic Animelee detection** when organizing the vault.
- HD portraits are cached for bundle/patch exports, so repeat exports are instant.

### 🔧 Changes
- Stage and character names are hidden in the grids for a cleaner look.
- Bug-report zips no longer count Dolphin distribution files as Slippi logs.
- More robust Dolphin controller-pipe connection during in-game tests.

## 0.4.2

### 🐛 Fixes
- **Character select portraits render alt costumes correctly.** Recolor/alt
  costumes were drawn with the default costume's low-poly mask, so accessories
  vanished or low-poly geometry poked through — Pikachu's blue/green hats were
  missing and the red cap showed an artifact, Pichu's backpack/cheeks were wrong,
  and Peach's Daisy sleeves were blocky. Each costume now uses its own visibility
  data. Regenerate CSPs to refresh existing portraits.
- **Jigglypuff's costume hats now show up in portraits.** Hats that ship as a
  separate model are spliced into the render and follow the posed head.
- **Merging a vault backup no longer corrupts custom characters you already have.**
  A conflicting item is now kept entirely as-is — the backup's copy of it (and any
  stray extra files) is skipped — instead of leaking files into your version. The
  merge also shows a report of what was added vs. kept.

### 🚀 Improvements
- **Vault restore now shows live progress.** Importing a vault backup displays an
  upload bar and then a per-file extract/merge status instead of an indefinite
  wait with no feedback.
- CSP rendering uses two-sided lighting so back-facing surfaces no longer go dark.

### 🔧 Changes
- Stages imported without a bundled screenshot no longer boot Dolphin to capture
  one during import. Use the bulk DAS "capture screenshots" flow instead.

## 0.4.1

### 🐛 Fixes
- **Ice Climbers no longer crash in Classic mode and online.** Nana's intro/result
  demo animations were exported empty, which made her T-pose on the VS banner and
  crash the game when starting a 1P or netplay match. Existing projects are repaired
  automatically on the next export.
- **Imported Jigglypuff costumes no longer crash the game.** The importer grabbed
  Jigglypuff's hat model (1 joint) instead of the body (50 joints), which crashed on
  load. Re-import affected Puff skins to fix existing ones.

## 0.4.0

The big update is finally here.

### ✨ New features
- **In-app updater** — future versions update from inside the app (Settings → Updates)
- **In-game testing** — test skins in game directly from the app
- **Stage screenshots** — capture clean in-game previews for stages
- **Custom characters & stages** — import, manage, and install them
- **Menu mods** — CSS + grid editor, SSS + grid editor, and HUD
- **Game banner editing**
- **Sound mods & stage music**
- **ISO scan** — pull every skin / stage / custom character / custom stage from any
  ISO into your vault (skips what you already have)
- **Start a project from a vanilla Melee patch** in your vault (Animelee, etc.)
- **Pose manager** improvements
- **Experimental stock-icon generator** (still janky)

### 🚀 Improvements
- Better loading screens and feedback
- Faster batch skin installation
- Better mod importing & project management
- **Exporting**: improved CSP compression, automated texture-pack scanning, and
  create/launch xdelta patches inside the app

### 🐛 Bug fixes
- Pokémon Stadium should finally be fixed
- Ice Climbers fixes
- Red Falcon fixes
- Kirby and Game & Watch actually work now

### ⚠️ Known issues
- Non-default Captain Falcon skins desync
- Extras still need work

### 🔜 Coming next
Trailer · guide · more bug fixes · better console support · website improvements ·
more mod-creation tools · and more :)

**Download:** https://ssbmnucleus.net/download
