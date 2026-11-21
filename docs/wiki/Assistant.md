# Randall in Nucleus

Model exports preserve material-animation objects needed by the fighter when it loads. Passing export checks still requires a separate in-game test before a costume is considered playable.

Randall comes with SSBM Nucleus from 0.9.0. Open **AI**
immediately after Upload. Randall's name and cloud icon appear at the top of the chat sidebar. The Tracker coach is not released yet.
Switch tabs to leave the conversation running. When you return, you can scroll the last reply fully above the message box, including with a multiline draft. Blue Randall settings are available from the sidebar.

The **workbench** beside the chat shows what Randall made:
- **3D** is the newest version in the live viewer. Drag to turn it, right-drag to move it (it stays under your cursor), scroll to zoom. Pick an animation from the list, or **Pose** to see it standing still; the round arrow puts the camera back. It reloads after each edit and keeps the animation you picked; another chat's model starts standing still, with its own camera.
- **Pictures** (retexturing a costume or a stage) are all the renders Randall made in the chat to judge his edits, grouped by step, newest selected. Click a picture to see it full screen (the arrow keys step through them, Esc closes). Right-click to copy it or attach it to your message, or drag it onto the chat to point Randall at it: he is shown the picture you attach.
- **In game** shows a running game test.

A model import shows its steps on its card in the chat while it runs. Once it has written the costume, the workbench opens on it in **3D**, named for the costume and its fighter; its portrait is on the card.

Hide the workbench with its arrow and bring it back with the **Workbench** tab on the right edge. The 3D view needs the desktop app.

Randall's vault assistant uses **GLM 5.3 Flash** as its main model, shown in **Randall settings**.
Straightforward searches, statistics and lookups can run on **Gemini 2.5 Flash Lite**
automatically. You stay in the same chat, with the same history, result cards and
approvals. Deeper analysis and editing continue with the main model; you do not
need to switch models or repeat your request.
For a new single-costume retexture, Gemini can find and acquire the source costume,
including the usual download approval. Randall then opens a private copy and
gathers its texture map and first texture sheet automatically. GLM chooses the
shade, affected parts and protected details, makes the edits, and reviews the
rendered result. Color words are interpreted in context rather than mapped to a
fixed preset. Ambiguous sources and continued edits stay with the main model.
Without a linked Patreon account, blue Randall keeps the same welcome screen and suggestions, with a locked message box and **Link Patreon** button. Eligible memberships use your provisioned AI key and the
same shared allowance as Tracker. AI access details are in Randall settings. Both modes use only Patreon-provisioned credentials. Both sidebars show a shared monthly usage bar, which resets on the 1st; the settings icon beside your name opens Randall settings. Everyone also gets a little free usage that refills every 3 days, and it is used first. When you are running low for what a chat is about to do, Randall says so above the message box and when it refills; you can still send, but the job may stop partway. In Tracker, memory is available from that panel.
Your messages, attached item names and tool results are sent to the AI provider.
Conversations and portrait previews are saved on this computer.
Randall limits older previews sent with each follow-up to reduce repeated image
traffic. Fresh preview batches and complete model comparisons stay available;
you can ask to inspect an older file again.

Tasks have no fixed step cutoff. During longer tasks, a notice above the message
box shows the step Randall is on and how long it has taken, and offers **Stop**.
The notice does not pause work or ask you to approve more steps.
If Randall announces its next action but omits the tool call, it tries to recover
from the work already done. Repeated unfulfilled promises, provider limits and
interrupted responses show an explicit message. Send **continue** to resume;
completed results and working copies are kept.

Both modes use a simple message box and an animated three-dot thinking bubble.
Tracker's signed-out screen uses the same three suggestions and locked message bar
as Nucleus. Link Patreon from the bar; failed membership checks offer Try again.
In Nucleus, new replies keep explanations, results and approval cards in the order
they happen. The dots appear beside Randall during the initial wait and disappear
as soon as text or tool activity starts appearing.
Tracker's model picker and context usage are in **Randall settings**, opened from
the sidebar, instead of below the message box.

## Try it

### Queue and send now

In Nucleus, press **Enter** while Randall is working to queue another message.
Queued messages appear as faint outgoing bubbles at the end of the conversation,
using Ozone's queue controls. They send oldest first when the current reply ends.
**Send now** on the last bubble delivers the whole queue into the ongoing work
at the next safe point; an already-running tool finishes first. Completed work
and attachments are retained.

Use the trash icon to remove a message. The **More** menu offers **Edit** (returns
text and attachments to the composer, appending to any draft) and **Copy**.
With three or more queued messages, **Clear all** appears. Stop or an error leaves
unsent messages queued; use **Send** to resume. Queues also survive reopening the
chat or restarting Nucleus. Credentials are never stored with queued messages.

### Example requests

- “Find the most downloaded Fox skins on the website.”
- “Show the most liked stage skins, excluding anime tags.”
- “Download the green version of this mod to my vault.”
- “Create a project called My Melee Build and install CDI Link and Kermit into it.”

- “Find my Marth skins.”
- “What does the Slippi safety result mean?”
- “Render a portrait preview of this costume.”
- “Put these selected skins in a folder called Favorites.”

Randall receives the current vault context. Background searches and inspections
appear as **Checked vault**; expand the entry to see what he read. Errors stay visible.
File/vault activity stays centered in the chat while Randall works,
when results arrive, and when you expand the details.
Thinking dots appear on the left with Randall's avatar beside them, even before reply text arrives.
Expanded lookups group a mod's variants together in a compact, scrollable list.
Ask him to show a skin or recommend a few to get portrait cards with color variants.
“Show me it” displays the saved skin card; ask to make or regenerate a CSP for a new render.
Use **Select for chat** to attach a presented skin to your next message, or click
its card to open that skin's edit menu in the vault. Clear attachments with the attached-skins button.
Randall uses the full-page **AI** tab. Opening a skin or project switches to its page;
return to AI to continue the same conversation.

When a website mod contains one costume in several color slots, its download card
offers **Default variant only** or **All variants**. Choose one, then **Download** to review it.
Requests for a specific color keep that color selected.

Ask **Download all of these** or use **Download all** above grouped website results
to approve up to 24 mods together. The review shows their images and file lists.
**Fix unsafe skins** starts checked; leave it on to fix unsafe costumes automatically
within that approved batch, or uncheck it to keep original files. There is no second
fix prompt for each mod. Duplicate color variants default to one costume unless you
request all variants. Original cards update to **In vault**, and one receipt shows
what was added. Failures and Stop keep downloads that already finished.
An animated Shine marks the mod being downloaded. For batches, the Shine fills as
mods finish processing and shows the completed count; failed downloads are counted
separately in the summary. The indicator stops when the batch finishes or is stopped.

Download reviews and **Added to vault** cards include all successfully imported mod
types, including stages. Costumes show portraits and stock icons; stages and other
mods show screenshots. The website preview is used when a file has no individual
image. Packs without individual receipts show their title, preview and added count.
An unavailable image has a placeholder; unsupported imports still show an error.

Folder changes show a preview with **Approve once** and **Decline**. Approval applies only to that exact action; there is no global permission toggle. Pending requests expire after 15 minutes, and Stop cancels them. The assistant can
create or reuse a folder and move costumes within one character. Use **Undo organization**
on its result to restore the previous memberships. Undo preserves other edits and
refuses to overwrite folder changes made afterward. Portrait rendering creates a
preview without replacing the saved portrait.
Ask Randall to make a CSP for a vault skin to see a fresh HD preview in chat.
A small **Making CSP** bubble shows animated dots while it renders, then becomes
the portrait preview. If rendering fails, its error stays visible in chat.

## Edit mod files

Stage download and saved-stage cards have **Edit** to open Stage Creator with
Randall beside it. Click the card preview to open that stage's vault edit menu.
The vault's **Edit Textures** and **Create New Mod** actions open the same editor
on its own, without Randall.

Ask Randall to recolor a vault skin using the Skin Creator's color palette, for
example, **Make this skin's blue clothes purple and show me the result**. He can
inspect the rendered 3D skin, identify color groups, shift their hue and saturation,
and check other viewing angles. Shading and transparency are preserved. He can
limit a recolor to selected textures and reset adjustments while experimenting.

Previews appear in chat and are also visible to Randall. A retexture saves itself:
when Randall's reply ends, the result is in your vault as a new costume with fresh
artwork and a Slippi check (no need to ask), and later changes in the same chat
update that same costume instead of adding another. Ask for "a separate copy" to
keep both. Your original stays intact. If a result cannot be saved, the reply says
why in one sentence and the next message tries again. Attached DATs can be edited
and downloaded; paired Ice Climbers copies must be saved together in the Texture Lab. These edits use a separate
working copy, so they do not alter an open editor. Image generation is not needed
for palette recolors and is not connected yet.

Attach a DAT, ZIP or PNG with **+**, or drop files onto Randall's message bar.
He can inspect DAT roots and costume textures, inspect meshes, export textures,
models and animations, replace textures with attached PNGs, remove selected meshes
or triangles, and render stage previews. Exported images and files appear in chat.

Edits always produce copies. Randall cannot overwrite existing vault mods or
attached originals, including an older Randall copy. Ask him to add an edited
costume copy to the vault to get a new entry with fresh artwork and a Slippi check.
You can also download edited files directly. Editing works from chat without
opening an editor. Paired climber copies must be saved together in the Texture Lab.

Click a vault skin card to open it in the vault. Its **Edit** button opens the Texture Lab with the same
Randall conversation beside it. He receives the current skin and selected texture
as context. A PNG file card's **Use on selected texture** button applies it through
the editor's normal import and undo workflow; Save creates a new costume.
Close Randall's sidebar with **×** and reopen it with **Randall** in the editor header.
You can also ask for new surface materials, such as **make these boots cracked
leather** or **give the shield hammered metal**. Randall generates a material
swatch, previews which pixels it will affect, then applies it to a private
costume copy. Each generation uses some of your monthly Randall usage, which
comes with your Patreon tier.

Ask him to change the pattern size, strength or mask to refine the same swatch
without generating a new one. Mask previews and swatches are inside
collapsed tool rows; the applied result appears as a 3D preview. He can undo
the material application or export it as a new copy. Check important details
and seams in the preview: a color selection alone may also select similarly
colored logos or trim. Randall can highlight where a texture appears on the
model before editing it, and enlarge tiny textures to hold material detail.
For a whole-surface change, his coverage preview can also find skin backgrounds
inside eye and face textures, with masks that protect the eye details. Matching
expression frames can be included in the same material application.
Reset restores their original size. Palette adjustments can darken colors as
well as change their hue.

Completed edits keep a recovery copy, so Randall can reopen the working skin
if its editing session expires. Generated swatches remain available for reuse.
Continuing a conversation restores recent image evidence and working file
references instead of relying only on earlier descriptions.

Arbitrary model/animation imports are not available yet.

## Projects

Ask Randall to list your projects, create a named project, or install vault costume
skins into a project. New projects use the vanilla Melee ISO configured in Settings.
Creation and installation each show a review with a confirmation button. The project
list refreshes when Randall creates a project, without restarting or waiting for his
whole reply to finish. The install
review shows the target project and selected costume portraits, including stored
Slippi-unsafe labels. Ice Climbers includes its paired Nana automatically.

Installs add costume slots and preserve existing slots. Installing the same skin
again adds another slot. Receipts show the installed count and any failures; use
**Open project** to view the target on the Install page. Switching the active project
does not redirect an approved install. Downloading to the vault alone does not install it.

Project installs through Randall support standard character costume skins only. Stages, extras,
installing custom fighters, slot replacement and ISO exporting are not available through him.
Separately, Randall can create a clone character in the vault from an imported model (see
[Custom Characters](Custom-Characters.md)); he saves it as a new custom character and does not install it.

## Conversations and stopping

File reads appear as a compact **Read 3 files** summary. Expand it to see the help pages and their excerpts. Repeated reads are grouped; errors remain visible.

Website results show a screenshot gallery, title, author, likes/downloads, and **View on website**.
Use the gallery arrows, keyboard arrows, or swipe to browse screenshots with smooth
transitions. Reduced-motion settings turn off the animation.
The heart shows likes. Sign in to your Nucleus account to like or unlike a mod, or
ask Randall to do it. Nucleus sign-in is separate from Patreon AI access.
Ask for newest, oldest, most liked, or most downloaded mods. You can combine a
character, category, creator, included tags, and excluded tags, or ask for another
page. Likes and downloads are all-time counts.

Click **Download** on the first card, or tell Randall which mod or costume variant you want.
The button opens a review dialog directly, without an AI request or scrolling the chat.
You can download while Randall is typing; the reply and download progress update independently.
Review the included mod cards and file list together, then choose **Confirm download** or **Cancel**.
Cards show portraits, stock icons, character/color, and filenames. Small downloads fit
in one compact review; search and pages of 20 items appear only for large packs.
The original card shows download progress, then **In vault**; it is not repeated.
Randall consumes the website's `nucleus://import` handoff inside Nucleus, keeping
approval and results in chat. Effect downloads carry their character and effect type
to the same importer used by website links. Posts with several effect files need
an exact file selection; ambiguous or unsupported effect tags produce an error.
Website costume and stage imports keep their website link across chats and app restarts.
The label checks the current vault and clears when all linked items are removed.
Older downloads are recovered from saved receipts when exact item IDs are available;
manual imports without a website link cannot be identified from their names alone.
Updates with no visible message or receipt do not add another Randall avatar.
The download includes separately hosted costume
CSPs and stock icons when available. Existing costumes are skipped. Downloaded costumes
are checked before anything is added. If a costume fails the Slippi check, choose
**Fix and add to vault** or **Add without fixing** directly below the mod image.
Use the **×** or Escape to cancel. Fix applies supported
repairs; the receipt reports fixes and any costumes still unsafe. Cancelling discards the
download without adding it. Import or artwork failures are reported. A download adds
to your vault; it does not install into a build. Large archives over 256 MB must be
downloaded from the website. Remove an unwanted import through the vault.
After importing, an **Added to vault** receipt shows each new costume's CSP and
stock icon. Click a costume receipt item to open that skin's edit menu in the vault.

Randall shows a three-dot typing bubble while working. Replies stream in gradually,
and mod cards ease into the conversation. Reduced-motion settings turn off these animations.

Nucleus and Tracker share the same chat layout. Use the sidebar button in the left rail to open the floating history drawer, and the button inside the drawer to collapse it. The rail also has a New chat shortcut. In Nucleus you can also search history.
Hover a conversation to reveal its **×** delete button; keyboard focus reveals it too.
Deleting a conversation does not undo its vault changes. **New chat** starts
fresh. Shift+Enter adds a line; Enter sends. You can draft the next question during a turn.

A new chat looks like a new chat in the Claude app: Randall, one line, and the message box in the middle of
the page. Under the box are five starting points in two groups, **Characters** and **Stages**:

- **Retexture a costume**: pick a costume from your vault or the stock roster (or name one, from the website
  too), then describe the look. The result saves itself to your vault as a new costume when Randall's reply
  ends; asking for changes in the same chat updates that costume.
- **Import a character model**: pick the fighter, attach the model and send.
- **Create a character**: build a whole new fighter, starting from a model. It is shown greyed out with a
  "Use MCP" label: it is not started from Randall's chat. Connect your own AI in Settings > AI; porting a
  fighter from another game also needs the creation toolkit (Settings > AI > Creation toolkit).
- **Retexture a stage**: pick a stage, then one of your vault versions of it or the stock stage, and describe
  the colors you want. Randall opens a private copy, shows you what he changes, and when his reply ends the
  result is saved by itself as a **new** stage variant in your vault; asking for changes in the same chat
  updates that variant instead of adding another, and your original is never changed. He can shift colors and
  change a surface's base color or swap a texture for a picture, but he cannot set an exact color or make a
  stage darker or lighter yet. Playing a saved variant in game works for the six tournament stages.
- **Import a stage model**: turn a 3D model into a playable stage. It is shown greyed out with a "Use MCP"
  label: it is not started from Randall's chat.

Choosing one (here, or from the same rows in the history sidebar) keeps the page as it is: the starting points
step aside and the bottom row of the message box shows what you chose, with a button next to it for what to
start from: **Choose costume**, **Choose fighter** or **Choose stage**. That button opens the picker just above
or below the box: type to search, use the arrow keys and Enter, and press Escape to go back a step or close it.
Pick a fighter and then one of its costumes (vault costumes first, then the stock colors, marked "Stock"), a
fighter, or a stage and then one of your versions of it or the stock stage. What you picked then sits in the
message box, with a small picture and its name ("Fox · Blue Hoodie"); click it to change it or **×** to clear
it. Click the workflow's name in the box to switch to another one or back to a plain chat (**Ask**). Once you
send the first message the box moves to the bottom as usual and the chat keeps that workflow; your message
shows what you picked.

For a model import the fighter list starts with **AI Choice** (a "?" tile): pick it to let Randall choose the
fighter; nothing is sent about the fighter, and the box reads "AI Choice" until you clear it.

A model import needs its tools, a one-time download in Settings (see **The import's tools** below), and reads
the fighters from your own vanilla Melee disc, so set it in Settings first. The first import
on a computer also gets the fighters ready from it, which adds a few minutes (about ten seconds a fighter, and
every fighter when Randall chooses); later imports skip that step.

Picking is optional: you can also type what you want. Picking a costume or stage replaces any skins attached
to the message. Everything else, including finding and downloading mods from the website, works in any chat:
just ask.

**Stop** prevents further tool calls. A render, project operation or folder operation already running
may finish; its result is kept. If you refresh during a turn, reopen the conversation
to recover its progress. An app restart can interrupt a turn.

The local-vault tools handle standard character costumes, documentation, portrait
previews and folder organization. Website downloads use Nucleus's supported import
formats. Organizing custom-character libraries, creating mods,
building ISOs and gameplay testing are planned extensions. Stored safety labels
describe previous validation; they are not a new gameplay test.

Related: [Vault Vs Project](Vault-Vs-Project.md), [CSPs And Poses](CSP-And-Pose-Workflow.md).

The sidebar slides and fades when opened or closed. Rows highlight on hover, and buttons ease into their hover and pressed states. Reduced-motion preferences disable these animations.

Randall's replies show his small avatar beside the bubble tail. Only the last bubble in a consecutive sender group keeps its tail; earlier bubbles have rounded corners. Sent messages use your mode's accent color, with iMessage-style bubbles on both sides.

For the next release, temporary free Randall access will require joining sc00p's Patreon for free (paid members qualify too), rather than only signing in. This promotion starts when enabled at release.

If your linked Patreon account is not a member of sc00p's Patreon, the message box says so and offers **Join free on Patreon** and **Check again**. Choose **Join**, not just Follow, then press **Check again** to unlock Randall. Settings → Files & setup → Account shows **Free member** or **Not a member of sc00p's Patreon** under your Patreon name. **Re-link** there links the same Patreon account again without signing out; use it if Check again still shows you as not a member.

Nucleus takes a Patreon link only when it comes back within 15 minutes of starting it from Nucleus (**Link Patreon** or **Re-link**); a link it did not start is ignored and says so. Linking a different Patreon account than the one already linked asks before switching.


Chat supports ordinary emoji and hides model reasoning tags. Single website mod
previews keep a compact card width with the gallery filling the card.

## Import a character model (experimental)

Drop a downloaded model onto Randall's message bar and ask him to import it, or
start an **Import a character model** chat and, if you like, pick the fighter. A
ZIP works best: keep it intact so its textures and materials stay together.
GLB, glTF, OBJ, FBX and DAE files also work. SMD files are not read: export the
model as FBX or DAE, or attach the download it came in.

**The import's tools.** The import runs Blender and a Python of its own. They
are not part of the installer: download them once in **Settings > Files &
setup > Model import tools**. The card says what they are for, how big the
download is (about 780 MB on Windows, 840 MB on Linux and 610 MB on macOS) and
how much room they take once unpacked (about 1.5 to 2 GB), and where each file
comes from: Blender from blender.org, Python from python.org (on macOS and
Linux, the python-build-standalone project's build), and its packages from PyPI.
Every file is checked against the checksum this version of Nucleus expects
before it is unpacked. You can keep using the app while they download;
**Cancel** stops the download, and the card shows it paused, with how much has
come down: **Resume** carries on where it stopped. **Remove** deletes them
again. After an app update that needs newer
tools, the card offers **Update**. If you ask Randall for an import before they
are there, he says so, nothing is imported, and the import's card in the chat
has a **Download** button; ask again once the download has finished. The same
holds when your own AI asks for an import over MCP.

**You give it the model, Randall does the rest.** The import runs from start to
finish without asking you anything along the way, usually in a few minutes. It
loads the model, puts it on the fighter's skeleton and writes the costume. The
card in the chat shows what it is doing as it goes.

**At the end you get the costume.** It is saved to your vault as a new costume,
with its portrait. If you did not name a fighter, the import picks the one the
model fits best and Randall tells you which and why ("I put him on Ganondorf:
...").

**Want it on another fighter?** Just say it ("put it on Marth instead").
Randall imports the same model again onto that fighter and saves it as a
**second** costume. The first one stays in your vault, so you can compare them.

**Something looks wrong?** Say what, in your own words: "the legs look wrong",
"his head is too big", "he faces backwards". Randall works out the one thing to
change (which way the model faces, where its joints are, or the size of the
head, the limbs, the trunk or all of it), builds the costume again and saves it
as another costume beside the first. He tells you what he changed and asks you
to look; he has not seen the result himself. One thing at a time works best.
Textures, colours and missing pieces cannot be changed this way: to try a
different version of the model, attach that one.

**Missing textures.** Before the import starts, Randall checks that the model
brought the texture files it names (an OBJ's .mtl and its pictures, the images a
DAE or FBX points to). If some are missing, nothing is imported yet and nothing
starts: he names each for what it is (an OBJ's .mtl is its materials file, the
pictures are its textures), the import's card shows it waiting on them, and he
asks for a ZIP that holds the model with those files. You can also tell him
to go ahead without them; the costume then comes out all white.

If the import's own check of the finished costume thinks it came out wrong (not
standing upright, or in pieces), Randall passes its words on as they are instead
of calling it done, and the import card shows them too.

**When it cannot finish**, Randall says where it stopped (loading the model
file, or putting it on the fighter), why, in one plain sentence, and what you
can try: another format or an archive with the textures when the file could not
be loaded; another fighter or another download of the character when it could
not be put on the fighter. Nothing is saved then.

An import started before November 2026 may have stopped to ask you something.
It is not carried on any more: attach the model again and ask Randall to import
it.

This is an experiment, not a finished porting service. A finished costume can
still stretch a limb, fold a cape oddly or show a gap in some moves. Look at the
pictures and test it in game before you share it.

### Stage editing

Whole-model palette recolors include base material colors alongside textures. You
can ask Randall to recolor only materials or only textures; palette Reset restores
both to their analyzed values without changing alpha.

Randall can also inspect and change material colors in costume and stage working
copies: diffuse, ambient, specular, texture-blending colors, opacity and shininess.
Ask him to inspect the materials first and preview the result. Animated colors
can override base values; previewing base colors does not remove animations from
the saved mod. Saving still creates a new copy.

Randall can open a vanilla or vault stage in Stage Lab, list textures, return
rendered previews, export or replace PNG textures, recolor one texture or all
textures, adjust the camera, and control animation. The result saves itself as a
new stage variant when his reply ends (later changes in the chat update it); ask
for a separate copy to keep both. Originals and companion archive files are preserved.

Stage Lab uses the same renderer as the human Stage Creator, with a separate
working copy. Returned PNGs can be applied in the editor using **Use on selected
texture**. Image generation and stage collision editing are not part of these tools.

Randall can also transplant scenery between stages: for example, put Jungle
Japes' forest behind Final Destination. He inspects both stages, renders the
selected objects to identify the background, copies them into the destination,
and can move, rotate, scale or hide scenery before saving a new variant. The
original stages stay intact. This preserves the destination's collision and
stage logic; it does not copy donor hazards or scripted effects. Some animation
types cannot be transferred, and the saved variant still needs in-game testing.

## Your own AI (MCP)

Settings > AI > **Connect your own AI (MCP)** lets Claude Code, Claude Desktop or Codex use Randall's
tools. Your AI app asks you before each tool call. A few things are also asked in the Nucleus window, and only
your answer there counts: connecting a **creation toolkit** folder (Nucleus then runs the Python in that folder)
shows "Connect a creation toolkit?" with the folder; choose **Allow** only for a Nucleus checkout you set up
yourself. Your AI cannot open files on a network share (`\server\share`), and in-game tests always use the
Slippi Dolphin set in Settings.

Porting fighters from other games and building custom stages (`native_port`, `stage_workbench`) are not part of
the installer: they run in the creation toolkit, a copy of Nucleus's source you set up once. Settings > AI >
**Creation toolkit** opens its setup guide, or ask your AI to set it up.

While your AI imports a character model, the top of the Nucleus window shows it: "Your AI is importing
*model* as *fighter*", with the step it is on and a **Cancel** button. Cancel stops the import and nothing is
saved; the note says so for a moment and then goes. Your AI can stop it the same way (its `cancel_import`
tool), for example when you tell it to. An import that already saved its costume stays saved. When an import
finishes, its costume shows in the Vault straight away, with no reload.
