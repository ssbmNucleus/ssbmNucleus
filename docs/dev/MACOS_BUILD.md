# Building SSBM Nucleus for macOS

Apple Silicon (arm64) only. Intel Macs are not targeted — the pinned MexCLI and
renderer releases are published for `osx-arm64` only.

## Prerequisites

```bash
# Homebrew lives at /opt/homebrew and is NOT on a plain ssh PATH
export PATH="/opt/homebrew/bin:$PATH"

brew install node python@3.12 xz     # xz supplies liblzma for xdelta3
brew install gh && gh auth login     # private forks only (or export NUCLEUS_FETCH_TOKEN); public releases need no login
```

macOS's system Python is 3.9, which is **too old** — the codebase uses `str | None`
type syntax (3.10+). Build the venv from Homebrew's Python.

## Build

```bash
bash tools/build/build-macos.sh        # or tools/build/build_mac.sh (refreshes the venv, notarises, logs)
```

No .NET SDK is needed: MexCLI and the headless renderer are prebuilt, self-contained releases of
the `ssbmNucleus-mex` / `ssbmNucleus-hsdlib` forks, fetched and sha256-verified by
`python tools/build/fetch_native.py all --platform osx-arm64` (tags pinned in
`app/utility/mex.manifest.json` and `hsdlib.manifest.json`).

Produces `dist-electron/SSBM Nucleus-<version>-arm64.dmg` (and a `.zip`).

## Code signing and notarisation

The build signs automatically **if** a `Developer ID Application` certificate is
in the keychain:

```bash
security find-identity -v -p codesigning
```

An `Apple Development` certificate is **not** sufficient. Those sign for your own
devices only; distributing a DMG needs a `Developer ID Application` certificate,
which requires a paid Apple Developer Program membership and is created in the
developer portal.

Two things to know:

* **Signing must run from a Terminal on the Mac itself.** Over SSH the login
  keychain is locked and `codesign` fails with `errSecInternalComponent`.
* **To build without signing** (runs locally, but Gatekeeper blocks anyone who
  downloads it): `export CSC_IDENTITY_AUTO_DISCOVERY=false`.

### Notarisation

**Signing on its own is not enough to distribute.** Gatekeeper checks a
downloaded file for a notarisation *ticket* as well as a signature, so an
unnotarised build fails on someone else's Mac with "cannot be opened because
Apple cannot check it for malicious software" — while running fine on the
machine that built it, because that copy never got a quarantine attribute. To
reproduce a real download locally:

```bash
cp dist-electron/*.dmg /tmp/t.dmg && xattr -w com.apple.quarantine "0081;0;;" /tmp/t.dmg && open /tmp/t.dmg
```

Step 7 of the build script notarises and staples automatically. Prefer an App
Store Connect **API key** over an Apple ID: it is a file rather than a password,
so it works over SSH and nothing has to type a credential.

```bash
export NOTARY_KEY=~/.apple-credentials/<team>/AuthKey_XXXXXXXXXX.p8
export NOTARY_KEY_ID=XXXXXXXXXX
export NOTARY_ISSUER=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Create the key at App Store Connect → **Users and Access → Integrations →
App Store Connect API**, role *Developer* or above. The Issuer ID is shown on
that same page. **A `.p8` can only be downloaded once** — there is no re-download,
only revoke-and-replace. It is a private key: store it outside the repo, mode
`600`, and never commit it.

Set `NOTARIZE=0` to skip the step. To notarise a DMG you already built:

```bash
xcrun notarytool submit dist-electron/*.dmg --key "$NOTARY_KEY" \
    --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER" --wait
xcrun stapler staple dist-electron/*.dmg
spctl -a -vv -t install dist-electron/*.dmg   # want: source=Notarized Developer ID
```

If it comes back `Invalid`, `xcrun notarytool log <submission-id>` (same key
flags) gives the per-file reason.

**Expect this to be slow.** The 0.6.4 DMG took **~18 hours**; a 44 KB probe from
the same certificate was accepted in under 41 minutes. Measured, not guessed —
resubmitting, switching DMG→zip, and shrinking the payload all made no
difference, so do not go hunting for a fault. Apple's own threshold for
treating a submission as broken is 24 hours.

### Two things that are easy to get wrong

**1. electron-builder does NOT sign the DMG by default.** `dmg.sign` defaults to
false, so the disk image ships unsigned even though the `.app` inside is signed
correctly, and `spctl -t open` on the downloaded DMG reports
`rejected / source=no usable signature`. `package.json` now sets
`"dmg": { "sign": true }`. Verify with:

```bash
codesign -dvvv dist-electron/*.dmg    # must NOT say "code object is not signed at all"
```

**2. Stapling the DMG does not staple the app inside it.** A DMG is read-only,
so `stapler staple <dmg>` attaches a ticket to the *image*, and the copy the
user drags to /Applications still has none. It launches fine — Gatekeeper falls
back to an online lookup — but a **first launch with no network can fail**. To
close that, notarise and staple the `.app` *before* the DMG is built:

```
build+sign app -> notarise app.zip -> staple .app -> build DMG -> notarise DMG -> staple DMG
```

That costs two notarisation rounds. Given the turnaround above, one round is a
reasonable trade for anything but a final release. Check which you have with:

```bash
xcrun stapler validate "/Volumes/<vol>/SSBM Nucleus.app"
```

Entitlements live at `tools/build/entitlements.mac.plist` (they must stay out
of `build/`, which is gitignored). They allow Electron's JIT and the unsigned
helpers the app spawns — the PyInstaller backend, `mexcli`, `hsdrawviewer`,
`xdelta3`.

## What differs from Windows and Linux

**Rendering.** macOS has no OpenGL 3.3 Compatibility profile — only legacy 2.1
(GLSL 1.20) or Core capped at 4.1 (GLSL 4.10). The engine's shaders are
`#version 330`, so Core is the only workable option, and the renderer requests it
there (`OpenTKResources.IsCoreProfile`). The few fixed-function calls left in the
host are skipped in that mode. The context is created through **CGL, not GLFW**,
because GLFW needs a window server even for a hidden window — so the renderer
works headlessly (CI, ssh, daemons), which it cannot do on Linux/X11.

**ISO extraction.** Extraction goes through the native Python FST reader in
`backend/shared/vanilla_extract/vanilla_refs.py`, the only ISO reader on every platform.

**The in-game harness needs a debuggable Dolphin — but no root.** macOS gates
`task_for_pid` on the TARGET's code signature, not on your privileges. Slippi
ships Dolphin with the hardened runtime and no `get-task-allow`, and that
refuses everyone including root, which is why `sudo` does not help. Re-sign a
COPY with `get-task-allow` and it works as the ordinary user:

```bash
cp -R ~/Library/Application\ Support/Slippi\ Launcher/netplay/"Slippi Dolphin.app" ~/dolphin-debug/
codesign -d --entitlements :- ~/dolphin-debug/"Slippi Dolphin.app" > /tmp/ent.plist
# add <key>com.apple.security.get-task-allow</key><true/> to /tmp/ent.plist
codesign --force --deep --sign - --entitlements /tmp/ent.plist ~/dolphin-debug/"Slippi Dolphin.app"
```

Then point the harness at it — no sudo, no cleanup, nothing left root-owned:

```bash
NUCLEUS_SLIPPI_PATH=~/dolphin-debug python backend/devtools/fps_batch.py --mode offline <iso>
```

Verified on macOS 26.x: boots, reads AND writes emulated RAM, navigates to
character select, HEALTHY at 59.9 fps.

The copy is ad-hoc signed, so it will not authenticate for Slippi **online**
play — keep it for local testing and play online on the real install.

> Do NOT run the harness under sudo. Dolphin launched as root creates
> `~/Library/Application Support/com.project-slippi.dolphin` owned by root, and
> Slippi Launcher then fails with `EACCES: permission denied, mkdir ...`. If that
> happens: `sudo chown -R $(whoami) ~/Library/Application\ Support/com.project-slippi.dolphin`

## Releasing

```bash
python tools/build/release_to_r2.py --platform mac
```

Publishes under the `mac` channel with platform key `mac-arm64`. The in-app
updater downloads the DMG and opens it for the user to drag across — a running
`.app` bundle cannot safely overwrite itself the way the Linux AppImage does.
