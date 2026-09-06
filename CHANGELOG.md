# Changelog

All notable changes to SSBM Nucleus are documented here.

## Unreleased

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
