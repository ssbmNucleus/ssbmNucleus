# Coach baseline packs

The Tracker coach ("Randall") reasons over **baseline packs** — precomputed
aggregate JSONs bundled with the app — plus the live replay index. There is no
playbook (removed by design decision 2026-07-13: stats-only coaching) and the
coach never reads raw replays at answer time.

## What ships

`backend/tracker/baselines/` (a data folder at the root of the `tracker` package; the
spec bundles it to `backend/tracker/baselines` in frozen builds). The Stats page reads it
through `tracker/stats/baseline_ranks.py` (`/deep/baselines`) and the coach through
`randall/coach/coach_data.py`:

| file | contents |
|---|---|
| `manifest.json` | tiers × characters available, row counts, provenance |
| `<tier>/<Char>.json` | population pack: metric medians/spreads, death-cause mix, death-% distribution, tech breakdown (ground/platform/after-throw), recovery success, per-matchup and per-stage slices |
| `situations.json` | option/outcome tables per situation × tier × matchup — situations: `out_of_shieldstun`, `ledge` (incl. ledgedash attempts), `tech` (in place / rolls / missed), `knockdown` (getup choices) |

Tiers: `platinum`, `diamond`, `master` are mined from the HF ranked-replay
dataset (`erickfm/melee-ranked-replays`, MIT; **same-tier matches only** — in
cross-tier shards there is no way to attribute a rank to a player, so they are
excluded). `summit` is the small top-pro corpus. Packs exist for every
character with enough games in those populations (opponents of Falco count,
so Marth/Fox/etc. packs fall out of the FALCO shards for free).

Death causes are classified per stock (see `analyzer_v2.py`): `raw` (killed by
knockback of an onstage hit), `edgeguard` (final hit taken while offstage),
`failed_recovery` (died offstage well after an onstage hit), `tech_chase`
(died right after a knockdown), `sd` (died untouched for 4s+). Deaths carry
their frame index (`f`) so own-replay deaths can be clip-linked.

**Adding a situation miner** (the OOS/ledge/tech state machines in
`analyzer_v2.py` are the pattern): verify action-state ids against the local
decomp enum (`melee/src/melee/ft/chara/ftCommon/forward.h` — CapturePulledHi
= 223 anchor; ids below 223 are canonical Slippi table territory), emit
`(option, dmg_swing, died)` tuples on a new row field, register the field in
`SITUATION_FIELDS` (both `build_packs_v2.py` and `deep_stats.py`), and bump
`ANALYZER_VERSION`. Tier tables then need a shard re-churn (local
`mine_cast.py` ~16h free, or `modal_mine.py` ~$15/~40min); the player's own
games re-mine incrementally in-app.

**In-app deep stats** (`tracker/stats/deep_stats.py`, routes in
`tracker/routes/stats.py`): the same analyzer (`tracker/stats/analyzer.py`, the
vendored `analyzer_v2.py`) runs over the
USER'S own replays per character — background job with progress
(`/api/nucleome/deep/*`), rows in nucleome.db keyed by `ANALYZER_VERSION`,
surfaced in the Stats page panel (character filter active) and the coach
tools (`my_deep_stats`, `start_deep_analysis`, `my_situation_mix`).

## Pipeline (`tools/rank-baselines/`)

```
fetch_shards*.py        download shard tarballs ($MELEE_SHARDS, default ~/melee-shards)
analyzer_v2.py          per-player frame stats for one game (both players),
                        incl. embedded OOS situation events
mine_shards_v2.py       extract -> analyze -> delete, per same-tier shard;
                        rows to $MELEE_MINE_ROWS/<shard>.jsonl (resumable)
mine_own_v2.py          my games + summit corpus rows + my OOS mix
build_packs_v2.py       rows -> baseline packs (writes straight into
                        app/backend/tracker/baselines/)
```

Regen recipe (after adding a stat to `analyzer_v2.py`):

```
venv/Scripts/python.exe mine_shards_v2.py --workers 10   # hours; resumable
venv/Scripts/python.exe mine_own_v2.py
venv/Scripts/python.exe build_packs_v2.py --date YYYY-MM-DD
```

Raw shards are only needed to re-mine when a stat DEFINITION changes; they can
be deleted and re-downloaded from HF at will. The rows JSONLs on D: are the
cheap intermediate — keep them and `build_packs_v2.py` re-runs in seconds.

## Serving

`backend/randall/coach/coach_tools_v2.py` is the coach's whole tool API: the
`TOOLS` dispatch and `TOOL_SCHEMAS` (player_summary, matchup_stats,
compare_to_baseline, death_breakdown, defense_stats, stage_stats,
situation_table, my_situation_mix, tier_baseline, corpus_matchups,
corpus_stats, corpus_trend, ...). The tools themselves live beside it by what
they read: `coach_tools_stats.py` (baseline packs and the player's mined
stats), `coach_tools_corpus.py` (the whole replay index), `coach_tools_combos.py`
(the mined combo corpus) and `coach_tools_games.py` (one game). `coach_data.py`
reads the packs (frozen-aware via `sys._MEIPASS`; the spec bundles the
baselines dir), `coach_prompt.py` holds the system prompt, and the live index
scopes are merged from `coach_tools_live.py`. `coach_api.py` serves one
stats-only variant; legacy client `mode` values map to it.

Personal packs now come exclusively from `deep_stats.build_player_pack` over
the current user's claimed accounts. Completed rows must match the analyzer
version and current replay size/mtime. This also applies to the list of mined
characters shown in `player_summary`. Missing mining produces setup guidance,
not the bundled Falco fixture. The personal comparison/breakdown tools accept
an optional `character`; otherwise they use the saved main or most-played
character. Population comparisons select that same character's baseline.

The coach doubles as a **stats analyst**: `corpus_stats` exposes every
section of the Stats page (overview, per-character, matchups, stages, months,
sessions/tilt, time heatmap, rivals, salt) over the full corpus, and
`corpus_trend` gives win-rate time series filterable by the player's
character AND the opponent ("when did my Marth get better").

Non-Falco mains use their in-app mined packs. Expanding population coverage
still requires mining the corresponding ranked shards. The OOS option
classifier remains Falco-tuned; do not present a Falco situation population
as a validated comparison for another character. Historical eval results that
depended on the bundled personal fixture do not establish current app behavior;
new evals need an explicit isolated replay index or injected test fixtures.
