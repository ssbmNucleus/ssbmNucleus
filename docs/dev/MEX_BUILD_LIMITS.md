# m-ex Build Limits (empirical)

> **Roster follow-up (2026-10-14):** current pinned tools retain a separate
> 64-slot effect table (including reserved slot 30), with content deduplication
> and explicit overflow refusal. Controlled 46-, 54-, 64- and 65-entry builds
> entered offline CSS; this does not establish a universal character-count
> limit or arbitrary-roster safety. The reported Slippi desync risk above 63
> total fighter entries is a separate online concern.

> **Note (2026-08-22):** the one-off probe scripts this doc references (`count_*.py`, `stress_probe.py`, `das_ladder.py`, `das_probe.py`, `das_test_setup.py`, `csp_sweep.py`, `fps_check.py`, `css_cycle_probe.py`) were removed from `backend/` in the cleanup pass; recover them from git history if the methodology needs re-running. `stress_build.py` and `fps_batch.py` remain.

How many costumes / DAS variants an m-ex build can hold before the game breaks,
and **why**. Every number here was confirmed **in-game** (Slippi Dolphin) via the
`backend/shared/ingame` solo engine + RAM/FPS probes, June 2026. Test tooling lives in
`backend/devtools/stress_build.py` and `backend/devtools/fps_batch.py` (the rest
were one-off probes; see the note above).

## TL;DR

| Thing | Limit | What happens past it | Mode |
|---|---|---|---|
| Costumes **per character** | **255** | count byte wraps → all costumes collapse to costume 0 | silent, no crash |
| **Total** costumes (whole build) | **CSP-memory bound, not a fixed count**: console/local uses the offline VS CSS number (~1150); Dolphin/Slippi uses the online CSS number (healthy through 1500 so far) | CSS **freezes** when CSP texture RAM overflows the heap | mitigated by CSP compression (auto) |
| Disc size (real hardware only) | **1,459,978,240 B** (1392.3 MiB) | won't boot on console / SD; **Dolphin runs over-disc fine** | hardware-only |
| Total ISO size | **~4 GiB** (2³²) | ISO won't boot at all | hard |
| DAS variants **per stage** | random pool; **no count cap** (healthy to 2048/stage) | only disc / the 4 GiB-ISO limit bounds it | — |

**The single most important rule: the total-costume limit is a CSS texture-MEMORY
budget, not a fixed count — and CSP compression is the lever.** The CSS loads a CSP
portrait for *every* costume; it freezes when that texture memory `≈ (128+total)·r²`
(r = CSP compression ratio; CSP sized 136r×188r) overflows the heap left for it
(which itself shrinks as the costume tables grow). So the max count depends on r:
**~510 with no compression (r=1.0); with the app's automatic CSP compression,
offline VS CSS is still pinned at ~1150 and the Slippi online CSS is healthy
through 1500 so far** (`core.helpers.calculate_auto_compression`, which scales r
down as you add costumes — and the app applies it for you on export). Disc size and
HD-texture mode do not change this.

> **Correction — this supersedes earlier versions of this doc.** A prior version
> claimed a hard count cap of **511/512 (0x200)**. That was WRONG — an artifact of
> testing at CSP compression **1.0** (no compression): with full-size CSPs the CSS
> texture RAM overflows near ~510 costumes (≈510 for *both* duplicate and distinct
> costumes, because each costume loads its own CSP — the "0x200" was a coincidence,
> not a table). Re-tested WITH the app's auto CSP-compression, **512 and 513 costumes
> are healthy (60 fps)** and the ceiling is far higher. The current split is
> console/local offline VS CSS ~1150 and Dolphin/Slippi online CSS healthy through
> 1500 so far. (An even earlier
> version blamed *disc size*; also wrong — Dolphin runs over-disc fine.)

---

## 1. Costumes per character → hard cap **255**

The on-disk costume count is a single unsigned byte (`MEX_CostumeIDs.CostumeCount`,
`MEX_CostumeRuntimePointers.CostumeCount`). The **effective** count the game uses is:

```
effective_count = total_costumes & 0xFF
```

Verified by building Fox to 255 / 256 / 260 costumes and reading the runtime costume
id (`fighter struct + 0x619`) in a live match:

| Built | Effective | In-game result |
|---|---|---|
| ≤ 255 | = built | every costume loads as itself (incl. ids 63, 64, 254); CSS X-cycler reaches all 255 and wraps at the count |
| 256 | **0** | every costume collapses to costume 0 (255 unreachable) |
| 260 | **4** | only ids 0–3 work; 4+ clamp to 0 |

Key properties:
- **It never crashes.** An out-of-range costume id clamps to costume 0 (vanilla
  "Limit Costume ID" behaviour). Out-of-range *character* ids likewise clamp to
  Mario.
- **The 6-bit `PlayerStandings.costume` field does NOT limit gameplay.** Costume 64
  loads correctly as 64 in-match; that 6-bit field only affects the post-match
  results screen.
- **The overflow is silent on the build side.** `mexcli import-costume` reports the
  true `int` count (256, 260, …) but serializes the wrapped byte — no error or
  warning. So a character with >255 costumes builds "successfully" but is broken.

## 2. Total costumes → a CSS texture-MEMORY budget (CSP compression is the lever)

There is **no fixed total-costume count cap.** The character-select screen loads a
CSP portrait for *every* costume and **freezes** (CSS scene loads, hand cursor even
comes alive, then the global frame counter `0x80479D60` stops forever) when the CSP
texture memory overflows the heap. That memory scales as **`(128 + total) · r²`**
(each CSP is sized `136r × 188r`; r = CSP-compression ratio), while the heap left for
it *shrinks* as the costume tables grow. So the max number of costumes is set by
**r**, not a magic number — and the app auto-picks r to stay safe
(`core.helpers.calculate_auto_compression`).

**Measured in-game** (ISOs all 1392 MiB unless noted, so disc size is out of it):

| Build | CSP compression r | CSS |
|---|---|---|
| 511 total, **duplicate** costumes | **1.0 (none)** | healthy; 512 hung |
| 509–513 total, **distinct** costumes | **1.0 (none)** | **all hung** (wall ≤ 509) |
| 509–513 total, **distinct** costumes | **~0.39** (app auto for +378) | **all healthy — incl. 512 & 513** |
| 1000 total, distinct, online CSS | auto (0.163) | healthy, 59.9 fps |
| 1100 total, distinct, online CSS | auto (0.121) | healthy, 59.9 fps |
| 1150 total, distinct, online CSS | auto (0.1 floor) | healthy, 59.9 fps |
| 1200 total, distinct, online CSS | auto (0.1 floor) | healthy, 59.4 fps |
| 1300 total, distinct, online CSS | auto (0.1 floor) | healthy, 59.9 fps |
| 1400 total, distinct, online CSS | auto (0.1 floor) | healthy, 59.9 fps |
| 1500 total, distinct, online CSS | auto (0.1 floor) | healthy, 59.1 fps |

Capacity should be tracked by CSS mode:
- **Console / local play:** use the offline VS CSS result.
- **Dolphin / Slippi netplay:** use the online CSS result, because the Slippi
  online character-select/matchmaking screen loads more memory.

`backend/devtools/fps_batch.py` now supports `--mode offline`, `--mode online`, and
`--mode both` so the same count ladder can pin the console and Dolphin numbers
side by side. The online probe enters the unranked CSS only long enough to load
CSPs and watch the frame counter, then holds B to leave before matchmaking.

The two uncompressed (r=1.0) rows show the wall sits at **~510 regardless of
count-vs-content** (duplicate ≈511, distinct ≈509) — because each costume loads its
own full-size CSP, so it is a **memory** wall, not a count cap. Dropping r to the
app's auto value (~0.39) makes **512 and 513 healthy**, proving there is no 512-slot
table. The old formula expectation that the r=0.1 floor would fail around ~1150 is
too conservative for the Slippi online CSS: that path is healthy through 1500 total
costumes so far, and the ceiling has not been found yet.

> `calculate_auto_compression(added)` is the team's empirically-derived safety curve
> from low/mid-count **online** CSS crash tests: it keeps a 15% margin below
> `(128+added)·r² ≳ 135 − 0.12·added` until it reaches the 0.1 floor (~1000+).
> The 1500-costume online ladder shows that high-count linear extrapolation was
> conservative after the floor. Quick Export and the install page apply it
> automatically, which is why a normally-built mod does **not** hit the ~510
> uncompressed wall.

What it is **not**:
- **Not a fixed count / 0x200 table.** 512 and 513 costumes run fine once CSPs are
  compressed; a table cap would hang them regardless of r. (The earlier "511/512"
  conclusion was the r=1.0 memory wall, mis-read as a count cap — 512 was coincidence.)
- **Not the disc size.** Every ISO above is the same size; the behaviour tracks r.
  (Disc size is a separate, hardware-only limit — below.)
- **Not a MexManager / serializer limit.** `MexCharacterSelect.ApplyCompression`
  iterates *all* costumes with no cap; per-fighter counts are bytes (§1).

### Disc size is a *separate, secondary* limit (real hardware only)
A GameCube disc holds **1,459,978,240 bytes (1392.3 MiB)**. A build over that
**won't boot on a real console / SD-card setup**, but **Dolphin runs it fine** (the
52-variant +25 MiB build booted normally). So for a Dolphin-only audience the disc
size is *not* a hard limit; for hardware builds it is. The two limits are
independent — you can be under the costume ceiling and over disc, or vice-versa.

### The real lever for disc space: shrink video (frees most of ~810 MB)
Vanilla content you can cut to make room **on the disc** (measured on
`test-base/files`):

| Category | Size | Notes |
|---|---|---|
| **Video** (`Mv*.mth`) | **811 MiB** | cutscenes/movies — `MvOmake15.mth` alone is 466 MB |
| **Trophies** (`Ty*`) | **84 MiB** | trophy gallery data — **NOT safely strippable** (MexManager's TrophyLoader reads them at project-open; deleting breaks the workspace) |
| Audio (`*.ssm/.sem/.hps`) | 255 MiB | replaceable but needed for sound |
| Costumes (`Pl*`) | 110 MiB | vanilla + added |
| Stages (`Gr*`) | 52 MiB | |

**The videos are not safely deletable either.** The game opens every `Mv*.mth` by
name with no missing-file check: a build without them crashes after the credits of
every Classic/Adventure/All-Star clear (`MvEnd<char>.mth`), when the title screen
idles into its attract loop or you open Data → Movies (`MvOpen.mth`,
`MvHowto.mth`), and in the 15-minute special (`MvOmake15.mth`). This was Nucleus's
"Free space" behaviour through 0.8.10 and it silently broke single-player on every
build that used it (Tracker #92).

As of 0.8.11, **"Free space" replaces each vanilla movie with a short, valid stub
cut from its own opening frames** instead of deleting it (`backend/core/movie_stubs.py`).
Every scene that plays a movie still works — it just plays for about a second
instead of the full runtime. `MvOpen.mth` (the title attract loop) gets a longer,
low-detail black stub instead, because its scene can't finish once its playback
timer stalls out on a short movie. Only the 28 known vanilla movie file names are
ever touched — never an added fighter's own `MvEnd<Name>.mth`. Projects a
pre-0.8.11 build already stripped are repaired automatically (stub regenerated
from your recorded vanilla ISO) the next time you run Free space or export.

Net gain is a little under the old ~810 MiB — measured on a real vanilla+m-ex ISO,
stubbing all 28 movies frees **791 MiB** (811 MiB down to 20 MiB of stubs; the 25
`MvEnd*.mth` stubs run 300–700 KiB apiece, `MvOpen.mth`'s long black stub is
~5.8 MiB). This **only helps the disc-size (hardware) axis. It does NOT raise the
costume limit** (that's the CSP-memory budget above, set by CSP compression — not by
disc space). The "Free space" tool in the install header does this for every
vanilla movie present.

## 3. DAS variants per stage → **random pool; NO count cap**

Earlier static analysis wrongly concluded 7 (1 default + 6 buttons). Confirmed
in-game that **no button held = a RANDOM pick from the entire variant folder** —
three no-button Dreamland boots returned three *different* skins. The six buttons
(B/X/Y/L/R/Z) are deterministic shortcuts to specific files; everything else is
reachable via the random default.

DAS variants are **stage files** (`GrXX/<name>.dat`) read by the DynamicAlternate-
Stages loader — a different subsystem from the costumes in §2, and DAS variants have
no CSPs, so the **CSP-memory limit does NOT apply.** Pinned with a count-ladder on Dream Land (`das_ladder.py` →
`das_probe.py`, which boots each build and drives a no-button random pick into a
real match):

| Variants on one stage | ISO | Loaded into match? |
|---|---|---|
| 64 / 256 / 512 / 768 | ≤ 1392 MiB | ✅ healthy |
| 1024 | 1461 MiB (+69 over disc) | ✅ healthy |
| **2048** | **2360 MiB (+968 over disc)** | ✅ **healthy** |
| 4096 | 4168 MiB | ❌ ISO won't boot — see below |

So a single stage holds **at least 2048 alternates** with no hang — far past any
practical need. There is **no DAS count cap** in the range a build can physically
reach. (At ~900 KB/variant the disc/ISO size limit below bites long before any
hypothetical count limit.)

### Bonus: Dolphin's over-disc tolerance and the **4 GiB ISO wall**
- Dolphin runs an ISO **well over** the GameCube disc size: the +968 MiB
  (2360 MiB) DAS build booted and played fine. (Real hardware / SD still needs
  ≤ disc — §2.)
- The 4096-variant build (**4168 MiB**) **failed to boot** (never reached the menu).
  4168 MiB > **4096 MiB = 4 GiB = 2³²**, so the ISO overflows the GameCube image
  format's **32-bit byte offsets** — a hard **~4 GiB ceiling on total ISO size**,
  independent of disc size and of DAS/costume counts. This is the ultimate size
  wall: a build cannot exceed ~4 GiB regardless of how you fill it.

## 4. "HD texture" / texture-pack mode → does NOT relieve the CSP-memory limit

Texture-pack mode (`backend/projects/install/texture_pack.py`, `export.py` `texturePackMode`) replaces
**CSP portraits** with tiny placeholders in the ISO and serves the real/HD CSPs from
Dolphin's texture-pack Load folder at runtime. It is **CSP-only — it does not shrink
costume model `.dat` files**, and the CSP is only ~5% of a costume's ISO cost
(~25 KB of ~497 KiB), so it shaves ~5% off **disc size** (the §2 disc/hardware axis).

It does **not** help the §2 CSP-texture-MEMORY limit: the CSS still loads a CSP per
costume at runtime (the placeholder is swapped for the Load-folder texture), so the
texture RAM is unchanged — or larger, if the HD replacement is bigger. **CSP
*compression* (shrinking the actual CSP the CSS loads) is the lever for the memory
limit — not texture-pack mode.**

## 5. Capacity model (for the build-size indicator)

The install-page indicator (`frontend/src/projects/DiscUsageIndicator.jsx`) shows **two
independent axes**:

```
# PRIMARY — costume count vs the CSP-MEMORY ceiling (what hangs the CSS):
total = Σ fighter.costumeCount
r     = CSP compression used on export; the app auto-picks
        calculate_auto_compression(total - 128), scaling 1.0 -> ~0.1 as count grows
# Low/mid-count fit: CSS freezes when CSP RAM overflows:
#   (128 + total) * r^2  >  ~(135 - 0.12*(total-128))
#   with AUTO r  -> offline pinned around 1150; online healthy through 1500 so far
#   with r = 1.0 (no compression) -> walls at only ~510
CONSOLE_COSTUME_HANG  ~= 1150  # offline VS CSS ceiling with auto-compression
DOLPHIN_COSTUME_HANG  ~= 1500  # online CSS tested-safe floor; ceiling not found
COSTUME_SAFE          ~= 1000  # warn approaching either ceiling

# SECONDARY — disc size, two thresholds:
CONSOLE_DISC  = 1_459_978_240 bytes             # real hardware / SD; over => won't boot on console
DOLPHIN_LIMIT = 4 GiB (2^32 = 4_294_967_296)    # ISO-format wall; over => won't boot ANYWHERE
used          = size(project/files/)
```

The indicator shows console + Dolphin disc bars and caps each "more costumes"
estimate with the matching CSS-memory ceiling: offline VS CSS for console/local
play, online CSS for Dolphin/Slippi. The costume ceiling **depends on the CSP
compression used**: the app applies auto-compression, so a normal build is safe
to the currently pinned value for each use case; an *uncompressed* (r=1.0) export walls at ~510.
Disc-space tools (strip video) move only the secondary axis.

## Bonus findings
- **Install speed:** every `mexcli import-costume` re-runs the full
  `MexWorkspace.Save()` (regenerates MxDt / PlCo / IfAll / MnSlChr / codes.gct / …),
  so N costumes = N full recompiles (~3–5 s each, almost all redundant). A batch
  command (open once → add N → Save once) — drafted at
  `<ssbmNucleus-mex>/MexCLI/Commands/ImportCostumesCommand.cs` (untested) — should be
  ~5× faster.
- **CSP color-smash quirk:** color-smash only runs when `csp-compression < 1.0`
  (`ExportCommand.cs:97` gate), so enabling color-smash at the default `1.0` silently
  skips it.
- **mexcli needs absolute project paths** (relative → `Invalid URI` crash).

## Single-player per-fighter data (0.8.11)
Classic / Adventure / All-Star read a few per-fighter entries from MxDt that
neither the game nor m-ex checks; a blank or missing one is a hard crash.
MexCLI now guards them on every workspace `Save()` (so on every export) —
`mexLib/Types/MexFighterSinglePlayer.cs`, called from `MexFighter.ToMxDt`:
- **ViWait symbol** (`files.demoWait`, e.g. `ftDemoViWaitMotionFileWolf`). The
  old `add-fighter` blanked it for every added fighter (it was read from the zip
  as if it were a file), and m-ex asserts `fighter N has no symbol` at the
  Adventure Brinstar cutscene (vi0401; later vi cutscenes too). Install keeps it
  now, and a blank one is refilled from the `ftDemoViWaitMotionFile*` root that
  exists in the fighter's own `demoFile` archive (a clone's is its donor's).
  This is written back to the fighter JSON; a set value is never touched.
- **Ending movie + congratulations images** (`media.endMovieFile`,
  `endClassicFile` / `endAdventureFile` / `endAllStarFile`). The movie plays
  right after the credits, the image on the congratulations screen; a blank or
  missing file crashes there (`devcom.c` / `file isn't exist`). For every
  playable slot, a name whose file isn't in `files/` is compiled into MxDt as
  the donor's (same `fighterDataSymbol`), else Mario's, else any fighter's
  existing file. Build-time only: the project's media fields and files are left
  as they are. `fighter.yml` packages often ship no ending media.
- Not guarded: a missing `demoFile` (DViWait archive) itself, `rstAnimFile`, and
  the standalone `ftDemoIntro/Ending<X>.dat` files (their absence only makes the
  fighter T-pose/vanish in the Classic intro and trophy fall).

## Methodology / reproducing

> The one-off probe scripts named below without a folder (`count_*.py`, `csp_sweep.py`, `fps_check.py`, `stress_probe.py`, `css_cycle_probe.py`, `das_*.py`) were removed from `app/backend/` in commit `60e616a59` and live in git history; `devtools/stress_build.py` and `devtools/fps_batch.py` are the maintained tools.
- Base = copy `storage/test-base` (a ready extracted project); import costumes via
  `mexcli`; export. No vanilla ISO needed.
- `backend/devtools/stress_build.py` — build N costumes on one char or a roster
  (`--characters`, `--distinct`), with `--strip video` and compression options.
- `count_bisect.py` / `count_narrow.py` — ladder of ISOs at given
  **total** counts, **csp=1.0** (no compression), video stripped. Found the ~510
  uncompressed wall (originally mis-read as a 511/512 count cap).
- `count_xcheck.py` — same but DISTINCT costumes / different roster (showed
  the wall is composition-near-independent at r=1.0).
- `count_compressed.py` — distinct costumes exported WITH auto CSP-compression
  (the realistic case): 512/513 healthy → **no count cap**.
- `count_compressed_high.py` — distinct + auto-compression high-count
  ladders. The online CSS ladder is healthy through 1500 so far; continue above
  that to find the hang point. `csp_sweep.py` — one count, many r levels.
- `backend/devtools/fps_batch.py` — boot a list of ISOs in sequence and score each
  HEALTHY / DEGRADED / HUNG by the CSS frame rate. Use `--mode offline` for the
  console/local-play number, `--mode online` for the Dolphin/Slippi number, or
  `--mode both` to compare both for the same ladder. `fps_check.py` is
  the single-ISO offline version.
- `stress_probe.py` — boot an ISO, memory-select a solo match as
  `(ckind,color)`, read the runtime costume id (`ft+0x619`).
- `css_cycle_probe.py` — count CSS-selectable costumes via the X-cycler.
- `das_test_setup.py` — install N DAS variants on a stage (one build).
- `das_ladder.py` — build a DAS count-ladder (video stripped, like the
  costume ladder); `das_probe.py` — boot each and drive a no-button random
  DAS pick *into a real match* (scored via `observe.Observer.watch`). How §3 was pinned.
