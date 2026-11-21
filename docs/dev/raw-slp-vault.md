# Raw .slp vault: upload the replay once, derive in the viewer

Status (2026-11-12): client and server are finished; the server change is on the meleeWebsite
branch `raw-slp-vault`. Desktop raw upload is **on by default** (an explicit
`vault_raw_upload = False` in the local kv turns it off; there is no UI). Until the server is
deployed, the first raw mint of a cycle fails the kind echo check and that desktop stays on frames
for a day, so shipping the desktop first is safe. Supabase migrations, edge functions, R2 and Pages
change only on the owner's explicit approval, one step at a time.

## Why

Today the desktop frame-parses every game, uploads a derived bundle (`frames-v4`, ~60–70 KB gz) and
the phone plays exactly those bytes. That causes two problems:
- Every playback fix (rollback dedupe, laser angles, item shapes, stage timing) needs a new
  `DERIVER` and a full re-derive and re-upload of every user's library.
- The first sync is a long multi-stage chain.

Measured on 348 local replays:

| Format | Average size per game |
|---|---|
| raw `.slp` | 1,450 KB |
| gzip-6 | 308 KB |
| brotli-5 | 245 KB |

A JS walk of the finalized frames takes ~1.5 ms per game (worst file 22 ms) on a laptop.

So the cloud artifact becomes the **gzipped .slp**, uploaded once and never re-uploaded. A single JS
module ([lite-deriver.md](lite-deriver.md)) turns it into the bundle at view time. Python keeps
combos, conversions, stats and Randall, and those upload as metadata.

## Defaults chosen (2026-10-18, owner said "use your recommended defaults")

- **Codec:** `gz1` = gzip level 6, `mtime=0`, no filename. The phone already inflates with
  `DecompressionStream('gzip')`. Brotli only after a gated prod spike proves R2-stored
  `Content-Encoding: br` decodes in iOS/Android PWAs. The `codec` field makes a later switch safe.
- **Public shares (changed 2026-11-12, owner):** a share link serves the game's **raw `.slp`**
  and the page works it out with the same JS deriver as the phone, so links improve with every
  viewer fix. Games uploaded before raw replays keep serving their frames file until their raw
  copy arrives. The Oct 18 rule (frozen derived snapshots, because a `.slp` carries each player's
  Slippi UID) was dropped: that ID is no secret, every `.slp` posted anywhere carries it, and the
  snapshot was a second data path to maintain.
- **Daily byte cap:** 20 GB → 64 GB per user per day (a 100k library ≈ 31 GB at gz1). The 10-minute
  limits are unchanged: 60 claims and 2 GB.
- **Desktop Watch Lite:** switches to the JS deriver in the same release as raw upload. The Python
  `/lite/clip` path stays one release behind a setting.

## Desktop side: `app/backend/tracker/cloud/vault_raw.py`

This lives beside `vault_sync.py` and reuses its helpers (`content_hash`, the `vault_hashes` cache,
`SyncCancelled`, quota handling). It does not modify them.

```sql
CREATE TABLE IF NOT EXISTS vault_raw (
    game_id      INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,      -- sha256 of the UNCOMPRESSED .slp (same as vault_objects)
    codec        TEXT NOT NULL,      -- 'gz1'
    bytes        INTEGER NOT NULL,   -- compressed size actually PUT
    pushed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_vault_raw_hash ON vault_raw(content_hash);
```

Local bookkeeping only; nothing here ever deletes anything remote.

Conversions have a separate, additive `vault_raw_conv` ledger (`game_id`,
`content_hash`, `codec`, `bytes`, `pushed_at`). `commit_pending_conversions` plans
acknowledged raw games with exactly two indexed players, probes `kind: "conv"`
once per nonempty pass before parsing, then calls `load_trace` and
`detect_conversions(trace, port)` for actor indices 0 and 1, just like
`/lite/conversions`. The trace must also contain exactly two players. The wire
body is compact JSON `{"0":[...],"1":[...]}` compressed at gzip level 6 with zero
mtime and no filename (`json-gz1`). These coordinates are **TRUE Slippi frames**.

Each actual mint also requires an exact `kind: "conv"` echo before PUT. The
follow-up commit carries only `content_hash` and `conv_bytes`, with no `combos`
or frames/raw artifact fields. Only acknowledged hashes enter the ledger;
missing/changed files, failed parses/uploads and unacknowledged games remain
pending. Duplicate hashes share one upload. Cancellation is checked around
parse/transport/acknowledgement, and account replacement clears this ledger.

```python
RAW_CODEC = "gz1"

def ensure_raw_schema(conn) -> None
def compress_slp(path) -> bytes                    # gzip-6, mtime=0, deterministic
def plan_raw(conn, limit=None, newest_first=True, game_ids=None) -> list[item]
    # Same selection rules as vault_sync.plan() (parse_ok, not refused for this codec; newest first),
    # minus games already in vault_raw with codec == RAW_CODEC. Items look
    # like plan()'s: {id, path, mtime, size, ...}.
def push_raw(conn, items, mint_urls, put, commit=None, on_progress=None,
             batch=100, should_cancel=None, compress_workers=4, put_workers=6)
    -> {"pushed": n, "skipped": n, "failed": [(game_id, reason)], "timings": {...}}
```

- **Mint:** `mint_urls(list[{game_id, content_hash, bytes, codec}]) -> {content_hash: put_url}`. The
  wire call adds `"kind": "slp"`.
- **Put:** `put(url, body: bytes) -> None`, raising on failure. It must be thread-safe.
- **Commit:** `commit(list[{game_id, content_hash, bytes, codec}]) -> iterable[acked content_hash]`.
  The wire rows carry `slp_bytes`, `slp_codec` and `meta`, and **no `combos` key**. The raw-aware
  vault-sync leaves a game's combos untouched on a raw commit without `combos`. The current one does
  not: it deletes them for every committed game. So raw commits need the new server first.

Same safety contract as `vault_sync.push()`:
- commit only after the batch's objects are in R2;
- unacked games stay pending;
- one quiet retry on a transient batch failure;
- an HTTP 429 quota error waits in cancellable slices for up to one window (`QUOTA_WAIT_S`);
- `should_cancel()` is checked between steps;
- a missing local file is skipped and never ledgered;
- files the header check refuses (fewer than 2 players, unreadable) are recorded once, in the
  same spirit as `vault_skips`.

Throughput:
- Compression runs in a `ThreadPoolExecutor(compress_workers)`. `zlib` releases the GIL, so there is
  no process pool and no PyInstaller child spawn.
- PUTs run concurrently with `put_workers`.
- The next batch compresses while the current one uploads.
- **There is no peppi parse anywhere in this path.**

`timings` reports per-phase totals in seconds: `hash`, `compress`, `mint`, `put`, `commit`,
`quota_wait`. Each batch's timings also go to the logger at INFO, which finally makes slow first
syncs visible.

**Raw autorun order:** `index → raw push → combo pass → combos commit → conversions`.
Conversions require a frame parse and run last; playback never waits for this pass.

## Server side (meleeWebsite branch `raw-slp-vault`)

**Migration** (additive):

```sql
alter table public.vault_games
  add column if not exists slp_key   text,
  add column if not exists slp_bytes integer,
  add column if not exists slp_codec text;
```

A rollback file comes with it. The new columns are nullable, so old clients are unaffected.

**Object key:** `_shared/r2.ts` gets `slpObjectKey(uid, hash, codec)` →
`v1/{uid}/slp/{hash}.slp.gz`. This is a separate prefix from the legacy `v1/{uid}/games/{hash}.json.gz`.

**`vault-sync` changes:**
- `mint`:
  - `{token, kind?: "frames"|"slp"|"conv", items:[{content_hash, bytes, codec?}]}`;
  - `kind` defaults to `"frames"`, the current behaviour unchanged;
  - `kind:"slp"` requires `codec == "gz1"` and signs `content-type: application/gzip` for `slpObjectKey`;
  - same quota RPC.
  - `kind:"conv"` requires `codec == "json-gz1"`; `convObjectKey(uid, hash)` is
    `v1/{uid}/conv/{hash}.json.gz`. Slp and conv mints echo their kind, so an old
    server that ignores it cannot cause a client to overwrite frames objects.
- `commit`:
  - a game row may carry `slp_bytes` + `slp_codec`. Then the server sets
    `slp_key = slpObjectKey(uid, hash, codec)`; the client never sends a key;
  - a row with only slp fields must not require `deriver`/`bytes` for the frames blob;
  - `object_key` stays as it is for existing rows;
  - for a new slp-only row, `object_key` is null. That needs it to be nullable: check the current
    constraint and add `alter column object_key drop not null` in the migration if necessary;
  - `combos` absent on a raw commit → combos untouched. (Today a frames commit deletes every committed game's combos even when `combos` is omitted; the draft keeps that for frames commits and preserves combos only for raw ones.)
  - `conv_bytes` sets the server-derived `conv_key`. A sidecar-only commit uses
    an owner-scoped UPDATE of an existing game, leaving metadata, other artifact
    fields and combos untouched. Missing games are refused rather than invented.
- `audit` also checks the `slp/` prefix.

**`vault-read` `urls`:** returns `{urls: {hash: {frames?: url, slp?: url, conv?: url}}}`. During
migration it also keeps a legacy flat form, `{urls: {hash: url}}` (frames url), for old PWA builds,
for example via a `v: 2` request flag.

The mobile raw path reads `slp` and `conv` concurrently, inflates the sidecar and
merges it as `bundle.conversions` without frame translation. Absent, malformed or
unavailable sidecars retain `null` and the existing percent heuristic. An explicit
`{"0":[],"1":[]}` is authoritative and disables that heuristic. Frames playback
does not fetch or merge true-frame sidecars.

**`vault-public` (shares, 2026-11-12):** `mint` needs only a playable artifact
(`object_key` or `slp_key`) and inserts the share row; nothing is built or
uploaded at share time, on the desktop or the phone. Public `get` signs
`slp_key` when the game has one, else `object_key`, and adds `conv_url` for a raw
game with a conversions sidecar. A function deployed before the raw migration
falls back to the frames-only select (42703), so existing links keep working.

The replay Worker passes bytes through and does no processing: `/replay/_b/<id>`
streams whichever file `get` signed, `/replay/_c/<id>` streams the conversions
sidecar, and `/replay/_d/<id>` drops both signed URLs and reports `has_conv`.
The share page (`public-viewer.js` via `api.shareBundle`) recognises a raw file
by its `{U\x03raw` header, derives it in the same hashed derive worker as the
vault, and puts the parser's row map in `meta.row_fids`/`row_first`, so
`snapshotComboFrame` maps the cloud's ROW-basis combos exactly as
`api.comboFrame` does. A frames file is parsed as before.

**Additional migration:** `20261020_vault_conv_sidecar.sql` adds nullable
`vault_games.conv_key` and `conv_bytes`; its rollback removes them and leaves
stored objects alone.

No R2 CORS change is needed: browsers only read through the Worker and the
signed GET URLs, and nothing is PUT from a phone.
**Quota:** `api_claim_vault_upload` daily byte cap 21474836480 → 68719476736.

## Phases

The full plan is kept in the notes from the planning session. Short form:
1. JS deriver.
2. Parity audit vs peppi (`tools/liteaudit/`).
3. Desktop Watch Lite on the JS deriver.
4. Frame basis. **Decision (2026-10-18): cloud combos stay in the ROW basis (`start_rf`) for every
   upload, old and new.** A client that derives from the raw `.slp` translates them with the parser's
   `rowFids` (`true = rowFids[rf - firstFrame]`). A client playing a legacy frames-v4 bundle uses them
   directly, because those rows ARE the row basis. This needs no schema flag and no re-commit. Local
   desktop combos keep both columns. Conversions (Python `trace.at`) are TRUE frames and need no
   translation against a raw-derived bundle.
5. Conversions sidecar `conv/{hash}.json.gz` (draft implemented).
6. Desktop raw push (`vault_raw.py`).
7. Server drafts.
8. PWA dual path (prefers `slp`, falls back to `frames`).
9. Gated rollout: server → PWA and share page → desktop release (raw on by default) → much later, approved cleanup of old frames blobs.
