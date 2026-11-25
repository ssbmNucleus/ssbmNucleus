# Release gates and preview policy

Living spec for the release gates; `app/backend/core/gates.py` and `app/electron/main.js` cite this file by name. The original 0.9.0 limited assistant preview is the worked example below.

**Status (2026-11-19): the assistant ships in 0.9.0.** Randall's chat and the
app MCP are on in every package, stable included: `core/gates.py` no longer
marks `assistant` `packaged_off`, `electron/main.js` no longer forces it off,
and every build script builds its UI when `ship_guard.py gate assistant` passes.
What follows was the contract the 0.9.0 preview packages ran under; the write
paths and the coach below are still shut in every package, and the preview
opt-in still works for a build that holds the assistant back again. It exists
so the switches are decided once, in `backend/core/gates.py`, instead of per
call site — and so the person on the second PC can tell, from the log, which
build they are holding.

Source: the independent integration review at
[`backend/artifacts/harness-experiment-20260922/ASTRA-INTEGRATION.md`](../backend/artifacts/harness-experiment-20260922/ASTRA-INTEGRATION.md).
Its conclusion, verbatim in substance: *hold the unrestricted preview; a
limited assistant preview is reasonable after fixing the vault-save policy,
reconciling API documentation, and checking the frozen verification path. Keep
automatic build commits, delivery/undo, wish submission, and scripting off.*

---

## 1. The policy table

Everything below is decided in **`backend/core/gates.py`** (`GATES`) and
injected by **`electron/main.js`**
when it spawns the backend for a packaged build.
`tests/backend/test_preview_policy.py` fails if the two halves drift.

### No release gate

Model-import exports and vault saves are not gated. The fit review, the native
round trip and the in-game check are tools: their findings come back as
`warnings` on the export, Randall explains them, and the user decides.

### OFF in a preview build — and in a release build

| Key | Value | What is closed |
|---|---|---|
| `NUCLEUS_BUILD_COMMIT` | `0` | Writing a prepared menu + code change **into** a managed build (`nucleus_api.builds.commit_change`, `POST /api/mex/builds/changes/<id>/approve`). A change can still be prepared, inspected and authorized; committing it is refused outright rather than half-applied. |
| `NUCLEUS_DELIVERY` | `0` | Delivering a finished change into the build someone boots (`randall/delivery/deliver.py`). Delivery rebuilds and **overwrites** that file. Closed means refused with a sentence, never a partial success that reads like one. |
| `NUCLEUS_WISH_SUBMIT` | `0` | Sending a recorded wish to the developer. Wishes are still classified, recorded and counted **locally** — that backlog is the point. What is closed is anything leaving the machine, and anything *claiming* something left it. |

`NUCLEUS_COMBO_VIDEO` stays `0`. `NUCLEUS_PLAY` defaults to `0` and opens when the packaged manifest names `play` in `releaseFeatures` or `previewFeatures`.

> **The assistant's model-import tools have no gate.** The release policy
> above, not a gate, governs what a model-generated save may claim.

### ON in a preview build — and, since 0.9.0, in a release build

| Key | Value | What opens |
|---|---|---|
| `NUCLEUS_ASSISTANT` | `1` | The assistant chat and its vault tools (`/api/assistant/*`) and the app MCP (`/api/mcp`). Since 0.9.0 no package sets it: the backend default (on) applies |
| `NUCLEUS_RANDALL` | `0` | Randall the Tracker coach / the Analyst tab (`/api/nucleome/coach/*`) stays OFF in every package (owner decision, 2026-10-04), and its code (`randall.coach`) is left out of them |

On with no separate switch, because none was ever committed: the narrator
reply, the existing approval-based any-mod download, the bounded search
fallback, and local traces.

rigswap's package (`utility/rigswap/app`) and the manifest of the model import
tools (`utility/model_import_tools.json`) ride on the same gate: `ship_rules.json`
tags them `ships_with_gate: assistant`, so every build stages them exactly when the
assistant ships, on Windows, macOS and Linux. Blender and rigswap's Python are not
in any installer: the user downloads them from Settings > AI > Model
import tools (docs/dev/MODEL_IMPORT_TOOLS.md), which keeps the installer small, as
the owner's 2026-10-16 note asked.

### How it is injected

Since 0.9.0 (the assistant is not `packaged_off`):

```
core/gates.py  assistant.packaged_off = False
  ├─ tools/build/ship_guard.py gate assistant   → exit 0 ("ships")
  │    └─ build.bat / build-linux.sh / build-macos.sh: VITE_ASSISTANT_PREVIEW=1
  │         → the frontend bundle builds the tab, the panel and the MCP card
  ├─ mex_backend.spec: randall, nucleus_api, aiengine, modellab in the bundle
  ├─ ship_rules.json: utility/rigswap/app + utility/model_import_tools.json staged and verified (every platform);
  │   Blender and rigswap's Python are a download from Settings (docs/dev/MODEL_IMPORT_TOOLS.md)
  └─ electron/main.js: NUCLEUS_ASSISTANT not in PACKAGED_OFF_GATES → backend default on
```

While the assistant is held back (`packaged_off=True`, as for the 0.9.0 previews):

```
NUCLEUS_PREVIEW_FEATURES=assistant          (the build selector, set by hand)
  └─ tools/build/build.bat
       ├─ ship_guard.py gate assistant → VITE_ASSISTANT_PREVIEW=1 → the frontend bundle builds the tab
       └─ --config.extraMetadata.previewFeatures=assistant
            └─ the PACKAGED package.json    (the tree's manifest stays clean)
                 └─ electron/main.js: 'assistant' in previewFeatures (PREVIEW_OPENS)
                      └─ backendEnv ← core.gates.policy_env(features='assistant')
```

`package.json` in the working tree must **never** carry `previewFeatures`: it is
written into the packaged manifest only, so a shared checkout cannot turn the
next release build into a preview. `test_preview_policy.py` asserts that.

At startup the backend logs one line, and a bug report carries it. For a build without Unlocked, the line includes the following values.

```
Feature switches: NUCLEUS_ASSISTANT=1 \
  NUCLEUS_RANDALL=0 NUCLEUS_BUILD_COMMIT=0 NUCLEUS_DELIVERY=0 NUCLEUS_WISH_SUBMIT=0 NUCLEUS_PLAY=0
```

### Play test builds

Unlocked (gate `play`) ships in Windows stable packages starting with 0.10.0. `PLAY_IN_STABLE`
makes `build.bat` write `releaseFeatures=play`, and Electron opens `NUCLEUS_PLAY` from the
packaged manifest. See [Play in stable builds](PLAY_CLIENT_FEED.md#play-in-stable-builds).
To make a **local, unsigned test build**, use the same selector the assistant previews used.

```powershell
$env:NUCLEUS_PREVIEW_FEATURES = 'play'                  # or 'assistant,play'
$env:NUCLEUS_BUILD_VERSION    = '0.10.1-play-preview.1' # a prerelease tag is REQUIRED
$env:NUCLEUS_ALLOW_UNSIGNED   = '1'
tools\build\build_logged.bat < NUL
```

```
NUCLEUS_PREVIEW_FEATURES=play     (set by hand; whole names, comma-separated)
  └─ tools/build/build.bat
       ├─ refuses unless NUCLEUS_BUILD_VERSION has a prerelease tag   (before any stage)
       ├─ ship_guard.py gate play → VITE_PLAY_PREVIEW=1 → features.js PLAY_ENABLED,
       │    Play mode (the wordmark's third mode) and the PlayApp chunk are in the bundle
       ├─ mex_backend.spec / the frozen smoke: the play package is frozen in
       └─ --config.extraMetadata.previewFeatures=play
            └─ electron/main.js: 'play' in previewFeatures → NUCLEUS_PLAY=1 for this package
```

Every other gate keeps its packaged value (`policy_env(features='play')` opens
`NUCLEUS_PLAY` and nothing else). Why it cannot reach a release by accident:

* The release stage (`ci.py stage`) packages the tree's plain `X.Y.Z`, so a stray
  `NUCLEUS_PREVIEW_FEATURES=play` in the shell makes `build.bat` refuse before the
  first stage. Nothing in the tree turns it on: `previewFeatures` is never in a
  committed `package.json`, and `build.bat` clears `VITE_PLAY_PREVIEW` before it asks the gate.
* `ship_guard.py` refuses a bundle with a `PlayApp` chunk when Play does not ship,
  and one without it when it does.
* The package counts as a test build (`previewFeatures`, prerelease version). With
  no `NUCLEUS_PREVIEW_CHANNEL` it reads only the public update manifest, so it is
  offered the next stable release once that is newer than its own version.

A test build installs as the same app (same app id, install folder and data
folder) as the released Nucleus, over it.

---

## 2. Before the build

Run these from `backend/` in a **clean checkout of the chosen build commit**.
Every path below exists in this tree.

```powershell
# 1. the build venv
$py = (Resolve-Path ..\venv\Scripts\python.exe).Path

# 2. the generated API document must BE the document
& $py -B -c "from pathlib import Path; from nucleus_api.gendocs import build; assert Path('nucleus_api/API.md').read_text(encoding='utf-8') == build(), 'API.md drift'"

# 3. the suites the night's changes cross
& $py -m pytest -q ../tests/backend/test_nucleus_api_contract.py ../tests/backend/test_verify_costume.py ../tests/backend/test_build_commit_transaction.py ../tests/backend/test_part_identity.py ../tests/backend/test_safe_extract.py ../tests/backend/test_custom_char_export_import.py

# 4. the whole backend suite
& $py -m pytest -q ../tests/backend

# 5. the frontend
npm --prefix ..\frontend test

# 6. the electron main process
node --test (Get-ChildItem ..\tests\electron\*.test.js).FullName

# 7. the preview frontend bundle actually builds
$env:VITE_ASSISTANT_PREVIEW='1'; $env:VITE_SHIP_GATES='0'
npm --prefix ..\frontend run build
```

Step 2 is also a test — `tests/backend/test_api_md_equality.py` — so step 4 covers it;
keep the one-liner for the case where you want the failure on its own.

Add to step 3, from this work:

```powershell
& $py -m pytest -q ../tests/backend/test_preview_policy.py ../tests/backend/test_frozen_import_coverage.py ../tests/backend/test_api_md_equality.py ../tests/backend/test_gates.py ../tests/backend/test_ship_guard_embedded_roots.py
```

Notes the review attached, kept here because they decide whether a red run
means anything:

* Use the **build venv's dev requirements**. Native-port coverage moved to the
  private ssbmNucleus-fighterport repo with its own requirements.
* Backend `pytest` discovers `tests/backend/` only. It does **not** run the frontend,
  Electron, or the evaluation campaign.
* The historical `trimesh`-copy and missing-`ssbh_data_py` failures are **not a
  blanket exemption for new failures**. UnRAR's absence should *skip* its
  suite; sandbox tests may skip when their developer runtime is absent.
* Still owed, and not covered by the existing unit suites: integration tests
  for verification → release, delivery → export locking, persisted unverified
  labels, and archive budget reuse.

---

## 3. The second-PC smoke checklist

On the second PC, run exactly these ten smoke checks:

1. Install into a fresh profile; open Assistant and Tracker. Confirm unreleased scripting surfaces remain absent.
2. Reopen an existing vault and project; inspect costumes, codes, and normal ISO export.
3. Search for CSS/SSS backgrounds; select a published `other` file and complete one approval.
4. Search a nonexistent mod; confirm bounded fallback, an honest empty result, and no fabricated download.
5. Recolor a vanilla costume and save a new copy; confirm the original remains unchanged.
6. Ask for Goku hair-only recoloring; unresolved/shared scope must stop a broad edit.
7. Import a known-good model; inspect cost narration, export, and save it to the vault.
8. Try a known-bad model; confirm its measured problems are explained as warnings and the user can still choose to keep it.
9. Start and stop an interactive test; then try automated verification with Dolphin already busy. The existing instance must survive.
10. Deny an approval, cancel a task, and restart. Check traces and absence of duplicate effects; disabled delivery/build/wish-submission requests must not claim success.

Check 10 is the one that tests *this document*: with `NUCLEUS_DELIVERY=0`,
`NUCLEUS_BUILD_COMMIT=0` and `NUCLEUS_WISH_SUBMIT=0`, each of those three
requests must refuse in words. A success message for an action the build cannot
perform is a preview-blocking bug, not a cosmetic one.

---

## 4. Packaging deltas that went with this policy

In `tools/build/mex_backend.spec`:

* **`nucleus_api` is collected explicitly.** Nothing in the production import
  graph reaches the facade — the assistant imports it inside a function — so
  only the spec puts it in the executable. Its modules are globbed from the
  package directory, not listed, and `API.md` ships beside them.
* The modellab `*.json` glob and the `menus/compatibility_manifest.json` entry
  were verified present and are pinned by tests. `ship_rules.json`'s
  `embedded_roots` include list now names the manifest too; the spec had moved
  first and `test_ship_guard_embedded_roots.py` had been red since.
* **Not solved with a broad `backend/data` glob**, deliberately. Every embedded
  file is named, and the guard compares that list to `ship_rules.json`.

Still open, marked in the spec as `TODO(S3/verification)`: the in-game
verifier's `engine_version()` hashes its own **source** files. Frozen, those
paths are absent, every hash collapses to `None`, and two different engines
share a cache key. The spec already ships
`backend/shared/ingame/engine_digest.json` if a generator writes one; no generator
exists under `tools/build/` yet.

Also open, and owned by the `nucleus_api` builder:
`nucleus_api.game.capture_moves` spawns `[sys.executable,
'devtools/frameshot.py']`. In a packaged build `sys.executable` is the backend
bootloader and `devtools/` is not on disk. `tests/backend/test_frozen_import_coverage.py`
carries it as the single allow-listed entry and fails on any new one.

---

## 5. Updates for testers: the preview channel

From `0.9.0-preview.8` on, a test build updates itself. `electron/updates/updater.js`
treats a build as a test build when its packaged manifest has
`previewFeatures` or its version has a prerelease tag. A test build that was
also packaged with a secret channel token polls two signed manifests and
offers whichever is newer:

| Manifest | Written by | Polled by |
|---|---|---|
| `https://releases.ssbmnucleus.net/<platform>/latest.json` | `release_to_r2.py` (plain `X.Y.Z` only) | every build |
| `https://releases.ssbmnucleus.net/<platform>/preview/<token>/latest.json` | `prerelease_to_r2.py --channel <token>` | test builds packaged with `<token>` |

The token is `NUCLEUS_PREVIEW_CHANNEL`: 16-64 characters of `[A-Za-z0-9_-]`,
with at least one letter. `build.bat` writes it into the packaged
`package.json` as `previewChannel`, and does that only for a preview build.
It refuses the token without `NUCLEUS_PREVIEW_FEATURES`, or without a
prerelease `NUCLEUS_BUILD_VERSION` (`0.9.0-preview.8`, never plain `0.9.0`,
which could never see stable `0.9.0` as newer, so testers could not leave).
It checks both formats before the build starts, rejecting stray whitespace
and newlines. After packaging it confirms the packaged value is exactly that
string (`tools/build/check_preview_channel.js`). The updater likewise
ignores a token on a plain version. The app source
and every stable build contain no preview path, so only a tester's install can
locate the channel. A test build without a token checks the public manifest
only. Use one token for the whole series. A build carries its token forever,
so a new token means testers must install the next build by hand, and a lost
token leaves every tester stuck on the build they have.

Ordering is SemVer: `0.9.0-preview.10` > `0.9.0-preview.9`, and `0.9.0` >
every `0.9.0-preview.N`. When 0.9.0 ships to the public manifest, testers move
back to stable without doing anything. Nothing in Settings lets a stable install
opt in, because a test build turns on features that have not been released.
The install path is the same as for stable: the Ed25519-signed manifest, a
download pinned to `releases.ssbmnucleus.net`, then a SHA-256 and size check
before the NSIS installer runs. Builds up to `preview.7` predate the channel.
Testers on one of those must install `preview.8` by hand once.

Create the token once and keep it with the release secrets. Never commit it:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(24))"   # 32 chars, store in 1Password
```

Building and publishing a test build (from `app/`):

```powershell
$env:NUCLEUS_ALLOW_UNSIGNED = '1'   # both build.bat and the channel's Authenticode gate honor it
$env:NUCLEUS_BUILD_VERSION = '0.9.0-preview.8'
$env:NUCLEUS_PREVIEW_FEATURES = 'assistant'
$env:NUCLEUS_PREVIEW_CHANNEL = venv\Scripts\python scripts\secret_cache.py read "<1Password ref of the preview channel token>"
tools\build\build.bat

python tools\build\prerelease_to_r2.py --channel $env:NUCLEUS_PREVIEW_CHANNEL `
    --version 0.9.0-preview.8 --slug <tester-slug> --landing --notes "<what changed>"
```

1Password reads (the channel token, the R2 keys, the report admin token) are
cached in Windows Credential Manager by `tools/build/secret_cache.py` after the first
approval. `python scripts\secret_cache.py prime` fetches all of them with one
approval; `forget` drops them. Run the uploads with `venv\Scripts\python` (boto3).

This uploads `windows/prerelease/<slug>/SSBM-Nucleus_<version>_x64-setup.exe`
(plus the landing page), then `windows/preview/<token>/latest.json`, signed
with the same key as a release (`.release-secrets/update-signing-private.pem`
or `NUCLEUS_UPDATE_SIGNING_KEY`). A local copy lands in
`releases/preview-latest-windows.json`. Console output shows the token as
`<token>`. The script refuses a plain `X.Y.Z` version, and it refuses an
installer whose embedded ProductVersion is not exactly `--version`. A mismatch
would make testers re-download the same build forever. The script refuses `windows/latest.json` under any arguments, and
without `--channel` it is the old link-only upload. To see what testers will
get, run `$env:NUCLEUS_PREVIEW_CHANNEL = ...; node tests/electron/manual/test-updater.js 0.9.0-preview.7` from the repo root.
The harness adds the token to the tree manifest and polls both manifests.
