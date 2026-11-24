# Model import tools: an optional download (0.9.0)

Owner, 2026-11-19: model import must work on Windows, macOS and Linux before 0.9.0 ships. The
Blender and Python it needs should be an optional download from Settings, not part of the
installer: they double its size, and many users never use the AI.

## What changes

Until now the Windows installer carried two folders:
- `utility/blender`: Blender 4.3.2, trimmed, about 730 MB;
- `utility/rigswap/python`: embeddable CPython 3.13 with bpy 5.2.2, numpy and the other wheels, about 800 MB.

Neither was ever built for macOS or Linux, so there model import said "not set up".

From 0.9.0 on:

| Piece | Where it comes from | Where it lives |
|---|---|---|
| rigswap's own package (bytecode + `source_kept`) | the installer, as now (`tools/build/fetch_rigswap.py`, pinned by `rigswap.manifest.json` `rigswap.commit`) | `resources/utility/rigswap/app` |
| Blender 4.3.2 for this platform | downloaded by the app from **download.blender.org** (or one of its mirrors when that turns the computer away), sha256-pinned | the user's data folder, `tools/model-import/blender/<version>/` |
| Python 3.13 for this platform | downloaded by the app: python.org's embeddable zip on Windows, python-build-standalone (`install_only_stripped`) on macOS and Linux, sha256-pinned | `tools/model-import/runtime/<key>/` |
| The wheels rigswap needs (bpy, numpy, pillow…) for this platform | downloaded by the app from **files.pythonhosted.org**, each by URL and sha256 | inside that runtime's site-packages |

So nothing new is hosted by us and nothing is uploaded at release. The app assembles the tools
on the user's machine from the official sources, verifying every file's sha256 before it is
unpacked. We no longer redistribute Blender at all.

## One manifest

`app/utility/model_import_tools.json` (tracked, shipped in the installer). It replaces
`blender.manifest.json` and the runtime half of `rigswap.manifest.json`; that file keeps only
the rigswap code pin. Platform keys are the ones `hsdlib.manifest.json` uses: `win-x64`,
`linux-x64`, `osx-arm64`.

```json
{
  "schema": 1,
  "platforms": {
    "win-x64": {
      "blender": {"version": "4.3.2", "url": "...", "sha256": "...", "size": 0, "format": "zip",
                  "root": "blender-4.3.2-windows-x64", "entrypoint": "blender.exe", "trim": ["..."]},
      "python":  {"version": "3.13.17", "url": "...", "sha256": "...", "size": 0, "format": "zip",
                  "kind": "embeddable", "entrypoint": "python.exe"},
      "wheels":  [{"name": "bpy", "version": "5.2.2", "url": "...", "sha256": "...", "size": 0}]
    },
    "linux-x64": {"...": "same shape; blender format tar.xz, python kind standalone"},
    "osx-arm64": {"...": "same shape; blender format dmg (Blender.app), python kind standalone"}
  }
}
```

- **The runtime's key** is a hash of its python entry and its wheels list. A new app version
  that changes neither keeps the same key, so nothing is downloaded again.
- **Blender** is keyed by its version.
- **`size`** is the download size. The Settings card shows the total.
- **`on_disk`** (per platform) is what a real install of these very downloads measured on disk, per piece:
  `{"blender": {"sha256", "bytes"}, "runtime": {"key", "bytes"}}`, from that install's `receipt.json`. It is the size
  on disk the card shows before the download, and what the free-space check counts (`assemble.files_for`,
  `estimate`). A piece counts only while its sha256 or runtime key is the pinned one; a piece without one falls back to
  per-format ratios (`assemble.ON_DISK`), which were up to 13% low (Linux Blender's tar.xz unpacks to 3.27x, not
  2.6x). Record receipts with `pin_model_import_tools.py --measured <receipt.json>...` (no network); a re-pin keeps a
  piece's size while its downloads stay, and drops it when they move.
- **A dev script fills in the pins** (`tools/build/pin_model_import_tools.py`): versions in, URL, sha256 and size out
  for every platform. It reads PyPI's JSON API and Blender's published sha256 file. Nobody types a hash by hand.

## In the app

- **Settings card "Model import tools".**
  - It says what the tools are for: importing 3D models as costumes, in Randall's chat and through the MCP's
    import_model.
  - It shows the download size and the size on disk, and says where the files come from (blender.org, python.org or
    python-build-standalone, PyPI).
  - It shows the state: not installed, downloading (with progress and Cancel), paused, installed, update needed, or
    failed (the error in words). It has Download, Remove and Update buttons.
  - Paused is a download stopped part way (Cancel, or the app closed) whose part is kept: "Paused · 168 of 779 MB",
    the header's "about 611 MB left of 779 MB" and a "Resume (611 MB)" button, all from the status's
    `downloaded_bytes` and `needed_bytes`. `service.need()` reads it as not installed (or update needed), so the
    import's `needs_tools` reply keeps its states. (0.9.0 build 3 smoke: it showed "Not installed".)
  - It's available to everyone: MCP imports are free and ungated.
- **Download.**
  - It checks free disk space first.
  - It resumes with HTTP Range, verifies each file's sha256, and unpacks into a temp folder beside the target. It
    renames that folder into place only when everything has checked out, then writes `receipt.json`.
  - A certificate failure switches that file, once, to `roots_only_context()`: certifi's roots plus Windows' trusted
    roots, without the intermediates Windows caches. Python's default loads that cache, and OpenSSL takes a cached
    expired cross-sign over the valid chain the server sends (blender.org's 2026-11-21 move to Let's Encrypt's
    YE1/Root YE chain failed "certificate has expired" on PCs holding the X2-by-X1 cross-sign that expired
    2025-09-15). The sha256 pins still decide what gets installed.
  - A file may list `mirrors` (Blender's do: mirror.clarkson.edu, ftp.nluug.nl, mirror.freedif.org, from
    `pin_model_import_tools.py` `BLENDER_MIRRORS`, each checked there to serve the same size). When a source answers
    401/403/451 (it turns this computer away) or 404/410, the next one carries on from the same part. Since mid-2026
    download.blender.org's Cloudflare front sometimes answers a scripted download with a challenge (403,
    `cf-mitigated: challenge`), depending on the user's network (VPNs above all); a browser passes it, urllib cannot
    (user report, 2026-11-23). When every source refuses, the error says so: all 404/410 means the tools list is old;
    anything else names the VPN and the way round by hand.
  - By hand: the file saved under its own name (as a browser saves it, e.g. `blender-4.3.2-windows-x64.zip`) in
    `tools/model-import/downloads/` is taken at the next Download when its sha256 is the pinned one.
  - Archive extraction is path-safe (tarfile `filter='data'`, zip members checked). The Blender trim list is applied
    after unpacking.
  - Wheels are installed by unpacking them into site-packages (the `.data/purelib|platlib` dirs moved in). No pip,
    and no code from the downloads is run during the install.
  - On macOS the .dmg is attached read-only with `hdiutil` (`-nobrowse`), Blender.app is copied out, then detached.
  - After a successful update, folders no current manifest names are removed.
- **When the tools are missing or out of date:**
  - `import_job.setup()` says so in its own words, `TOOLS_MISSING`, not "not set up".
  - Randall's import card shows "Model import needs its tools (about N MB)" with a Download button. The button starts
    the same download, and the import can be retried after it.
  - The MCP's `import_model` answers `needs_tools` at once, in words that send the user to Settings. It never starts a
    download itself.
  - Both say the size and where the files come from on this platform: `service.need()` carries `sources`, the
    pieces' sources the Settings card lists (`service.SOURCES` by what the manifest pins: python.org on Windows,
    python-build-standalone on macOS and Linux), and `import_job._download` words them. (0.9.0 build 3 smoke: the
    words named python.org on every platform.)
- **The paths a packaged app gives rigswap** (`import_job._defaults`, frozen):
  - `RIGSWAP_PYTHON`: the installed runtime's python;
  - `RIGSWAP_HOME`: `resources/utility/rigswap/app`;
  - `RIGSWAP_BLENDER4`: the installed Blender's entrypoint;
  - `RIGSWAP_HSDRAW`: `core.config.HSDRAW_EXE`, the headless HSDRawViewer on macOS and Linux;
  - targets and vanilla files as now.
- **A source checkout** keeps `DEV_ENV`, unchanged.

## In the build

- `app/package.json` `extraResources`, `tools/build/build.bat`, `build-linux.sh` and `build_mac.sh` stop carrying
  `utility/blender` and `utility/rigswap/python`. All three platforms carry `utility/rigswap/app` and
  `model_import_tools.json`.
- `THIRD_PARTY_NOTICES.md` no longer lists Blender as shipped. It says the tools are downloaded on request, from where,
  and under which licences.
- The release preflight and the ship rules follow. Tests that read the bundled Blender move to the downloaded one, or
  to a dev path.

## As built (2026-11-19)

- **Pins.** `tools/build/pin_model_import_tools.py` writes every URL, sha256 and size into
  `app/utility/model_import_tools.json` from the publishers (`--check` compares without writing). Trusted sources:
  Blender's `blender-4.3.2.sha256`; python.org publishes no checksum file, so the digest comes from the release's
  `.sigstore` bundle (`messageSignature.messageDigest`); python-build-standalone's `SHA256SUMS` (newest 3.13 in the
  release named by `--pbs`); PyPI's JSON API for the wheels. `utility/rigswap.requirements.txt` stays the one list of
  versions; the win-x64 wheel picked must have the sha256 written there. Wheel choice: CPython 3.13 first, then
  abi3, then pure; glibc floor 2.28; macOS floor 11.0; the lowest floor wins.
- **Assembly.** `app/backend/randall/model_import/tools/assemble.py` (standard library only; also a CLI:
  `python -m randall.model_import.tools.assemble --root <dir>` from `app/backend`). The install is
  `<data>/tools/model-import/`: `blender/<version>/`, `runtime/<key>/` (the key hashes the Python and the wheel
  list, so a wheel bump makes a new runtime and keeps Blender), `receipt.json`; `downloads/` holds
  `<sha16>-<name>` and its `.part` only while a download runs. Each piece is built in `.staging-*` and renamed into
  place; a folder an update leaves behind is renamed aside and deleted, or, when Windows refuses (a running import
  holds it), deleted by the next status read. On Windows the embeddable Python's `._pth` is rewritten
  (`python313.zip`, `.`, `Lib\site-packages`, `import site`). Every runtime gets `nucleus_rigswap_home.pth`, which
  puts `RIGSWAP_HOME` on `sys.path`: the embeddable ignores `PYTHONPATH` and the current folder.
- **The app.** `tools/service.py` (state, the `model_import_tools` job, Remove waits for a running import),
  `randall/routes/model_import_tools.py` (`GET /api/assistant/model-import-tools`, `POST .../start|cancel|remove`),
  the Settings card (`frontend/src/settings/ModelImportToolsSection.jsx`, `modelImportTools.js`,
  `useModelImportTools.js`) and the import card's button (`randall/assistant/ImportToolsDownload.jsx`).
  `import_job.tools_reply` is the `needs_tools` reply; `studio_import.tools_missing`/`starts_nothing` put it on the
  turn's card and drop words written before the call; the MCP's `import_model` and `fix_import` answer it at once.
  A RIGSWAP_PYTHON and RIGSWAP_BLENDER4 in the environment stand in for the tools.
- **Stop on macOS and Linux.** rigswap starts in a session of its own (`start_new_session`); a stop sends its group
  SIGTERM, then SIGKILL after `import_job.STOP_GRACE` (5 s), so Blender 4 and the headless viewer end with it.
- **The build.** `build.bat`, `build-linux.sh` and `build-macos.sh` run `tools/build/fetch_rigswap.py` behind the
  assistant gate. It compiles with any CPython 3.13: `--python`, the running one, `python3.13` on PATH, else the
  manifest's own Python for that platform, fetched by `assemble.py` into `app/build/rigswap-compiler/`.
  `fetch_blender.py` and `blender.manifest.json` are gone.
- **Moving the data folder** skips `tools/model-import` (`storage_relocation.REGENERABLE`): it can be downloaded
  again, and on macOS and Linux it holds symlinks the worker refuses.
- **The name `randall.model_import.tools`** was a deleted v1 module; `test_no_retired_model_import.py` now allows
  the package and still refuses any import of a name it does not define.

Measured on Windows (this desktop, 2026-11-19):
- Assembly from the manifest: 779 MB downloaded, 154 s, 1.54 GB on disk (Blender 780 MB, runtime 762 MB); the
  card's estimate before the download was 1.55 GB.
- One real import (Clank → Pichu, rigswap 952efa7, fresh AI cache): `done` in 215 s, $0.024, 20 asks. The same
  import on the installer's compiled package (`utility/rigswap/app`, the cache warm) took 84 s and wrote a
  byte-identical costume (234,574 B). rigswap's own check warned that small round parts float apart from the body,
  which the portrait shows (a loose part beside the head, the right hand off the arm): rigswap's result, not the
  tools'.

| Platform | Download | On disk (measured, 0.9.0 build 3) | Blender | Runtime |
|---|---|---|---|---|
| win-x64 | 779 MB | 1.54 GB (1,541,804,747 B) | 780 MB | 762 MB |
| linux-x64 | 840 MB | 2.32 GB (2,320,129,436 B) | 1.21 GB | 1.11 GB |
| osx-arm64 | 613 MB | 1.70 GB (1,703,971,820 B) | 862 MB (Blender.app is not trimmed) | 842 MB |

These are the manifest's `on_disk`, so the card shows them before the download. The ratios alone had said 1.55, 2.02
and 1.63 GB.

## The macOS and Linux port

Verified on the tower (Linux x64) and the MacBook (arm64) before 0.9.0, with a real import on each:
- the headless HSDRawViewer runs every command rigswap calls (`--model export|import` with `--dobjs`, `--fighter`,
  `--names`, `--alpha-mode`; `--accessory`; `--anim list`; `--dump-pose`);
- bpy 5.2.2 renders rigswap's Workbench pictures in its background process;
- Blender 4.3.2 converts DAE to GLB;
- rigswap's own platform assumptions hold.

Fixes to rigswap go to its `core` branch and are shipped by moving the pin. Fixes to the headless viewer go to the
HSDLib fork, as a new release tag.

### What the 2026-11-19 port test found

The tools were assembled from the manifest's pins on both machines, and three downloads were imported on each:
Clank→Pichu (OBJ), plus Scorpion→CaptainFalcon and Sackboy→Ness (both FBX). Scorpion and Sackboy each used a target
made from scratch on that machine. The AI answers came from the Windows cache; no key left the desktop.

Blender 4.3.2 ran in every import, writing the costume's DAE for the viewer. It also converted both downloads' DAEs to
GLB, with the Linux trim applied, to the same sizes as on Windows within a few dozen bytes.

Every import finished with the read-back passing, on the same swap path as Windows:

| Download | Windows | Linux x64 | macOS arm64 |
|---|---|---|---|
| Clank→Pichu (tripwire retry) | 234,410 B | 234,410 B | 234,006 B |
| Scorpion→CaptainFalcon | 716,052 B | 715,196 B | 715,016 B |
| Sackboy→Ness | 430,072 B | 430,072 B | 430,072 B |

These are the sizes of the costume .dat each platform wrote.

The tools are only complete with these fixes:
- **rigswap `core` 952efa7** (the pin must move there; since 0343b44, below):
  - it recognises the headless viewer's build for the import record;
  - on Linux it drops `DISPLAY`/`WAYLAND_DISPLAY` before bpy loads. A broken GLX made bpy segfault at the first
    render. The tower's NVIDIA kernel module and libraries were at different versions, which is common after an
    unattended upgrade that has not been rebooted. With the drop, bpy renders through EGL, and through Mesa llvmpipe
    when the GPU's EGL is unusable;
  - on macOS it labels pictures in Arial Bold, as Windows does. Before, a Mac fell back to Pillow's built-in
    regular face. Linux uses DejaVu Bold, as before.
- **HSDLib `headless-anim`**: the headless viewer lacked `--anim`. It needs a new release tag and an
  `hsdlib.manifest.json` bump.
- **rigswap `core` 0343b44** (the pin since 0.9.0 build 3's smoke): a ZIP whose folders are split by backslashes
  (Windows PowerShell's Compress-Archive: `Clank\Clank.obj`) extracts into those folders on Linux and macOS too.
  Python's zipfile turns `\` into `/` only where `os.sep` is `\`, so the entries landed as files named
  `Clank\Clank.mtl` and the OBJ found no materials. rigswap's `load.open.entry_name` and the app's texture check
  (`chat/textures.py` `entry_path`) both split on either slash; extraction still refuses `..`, absolute paths and
  drive letters. The app hands the ZIP to rigswap whole: rigswap is what extracts it.

An AI answer cached on one platform does not answer the same ask on another. The pictures differ in their label fonts
and in tiny rasterisation details, and the cache key hashes the picture bytes. So each user's cache is their own, as
it already is.
