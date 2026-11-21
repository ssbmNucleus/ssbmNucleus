# Model import: the record plan (draft for the owner's OK, 2026-11-09)

Status (2026-11-09, evening): **steps A to D are coded, checked once each and committed**, on rigswap branch `rec`
(`6a14b23`, `fce630e`, `0a4d275`; off core `6974c04`) and on app branch `import-record` (`9c181c43a`, worktree
`ssbmNucleus-import-record`). **Both were merged locally the same evening on the owner's word**: rigswap `rec` into
`core` (`770029f`), the app's `import-record` into `main` (`c7fa16dbc`). Nothing is pushed, built into an installer
or uploaded, and the installer's rigswap pin (`app/utility/rigswap.manifest.json`) is not moved: it must be before
the next installer build, or a packaged app cannot make a change. Step E's result is in the table.

| Step | State | The one check, and what it showed |
|---|---|---|
| A, the record | committed | `seam-1`: 20 of 20 scope swaps the same as core on every stage. `seam-2`/`seam-3`: rebuilt from the written records, same file and mesh. |
| B, the fill | committed | `fill-0` (core) beside `fill-1` (the look fills the body), 17 downloads: of the 15 that can be compared, the look's build is right where core's is a wreck on 4 (Andromon, Daisy, Rabbids Mario, Richard) and the same on 11; none is worse. One fails at export in both (a material with no picture source), one was not compared. Sheets: `rigswap-core/work/rec/b-1.png` to `b-4.png`. |
| C, the tripwire | committed | On builds already on disk: 14 of 14 wrecks alarmed, 0 of 34 fine ones. In `fill-1` it ran on 13 builds and alarmed on none (all 13 stand). |
| D, a complaint | committed (both repos) | Six complaints on real builds with the change expected written first: 6 of 6 named it once the question said the person's word stands (5 of 6 before). Three rebuilt, the change shows (`d-1.png`). A staged misread (a leg read one joint short) was put right by "his left leg looks wrong": the rebuild is the same file and mesh as before the misread (`d-2.png`). About 0.1 to 0.2 cents a complaint. |
| E, the fit test | **run once, did not work, code taken out** | `fit-1`: Swampert and Machoke matched to the fighter as its idle has it, then bound back to its rest. Machoke came out worse (chest swollen over the head, tears in the run), Swampert no better (head on a stretched neck). Pictures `fit-machoke.png`, `fit-swampert.png`; the code is kept in `rigswap-core/work/rec/fit-test/`, not on the branch. |
| D, in the app | merged, **run once for real** (2026-11-09) | One real import and two corrections through the app's own chat route (real chat model, real rigswap, the dev vault; `app/scratch/import-record/real_chain.py`, chat `aae64f1a…`, project `bart-15caa6`). The import worked first time: Bart, no fighter named, put on Ness with the reason said, 131 s, 1.5 cents. "His head is too big": Randall called `import_model(project, change)` and reported a smaller head, but the costume was the same file. Two faults, both fixed and merged (rigswap `a3bdf2b`, core `bb619d9`): a head placed by its neck (a model with no neck) ignored the record's head size, and a change that rebuilt the same file was handed on as a second costume; it is now a failure said plainly. Said again after the fix, the head came out at 0.6 and "Bart 3" was saved (`real-bart.png`). Seen of the chat model: it rewrote the user's words and added a size of its own ("around 0.6"), and it spoke of the portrait. The first is fixed in structure, not wording (rigswap `75386e2`, core `9a37e65`, app `1c047d0c5`): the app sends the user's own newest message as the complaint and the chat model's wording beside it, which the look uses only for which part is meant; a size says which way, and how much only when the user named an amount, else code takes one step (0.8 or 1.25). Run once more for real: to "Now his head is too small." Randall wrote "around 0.7 of the original", the import read the user's words and went 0.6 to 0.75. The chat model still talks in numbers of its own to the user; that part is wording and is not fixed. The test costumes were removed from the dev vault. |

**Five more models, 2026-11-09 night** (the app's chat route, no fighter named; then each saved costume run in the real
game with `shared/ingame/verify_costume.py`; sheets `app/scratch/import-record/five-in-game.png` and
`five-renders.png`): Spider-Man on C. Falcon, Crash on Mario, Lucario on Mewtwo and Dark Magician on Ganondorf
came out standing and whole first time (63 to 151 s, 1.3 to 2.7 cents each); Crash only after the import's own
check threw out its first body and the second model's stood. All five boot and play. What is wrong with them:
Lucario's head tassels stick straight out behind him, Dark Magician's robe breaks into flat panels when he runs,
and the fifth, a cartoon ferret, was put on Pikachu, where he sits on the floor. The import's check said so both
times; a complaint moved his hips joint and changed nothing, because the fault was the fighter; on Yoshi, asked
for by name, he stands. Two things seen there that are not fixed: the pick chose a fighter whose own stance is a
squat, and Randall, looking at the portrait, told the user the ferret was "in that same seated pose on Yoshi too"
and that the pose was "baked into the model file", which is untrue (the check passed and he stands).
A sixth, Goku (`goku-budokai`, a posed statue with no skeleton, asked for by the owner): put on C. Falcon with his
upper arms detached at the shoulders. The import's check said so on both tries and Randall passed it on; "his arms
are detached at the shoulders" came back as thinner limbs and changed nothing that mattered. Core's own reading
mangles him the same way (`seam-1`, on Mario), so this is the old fault of that kind of file, not a new one, and
nothing in the record can put it right (`goku-in-game.png`). Of the five above, Spider-Man (on this same
fighter) and Lucario are in rigswap's standing scope set, so they are not fresh evidence for the body; Crash,
Dark Magician and the ferret are outside it.
Cloth, as the export's own readback says for Dark Magician on Ganondorf: his two hair strands are m-ex accessories
with the game's dynamics (they swing); the robe is not. A gown is laid on the fighter's own skirt bones where the
game swings a skirt (Peach, Zelda) and on the two legs where it does not (`cloth.py`), and Ganondorf's game
swings a cape, so the robe's front and rear panels follow his legs: the flat slabs in his run.
Also found, and fixed the same night on the owner's word: the rigswap loop's own Dolphin pass had failed for every
batch since 2026-11-03, so none of this plan's queue batches has in-game frames; their checks were made on renders
posed with the fighter's frames. Two causes, both from that day's app changes, both in `randall-runs/rigswap-ingame`
(not a git repo; the files as they were are kept as `*.bak-2026-11-09`): `ingame_batch.py` forbade rebuilding the
pristine m-ex base, which is keyed to the MexCLI build and so went stale when the pin moved (guard removed: the
backend rebuilds it under its own lock, 26 s); and `frameshot_driver.py` hooked `MoveRunner._execute`, which the
app had folded into `execute` (it now hooks whichever exists). Proof: pass `app-4`, 5 of 5 costumes shot in 99 s
on the desktop and the laptop (`app/scratch/import-record/five-loop-pass.png`).

Known gaps: the chain has run through the app's chat route but not in the app's window (the cards and the vault list
were not looked at); only a head size was corrected for real, joints only through the queue. One queue worker
(`desktop-build-5`) was started by my `fill-0` command with `RIGSWAP_TRIPWIRE=0` in its environment and keeps it
until it is restarted: builds of `rec` code that land on it skip the tripwire (core has none, so core runs are not
affected).

Step A's check: scope batch `seam-1`, 20 of 20 built, every swap the same as core's last scope run (`hd-scope-2`) on
every stage, the exported file and the built mesh included. `seam-2` rebuilt Gardevoir, Kamek and Cammy from the
records `seam-1` wrote: the same exported file and mesh for all three. One gap showed: Kamek's rebuild asked one
question again, live, because a rebuild skipped drawing a picture that question shows first; fixed in code, not yet
rerun. Still outside the record: which files of a several-file model are worn, which loose objects hang where, and
which contacts of a rip in pieces are real. A rebuild takes those from the cached answers. Written after a review of every importer attempt since June and three one-shot tests run the same day.

Step A so far: every run writes `<out>/record.json` and the build reads the body, its joints, the chains' names, the
digits and the props' kinds back from that file; a run whose load has a `record.json` beside it takes that one and
skips what it covers. 351 unit tests pass. A no-build check (`rigswap-core/work/rec/check_seam.py`) reads each
scope model, writes the record, reads it back and compares: the same on all 10 it can cover (the other 10 are made
from pieces or several files at run time). The real check, the scope run, waits on the owner's OK.

## The goal
Drag in a character model and get a Melee costume the fighter's own animations drive. One shot. If something is
wrong, the user says so in chat ("the legs look wrong") and the import goes back and fixes that.

## Why another change, and why this one is not attempt ten
Every attempt so far tried to be right without looking at its own result, and stored what it learned about each
model in shared code. Models never stop being new, so that never converges: this is the rule cancer. The Pokémon
hand ports worked because something with eyes looked at the draft and the fix stayed with that one mon.

So the per-model knowledge moves out of the code into a small **record** per import:
- which of the model's joints is each joint of a body, which way it faces, what kind of body it is;
- what each extra part is (hair, cloth, tail, prop) and what is dropped;
- a few sizes: overall, head, limb width, trunk width, tail.

The middle of rigswap then builds **only from the record**. Something that can see fills the record, and anything
that can see (a second look, the user) can correct it.

This is not a rewrite. Loading, the Melee plugin (export, props and weapon slots, eyes and blink, physics, the
fighter-specific handling), the texture steps and the geometry all stay. What changes is who decides what the body
is.

## What the three tests showed
All in `rigswap-core/work/rec/`. Each ran once.

1. **Is a record enough?** (`rec-1`: five Pokémon built from records written by hand, compared with the corrected
   ports.) Combusken and Sceptile came out much closer: their faults were misreads and limb width. Machoke and
   Swampert barely changed: their joints were already read right, and what is wrong is how a bulky body is fitted.
   Quilava's misread was fixed, then the build crashed on its collapsed flame meshes.
2. **Can one look fill it?** (Five mons, four models, three tries, scored against the hand records.) Sonnet got all
   five right. Gemini 3.7 Flash was right or one joint off on every key joint, at about 1 cent a fill. GLM 5.3
   Flash, today's model, was the weakest and changed a third of its answers between tries. Left and right came back
   swapped 3 times in 60.
3. **Can a look judge the draft?** (22 drafts, corrected ports and known-bad builds, unlabeled.) Every model caught
   the wrecked draft. No model's "good" verdict could be trusted: the strict ones never say good, the lenient ones
   passed bad drafts. The stronger models did name specific faults ("head too big").

## The design in five parts

### 1. The record is the middle's only input (rigswap)
- One `record.json` per import, with a version and, per entry, who said it (reading, look, user).
- The build is a function of the load and the record. After the record is complete, nothing in the body path asks
  an AI or reads the body again.
- Today's reading (twins, trunk, limbs, the label and fork asks) becomes the **first guess** that writes a record.
  It is frozen: no new clauses go into it.
- A rebuild from an edited record reuses everything cached. Target: under a minute.
- The record gains what `rec-1` showed missing: a tail size, and "drop this mesh" for junk such as collapsed effects.
- The build must not crash on junk geometry (Quilava): a collapsed mesh is dropped, not measured.

### 2. One look fills the record
- One call per import: the model in its colours from four sides, two sides with every joint numbered, a joint
  table. The answer is the record's meaning: joints, facing, body plan, what each part is, what to drop.
- Code does what code is sure of: left and right come from positions, never from the answer; a limb's joints must
  lie in order on one chain. An answer that fails those is asked once more with a close-up, then marked unsure.
- An unsure entry is said to the user in plain words, as decided 2026-10-08: finish the import and say which limb
  may be wrong.
- The model is one config line. Start with Gemini 3.7 Flash. The lab (`lab_ask.py`, `lab_score.py`) is the test for
  changing it, and takes minutes.
- Sizes start from what the hand ports did: the head at the body's scale. Limb width has no rule, so it starts as
  today and is mostly set by corrections.

### 3. A tripwire, not a judge
- After the build, the draft is posed in two real frames (the posing code exists, no Dolphin) and one cheap look
  answers two things only: is it upright, is every part attached.
- On an alarm: one more fill with a stronger model, one rebuild. If the alarm stands, the import finishes and says
  plainly that it probably failed.
- There is no loop "until it looks good". The tests showed no model can be trusted to say that.

### 4. "The legs look wrong" (the app)
- `import_model` keeps the record with the import and returns it.
- A complaint goes back through the same tool with the import named. A look gets the source, the draft and the
  user's words, and answers with one change to the record. The import rebuilds and the reply says what changed.
- Plain size requests ("make the head smaller") change a size directly, no look.
- The chat's prompt, the tool's schema and the result card are brought in line. The prompt still describes the
  importer that was removed, and the cards for it are still in the frontend.

### 5. Bulky and hunched bodies (separate, and after a test)
- A record cannot fix Swampert or Machoke. The hand ports fixed them by fitting at the fighter's idle, not its rest
  pose. That is a guess about the cause, not a finding.
- One test first: rebuild those two from the records that exist with that one change, and compare with the
  corrected ports. It goes in only if it visibly works.
- **Result (2026-11-09, `fit-1`): it did not, and it is not in.** What reading the two hand scripts showed
  afterwards (`swampert_v2_hand.py`, `hand_machoke.py`): they did place parts at the fighter's idle and bind them
  back, but what they chiefly did is keep the head, hands, feet and trunk at the mon's own shape, one scale for the
  whole body, where the fit stretches each bone to the fighter's length ("the fit squeezed the head to 4.6 wide, 6.8
  tall and 3.1 deep"). The test changed only where the fit happens and left that stretch as it is. So the open
  question for bulky bodies is the stretch, not the pose. That is a new guess, untested, and by this plan's own rule
  it gets one test of its own or none. Until then a bulky body stays as core makes it, and the user's levers are the
  record's sizes ("make his chest less wide").

## The rule that keeps this from looping
Shared code changes for two reasons only: a fact about the game, or a fault that still shows when the record is
correct. A wrong import is otherwise fixed in its record. If the look filled the record wrong, that is a question
about the model or the picture, and the lab answers it; it is never a new clause in the reading.

## Order, and what is looked at after each step
Each step ends in one thing to look at, once.

| Step | What is built | The check |
|---|---|---|
| A | The record seam: the reading writes a record, the build reads only it, rebuild from an edited record | The 20 scope swaps come out the same as core today |
| B | The fill, sides from positions, the order check | A batch of about 20 ordinary downloads never seen before, beside the same batch from core today |
| C | The tripwire | Known wrecks and known-good builds already on disk: it alarms on the wrecks only |
| D | The app side: record kept, the complaint path, prompt, schema and cards | In the dev app: import one model, say "the head is too big", see it change |
| E | The fit test for bulky bodies | Swampert and Machoke beside their corrected ports |

A is the largest piece. B and C are small: most of their code exists from the tests. D is medium. E is independent
and can run any time after A. An installer build happens only when the owner says "build".

## Cost and time per import (estimates from the tests)
- Fill: about 1 cent. Tripwire: about 0.1 cent. The texture and eye asks stay as they are.
- Roughly 1.5 cents an import against about 0.35 today, under the 5-cent free pot.
- A correction is one look by a stronger model: unmeasured, expected to be a few cents.
- Time: today's build (35 to 55 seconds) plus about 20 seconds for the fill and 10 for the tripwire.

## What is not known
- The fill was tested on five Colosseum mons that the reading had misread. Ordinary downloads are untested: a rip
  with 300 bones may not fit one readable picture, and a mesh with no skeleton takes its joints from the fitted
  skeleton. Step B is where that shows.
- Whether a look can turn a complaint into the right record change. The draft test only showed that the stronger
  models name faults.
- The wreck alarm rests on one wrecked draft.
- Bulky bodies stay wrong: step E's test did not work (above).
- Answered since: ordinary downloads (step B, 17 of them) and whether a look can turn a complaint into the right
  change (step D, 7 complaints). Both rest on one small batch each.

## Decisions for the owner
1. Gemini 3.7 Flash for the fill, at about a cent an import, in place of GLM for the body questions. (Built that
   way on `rec`; GPT-6 Luna is the second model when Gemini's answer cannot be used.)
2. A stronger, pricier model for the rare calls: the re-fill after an alarm, and a user's complaint. (Built with
   GPT-6 Luna for both and for the tripwire; a complaint cost 0.1 to 0.2 cents.)
3. Merging rigswap `rec` into core, and the app's `import-record` into main: done locally 2026-11-09 on the owner's
   word. Still his: pushing either, and moving the installer's rigswap pin before a build.
4. Whether bulky bodies get one more test (the stretch), or stay as they are for now.

## Where things are
- Test branch: the rigswap worktree `.claude/worktrees/rec` (`core/record.py` and about 115 changed lines).
- Runs, tools, pictures and scores: `rigswap-core/work/rec/` (`lab/` is the fill test, `lab2/` the draft test),
  `rigswap-core/runs/rec-1`.
