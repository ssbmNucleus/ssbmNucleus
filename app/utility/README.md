# app/utility

Tools and bundled data used by the app. Nothing here is built by `npm`.

## Pinned prebuilt toolchain (source moved to the fork repos, 2026-10-03)

The m-ex and HSDLib source trees no longer live in this repo. Their forks publish self-contained
builds as GitHub Releases, and two tracked manifests pin one tag and one sha256 per platform
(`win-x64`, `linux-x64`, `osx-arm64`):

| Manifest | Fork repo (private) | Unpacks to (git-ignored) |
|---|---|---|
| `mex.manifest.json` (MexCLI, mexLib, HSDRaw.dll, `codes.gct`, `seed_codes.ini`) | https://github.com/ssbmNucleus/m-ex | `mex/<rid>/` |
| `hsdlib.manifest.json` (HSDRawViewer on Windows, the headless `hsdrawviewer` elsewhere, `Scripts/`) | https://github.com/ssbmNucleus/HSDLib | `hsdraw/<rid>/` |

`python tools/build/fetch_native.py all [--platform host|win-x64|linux-x64|osx-arm64] [--check] [--force]`
downloads, verifies and unpacks them (public releases need no login; private repos need `gh` or `NUCLEUS_FETCH_TOKEN`). The dev launcher
and the build scripts call it. To bump a tool, publish a new tag on the fork and update `tag` and the
sha256 values from the release's `SHA256SUMS.txt`. Change the fork repos, never an unpacked copy.

`ffmpeg.manifest.json` pins the ffmpeg build the same way (`tools/build/fetch_ffmpeg.py`).

`rigswap.manifest.json` pins rigswap's package, which `tools/build/fetch_rigswap.py` compiles into
`rigswap/app/` (git-ignored) and every installer carries with the assistant. Its Python and Blender are not
shipped: `model_import_tools.json` pins the official downloads (Blender 4.3.2, a CPython 3.13, the wheels in
`rigswap.requirements.txt`) per platform, filled by `tools/build/pin_model_import_tools.py`, and the app
assembles them on the user's request from Settings (`backend/randall/model_import/tools/`,
`docs/dev/MODEL_IMPORT_TOOLS.md`).

## Other first-party code

- `tools/processor/`, `tools/services/` - Python/asset processing helpers.
- `scripts/` - small utility scripts.

## Third-party binaries (not ours)

- `unrar/`, `unrar-linux/`, `unrar-mac/` - RAR extraction.
- `xdelta-linux/`, `xdelta-mac/` - xdelta3 patching.
- `DynamicAlternateStages/` - community stage-alternate loaders (UnclePunch's DAS). Each
  ships as `<root>.xdelta` (`GrPs.usd.xdelta`, `GrNBa.dat.xdelta`, ...), a patch rebuilt
  against the user's own vanilla stage file at install
  (`backend/projects/install/das_loaders.py`).
- `wit-*` - Wiimms ISO Tools (being removed).

## App data

- `assets/` - bundled app assets.
- `ffmpeg.manifest.json` - pinned download manifest for FFmpeg.
- `rigswap.manifest.json`, `rigswap.requirements.txt`, `model_import_tools.json` - rigswap's pinned package and
  the model import tools the user downloads (above).
- `clear_storage.py` - dev helper to reset app storage.
