# Linux Build Guide for SSBM Nucleus

SSBM Nucleus runs natively on Linux and ships as an AppImage. **No Wine is
required** — the CSP/model renderer that used to be a Windows-only WinForms app
(`HSDRawViewer.exe`) now has a native, headless port (`HSDRawHeadless` →
`hsdrawviewer`) that renders through a hidden GLFW window + offscreen FBO.

## What works on Linux

- ✅ **Electron app** — native Linux, AppImage packaged
- ✅ **Python backend** — PyInstaller bundle (`mex_backend`), no interpreter needed
- ✅ **MexCLI** — prebuilt .NET 8 `linux-x64` self-contained release of the m-ex fork; builds/exports ISOs
- ✅ **CSP / stock icons / model export / menu & stage assets** — native
  `hsdrawviewer` (`--csp`, `--csp-server`, `--model`, `--stock-icons`, `--css-*`,
  `--pause-screen`, `--hud-textures`, `--bg-textures`, `--stage-*`, `--dobj-info`, …). No Wine.
- ✅ **Live 3D model viewer / skin lab** — `--stream` WebSocket → browser canvas
- ✅ **In-game testing** — the `backend/shared/ingame/` harness reads Dolphin RAM via
  `process_vm_readv`, drives the controller FIFO, and captures the render window
  via X11. Needs a GPU-accelerated Slippi Dolphin (see Limitations).
- ✅ **ISO scanning** — built-in native Python FST reader
- ✅ **Auto-update** — in-place AppImage replacement (`electron/updates/updater.js`)

## Prerequisites

### System dependencies

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3 python3-venv python3-pip nodejs npm xdelta3

# Fedora
sudo dnf install python3 nodejs npm xdelta3

# Arch
sudo pacman -S python nodejs npm xdelta
```

The packaged AppImage additionally needs the usual Electron/Chromium runtime
libraries (`libnss3`, `libgtk-3-0`, `libgbm1`, `libasound2`, …); these are
present on any standard desktop. In-game testing additionally needs a working
GPU OpenGL stack (Mesa) for Dolphin — again standard on a real desktop.

### No .NET SDK needed

MexCLI and the headless renderer are **prebuilt, self-contained releases** of the
`ssbmNucleus/m-ex` and `ssbmNucleus/HSDLib` fork repos (the sources no
longer live in this repo). The build fetches the tags pinned in
`app/utility/mex.manifest.json` and `hsdlib.manifest.json`, verifying each sha256. Public
releases download with no login; for private forks run `gh auth login`, or export
`NUCLEUS_FETCH_TOKEN` with a token that can read them.

## Build

```bash
./tools/build/build-linux.sh
```

Stages: PyInstaller backend → fetch the pinned MexCLI `linux-x64` (+ `codes.gct`) and HSDRawHeadless
`linux-x64` (`python tools/build/fetch_native.py all --platform linux-x64`) → React frontend → `electron-builder --linux`
(AppImage). Output: `dist-electron/SSBM Nucleus-<version>.AppImage`.

## Run

```bash
chmod +x dist-electron/*.AppImage
./dist-electron/*.AppImage
```

## Release

```bash
# after build-linux.sh
python tools/build/release_to_r2.py --platform linux [--notes "..."] [--dry-run]
```

Publishes the AppImage + `latest.json` (platform key `linux-x86_64`) to
`s3://<bucket>/linux/`. The in-app updater checks
`https://releases.ssbmnucleus.net/linux/latest.json`, downloads the new
AppImage, verifies sha256, replaces the running image in place (stage-beside +
`rename()` to avoid `ETXTBSY`), and relaunches.

## Architecture notes

- **Renderer** (`HSDRawHeadless/` in the `ssbmNucleus-hsdlib` fork repo): reuses the WinForms
  viewer's `Rendering/`/`Converters/`/`Tools/`/`Sound/` sources verbatim; only
  the host is swapped — `Platform/OpenTKResources.cs` (hidden GLFW `NativeWindow`,
  GL 3.3 compatibility) and `GUI/ViewportControl.cs` (MSAA FBO + resolve FBO
  readback, since a hidden window's default framebuffer is undefined on X11/
  Wayland). WinForms types the shared sources reference are satisfied by
  `Shims/`. The Windows `HSDRawViewer` build is unchanged.
- **In-game harness** (`backend/shared/ingame/`): `melee_mem.py` uses
  `/proc/<pid>/maps` + `process_vm_readv`/`writev`; `melee_pipe.py` writes the
  Slippi controller FIFO under `<UserDir>/Pipes/slippibot<N>`; `screenshot.py`
  dispatches to `screenshot_x11.py` (XGetImage on Dolphin's window by
  `_NET_WM_PID`). Everything is behind `os.name` — the Windows paths are intact.
- **Paths** are resolved in `backend/core/config.py` (`MEXCLI_PATH`,
  `HSDRAW_EXE`) and branch on `os.name`; the frozen AppImage keeps writable state
  under `~/.melee-nexus`.

## Limitations / final validation

- **In-game testing needs GPU-accelerated Dolphin.** Under WSLg the GPU is not
  wired for OpenGL, so Dolphin falls back to Mesa **llvmpipe** (software) and
  emulation stalls. The three harness primitives (RAM read/write, FIFO input,
  X11 capture) are verified working against real Linux Slippi Dolphin, but a
  full match at speed requires a real GPU — a native Linux desktop or a VM with
  GPU passthrough. This is an environment ceiling, not an app limitation
  (Slippi runs natively on Linux).
- **Dolphin window embedding** (the "game appears in-app" panel) has no Wayland
  analogue; on Linux Dolphin runs as a normal window. The window endpoints
  answer `supported: false` off Windows, so the panel (Test in game AND the
  nucleOME Watch modal) shows "The game is playing in a separate Dolphin
  window" and hides the pop-out controls instead of waiting for an embed.

## Troubleshooting

- **Build script won't run** — `sed -i 's/\r$//' tools/build/build-linux.sh`.
- **`libnss3.so` / GTK errors launching the AppImage** — install the desktop
  runtime libs listed under Prerequisites (missing only on minimal/headless
  images).
- **CSP renders are slow / say `llvmpipe`** — no GPU GL. One-shot CSP renders
  still work (they aren't realtime); realtime uses (`--stream`, in-game) want a
  GPU.
- **`fetch_native.py` fails with "has no … anyone can download (404)"** — the pinned repo is private
  (or the release is missing); `gh auth login` or set `NUCLEUS_FETCH_TOKEN` to a token with read access to both.
- **"Add to Nucleus" / Patreon link does nothing, or the browser says "no
  application available"** — the `nucleus://` scheme has no owner. An AppImage
  installs nothing, so the `.desktop` entry electron-builder generates from
  `build.protocols` stays sealed inside the image, and
  `app.setAsDefaultProtocolClient` is a no-op on Linux (Electron routes it
  through `xdg-settings` and gives up without `$CHROME_DESKTOP`).
  `electron/protocol/linux-protocol.js` fixes this by writing
  `~/.local/share/applications/ssbm-nucleus.desktop` on every packaged launch,
  with `Exec` pointing at `$APPIMAGE` — never `process.execPath`, which inside
  a running AppImage is a `/tmp/.mount_*` FUSE path that dies with the process.
  To check: `xdg-mime query default x-scheme-handler/nucleus` should print
  `ssbm-nucleus.desktop`, and `xdg-open 'nucleus://import?url=…'` should raise
  the app. Launch the AppImage once after installing it; browsers started
  before that may need a restart to pick up the rebuilt MIME cache.
  `NUCLEUS_NO_PROTOCOL_REGISTER=1` opts out.
