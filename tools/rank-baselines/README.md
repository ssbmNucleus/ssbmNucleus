# rank-baselines

rank-baselines: mines ranked Slippi replays (HuggingFace erickfm/melee-ranked-replays) into the per-tier baseline packs the app ships in app/backend/tracker/baselines/ (Tracker Stats '/deep/baselines' and the Randall coach read them). Regenerating packs changes a released feature; treat like a release step.

```
fetch_shards*.py / prefetch_remaining.py     download ranked shards
        │
laptop_mine.py / modal_mine.py / mine_*.py   churn them through the analyzer
        │
analyzer_v2.py                               per-player frame-derived stats
        │
build_packs_v2.py                            aggregate into baseline packs
        │
        └─> app/backend/tracker/baselines/   (76 committed files)
```

## Re-running this changes a RELEASED feature

The packs are not only Randall's. The Stats page reads them too — `/deep/baselines`
maps each of your metrics onto the tier it looks like ("your L-cancel rate looks
platinum"), and that route is **not** behind the Randall gate. Randall is a
second consumer, currently gated off.

So regenerating packs changes what shipped Stats tells users about their play.
Treat it like `tools/release_to_public.py`: deliberate, reviewed, not casual.

## The scripts

| Stage | Scripts |
|---|---|
| Fetch | `fetch_shards.py` (→ G:/AI/melee-shards), `fetch_shards_chars.py`, `prefetch_remaining.py` |
| Mine | `laptop_mine.py` (standalone), `modal_mine.py` (cloud, ~30 min vs ~16 h local), `mine_shards_v2.py`, `mine_own_v2.py`, `mine_cast.py` |
| Analyse | `analyzer_v2.py` — the core; `response_mining.py` (out-of-shieldstun option mix) |
| Build | `build_packs_v2.py` |

## Notes

- **Flat on purpose.** `mine_own_v2` and `mine_shards_v2` import
  `analyzer_v2` and `response_mining` as siblings, which only works in one
  directory.
- **The corpus is at the repo root, not here.** These scripts lived AT the root
  until 2026-08-22, so `data/` used to be the script's own directory; this folder moved to
  `tools/rank-baselines/` on 2026-10-03, so every path now walks three levels up. `data/` is ~1 GB of untracked working input and is not
  part of this package.
- `laptop_mine.py` is the exception: its `rows/`, `work/` and `dl/` stay beside
  the script because it is meant to be copied onto another machine and run alone.
- Two vendored copies of this code live in the app, in `app/backend/tracker/stats/`:
  `tracker/stats/analyzer.py` (<- `analyzer_v2.py`) and
  `tracker/stats/pack_math.py` (<- `build_packs_v2.py`). The packs themselves stay in
  `app/backend/tracker/baselines/`, read by `tracker/stats/baseline_ranks.py`
  (Stats) and `randall/coach/coach_tools_v2.py` (the coach).
  `tests/backend/test_vendored_sync.py` keeps `analyzer.py` in sync with
  `analyzer_v2.py` (AST comparison). `pack_math.py` is an intentional subset of
  `build_packs_v2.py` with different `MIN_GAMES` thresholds.

## History

The early July 2026 scripts (`scan_corpus.py`, `stats_demo.py`,
`analyze_game.py`, `falco_report.py`, `career_report.py`, `mine_shard.py`) were
archived on 2026-10-02; see `ssbmNucleus-archive/baseline-early.zip`
for what each did and the findings. `response_mining.py` stayed because
`mine_own_v2.py` uses it.

Layered design of the prototype: **parse -> events -> stats -> comparison ->
(future) AI coach.** The AI layer never sees raw frames; it gets computed facts.

### Historical data sources (July 2026 analysis)

- **Own replays:** a local Slippi replay folder (~20.8k games). Player identified by
  the most frequent connect code (`MINE_CONNECT_CODE` for `mine_own_v2.py`).
- **Pro packs:** e.g. Summit-11.zip (Desktop) — 419 console-recorded .slp; no
  netplay metadata, read characters from the game-start block. Good for named-pro
  style features only (tiny n per matchup).
- **Ranked at scale:** [erickfm/melee-ranked-replays](https://huggingface.co/datasets/erickfm/melee-ranked-replays)
  (HuggingFace, MIT) — ~1.19M anonymized ranked games, 1.43 TB, sharded by
  character x rank pair (platinum->master). FALCO folder alone = 244 GB / 36 shards.
  NOTE: anonymization strips `metadata.lastFrame` — don't filter on it.

### Findings from the July 2026 analysis

- **Execution stats compare across populations; outcome stats don't.** Outcome
  metrics (damage/conversion, kill %) are inflated by weak opponents — always
  compare within rank tier. This is why the HF rank sharding matters.
- From 294 master Falco-vs-Marth games, 1,491 out-of-shieldstun situations:
  aerial OOS is +EV at every level; shine OOS is +EV at mid-level but -EV with
  3.9% death rate at master.
- v1 miner gaps: "other" bucket (~25-30%) needs splitting; edgeguard deaths
  after regaining actionability aren't credited to the killer's conversion;
  grabs-from-shield need their own situation predicate.

### Roadmap (from 2026-07 brainstorm)

- Situation taxonomy (~40-60 canonical melee situations) each with option
  classifier + outcome
- SQLite situation/event store over the corpus
- Rank-percentile report card; "which pro are you" style fingerprint
- Combo maker/searcher; replay recorder with mods
- AI coach over the stats DB with tool access (shipped as Randall)
