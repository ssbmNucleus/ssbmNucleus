# Vault Storage Migration: `metadata.json` → SQLite

**Status:** IMPLEMENTED (Phases 0, 1, 3, 4 done; Phase 2 — structural reorder — deferred).
Behind `NUCLEUS_VAULT_DB`; shipped builds default to the DB backend with dual-write.
**Author:** (drafted with Claude) — 2026-06-30
**Target release line:** post-0.4.x (0.5.x)
**Scope:** Backend (Python/Flask) + one launcher-env line. **No C# changes. No frontend changes.**

---

## 1. Executive summary

The desktop app stores all vault state in a single `storage/metadata.json` blob that is
read-modify-written (RMW) from ~20 backend modules. Two recurring problems motivate this work:

1. **Ordering bugs.** Costume and stage-variant order is encoded as *list position* inside
   the JSON. The displayed list appends "disk-only" entries that aren't in the metadata list,
   so frontend indices drift from the metadata indices — the direct cause of the
   `"Invalid fromIndex or toIndex"` class of bugs (most recently the 0.4.3 DAS reorder bug).
2. **Concurrency.** Concurrent writes are band-aided with an **in-process** `threading.RLock`
   plus atomic temp-file + `os.replace`. The lock does not protect against multiple processes,
   and every mutation rewrites the whole ~1 MB file.

SQLite fixes both: an explicit `sort_order` column with stable-ID reorders eliminates the
index bug class entirely, and WAL-mode transactions replace the lock/atomic-write dance with
real ACID writes that are also safe across processes.

### Two findings that change the original scope

The original task framing flagged **C# coupling as the main risk** and assumed the frontend
might read the file directly. **Investigation disproved both:**

- **C# (`MexManager`/`MexCLI`) never touches the vault `metadata.json`.** A grep across all
  217 `.cs` files found zero references to it. C# serializes its *own* project-workspace files
  (`mex.json`, `css.json`, `sss.json`, `series.json`, `music.json`, `scene.json`, per-fighter
  `NNN.json`) via `MexJsonSerializer` in `<ssbmNucleus-mex>/mexLib/MexProject.cs`. The
  Python↔C# boundary is purely command/argument based (`app/backend/mexcli/`). ⇒
  **There is no C# work and no "generated JSON view" needed.**
- **Frontend/Electron never read `metadata.json` directly** — all vault state flows through the
  Flask REST API. ⇒ **No frontend changes are required** as long as API response shapes are
  byte-compatible.

This reduces the project to a self-contained backend refactor, which is reflected in the phasing
below.

---

## 2. Goals and non-goals

### Goals
- Move authoritative vault state from `metadata.json` to a single SQLite DB (`storage/vault.db`).
- Replace list-position ordering with an explicit, stable `sort_order` (kills the reorder bug class).
- Replace the global RMW lock with per-transaction SQLite concurrency (WAL).
- **Lossless, validated, reversible migration** for existing users (both dev `storage/` and the
  installed `%LOCALAPPDATA%\SSBM Nucleus\storage`).
- Ship behind a feature flag; the JSON path keeps working until the DB path is proven.
- Substantially expand automated test coverage of the storage layer (characterization +
  equivalence + concurrency + migration tests), as a safety net for the refactor.

### Non-goals (this project)
- Migrating the C# project-workspace JSON files (separate format, separate concern).
- Migrating the **menu-mod catalogs** (`menus/*` `metadata.json` and per-mod `mod.json`) — these
  are *different files* that happen to reuse the `load_metadata`/`save_metadata` helper via a
  custom `path=` argument. They stay JSON. (Could be a future follow-up.)
- Changing any REST API request/response shapes.
- Cross-machine sync / server backend (out of scope; single local file remains).

---

## 3. Current-state analysis

### 3.1 Storage location

`STORAGE_PATH / 'metadata.json'`, where `STORAGE_PATH = PROJECT_ROOT / 'storage'`
(`backend/core/config.py`). `PROJECT_ROOT` is the repo root in dev and
`%LOCALAPPDATA%\SSBM Nucleus` in the installed (frozen) build. Current sizes: ~992 KB (dev),
~1.1 MB (installed) — small enough that whole-file operations are cheap, but large enough that
rewriting it on every mutation is wasteful.

The new DB will live alongside it at `STORAGE_PATH / 'vault.db'` (+ `-wal`/`-shm` sidecar files).

### 3.2 Full schema (top-level keys)

```
{
  "version": "1.0",
  "characters":        { <CharName>: { "skins": [...], "extras": {...} }, ... },   # dict, ~26
  "stages":            { <stage_key>: { "variants": [...] }, ... },                # dict, 6
  "xdelta":            [ {...}, ... ],                                             # list
  "custom_characters": [ {...}, ... ],                                            # list
  "custom_stages":     [ {...}, ... ],                                            # list
  "bundles":           [ {...}, ... ]                                             # list
}
```

**`characters[name].skins[]`** (costumes) — fields observed:
`id, color, costume_code, filename, has_csp, has_stock, csp_source, stock_source, date_added,
slippi_safe, slippi_tested, slippi_test_date, slippi_manual_override, has_hd_csp,
hd_csp_resolution, hd_csp_size, csp_hash, alternate_csps[], active_csp_id, dat_hash`,
plus IC-pairing fields used by code (`is_popo, is_nana, paired_nana_id, paired_popo_id, visible`)
and folder fields (`type:'folder'` entries inline in the list, items carry `folder_id`).
`alternate_csps[]` = ordered list of `{id, filename, pose_name, is_hd, timestamp}`.

**`characters[name].extras`** — heterogeneous per character:
`laser, sideb, upb, shine, gun, laser_ring` (Fox/Falco), each an ordered list of
`{id, name, date_added, source, ...}` with an arbitrary nested `modifications` dict (or
`model_file` for `gun`). These are effectively free-form JSON.

**`stages[key].variants[]`** —
`id, name, filename, has_screenshot, date_added, slippi_safe, slippi_tested, slippi_test_date`;
ISO-scan variants may lack `filename` and instead carry `source, md5`. Folders inline as
`{type:'folder', id, name, expanded}`; variants carry `folder_id`.

**`xdelta[]`** — `{id, name, description, filename, created}`.

**`custom_characters[]`** —
`{slug, name, source, date_added, series_id, costume_count, has_css_icon, costume_meta[],
added_skins[], victory_theme{}, has_announcer}`. `costume_meta[]` and `added_skins[]` are
ordered lists; `added_skins[]` entries have the same shape as canonical skins.

**`custom_stages[]`** —
`{slug, name, source, date_added, series_id, sound_bank, dat_files[], has_banner, has_icon,
playlist[]}`. Note real-world unicode in data (e.g. `"Peach�s Castle 64"`).

**`bundles[]`** —
`{id, name, description, build_name, filename, size, size_mb, texture_count, created}`.

> ⚠️ This enumeration is *observed*, not authoritative. Real users' files will contain fields
> not seen here. The migration design (§5.3) uses a per-table `extra_json` catch-all so any
> unmodeled field round-trips untouched.

### 3.3 The ordering bug class (core motivation)

Costumes (`skins[]`) and stage variants (`variants[]`) are ordered lists; folders are inlined as
entries in the *same* list. The frontend computes drag `fromIndex`/`toIndex` against a **display
list** that the backend has to *reconstruct* server-side because it appends "disk-only" entries
(zips on disk with no metadata entry). See `display_ordered_stage_variants()` and
`reorder_stages()` in `backend/vault/routes/storage_stages.py`, and the costume equivalents in
`backend/vault/routes/storage_costumes/`:

```python
display, hidden = display_ordered_stage_variants(stage_data, stage_folder)
if from_index < 0 or from_index >= len(display) or ...:   # <-- the 400 that bites users
    return ... 'Invalid fromIndex or toIndex'
entry = display.pop(from_index); display.insert(to_index, entry)
stage_data['variants'] = display + hidden
```

With stable IDs + a `sort_order` column, reorder becomes *"place item X between Y and Z"* (by ID),
computed in a single transaction. There is no index arithmetic and no disk-only drift, so the bug
class disappears.

### 3.4 Concurrency model today

- `core/state.py` defines `metadata_lock = threading.RLock()` (in-process only).
- Mutation sites either go through `core.metadata.save_metadata` or write directly with
  `tempfile` + `os.replace` under `metadata_lock` (see `custom_characters.py`, `custom_stages.py`,
  `bundles.py`, `das.py`).
- This protects threads in one process but not multiple processes, and rewrites the whole file
  per mutation. SQLite WAL + transactions supersede all of it and add cross-process safety.

### 3.5 Call-site inventory

There are **two classes** of access. A clean migration depends on funneling *both* through one
data-access layer (DAL) before flipping storage.

**(A) Helper-routed** — `from core.metadata import load_metadata, save_metadata` (default path):

| Module | Notes |
|---|---|
| `vault/routes/storage_costumes/` | ~54 calls — the largest surface (list/reorder/folders/CSP/slippi) |
| `vault/routes/storage_stages.py` | ~25 calls (variants/reorder/folders/slippi/screenshot) |
| `vault/routes/poses.py` | 4 load / 3 save |
| `vault/importing/unified/{characters,archive,stages,effects}.py` | import-time read+append |
| `projects/routes/test_in_game.py` | read-only |
| `vault/menus/store.py` | **OUT OF SCOPE** — reuses helper with custom `path=` for menu-mod catalogs / `mod.json` |

**(B) Direct-access** — bypass the helper, open `STORAGE_PATH / 'metadata.json'` directly:

| Module | Owns | Notes |
|---|---|---|
| `vault/catalog/bundles.py` | `bundles` | `_load_bundles`/`_save_bundles`, locked + atomic |
| `vault/catalog/custom_characters.py` | `custom_characters` | `METADATA_FILE` const, atomic append under lock |
| `vault/catalog/custom_stages.py` (reads), `vault/routes/custom_stages.py` (writes) | `custom_stages` | same pattern |
| `vault/routes/das.py`, `projects/routes/das.py` | stage `variants` | 4 direct reads/writes |
| `vault/routes/extras/colors.py` | character `extras` | 5 direct accesses |
| `vault/routes/extras/models.py` | character `extras` (gun/etc.) | 3 direct accesses |
| `projects/routes/mod_export.py` | reads whole blob | export packaging |
| `duel_assembler.py` | reads whole blob | own `_load_metadata()`, read-only |

**Read-only consumers** (must keep getting a faithful blob/view): `mod_export.py`,
`duel_assembler.py`, `test_in_game.py`, and the GET `/api/mex/storage/metadata` endpoint
(`get_storage_metadata` returns the entire blob as `{success, metadata}`).

### 3.6 Existing tests

`tests/backend/` has ~24 pytest files (incl. `test_metadata_concurrency.py`,
`test_storage_stages.py`, `test_delete_costume_cleanup.py`). There is **no `conftest.py`** (each
test does its own `sys.path` insert) and **no CI** (`.github/workflows` absent). Tests
monkeypatch the blueprint-level names, e.g.:

```python
monkeypatch.setattr(ss, 'load_metadata', lambda: meta)
monkeypatch.setattr(ss, 'save_metadata', lambda m: None)
monkeypatch.setattr(ss, 'STORAGE_PATH', tmp_path)
```

This is the **key seam**: as long as `load_metadata`/`save_metadata` remain the public API with
the same blob shape, existing tests and call sites keep working while the backend swaps underneath.

---

## 4. Target architecture

### 4.1 Storage
- One SQLite file, `storage/vault.db`, **WAL** mode, `foreign_keys=ON`, `busy_timeout` set
  (e.g. 5 s) to ride out transient Windows file locks (antivirus, indexer).
- All writes wrapped in transactions; the `metadata_lock` / atomic-write dance is removed in
  the modules that fully move to the DAL.

### 4.2 Data-access layer (DAL): `core/vault/`
Introduce a repository module that is the **single** entry point for vault state. It exposes
**two tiers** so we can migrate incrementally:

1. **Whole-blob compatibility API** (keeps every existing call site working):
   - `load_metadata()` → materializes the exact legacy blob shape from the DB (or reads JSON in
     JSON-mode).
   - `save_metadata(blob)` → in DB-mode, upserts the blob into tables inside one transaction
     (in JSON-mode, writes the file). Crucially, in DB-mode `save_metadata` **preserves existing
     `sort_order`** for known IDs and only assigns new order to new IDs — so a legacy call site
     that merely edits a field never reshuffles order.
2. **Granular repository methods** used by hot/buggy paths:
   - e.g. `costumes.reorder(owner, item_id, before_id|after_id|index)`,
     `costumes.set_folder(item_id, folder_id)`, `stages.add_variant(...)`,
     `folders.create/rename/delete/toggle(...)`.
   - These run as small transactions and are where the ordering fix actually lands.

The GET `/api/mex/storage/metadata` endpoint and read-only consumers use tier-1 `load_metadata()`
(materialized view), guaranteeing the API stays shape-compatible.

> **Design tension to note for the reviewer:** the tier-1 shim alone changes *storage* but not
> *behavior* — if it round-trips list→DB→list by position, ordering bugs persist. The fix comes
> from migrating reorder/folder endpoints to tier-2 (§ Phase 2). The shim is the bridge, not the
> cure.

### 4.3 Schema (proposed)

Hybrid relational + JSON: relational columns for everything we order/query/filter; a JSON text
column for heterogeneous/nested bits; and an `extra_json` catch-all on every table so unmodeled
fields survive.

```sql
-- bookkeeping
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT);   -- e.g. ('schema_version','1'), ('source_json_version','1.0')

-- folders (shared by costume groups and stage groups)
CREATE TABLE folders (
  id          TEXT PRIMARY KEY,            -- 'folder_xxxxxxxx'
  owner_kind  TEXT NOT NULL,               -- 'character' | 'stage' | 'custom_character'
  owner_id    TEXT NOT NULL,               -- char name | stage key | custom slug
  name        TEXT NOT NULL,
  expanded    INTEGER NOT NULL DEFAULT 1,
  sort_order  INTEGER NOT NULL,
  extra_json  TEXT
);

-- costumes (canonical character skins AND custom-character added_skins)
CREATE TABLE costumes (
  id          TEXT PRIMARY KEY,            -- skin id
  owner_kind  TEXT NOT NULL,               -- 'character' | 'custom_character'
  owner_id    TEXT NOT NULL,               -- char name | custom slug
  color TEXT, costume_code TEXT, filename TEXT,
  has_csp INTEGER, has_stock INTEGER, csp_source TEXT, stock_source TEXT,
  date_added TEXT,
  slippi_safe INTEGER, slippi_tested INTEGER, slippi_test_date TEXT, slippi_manual_override TEXT,
  has_hd_csp INTEGER, hd_csp_resolution TEXT, hd_csp_size TEXT, csp_hash TEXT,
  active_csp_id TEXT, dat_hash TEXT,
  is_popo INTEGER, is_nana INTEGER, paired_nana_id TEXT, paired_popo_id TEXT, visible INTEGER,
  folder_id   TEXT REFERENCES folders(id) ON DELETE SET NULL,
  sort_order  INTEGER NOT NULL,
  extra_json  TEXT
);
CREATE INDEX ix_costumes_owner ON costumes(owner_kind, owner_id, sort_order);

CREATE TABLE alternate_csps (
  id TEXT PRIMARY KEY, costume_id TEXT NOT NULL REFERENCES costumes(id) ON DELETE CASCADE,
  filename TEXT, pose_name TEXT, is_hd INTEGER, timestamp TEXT,
  sort_order INTEGER NOT NULL, extra_json TEXT
);

-- per-character "extras" (laser/sideb/upb/shine/gun/laser_ring); modifications kept as JSON
CREATE TABLE character_extras (
  id TEXT PRIMARY KEY, character TEXT NOT NULL, extra_type TEXT NOT NULL,
  name TEXT, date_added TEXT, source TEXT, model_file TEXT,
  modifications_json TEXT, sort_order INTEGER NOT NULL, extra_json TEXT
);

CREATE TABLE stage_variants (
  id TEXT PRIMARY KEY, stage TEXT NOT NULL,
  name TEXT, filename TEXT, has_screenshot INTEGER, date_added TEXT,
  slippi_safe INTEGER, slippi_tested INTEGER, slippi_test_date TEXT,
  source TEXT, md5 TEXT,
  folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
  sort_order INTEGER NOT NULL, extra_json TEXT
);
CREATE INDEX ix_variants_stage ON stage_variants(stage, sort_order);

CREATE TABLE custom_characters (
  slug TEXT PRIMARY KEY, name TEXT, source TEXT, date_added TEXT, series_id TEXT,
  costume_count INTEGER, has_css_icon INTEGER, has_announcer INTEGER,
  victory_theme_json TEXT, sort_order INTEGER NOT NULL, extra_json TEXT
);
-- bundled costumes for a custom character (the costume_meta list)
CREATE TABLE custom_character_costumes (
  id TEXT PRIMARY KEY, custom_slug TEXT NOT NULL REFERENCES custom_characters(slug) ON DELETE CASCADE,
  sort_order INTEGER NOT NULL, data_json TEXT NOT NULL   -- shape varies; keep whole entry as JSON
);

CREATE TABLE custom_stages (
  slug TEXT PRIMARY KEY, name TEXT, source TEXT, date_added TEXT, series_id TEXT,
  sound_bank TEXT, has_banner INTEGER, has_icon INTEGER,
  dat_files_json TEXT, playlist_json TEXT, sort_order INTEGER NOT NULL, extra_json TEXT
);

CREATE TABLE bundles (
  id TEXT PRIMARY KEY, name TEXT, description TEXT, build_name TEXT, filename TEXT,
  size INTEGER, size_mb TEXT, texture_count INTEGER, created TEXT,
  sort_order INTEGER NOT NULL, extra_json TEXT
);

CREATE TABLE xdelta (
  id TEXT PRIMARY KEY, name TEXT, description TEXT, filename TEXT, created TEXT,
  sort_order INTEGER NOT NULL, extra_json TEXT
);
```

**Ordering representation.** Use an integer `sort_order`. On reorder, **renumber the affected
group in one transaction** (groups are at most a few hundred rows — trivially cheap). This is the
simplest *correct* option. Fractional/gap indexing is noted as a future optimization but is not
needed at this scale. The `meleeWebsite` sibling project already uses a `sort_order` column, so
this is a known-good pattern in the codebase family.

**Why JSON columns for some fields:** `extras.modifications`, `victory_theme`, `playlist`,
`dat_files`, and `custom_character_costumes` entries are heterogeneous and never queried
relationally — storing them as JSON text preserves them exactly with zero risk of field loss,
while the *ordered/queried* parts (sort_order, folder_id, slippi flags, dat_hash) get real columns.

### 4.4 Concurrency
- Reads: plain `SELECT` (WAL allows readers during a writer).
- Writes: `BEGIN IMMEDIATE` … `COMMIT` per logical operation; `busy_timeout` handles contention.
- The in-process `metadata_lock` becomes unnecessary for DAL-routed writes and is removed in
  modules that fully migrate (kept only where a non-DB resource still needs serializing, if any).

---

## 5. Migration strategy (correctness is paramount — many existing users)

### 5.1 Principles
- **Backup first, never destroy.** Copy `metadata.json` → `metadata.json.bak.<ISO8601>` before
  anything. The original JSON is *not* deleted even after a successful migration (the flag decides
  which store is authoritative).
- **Validated.** After building the DB, materialize the blob back out and **deep-diff** it against
  the original (order-insensitive on dicts, order-*sensitive* on the lists that carry ordering).
  If they differ, **abort**, log the diff, leave the flag on JSON. Migration success = provable
  round-trip equality.
- **Catch-all.** Every table has `extra_json`; the importer routes any unmodeled key there so the
  diff stays clean even for fields this plan didn't enumerate.
- **Idempotent.** Re-running detects an existing up-to-date `vault.db` (via `schema_meta`) and
  no-ops; a `--force` re-imports from the backup.
- **Reversible.** A `vault-export-json` command regenerates `metadata.json` from the DB at any
  time; flipping the flag back to JSON resumes the JSON path with no data loss.
- **Both vaults.** The migration runs wherever `STORAGE_PATH` points — dev `storage/` and the
  installed `%LOCALAPPDATA%\SSBM Nucleus\storage`. On the user's machine it runs once at app
  startup (hook in `backend/shared/vanilla_extract/first_run_setup.py` / startup), is fully logged, and is **non-fatal**:
  any error falls back to the JSON path so a user is never blocked from launching.

### 5.2 Schema versioning
`schema_meta('schema_version', N)` drives a tiny forward-migration runner (list of idempotent
`vNtovN+1` steps). This is what `metadata.json`'s unused `version: "1.0"` should have been.

### 5.3 Validation corpus
Migration tests run against: the dev file, a copy of an installed file, and synthetic edge cases —
folders + items with `folder_id`, disk-only variants, ISO-scan variants without `filename`,
unicode names (`Peach�s Castle 64`), empty/missing top-level keys, custom chars with
`costume_meta` + `added_skins`, Fox `extras` with nested `modifications`.

---

## 6. Rollout / feature flag

- **Flag:** `NUCLEUS_VAULT_DB` (env) and/or a `user_settings.json` key, resolved in
  `core/config.py` → `VAULT_BACKEND ∈ {json, db}`.
- **Default:** `json` until the DB path is proven on real data; then default `db` with JSON export
  retained as a fallback.
- **Canary (dual-write):** an optional intermediate mode where DB is authoritative but every
  commit also re-exports `metadata.json` (so a downgrade/rollback loses nothing). Drop dual-write
  once confident.
- **Safety valve:** on any DB open/migrate error, log and fall back to `json` for that session.
- **Backups:** add `vault.db` (+ backup JSON) to the `ssbm-backup` mirror tooling
  (see `mod-pool-backup`).

---

## 7. Phased implementation plan

Each phase is independently shippable, keeps tests green, and does not change API shapes.

**Phase 0 — Safety net & seam (no behavior change, JSON still authoritative)** — ✅ DONE (except CI)
- ✅ Added `tests/backend/conftest.py` with the `vault` fixture (temp vault wired to the REAL
  `core.metadata` IO + Flask client helper), so its tests are backend-agnostic.
- ✅ Wrote **characterization tests** locking in current behavior:
  `test_storage_characterization.py` (costumes/stages: read, reorder incl. the disk-only edge
  case, move-to-top/bottom, folder lifecycle, set-folder), `test_extras_metadata.py`
  (extras create/list/delete), `test_bundles_metadata.py` (bundles + sibling-key safety).
- ✅ Turned `core.metadata` into the DAL: **atomic** `save_metadata` (was a plain write) + a
  locked `metadata_transaction()` primitive; moved `metadata_lock` here (re-exported from
  `core.state`). Unit-tested in `test_metadata_dal.py`.
- ✅ Funnelled ALL **direct-access** modules (§3.5 B) through the DAL: `custom_characters`,
  `custom_stages`, `bundles`, `das`, `extras/colors`, `extras/models`, `mod_export`,
  `duel_assembler`. Full suite green (356 passed).
- ⏳ TODO: add CI (`.github/workflows`) running `pytest` (windows-latest; scope to the hermetic
  storage/DAL tests first).

**Phase 1 — SQLite backend behind the flag (default off)** — ✅ DONE
- ✅ `core/vault/` implements the SQLite backend. Design: each reorder-prone collection (skins,
  stage variants) + extras + top-level lists is decomposed into ROWS with an explicit
  `sort_order`, while every row stores its entry VERBATIM as `data_json` and a `__skeleton__`
  copy holds all non-decomposed structure with those lists emptied. This guarantees a provably
  lossless round-trip and still gives Phase 2 real `sort_order` rows to mutate.
- ✅ `config.VAULT_BACKEND` flag (env `NUCLEUS_VAULT_DB`, default `json`); `core.metadata`
  `load_metadata`/`save_metadata` dispatch JSON vs DB (explicit `path=` always stays JSON). DB
  writes are single transactions; WAL + `busy_timeout` on the connection.
- ✅ `migrate_json_to_db` (backup + **round-trip-validation gate** → raises on mismatch),
  `export_db_to_json` (reversibility), `ensure_migrated` (startup hook, wired in `app.py`
  with fall-back-to-JSON on failure so the vault never reads empty).
- ✅ Tests: `test_vault_db_roundtrip.py` (synthetic edge cases + the **real dev metadata.json** +
  migration/backup/export/ensure_migrated) and `test_backend_equivalence.py` (same ops on
  `{json, db}` via the `dual_backend` fixture). Full suite 385 passed. Caught + fixed one edge
  case: `extras._vanilla_laser` is a dict, not a list — the catch-all preserved it.
- Note: the round-trip round-trips the WHOLE blob (tier-1). Ordering is still by list position
  until Phase 2 wires reorder to `sort_order`.

**Phase 2 — Kill the reorder bug class** — ⏸️ DEFERRED (needs a frontend rework)
- Investigation (2026-06-30): the reorder bug is in endpoint *logic* (index-based drag reorder vs
  a server-reconstructed display order), not storage. move/folder/set-folder are already ID-based;
  only drag-`reorder` is index-based, the frontend already sends adjacent index swaps
  (`frontend/src/projects/characters/useCostumes.js`), and the drift is already band-aided by display reconstruction.
  Phase 1's design already writes an explicit `sort_order` on every save, and equivalence tests
  confirm reorder works correctly through the DB backend.
- The remaining *structural* fix (ID-based reorder that can't drift) requires reworking the
  frontend's adjacent-swap drag queue — out of the backend-only migration scope. **Deferred to a
  separate, deliberate change** with preview verification. Not required for the migration.

**Phase 3 — Rollout: dual-write canary + flip the default** — ✅ DONE
- ✅ Dual-write (`config.VAULT_DUAL_WRITE`, default on): in DB mode every save also mirrors
  `metadata.json`, so it stays a live rollback backup and any `path=` JSON consumer (duel
  assembler) keeps seeing current data. Disable via `NUCLEUS_VAULT_DUAL_WRITE=0` once DB is proven.
- ✅ Flipped the shipped default to DB via the launcher (`electron/main.js` sets
  `NUCLEUS_VAULT_DB=1` for packaged builds), not `config.py` — so dev/tests stay on JSON and the
  swap is reversible + doesn't surprise-migrate a dev vault. First launch runs `ensure_migrated`
  (backup + round-trip gate) and falls back to JSON on any error.
- Skipped (per Phase 2 finding): rewriting the already-working mutators to granular repo methods —
  the whole-blob DB path is correct and fast enough at vault scale. `metadata_lock`/atomic-write
  code is retained (still used by the JSON path + `path=` writers).

**Phase 4 — Cleanup & docs** — ✅ DONE
- ✅ Vault backup/restore made DB-aware: `vault.db` (+ WAL sidecars) is excluded from backups
  (it's a rebuildable cache; naively zipping a live WAL DB is unsafe) and rebuilt from the
  restored/merged `metadata.json` on restore (`_sync_db_after_restore`). Tests in
  `test_vault_backup_blueprint.py`.
- ✅ Updated `docs/dev/ARCHITECTURE.md` (Core Modules + directory structure) and this doc.
- No JSON-path removal: JSON is retained indefinitely as the portable/fallback format (decision
  §10.2). `metadata_lock`/atomic-write code stays (JSON path + `path=` writers still use it).
- Full suite: 391 passed.

---

## 8. Testing strategy (explicit ask: expand coverage, fill gaps)

Tests are written **first** (Phase 0) so the refactor is provably behavior-preserving.

1. **Characterization / API-contract tests** — for each endpoint in `storage_costumes/`,
   `storage_stages.py`, `poses.py`, `import_unified/*`, `bundles.py`, `custom_characters.py`,
   `custom_stages.py`, `das.py`, `extras/*`: seed a fixture vault, hit the endpoint, snapshot the
   JSON response and the resulting stored state.
2. **Backend-equivalence tests** — the *same* suite parametrized over `{json, db}`; identical
   inputs must produce identical API responses. This is the core proof that the migration is
   transparent.
3. **Migration / round-trip tests** — for the validation corpus (§5.3): migrate → materialize →
   deep-diff equals original; assert backup created; assert idempotent re-run; assert
   `vault-export-json` reproduces the file.
4. **Ordering tests** — reproduce the historical bugs (disk-only `fromIndex/toIndex`, DAS variant
   reorder) and assert they're fixed under the DB backend.
5. **Concurrency tests** — port `test_metadata_concurrency.py` to the DB: N threads importing /
   reordering concurrently, assert no lost updates and consistent final order. (Bonus: a
   multi-*process* variant, since the old lock couldn't cover that.)
6. **Gap-filling** — areas currently thin: folder operations, custom-character `costume_meta`
   handling, extras CRUD, bundles list integrity, unicode handling. Add targeted unit tests for
   the DAL methods directly (not just via HTTP).

---

## 9. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Data loss / field drop on migrate | Med | Backup-first; round-trip deep-diff gate; `extra_json` catch-all; dual-write canary |
| Unmodeled fields in real users' files | High | `extra_json` per table; diff gate catches anything missed |
| Ordering shim doesn't actually fix bugs | Med | Explicit: fix lands in Phase 2 tier-2 ops, not the shim |
| Windows file-locking (AV/indexer) on `vault.db` | Low | WAL + `busy_timeout`; retry; non-fatal fallback to JSON |
| Migration fails on user machine at upgrade | Med | Runs once at startup, fully logged, **non-fatal** → JSON fallback |
| PyInstaller frozen build missing sqlite | Very low | `sqlite3` is stdlib, always bundled; add a smoke test in the packaged build |
| Hidden consumer we didn't find | Low | Phase 0 funnels all access through one seam; grep-verified inventory in §3.5 |

---

## 10. Decisions (resolved 2026-06-30)

1. **Ordering:** ✅ Integer `sort_order` with **renumber-on-reorder** (simplest correct option).
   Fractional/gap indexing deferred as a future optimization only if scale ever demands it.
2. **JSON fallback longevity:** ✅ **Keep the JSON export path indefinitely** as a safety valve
   (`vault-export-json` + on-error fallback). Do not retire it.
3. **C# / external consumers:** Treated as confirmed — no C# work; vault `metadata.json` is
   backend-private (re-verify if any undocumented consumer surfaces).
4. **Menu-mod catalogs:** Stay JSON (out of scope); possible future follow-up.
5. **Canary cadence:** TBD nearer Phase 3 (dual-write duration + which release flips default to `db`).

### Kickoff
Proceeding with **Phase 0** (safety net + DAL seam) now; no storage backend change in this phase.
