# Mobile Vault — your replay library, on your phone

**Design proposal (2026-08-15). Nothing described here is built.** Supersedes
`mobile-clip-sharing.md` (same file, renamed), which proposed public share links
as v1. That premise was wrong — see [Rejected](#rejected-and-why). Measurements
in this doc were taken 2026-08-15 against a live backend with 22,381 games
indexed; code references were verified the same day.

Research-tier doc: describes a thing we might build. If it gets built, the
durable parts move into `ARCHITECTURE.md` / `API_REFERENCE.md`.

---

## The product

You open your phone. Your entire replay library is there — every game, every
combo, filterable, watchable. Not recordings. The actual replays, rendered.

The thing that makes this worth building is **scale without recording**. Any
player can screen-capture one combo and post it. Nobody can browse eleven
thousand of their own games from the couch. That is the feature, and it is why
the payload is derived data rather than video.

The thing that makes it *cheap* is that Watch Lite already renders replays with
no native code. `.slp` parsing, combo detection and animation geometry all
happen once on the desktop at index time, and what comes out is small JSON. The
phone needs a canvas and a fetch.

## Decisions

| Decision | Value |
|---|---|
| Transport | Cloud vault (R2 + Supabase). Desktop does **not** need to be on. |
| Gating | Patreon-only. Owner key is `patreon_user_id`. |
| Sync model | One "Sync" button, whole library, incremental, **append-only**. No per-replay UI. |
| v1 payload | Derived data only. Raw `.slp` archive deferred. |
| Animation geometry | Per-character packs, cached on device. **Not** per-clip slices. |
| Client | Mobile web app, PWA later. Native app is a separate project. |
| Sharing | Deferred entirely. See [Later](#later). |

---

## Measurements

Everything below is measured, not estimated. This is the section to distrust
first if something later doesn't add up.

### The payload is almost entirely animation geometry

One game (194s, two characters), through the existing
`GET /api/nucleome/lite/clip/<id>`:

| | total gzipped | `anim` | `bundle` (frame data) |
|---|---|---|---|
| 10s clip (600 frames) | 1,083 KB | **1,068 KB — 99%** | 8 KB — 1% |
| whole game (11,701 frames) | 3,107 KB | **2,978 KB — 96%** | 87 KB — 3% |

`anim` grew 2.8× from a 10s clip to a whole game while `bundle` grew 10.9×,
because a full game touches most of a character's animation set while frame data
scales linearly. A whole-game `anim` slice is therefore ≈ a full character pack:
**~1.5 MB gzipped per character.**

**This inverts the previous design.** `clip_render.anims_for_clip()` narrows
animations to exactly what one clip touches — optimal for a stranger who loads
one clip and never returns, pessimal for a vault where you watch fifty Falco
clips in a sitting and re-download Falco's animations fifty times.

For a 12,389-game library:

- animations shipped separately, once per character: **1.03 GB**
- animations inlined per game, as previously designed: **36.7 GB**

36×. Per-character packs are not an optimisation, they are the difference
between viable and not.

There is no "uncached character" problem to solve: all 26 packs exist and are
already served. A character you haven't watched yet is a 1.5 MB download you
haven't done yet.

### Frame data cost

Fitted across 7 games spanning 4s–213s: **0.54 KB gzipped per second of
gameplay** (samples 0.45–0.67). Mean game 107.1s over a 200-game sample →
**57.8 KB per game**, against ~1,536 KB for the raw `.slp`.

| library | games | derived | storage/mo | first sync (Class A writes) |
|---|---|---|---|---|
| the author's, indexed | 22,381 | 1.23 GB | $0.02 | $0.10 |
| 5× that | 111,905 | 6.17 GB | $0.09 | $0.50 |
| 10× that | 223,810 | 12.34 GB | $0.19 | $1.01 |
| 50× that | 1,119,050 | 61.72 GB | $0.93 | $5.04 |

R2 at $0.015/GB-month with zero egress; Class A writes at $4.50/million.

**Storage is not a constraint.** Even the absurd case is under a dollar against
a $5 tier — and it is absurd: 1.1M games is 33,000 hours, thirty years of
playing three hours a day. A realistic heavy patron is 3–5× the author's
library, so single-digit cents. A thousand patrons averaging 2× is ~$37/month.

**The first sync is CPU-bound, not bandwidth-bound.** Measured through the real
deriver (`vault_sync.dry_run`, 60 games): 57.3 KB per game — corroborating the
57.8 KB fitted from the clip endpoint by a different route — but **0.32 seconds
per game to derive**, because every replay must be frame-parsed. A full 21,216-
game library is **1.16 GB and ~1.9 hours of derivation**, against roughly 15
minutes to upload it. So Sync is a resumable background job, not a button that
finishes; every sync after the first is incremental and near-instant.

**Write operations are the only thing that scales badly**, and only if sync
re-uploads. At one object per game the 50× user's first sync costs $5.04 —
more than five months of their storage — but that is once per game ever,
provided sync is incremental. Per-game objects are worth keeping for fetch
granularity; the op cost is noise at realistic sizes.

---

## Architecture

### What the desktop uploads

Sync is one button that pushes everything not already pushed. No per-replay
selection, no per-replay deletion UI.

| Tier | Where | What | When |
|---|---|---|---|
| Frame data | R2, per-owner prefix, one object per game | ~58 KB gzipped | on sync |
| Index rows | Supabase Postgres | queryable metadata, combos | on sync |
| Character packs | R2, shared public prefix | ~1.5 MB × 26, not per-user | once, globally |

Character packs are slippilab's geometry (MIT), identical for every user, so
they are uploaded once for everyone rather than per-vault. Keep the attribution.

### What the phone does

Authenticate with the Patreon app token → list games from Postgres → fetch the
per-game blob and the relevant character packs from R2 → `paintFrame`. No
backend in the read path, free egress, works with the desktop powered off.

### Do not parse `.slp` in the cloud

`peppi_py.read_slippi` is Rust via pyo3 and cannot run on Workers, so cloud
parsing means a container. The desktop already parses, on hardware we do not pay
for. And do not add a second parser: `@slippi/slippi-js` is pure JS and would
run in a Worker, but `game_trace.py`'s docstring exists because of a frame-basis
bug (Slippi frames start at −123; array index 0 is not elapsed second 0). Two
parsers that must agree frame-for-frame is how that bug comes back.

### What already exists

Every endpoint v1 needs is built. This is a front-end and plumbing project, not
a backend one.

| Need | Endpoint | Source |
|---|---|---|
| Browse | `GET /api/nucleome/replays`, `/facets`, `/months` | `nucleome_replays_bp.py` |
| Combos | `GET /api/nucleome/combos` | same |
| Clip payload | `GET /api/nucleome/lite/clip/<id>?start=&end=` | same, via `_clip_response()` |
| Animation maps | `GET /api/nucleome/lite/charmaps` (88 KB) | same |
| List icons | `/stock/<ext_id>/<costume>`, `/stage-icon/<id>` | same |

Renderer: `frontend/src/components/nucleome/litePaint.js` is pure Canvas 2D,
already extracted from React for the Combo Video exporter, so it is proven to
run outside a React tree. `WatchLiteClip.jsx` is the reference consumer — most
of its 419 lines are desktop chrome a phone does not want.
`frontend/src/utils/liteBundleCache.js` is an LRU bundle cache with prefetch.

R2 upload plumbing exists on the website:
`frontend/functions/api/intake/presign.js` does SigV4 query presigning against
R2's S3 API so bytes go client→R2 without passing through a Worker. Desktop→R2
is the same shape.

### Desktop control surface

`vault_client.py` / `vault_sync.py` are driven by these routes (all on
`nucleome_bp`, added in `nucleome_replays_bp.py`; background threads and the
launch autorun live in `nucleome_replays/vault_jobs.py`):

| Route | Does |
|---|---|
| `GET /api/nucleome/vault/status` | configured / flags / synced / pending / last_sync_at / live `sync` progress. Offline — never calls the vault |
| `POST /api/nucleome/vault/token` | store or clear the Patreon app token. Never echoed back |
| `GET,POST /api/nucleome/vault/settings` | the two launch flags |
| `POST /api/nucleome/vault/pair` | mint a device token — the **only** time `device_token`/`pair_url` exist |
| `GET /api/nucleome/vault/devices`, `POST /vault/revoke` | paired-device management |
| `POST /api/nucleome/vault/sync` | background push; 409 if one is running |

Settings live in the nucleome kv (`indexer.kv_get`/`kv_set`), not in the
frontend, because the autorun runs before a window exists: `vault_app_token`,
`auto_scan_on_launch`, `auto_sync_on_launch`, `vault_last_sync_at`. Both auto
flags default **false**.

`maybe_autostart()` is called from `mex_api.py` beside `warm_ollama_probe()`
and, in one daemon thread, runs index → combos → push in that order (a
dependency chain: combos read what the index writes, the push derives from
both). A missing token or an unreachable vault is swallowed — a failed autorun
must never stop the backend booting.

Gate: **`NUCLEUS_VAULT`**, off in packaged builds via `electron/main.js`
(`backendEnv.NUCLEUS_VAULT = '0'`), same arrangement as `NUCLEUS_COMBO_VIDEO`.
It covers both the routes and the autorun.

---

## Identity and entitlement

**Owner key is `patreon_user_id`**, matching `ai_grants`. Not a Supabase user id
— the Nucleus/Supabase account is the community account for uploading mods and
is deliberately not involved in entitlement.

`ai-entitlement` hashes the app token (SHA-256) and looks up
`patreon_links.app_token_hash` → `patreon_user_id`. `patreon_user_id` is stable
across pledge lapses, so unsubscribing pauses sync without orphaning the vault,
and resubscribing must never require re-uploading the library.

⚠️ **The current entitlement model lives on `meleeWebsite` branch
`nucleome-website`, not `main`.** `main` auto-deploys the public site so
nucleome work is held off it, and `main`'s edge functions are from 2026-07-13/14
describing a superseded Supabase-JWT design. Reading `main` gives the wrong
model; this has already cost one wrong conclusion. Fix by merging, not by
editing comments.

There is no `auth.uid()`, so no RLS. Scoping happens in edge functions with the
service key — already the house pattern. Given that, resolve identity in exactly
**one** place: a shared `resolveOwner(token) → patreon_user_id` in
`supabase/functions/_shared/`, called by every vault endpoint.

### Schema, decided before rows exist

Today `games.path TEXT UNIQUE NOT NULL` (`backend/nucleome_replays/indexer.py`)
makes game identity a local filesystem path, and no table — `games`,
`game_players`, `combos`, `clip_refs` — has an owner column. For a vault,
identity becomes **`UNIQUE (owner_id, content_hash)`**. That is the whole
migration and it is cheap now, painful after data exists.

Uploader-owned private vaults dissolve the harder problem: both players in a set
uploading the same game is a non-issue, because they are rows in separate vaults
with nothing to reconcile.

### Per-device tokens — do this first

`patreon_links.app_token_hash` is a single column: one token per Patreon
account, and re-linking elsewhere revokes the previous one. Pairing a phone
would either share the desktop's token string (no per-device revoke) or kick the
desktop off. Split into a child table keyed on `patreon_user_id`, one row per
device with a label and `last_seen`. Trivial now, nasty after people have paired
phones.

---

## Patterns to lift from vAMP

vAMP (`projects/vAMP/vAMPWeb`) already ships this exact shape — per-user cloud
vault, R2 blobs, subscription-gated, presigned reads. Lift rather than reinvent:

- **One entitlement gate, first line.** `src/pages/api/sync/batch-stream-urls.ts`
  opens with `await subscriptionRepo.requireStream(ctx)`. Ours is
  `requirePatreon(ctx)`, and it is the same chokepoint `resolveOwner` wants to be.
- **Ownership enforced twice.** The repo enforces row ownership on fetch, then
  `r2Storage.validateR2Key(ctx.user.id, objectKey)` re-validates the derived key
  before minting a presigned GET — because key columns are client-supplied.
  Defence in depth, and cheap.
- **Lapsed-payer lifecycle already solved.** `src/lib/billing/grace-cleanup.service.ts`
  plus `src/pages/api/cron/purge-expired.ts` and `cleanup-deleted.ts`: grace
  window, soft delete, then R2 keys.

### The scar worth heeding

The note at `grace-cleanup.service.ts:12` (dated 2026-08-10) records that the
cleanup planner once summed a **client-declared** `total_size_bytes` — sent
before upload, so a guess about a folder that did not exist yet, schema default
`0`. A library of 0-byte-declared songs never satisfied the "have I freed
enough?" loop, so **every song was selected for hard deletion.** The field is
now absent rather than merely unused, so no future edit can reintroduce the
dependency by reflex.

Same trap is wide open here: the desktop is the only thing that knows how big an
upload was. **Sizes come from R2, never from the client.**

---

## v1 scope

**In:** desktop Sync button (incremental, whole library); R2 + Supabase write
path; edge functions for auth, list and presigned reads; per-character packs
uploaded once; mobile web client with browse, filters, combos list, and the Lite
player.

**Out:** sharing of any kind; raw `.slp` archive; coach/Randall on mobile;
`watch-mods` (that is Dolphin); `replays/scan` and `deep/*` (indexing jobs, they
stay on desktop); the stats page; native app packaging.

### Order of work

1. **Prove `paintFrame` on a real phone** before building any UI — see open
   questions. Throwaway page, one hardcoded clip, watch the frame counter.
2. Schema with `UNIQUE (owner_id, content_hash)` and the per-device token table.
3. Upload path: character packs once, then incremental per-game sync.
4. Read path: `resolveOwner` + list + presigned GET, gated.
5. Mobile client.

---

## Open questions

1. **`paintFrame` on real phone hardware.** Worth ten minutes of sanity check,
   not a research project — it is Canvas 2D stroking a handful of paths per
   frame, and phones render far heavier than that all day. The one thing that
   could actually bite is `devicePixelRatio`: `paintFrame` takes `dpr`, and a
   full-width canvas backed at native resolution on a 3× screen is a lot of
   pixels. That is a tuning knob, not a viability question.
2. **How does the phone get the token?** QR from desktop is the obvious answer
   and needs no mobile login, but it depends on per-device tokens landing first.
3. **Does the free tier see anything at all?** Gating is decided, but the derived
   half costs ~2¢ per user per month, so the gate is a tier-value decision rather
   than a cost one. A read-only taste (last N games) is affordable if it sells
   the tier.
4. **Sync is append-only — so how does anything ever leave?** Decided: deleting
   replays locally must never delete them from the vault, because a dead drive
   would otherwise wipe the cloud copy. Deliberate, but it means the vault only
   grows and there is no answer yet for "I genuinely want that game gone." An
   explicit per-game delete on the phone is the likely escape hatch, and it
   belongs outside the *sync* path, where the damage would be silent.
5. **PWA or plain mobile web for v1?** PWA buys a home-screen icon and offline
   caching of packs and watched clips, which is most of what "an app" feels like.

---

## Later

**Sharing.** Deferred, but the shape is decided: a shared replay is a
**self-contained artifact** — one HTML file with the data embedded, like a Claude
artifact — rather than a page that fetches a key. No token to resolve, no
lifetime to manage, works forever, and at 58 KB of frame data plus the packs it
is a plausible single file. `clip_refs` (`ref` PK, `game_id`, `start_frame`,
`end_frame`, `label`, `created`) already exists with the right semantics and was
built so Randall could not hallucinate a clip reference.

**Native app.** App Store is a separate project but not a from-scratch one —
vAMP already has `fastlane`, a `mobile/` tree, and App Store Connect
credentials. The web client should be the thing a shell wraps, not a throwaway.

**Raw `.slp` archive.** Deferred, not abandoned. `interactions.py`, `combos.py`
and `deep_stats.py` will change, and derived-only means never being able to
backfill. With an archive, a detector improvement is one container chewing
through a bucket overnight — a one-off job cost, not a running cost. It is 26×
the storage of the derived half, so it belongs behind its own toggle.

---

## Rejected, and why

Recorded so these do not get re-litigated.

- **Video/MP4 as the share or sync artifact.** Kills the entire premise. The
  product is thousands of replays watchable without recording anything; a video
  is a recording. Also forfeits scrubbing, slow-mo, camera control, and "open
  this in Nucleus."
- **Desktop-as-server (phone as thin client over LAN or a tunnel).** Cheapest
  possible build — the desktop already has the index, the endpoints and the
  browse UI — but it requires the desktop to be powered on, which is a product
  tax nobody wants to pay. It would also mean exposing a backend that builds ISOs
  and reads the filesystem (`mex_api.py:315` binds `127.0.0.1` with no auth).
- **Share links as v1.** The vault is the product; sharing is a feature of it.
  Building sharing first meant building the renderer plumbing without the thing
  that makes anyone want it.
- **Per-clip animation narrowing in the cloud.** 36× the storage. See
  [Measurements](#measurements).
- **Batching many games per R2 object.** Considered to cut Class A writes, but
  writes are $5 one-time for a fictional 30-year library. Not worth the fetch
  granularity.
- **Supabase account as vault owner.** Deliberately separate from entitlement;
  coupling them re-entangles two identities that were split on purpose.
- **3D model viewer on mobile.** `EmbeddedModelViewer.jsx` is a native
  HSDRawViewer OpenGL window over Electron IPC — there is no web renderer to
  port. A read-only viewer is achievable via batch glTF export server-side
  (the harness already does `hsdraw --mode model export` → DAE) plus three.js.
  Spin a model: yes. Live-edit: no.
- **Painting models on mobile.** Half-viable, bad product. `usePaintCanvas` is
  browser canvas so painting ports, but the DAT texture round-trip is HSDRaw
  (C#) and the live preview is the native window — the phone would need a server
  on both ends. Then you are asking someone to paint Melee UV maps on a 6-inch
  screen.
- **ISO building, mexcli, m-ex, watch-with-mods, the in-game harness.** x86 C#
  and Dolphin. Not a portability question.
