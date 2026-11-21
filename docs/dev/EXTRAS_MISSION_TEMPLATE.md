# Extras Mission Template — the per-character campaign pipeline

Standing instructions for the extras campaign's subagent missions, so each
mission prompt only carries the CHARACTER-SPECIFIC facts (targets, reference
mods, pre-verified markers) plus a pointer here. Update THIS file when a
mission learns a new lesson — it is the single source of truth the next
mission reads.

Canonical workflow + status table: `docs/dev/EXTRAS_AUDIT.md`. Harness:
`docs/dev/INGAME_TESTING.md`. Reference mods: `research/docs-research/
color-effects-reference/Reference-Mods-Index.md`. Master list: `research/docs-research/
color-effects-reference/Effect-Offsets-Reference.md`. Decomp ground truth:
a local `doldecomp/melee` checkout.

## Pipeline: one character = MAP → WIRE → EYEBALL

**MAP (Opus — mapping is mostly mechanical; it does first-pass capture reads,
while the authoritative visual verdict stays with main-session EYEBALL).**
Diff reference mods,
marker-verify cites, live-poke with `backend/devtools/effect_probe.py` (the standard
spec-driven mapper tool — write a JSON spec per `backend/
effect_probe.example.json` instead of a new driver script), judge every
capture immediately. Deliverable: a **mapping spec** at
`research/docs-research/effect-maps/<char>.md` (schema below) + a one-paragraph report.
Does NOT touch configs/UI.

**WIRE (Sonnet — mechanical, no image judgment).** Takes the mapping spec and
does the fan-out exactly per precedent (`falcon_kick`/`raptor_boost` are the
model): both config mirrors (`backend/core/extra_types.py` +
`frontend/src/shared/data/extraTypes.js`), editor registration
(`ExtraEditorModals.jsx`, `DualColorEditorModal.jsx` whitelist + preview,
the card preview in `vault/extras/previews/` plus the id list in the
`ExtraPreviews.jsx` dispatcher), `AUDIT_HINTS`, docs
(`EXTRAS_AUDIT.md` rows + reference doc ✅ marks), `py_compile` + esbuild
checks, then runs the FINAL VERIFY build per extra
(`python devtools/extras_audit.py --char X --extra <id> --colors <from spec>`) and
reports the capture paths. Does NOT interpret captures beyond "files exist".

**EYEBALL (main session — Fable).** Main reads the final-verify captures
against the spec's expected placement and marks the status row ✅ (or bounces
it back). This is the ONLY stage that needs Fable-grade image judgment; MAP's
own capture reads are first-pass filters, and any capture MAP is unsure about
gets flagged in the spec for EYEBALL instead of agonized over.

One Dolphin rule means stages run sequentially; WIRE's file work may overlap
the NEXT character's MAP only if WIRE's final build is explicitly deferred.

### Parallelization (2026-07-02): MAP splits into STATIC + LIVE

Only the emulator serializes. **MAP-STATIC** (any number in parallel, NO
Dolphin, no game boots): ptcl_parse inventory + decomp efSync_Spawn move
cross-ref + reference-mod diff + marker verification, delivering a draft
spec at `research/docs-research/effect-maps/<char>.md` with candidate tables AND a
ready-to-run probe spec JSON (`backend/probes/<char>_probe.json`) covering every
candidate. **MAP-LIVE** (one at a time, owns Dolphin): runs the queued probe
spec, judges captures, upgrades the draft spec's rows from candidate to
verified/dead. STATIC missions must not touch configs/UI, other characters'
files, or the shared docs beyond their own spec file. WIRE remains
single-lane (all WIREs edit the same shared config/preview files).

## Mapping spec schema (`research/docs-research/effect-maps/<char>.md`)

Per proposed extra: id + name; target file; per-layer rows:
`layer_id | format (CF-multi/070707/RGB/RGBY/42_48/BYTE) | offsets (exact,
marker-verified) | vanilla bytes | verified semantic ("foot fire core") |
how verified (live-poke/build) + capture path`. Plus: AUDIT_HINTS line
(move:frames + forced anti-colors), suggested editor grouping
(_c1/_c2 fan-out mapping), on-hit/pending layers flagged, EfCoData or other
shared-file findings quarantined into their own section (never shipped as
char layers), and open leads.

## Operating rules (all stages)

- No heartbeats needed — the user reads mission transcripts directly. Send
  ONE final report to "main" when done (or when stopping early).
- ONE Dolphin; kill your leftovers; Slippi closed; never modify
  `storage/test-base/files` in place; timeout 600000 on exports/boots;
  backend scripts run from `backend/` with `python`.
- Judge captures immediately; never bank unjudged piles.
- Stay in your lane: don't touch other characters/workstreams.
- Stall or ~90 min elapsed → STOP, write findings to the spec/docs, report.

## Artifacts path gotcha (bit two missions)

Verification captures live at `<repo-parent>/app/scratch/ingame/extras-audit/`
— ONE LEVEL ABOVE the `ssbmNucleus/` repo dir (extras_audit.py's
`ART_ROOT = PROJECT_ROOT.parent / "tests" / "artifacts"`). The in-repo
`ssbmNucleus/app/scratch/ingame/` holds only stray/old dirs. A mission that
"finds no captures" almost certainly looked in the repo copy — check the
parent. 60+ `<Char>-<extra>/` dirs exist there covering the whole cast.

## Structural parser (USE THIS FIRST in MAP missions)

`python shared/rendering/ptcl_parse.py <Ef*Data.dat>` (from `backend/`) decodes every
particle script and color operand with exact file offsets — no marker
scanning. `--models` adds the model-region 07/42/98 blocks by signature;
`--json` for tooling; `--verify` self-tests against in-game-verified ground
truth. Grammar + effect-id→script mapping: `research/docs-research/PTCL_FORMAT.md`.
Empirical-label decoder ring: "CF record" = PrimCol opcode 0xCF (next byte =
interp frame count), "AD DF" = PrimEnv flag + EnvCol 0xDF, "secondary at
colorpos+7" = the EnvCol color (env dominates sustained tint). Map script→
move via gfx_id − EffectIDStart (Fox 3000, Falcon 4000, Mewtwo 13000, Samus
2000) cross-referenced with fighter `efSync_Spawn` calls in the decomp.
Start MAP from the parser's inventory — but the parser is TRUSTED ONLY FOR
STRUCTURE (where colors are, which script owns them), NEVER for semantics.
No layer ships, gets named, or gets a 🟢 without a live-poke capture judged
by eyes: poke an anti-color, see the effect change, name what you saw. The
gfx_id→move mapping narrows candidates, it does not verify them (moves spawn
multiple scripts; some effects are subtle — Mewtwo-upsmash lesson). The
parser turns pokes from exploratory scans into one confirmation pass over a
complete checklist; unpoked scripts go in the spec as open leads, not layers.

## Accumulated lessons (append here; do not relearn)

-2. (bag mirror — ROOT CAUSE FOUND & FIXED 2026-07-02) The bag was MIRRORING
   the attacker's pipe inputs frame-for-frame (bag did Mario's up-B; both
   clanked into Rebound). Root cause: the CSS→SSS warp path skips vanilla's
   PlayerInitData→StaticPlayer copy (gm_16AE.c fn_8016D8AC), so every port kept
   the InitOrResetPlayer default `player_id = 0`. The fighter polls its pad via
   `HSD_PadGameStatus[player_id]` (decomp fighter.c: fp->x618_player_id =
   Player_GetPlayerId(fp->player_id)), so BOTH fighters read pad 0 = the harness
   pipe. NOTE this is `player_id` (StaticPlayer +0x48), NOT controller_index
   (+0x46 — that's color/effects, poking it does nothing). Solo runs never
   noticed (the lone player IS pad 0). FIX: `match_setup.fix_player_pad_indices`
   writes each active port's StaticPlayer.player_id (+0x48) AND its live
   fighter's cached ft+0x618 after the match loads; frameshot calls it right
   after wait_in_game. StaticPlayer base 0x80453080 stride 0xE90.
   The old "bag engagement limit" (first hit knocks the 0%-bag out of range →
   rapid-jab/Gerudo undemonstrable) was LIKELY CAUSED by the mirror: the bag's
   simultaneous counter-move traded/clanked instead of taking a clean hit. Now
   that the bag stands still and takes hits (verified Mario up-B → DamageFlyN,
   Ness PK Fire → DamageAir1/2), re-testing rapid-jab finishers (Attack100) and
   command grabs (Gerudo) is worthwhile before declaring them undemonstrable.
   If a genuine knock-out-of-range limit remains, suppress knockback entirely
   (not just percent-zero) or re-pin the bag per frame.
-1. (common-bank demos) A shared-effect extra's demonstration is
   per-CHARACTER: which moves draw a common script varies by fighter
   (Zelda's jab draws the electric pool, Pikachu's jab doesn't). When a
   verify capture is null, first re-demo with the character/move the LIVE
   pass actually used; and anchor impact-flash frame WINDOWS at that
   specific move's hitbox frame (Pika jab hits f2, Zelda's f10-11).
0. (probe-spec ordering) Moves that leave the fighter in a non-Wait resting
   state (Zelda/Sheik Transform → Sleep) POISON every later experiment in the
   boot — safe_reset only handles REBIRTH. Put such moves LAST in the spec or
   give them a lone boot. (Candidate harness fix: teach safe_reset about
   Sleep/transform states.)

1. Reference cites are often line starts: off by 1–8 bytes (07-cites have
   been +4 drifted = pointing at color1). Marker-verify EVERY cite; a shifted
   070707 write can HANG the game.
2. 07-blocks: marker+4 = bright core, marker+8 = glow (consistent so far).
3. CF records carry a SECONDARY color at colorpos+7 dominating sustained puff
   tint — expose `_c1`/`_c2` multi-RGB lists (legacy 'CF' format misses it).
4. Community-mod diffs contain find-replace shrapnel — candidates, not
   answers. Verify a mod's base file md5 before trusting its diff; re-saved
   (size-changed) mod files are unusable for offsets.
5. A dead live-poke ≠ dead offset (load-time consumption) — one build-path
   check before declaring dead. And whole-frame histogram diffs MISS subtle
   changes (Mewtwo upsmash) — eyeball the effect region before a null verdict.
6. Anti-color rule: test colors must be far from the effect's vanilla hue.
7. On-hit-only effects ARE now verifiable: the punching-bag harness (built
   2026-07-02) adds a 2nd HUMAN port with no controller — stands still, never
   attacks, never moves the camera (do NOT use a CPU). frameshot/extras_audit:
   `--bag dk --bag-pos 12,0` / AUDIT_HINTS keys `"bag"`+`"bag_pos"`;
   effect_probe spec key `"bag": {"char": "dk", "dx": 12}`. The sidecar's
   `bag.hit` + per-capture bag states confirm contact (victim in a Damage*
   state); dx 12 connects Falcon side-B on frame 17, deterministic across
   boots. Unattributable diff regions = on-hit candidates — probe them WITH
   the bag now, not "pending".
8. `get_dynamic_offsets` merges detected over config now; config-only layers
   survive, but prefer extending finders for shift-robustness.
9. Falcon Kick-style movement moves can slide off FD (RebirthWait) — recenter
   between reps (`effect_probe.py` recenters to `START_X`).
10. Fighter-specific action states: use gamestate snapshots, not assumptions;
    frame windows for AUDIT_HINTS come from the live-poke session.
11. Anti-colors are per-OPERAND: an EnvCol layer's test color must be far
    from the ENV vanilla hue (Samus needles: palette blue on a vanilla-blue
    EnvCol looked like a no-op; the patch was fine). When a verify capture
    looks null, byte-check the built ISO before suspecting the wiring.
12. A spec's grouped layer table may share one vanilla string across records
    whose actual vanilla bytes DIFFER (Mario hand_smoke/tornado 42-blocks).
    WIRE must byte-verify vanilla per record and split the group into
    per-record keys when they differ — a grouped vanilla ships wrong
    reset/preview colors.
13. Special-format extras (`shine_gradient`, texture types) have a SECOND
    patch mirror inside `extras_audit.py` (e.g. `_patch_shine`) — a new layer
    wired only into colors.py passes py_compile but silently no-ops in the
    verify build. Extend the audit mirror in the same change.
14. Punching-bag gotchas (raptor_boost validation 2026-07-02): the bag's
    percent is zeroed every rep (an uncontrolled port never techs/gets up —
    keep knockback tiny so it's never launched off or knocked down); a bag
    char can idle in a char-specific state (DK sits in CharSpecific_379) —
    judge contact by Damage* states, not Wait. And the on-hit BURST may mix
    wired ptcl layers with UNWIRED vanilla elements (raptor's uppercut fire
    pillar + radial glow stayed orange while smoke/dots recolored) — compare
    against a `--vanilla` control run with the same bag before attributing.
15. (grab recipes — Link hookshot re-probe 2026-07-02) `PRESS Z` is SWALLOWED
    by the Slippi named-pipe controller: it produces NO grab (held 15 f from
    Wait stays in Wait, though A/L register fine). `shared/ingame/moves.py` grab
    recipes are now L(shield)+A: `grab` = PRESS L, step 3, PRESS A → Catch
    (212); `dashgrab` = dash then PRESS A + PRESS L on the SAME frame (A listed
    first, stick still forward) → CatchDash (214). L-before-A during a run rolls
    (EscapeF). This was the real hookshot blocker (NOT the old "grab window too
    short" theory). NOTE Link's STANDING grab is a short hand-grab (no tether);
    only DASH/pivot grab extends the hookshot.
16. (tether/projectile effects vs the parked bag) The punching-bag harness
    force-parks the victim straight INTO the grab/hit state, which skips a
    tether's mid-air FLIGHT phase — Link's hookshot chain/tip effects (s93/s331)
    never render because the grab resolves on frame 1 against a pre-placed bag.
    For a travelling-projectile/tether effect, WHIFF it into empty air (no bag)
    so the article flies its full length and spawns its flight-phase ptcl.
17. (on-hit counter/reflect effects) Counter flashes (Marth/Roy gfx 1265, etc.)
    fire only when the fighter is STRUCK inside the counter window. The
    uncontrolled-human bag NEVER attacks, so these are un-demonstrable with the
    current harness — genuinely harness-blocked, not dead. Needs a scripted
    single-hit CPU or a memory-forced counter-success branch.
19. (bag-pin + air-specials, BAG-FIXED RE-TEST 2026-07-02) Two harness additions:
    (a) **`--bag-pin`** — opt-in knockback suppression for the punching bag
    (`effect_probe` spec key `"bag":{...,"pin":true}`; `Bag.pin()` in
    `shared/ingame/gamestate.py` zeros self_vel/kb_vel/ground-vel + re-pins position each
    stepped frame). UNBLOCKS command-grab bursts: Ganon's Gerudo now lands cleanly
    (bag → DamageFlyTop throw instead of failing to re-grab) — attributed the
    Gerudo dragon FLAME AURA to EfGn s12/14/15/16 (smoke = s7/9/10/11). It keeps a
    hit target GROUNDED and in range (fixes lesson-14's "knocked airborne on hit
    1"), but does NOT by itself make Fox reach the Attack100 rapid-jab LOOP —
    that's a separate INPUT-recipe gap (rapid jab needs sustained held-A; mashing
    only chains jab1↔jab2). (b) **air specials** — `moves.py` now has
    `airneutralb`/`airsideb`/`airupb`/`airdownb` (jump to apex via `_to_air`, then
    the B-move in the air). This VERIFIED `pikachu_thunder_jolt_air` (green core +
    magenta flare, shipped) and re-probed Bowser's aerial fortress (trail is WHITE,
    not blue — fortress_model_blue/fortress_ptcl both DEAD for it too). Open gap:
    a `rapidjab` (held-A) recipe for Attack100 finishers.
18. A hardcoded/config offset is only correct until the next re-save shifts
    it (texture/model import via HSDRawViewer can move everything after the
    edit point). `backend/vault/extras/relocate.py` guards every write
    in `apply_hex_patches`/`patch_shine_sparkle_color` against the config's
    `vanilla` bytes and auto-relocates via `ptcl_parse` identity (ptcl-bank
    operands) or signature scan (070707/model blocks) when the guard fails,
    skipping loudly instead of writing on an unverified offset. See
    docs/dev/EXTRAS_AUDIT.md "Offset safety: guard + relocation". New write paths
    should thread a `safety` context (`helpers.make_write_safety`) through
    rather than seeking+writing raw.
20. (texture-extra color-picker migration, 2026-07-02, task #12) `type:
    "texture"` extras (textures.py, CLI export/hue-shift/import) can be
    NESTED inside a sibling color extra's editor with no standalone card of
    their own (e.g. upb_texture lives inside UpBEditorModal's
    `modifications.fire`) -- always grep for how a SIMILAR character's
    texture extra is wired before assuming a config-defined one is unwired:
    punch_texture had a full config + backend routes but ZERO frontend
    wiring (no card, referenced nowhere) until this migration added it to
    DualColorEditorModal, mirroring upb_texture's pattern. When migrating a
    hue-degrees slider UX to a ColorPicker, the back-compat-mandatory design
    is: keep the SAME static config `vanilla_hue` constant as the apply-time
    shift source, do NOT live-remeasure it (this deliberately diverges from
    texture_recolor's live-measure principle) -- a live remeasurement could
    make the same saved mod produce a drifted shift across re-installs,
    breaking byte-for-byte reproduction of old saves. The equivalence to
    test is "a NEW color whose OWN hue equals an OLD saved absolute `hue`
    value reproduces the identical final shift" -- NOT "color ==
    vanilla_hue + old_hue", because `apply_texture_extra_hue`'s `hue`
    parameter has always been an absolute target hue (`shift = hue -
    vanilla_hue`), never a relative shift amount, even under the old slider
    UI. Both `type: "texture"` config mirrors need a `SIBLING_TEXTURE_EXTRAS`-
    style generic dispatch in colors.py's install/restore-vanilla (a single
    hardcoded `if extra_type == 'upb'` special case silently misses the
    next character that gets the same nested-texture pattern).
21. (bag-pin passthrough, kirby+gerudo WIRE mission 2026-07-02) `effect_probe.py`
    (the MAP-LIVE tool) had `bag.pin`/`_pinned_step` wired from lesson 19's
    original add, but the WIRE-facing tools (`frameshot.py`, which
    `extras_audit.py` shells out to) did NOT -- a spec's AUDIT_HINTS `bag_pin`
    key would have silently done nothing at verify-build time. Fixed by
    mirroring `effect_probe.py`'s `_pinned_step` helper into `frameshot.py`
    (new `--bag-pin` flag, wraps the per-target stepping loop) and adding the
    `AUDIT_HINTS` `"bag_pin"` key + passthrough in `extras_audit.py::main`
    (mirrors the existing `"bag"`/`"bag_pos"` first-hint-wins pattern). When a
    spec calls for a harness feature already proven in MAP-LIVE, verify it
    ACTUALLY reaches the WIRE-side CLI before assuming AUDIT_HINTS can just
    reference it -- MAP and WIRE can drift onto different tool surfaces even
    though they share the same underlying `shared/ingame/gamestate.py` primitive.
22. (three new on-hit recipes, STRAGGLER-CLOSEOUT 2026-07-02) `shared/ingame/moves.py`
    gained THREE recipes that unblock previously harness-blocked on-hit stragglers.
    All run on the frozen-step pipe + the pinned bag; all registered in `MOVES`
    so `effect_probe`/`frameshot` specs can name them.
    (a) **`rapidjab`** — reaches Attack100Loop (the rapid-jab finisher). The fix
    was NOT knockback/range (bag-pin already solved that) and NOT the old theory
    of "sustained held A": on the frozen-step pipe a CONTINUOUS hold plays jab1's
    full ~17f then drops to Wait (no chain), and MASHING resets to jab1. What
    works is a **1-frame-ON / 1-frame-OFF A toggle** -- it presents a fresh A
    press-edge inside every jab's small IASA window, chaining Attack11→12→
    Attack100Start→Loop deterministically (verified Fox). This finally VERIFIED
    EfCoData `jab_finisher_spark` (s11/s15/s91 recolor the finisher connect burst;
    ship as a grouped color extra, all cast). Decomp basis: ftCo_Attack1.c /
    ftCo_Attack100.c (x1A54 accumulates per A-held frame; x2218_b1/b2 gates set by
    the jab subaction). USE the toggle for ANY multi-hit rapid chain.
    (b) **`bombthrow`** — Link down-B pulls a bomb, then tosses it forward (stick-
    forward + PRESS A = item LightThrow; Z is swallowed per lesson 15, item-toss
    is A not grab). The bomb flies + DETONATES on a bag parked at DISTANCE
    (dx~34). Reusable for ANY pull-item→throw→detonate probe. It proved EfLkData
    is DEAD for the bomb explosion (the explosion is the article item file /
    PlLk.dat / EfCoData, per ITEMS-PASS).
    (c) **full-charge fire pattern (no new recipe, just a spec idiom)** — to test
    a FULLY-charged Samus charge-shot flash: `execute("neutralb")` starts the
    charge, then the move's `inputs` schedule HOLDS B ~56f (PRESS B early, RELEASE
    late), then RE-PRESS B to FIRE; park the bag at dx~20 so the ball travels +
    connects. This closed the flashA/warm "fully-charged caveat" NEGATIVE (still
    DEAD -- the charged-shot connect flash is texture/model).
    NOTE all three build a fresh vanilla ISO via `mexcli export project.mexproj`
    (mexcli.commands.run returns a CompletedProcess, NOT a dict -- don't call
    `.get()` on it).

23. (Kirby copy-ability primitive + three traps, KIRBY-COPY LIVE 2026-07-02)
    `match_setup.install_kirby_copy_via_rebirth` gives a harness Kirby any
    donor's copy ability (no inhale possible solo/bag): poke the persisted copy
    kind (StaticPlayer +0x4D, INTERNAL FtKind) and KO→rebirth him —
    `ftKb_Init_OnDeath` calls the real installer `ftKb_SpecialN_800F1BAC` on
    respawn. Plumbed as frameshot `--kirby-copy <donor>` and effect_probe
    `"kirby_copy"` (specs `backend/probes/kirby_copy/<donor>.json`). All 8
    mapped EfKb copy banks LIVE-verified with it (kirby.md §6.4b). THREE traps,
    each live-proven the hard way:
    (a) **flags.b1 (+0xAC mask 0x40) is the Classic TEAM-FIGHTER flag, not a
    "has copy" flag** — setting it makes the next death REMOVE the player
    (slot→NA, gobj NULL forever). The vanilla b1 check inside ftKb_Init_OnDeath
    is instead NOP'd (verified opcode patch @0x800EE638) so unk4D alone arms
    the install; unk4D's vanilla in-match value is 4 = no copy.
    (b) **Dolphin-JIT: code patches must land before the code first RUNS.**
    ftKb_Init_OnDeath compiles at Kirby's FIRST spawn; a mid-match RPM patch
    hits the stale compiled block and silently does nothing. Arm in the same
    early boot phase as `patch_one_player`. (Generalizes: ANY harness opcode
    patch must beat the JIT to the function.)
    (c) **Copy data loads per-PRESENT-fighter at match start** — the EfKb banks
    are NOT all preloaded; installing a copy of an absent donor dereferences
    never-loaded data and HANGS the game (frame counter frozen, unrecoverable).
    One boot per donor with bag=donor. Also: the warp path leaves
    StaticPlayer.stocks=0 (same family as the lesson -2 pad gap), so a death
    without seeding stocks destroys the fighter instead of respawning — the
    primitive seeds 5.
    Bonus reads: `hat.kind` (fp+0x2238) is a u32 — a u8 read at that address
    returns the zero MSB and misleads (this hid the initial-spawn OnDeath run
    for a whole session). Copy-install success = hat.kind == donor FtKind AND
    neutral-B enters `KIRBY_COPY_STATES[donor]` (e.g. Ganon 528) instead of 353.

24. (FD plain-bg stars + live GObj walking, FINAL DOLPHIN SWEEP 2026-07-02) The
    drifting FD background sparkles that pollute `--plain-bg` captures are
    **efLib PARTICLES** (killing the main ptcl render GObj — classifier 8,
    gx_link 7, `efLib_render_callback` — blanks them 16/16 frames), NOT stage
    JObj geometry; the earlier static analysis was wrong, which is why the
    x180[] render-flag pokes failed. **SOLVED (2026-07-02, generator pass):**
    the stars are ONE long-lived psLib generator with `bank == 0x1E` — the
    stage SPtcl bank (`efLib_Cb_SPtcl` routes bank 0x1E to grLib, eflib.c:998)
    — while fighter effects use their own ef banks (fox up-B = banks
    0x00/0x03). `frameshot.py --plain-bg` on FD now unlinks bank-0x1E
    generators (list head 0x804D78FC) and particles (per-linkNo heads
    0x804D0908) at the plain-bg poke points (`kill_stage_particles`); the
    particle render pass walks those live lists per composited frame, so the
    unlink takes effect even while frozen. Stars gone, fox up-B fire intact
    (regression: `--char fox --move upb --frames 40,60 --plain-bg`). Found with
    one-off GObj and generator/particle-list A/B sweeps (removed in November 2026).
    Walking gotcha: the per-p_link GObj list HEADS are `*(0x804D782C)`
    (`HSD_GObj_Entities`); `plinklow_gobjs` @0x804D7828 holds the TAILS —
    walking `next` from the tails visits one GObj per p_link and misses the
    stage GObjs entirely.

25. (disk-full mexcli exports, common_shield WIRE 2026-07-10) A mexcli
    `export` on a FULL disk reports success and writes an ISO with a valid
    GALE01 header but a GARBAGE FST string table (every filename resolves to
    one string) — the game then hangs before the boot menu ("scene 0x01
    never appeared") and `vanilla_refs.extract_file_from_iso` returns False.
    Before diagnosing a boot hang as a bad patch, check free space; the
    isolated per-boot `storage/test-runs/test-*` User dirs accumulate
    gigabytes and are safe to delete. Also: the shield/`texture_region`
    verify pattern — full-region byte containment offline + one
    checkerboard build capture — is cheap and decisive for texture-blob
    extras (no anti-color reasoning needed).

## Editor polish pattern (laser-grade extras editors)

Established by the EDITOR-POLISH PILOT (C. Falcon + Samus, 2026-07-02). This
is the reusable pattern the fan-out replicates cast-wide. It is a PURE
FRONTEND change: the vault create/save `modifications` shape is unchanged, so
no backend/config-schema edits are needed to adopt it. All pieces live under
`frontend/src/`; the two extras those chars own now use them.

### Reusable components (build once, reuse everywhere)

1. **`vault/lib/relativeRecolor.js`** — the Simple-mode macro. `computeDominantHue`
   (saturation-weighted circular mean over an extra's `vanilla` values, skips
   whites/grays/blacks), `resolveDominantHue(extraType)` (prefers a config
   constant `vanillaDominantHue`/`vanillaHue`, else computes), and
   `relativeRecolorLayers(targetHex, vanilla, dominantHue, keys)` which rotates
   every layer's vanilla color by `(targetHue − dominantHue)` **in HSV,
   preserving each layer's own S/V** (achromatic layers `s<0.04` pass through
   unchanged, so white cores/grey smoke stay neutral). Self-contained HSV
   helpers (do NOT use colorUtils' HSL — its 0-100 int rounding loses
   precision, and "preserve S/V" is an HSV contract). Verified numerically:
   falcon_kick dominant 33.9°→green keeps the pale cream core pale, whites
   white, dark trail muted.

2. **`vault/extras/useBespokeSimpleMode.js`** — the Simple/Advanced hook (the older `useSimpleMode.js` was removed 2026-10-04).
   Owns the mode flag + single simple-mode swatch; `applySimpleColor(hex)` fans
   the macro across the layer keys into the editor's existing `colors` state.
   The editor still owns `colors`/`setColors`; the hook only layers the macro
   on top, so Advanced mode is byte-identical to the pre-polish editor.

3. **`vault/extras/pictograms.js`** — per-layer pictogram registry.
   `pictogramSrc(extraId, layerId)` → `./extras/pictograms/<extra>_<layer>.png`
   or null (graceful fallback). PNGs are static public assets (served from
   `frontend/public` as they are — no bundler import). A
   `SUMMARY_ALIAS` maps the summary `color1/color2` pickers to a representative
   layer's pictogram.

### Wiring into an editor (DualColorEditorModal is the model)

- `ColorPicker` gained an optional `picto` prop (renders a 44px in-game crop
  left of the header via `.laser-color-topline` / `.layer-pictogram`; the
  `<img onError>` hides itself if the asset 404s — belt-and-suspenders on top
  of the null-returning registry).
- A `.extra-mode-toggle` (Simple | Advanced) shows only when `multiLayer`
  (>1 controllable layer; a single-color extra like charge_ball skips it).
  Simple = one "Effect Color" picker → `applySimpleColor`; Advanced = the
  existing per-property pickers, each with its `pictogramSrc(id, prop.id)`.
- **Save change (one line, back-compat):** the `_c1/_c2` fan-out now prefers an
  explicit `colors[offsetKey]` when present (that's how Simple mode ships
  DISTINCT per-layer colors), falling back to the `color1/color2` summary
  otherwise. Advanced mode never sets per-layer keys, so it hits the fallback
  and is byte-identical to before. The emitted `modifications` object shape is
  unchanged — vault/backend untouched.

### Accurate previews (design against the captures, bind per-layer)

Both `ExtraPreviews.jsx` mirrors and the modal's `EffectPreview` gained an
`L(key, fallback)` per-layer color getter (reads the saved per-layer key /
`colors[key]`, falling back to a summary color) so the SVG binds each visual
element to the layer that actually controls it — and so the preview updates
live in BOTH Simple and Advanced mode (both populate the per-layer keys). Draw
the real placement seen in `app/scratch/ingame/extras-audit/<Char>-<extra>/`
(each layer's anti-color makes its element identifiable). Be HONEST about
unwired vanilla elements (raptor's orange fire pillar / star flash,
charge_shot's blue aura, the missile body) — draw them fixed-color, not
recolored, per lesson-14.

### Per-character fan-out cost (what each editor-polish mission takes)

1. Crop pictograms: read that char's `<Char>-<extra>` captures, pick a frame
   per layer where its anti-color is clearly visible, crop→112px into
   `frontend/public/extras/pictograms/<extra>_<layer>.png` (a throwaway PIL
   script; the pilot's is a good template). Then add the extra's layers to the
   `HAVE` map (and `SUMMARY_ALIAS` if it uses summary pickers) in
   `pictograms.js`.
2. Upgrade that extra's preview block (`vault/extras/previews/`, the
   `dualColor*.jsx` group for its character) +
   the modal's `EffectPreview`, binding per-layer via `L(...)`.
3. Nothing else — the Simple-mode toggle + macro are automatic for any
   multi-layer extra routed through DualColorEditorModal (they read
   `extraType.vanilla`/`offsets`). Extras with their own bespoke editor
   (LaserEditorModal etc.) need `useSimpleMode`/`ColorPicker picto` ported into
   that editor the same way.
4. Checks: `esbuild` dry-parse touched `.jsx/.js`; view the cropped
   pictograms yourself to confirm they isolate the right element.

### Fan-out completion (EDITOR-POLISH FAN-OUT mission, 2026-07-02)

The cast-wide fan-out is DONE. What it found and did:

- **Previews were already cast-wide.** The pilot's `DualColorEditorModal`
  `EffectPreview` and `frontend/src/vault/extras/ExtraPreviews.jsx` `DualColorPreview`
  already carried accurate, `L(...)`-bound blocks for EVERY multi-layer extra
  in scope (Mario/Luigi/Ness/Pikachu/Mewtwo/Zelda/Bowser/Jiggly/Ganon/ICs/Link
  + commons), not just Falcon+Samus. Only the **charactermode mirror**
  (the Character Mode `ExtraPreviews.jsx` copy) lagged: its
  `DualColorPreview` bound only the summary `color1Hex/color2Hex` and drew
  cruder shapes for the six genuinely multi-layer extras. Brought to PARITY by
  adding the `L(key, fallback)` getter and porting the storage-mirror's
  accurate blocks for `falcon_punch`, `falcon_kick`, `raptor_boost`,
  `screw_attack`, `missile`, `charge_shot`. All other extras were already
  byte-identical between the two mirrors (single summary-color shapes), so they
  were left untouched. Simple-mode toggle + macro remain automatic for every
  DualColor-routed multi-layer extra (no per-extra wiring needed).

- **PICTOGRAM INVENTORY (84 total — 17 pilot-era + 67 added by the PICTOGRAM
  FAN-OUT, 2026-07-02).** The earlier fan-out's "captures do not exist" claim
  was WRONG: it looked in `ssbmNucleus/tests/` but `extras_audit.py` writes to
  `ART_ROOT = PROJECT_ROOT.parent / "tests" / "artifacts" / "extras-audit"`
  (one level ABOVE the repo dir). 62 clean `<Char>-<extra>/` capture dirs cover
  the whole cast. This pass cropped per-layer pictograms from them (a color-
  localization PIL script: each layer's forced anti-color from `applied.json`
  is found in the frames, tight-cropped with context, downscaled to 112px).
  Coverage (43 extras):
  `falcon_punch`(color1,fire,color2,flare_lines_c2,flare_small_c1,flare_big_c1,
  smoke) `falcon_kick`(color1,color2,front_c1,trail_c1,dots_c1)
  `raptor_boost`(color1,color2,hit_smoke_c1,hit_smoke_c2,hit_dots_c1,hit_mat_c1)
  `screw_attack`(arc_c1,arc_c2) `missile`(contrail_c1,backblast_c1)
  `charge_shot`(needles_c1,needles_c2) `charge_ball`(color1)
  `shadow_ball`(color1,color2,charge_c1,charge_c2,bolts_c1,bolts_c2)
  `upsmash`(color1,color2) `upb`(body,rings) `laser_ring`(color1,color2)
  `thunder`(color1,color2 — shared Pikachu/Pichu) `pikachu_fsmash`(_c1,_c2)
  `pikachu_thunder_jolt_air`(mid_c1,mid_c2)
  `pikachu_thunder_jolt_ground`(a_c1,a_c2,head_c1) `common_electric`(1 rep)
  `thunder_jolt_spark`(1 rep) `ness_pk_thunder`(tip_c1,ball_flare1_c2)
  `ness_psi_magnet`(psimag_a_c1,_c2) `ness_pk_fire`(ring_in_c1,_c2)
  `mario_fireball`(hand_smoke,ball_particles,landing_dust)
  `mario_fireball_aura`(aura_07_c1) `mario_tornado`(swirl,ground_ripple)
  `mario_cape`(cloth_c1) `cape_sparkles`(sparkle_a_c1,sparkle_trail_c1)
  `mario_coins`(color1) `doc_cape`(cloth_c1) `luigi_cyclone`(1 rep)
  `luigi_fireball`(1 rep) `luigi_fireball_smoke`(1 rep) `luigi_hitspark`(1 rep)
  `common_fire`(color1) `common_flash`(color1) `zelda_farore`(farore_c1)
  `zelda_transform`(transform_c1) `bowser_fire_breath`(1 rep)
  `sing_notes`(red,blue,green note cores) `warlock_punch`(1 rep)
  `wizards_foot`(color1) `gerudo_dragon`(1 rep) `ice_shot`(1 rep)
  `kirby_stone`(1 rep) `spin_attack_trail`(color1,color2).
  Whole-effect extras whose many layers all share ONE anti-color get a single
  representative crop keyed to the primary layer; SUMMARY_ALIAS points the
  editor's `color1`/`color2` summary pickers at a representative `_c1`/`_c2`
  crop. Consistency-checked: every HAVE entry ↔ a real PNG, every PNG
  registered (84 ↔ 84), all SUMMARY_ALIAS targets present; `esbuild` dry-parse
  clean. SKIPPED layers (no clean isolation): Fox `upb` tip/trail/small_trail
  (all overlap the same flame region as `body` — indistinguishable duplicates,
  dropped); the RGBY-matrix laser/shine layers (bespoke mixed-region editors,
  not spatially separable by anti-color); and per-layer crops inside single-
  anti-color whole-effect groups (collapsed to one rep each, by design). The
  `common_flash` crop is a legible-but-loose read (its recolored star-burst is
  genuinely tiny + adjacent to the vanilla yellow bolt).

- **(Historical, now corrected) The earlier fan-out reported NO PICTOGRAMS
  POSSIBLE — captures do not exist.**
  `app/scratch/ingame/extras-audit/` holds only `Fox-13620swap`, `tex-id-fire`,
  `tex-id-fire2` — there are NO `<Char>-<extra>` verification-capture dirs for
  ANY fan-out character (they were judged live and discarded per the
  "never bank unjudged piles" rule; the MAP-LIVE pipeline does not persist
  them). So EVERY remaining extra (all Mario/Doc/Luigi/Ness/Pikachu/Mewtwo/
  Zelda/Bowser/Jiggly/Ganon/ICs/Link/common extras) SKIPS pictograms. This is
  handled gracefully: `pictogramSrc` returns null for unregistered layers and
  `<img onError>` hides any 404. If a future mission wants these pictograms it
  must FIRST re-run `extras_audit.py`/`frameshot.py` to regenerate the
  `<Char>-<extra>` captures, then crop.
  **CORRECTION (2026-07-02): this conclusion was a wrong-directory error** — the
  captures existed all along under `PROJECT_ROOT.parent/app/scratch/ingame/
  extras-audit/` (not `ssbmNucleus/tests/`). The PICTOGRAM FAN-OUT above
  cropped all 67 from them; nothing needed re-running.

- **BESPOKE EDITORS PORTED (Simple/Advanced toggle + `picto` prop).**
  `LaserEditorModal`, `ShineEditorModal`, `UpBEditorModal` now each have a
  Simple/Advanced toggle and pictogram-capable `ColorPicker`s. Because these
  editors store colors in MIXED per-layer formats (RGBY matrix layers, RGB
  6-hex core/texture layers, plus exotic 42_48/CF/070707), the generic
  `relativeRecolor` HSV macro (which emits plain RGB hex and can't know a
  layer's on-disk format) would CORRUPT the RGBY saves. So they use a new
  `vault/extras/useBespokeSimpleMode.js` hook: Simple mode is one
  live color picker fanned to every layer IN ITS NATIVE FORMAT via an
  editor-supplied `fanOut` callback (exactly what each editor's existing
  "apply to all" preset buttons already did, driven by a picker instead of six
  fixed swatches). Advanced mode is the editor's original per-layer UI,
  byte-identical. Save/vault `modifications` shape is unchanged. This DELIBERATELY
  DIVERGES from the DualColor path's HSV-preserve-S/V macro — do not "fix" the
  bespoke editors to use `relativeRecolorLayers`, it will corrupt RGBY bytes.
  (Shine keeps its interactive region-selector hexagon in Advanced; Simple hides
  the region buttons and shows one picker with the hexagon as a live preview.)
