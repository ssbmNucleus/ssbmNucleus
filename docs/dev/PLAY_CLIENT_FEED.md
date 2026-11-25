# The Nucleus Unlocked client feed

Play installs and updates Nucleus Unlocked, the game client (the Source Port client the client repository's
`windows-build/client_release.py` packs, `docs/client-release.md` there) from one signed file:

    https://releases.ssbmnucleus.net/client/windows/latest.json

Code: `app/backend/play/client_feed.py` (the feed, the checks, the unpacker),
`app/backend/play/managed.py` (install, update, the switch), `app/backend/play/ed25519.py`
(the signature check, pure Python), the Play page's cards (`app/frontend/src/play/`), and the
publisher's side `tools/build/client_feed.py` plus `tools/build/release_to_r2.py --client-zip`.

## Trust

The same scheme as the app's own update feed (`electron/updates/updater.js`), with the same key:

* Ed25519, key `electron/updates/update-public-key.pem` (copied into
  `client_feed.PRODUCTION_PUBLIC_KEY_PEM`; `tests/backend/test_play_client_feed.py` fails if the two differ).
* The signature covers the canonical JSON of the feed without its `signature`: keys sorted, no
  spaces, UTF-8 (`release_to_r2.canonical_manifest_bytes`), and is
  `{"algorithm": "ed25519", "value": "<base64 of 64 bytes>"}`.
* Every address in the feed, and every redirect, must be HTTPS on `releases.ssbmnucleus.net` under
  `/client/windows/`. The ZIP and the file list are pinned by exact length and SHA-256.

A development backend (never a packaged one) can be pointed at a local stand-in for testing:
`NUCLEUS_CLIENT_FEED_URL=http://127.0.0.1:<port>/...` together with
`NUCLEUS_CLIENT_FEED_PUBLIC_KEY=<a PEM file>`. Only then is that key accepted, and only for URLs on that
same address and port. A frozen build reads neither variable.

## The feed (format 1)

```json
{
  "schema": "nucleus-client-feed",
  "format": 1,
  "version": "0.1.0",
  "minAppVersion": "0.10.0",
  "commit": "81447d35...",
  "notes": "Nucleus Unlocked 0.1.0",
  "pub_date": "2026-11-25T08:00:00Z",
  "platforms": {
    "windows-x86_64": {
      "url": "https://releases.ssbmnucleus.net/client/windows/NucleusClient-0.1.0-win64.zip",
      "size": 123456789,
      "sha256": "<64 hex>",
      "manifest": {
        "url": "https://releases.ssbmnucleus.net/client/windows/NucleusClient-0.1.0-win64.manifest.json",
        "size": 45678,
        "sha256": "<64 hex>"
      }
    }
  },
  "signature": {"algorithm": "ed25519", "value": "<base64>"}
}
```

| Field | Meaning |
|---|---|
| `version` | the client's version, plain `X.Y.Z`; its `melee_source.exe --print-info` must say the same |
| `minAppVersion` | the oldest SSBM Nucleus that may install it (a prerelease tag on the app is ignored) |
| `commit`, `notes`, `pub_date` | shown only |
| `platforms.windows-x86_64.url/size/sha256` | the client ZIP, `NucleusClient-<version>-win64.zip` |
| `…manifest.url/size/sha256` | the packager's sidecar, `NucleusClient-<version>-win64.manifest.json`, unchanged |

The sidecar (written by `client_release.py`): format 1, kind `nucleus-client` (exactly; the older
`melee-unlocked-source-port-client` is refused), `name` `NucleusClient-<version>-win64` (the ZIP's one top
folder and the stem of both file names), `version`, the build facts (`git_commit`, `toolchains`,
`plugin_format`, `plugin_abi`, `notes`, and `print_info`, the packaged program's own `--print-info`
answer), `files` (every file's `path`, `size`, `sha256`, sorted, without `release-manifest.json`) and
`zip` (`name` = `<name>.zip`, `size`, `sha256`). The ZIP holds `<name>/<path>` for every listed file
plus `<name>/release-manifest.json`, the sidecar without `zip`, which must be there and match.
Nothing else is accepted: an entry outside the folder, an unlisted or missing file, a size or hash that
differs, a link, an encrypted entry or a Windows-unsafe name fails the install.

The installed client must also be a release build: after unpacking, its `melee_source.exe --print-info`
must say `"public_build": true` and `"game_public_build": true` (the client's `NUCLEUS_PUBLIC_BUILD`;
`client_release.py` packages nothing else). Play refuses to install or start a managed client that
does not; a client folder picked by hand (developers) may be any build.

## Where it installs

Beside Play's own data, never inside it (the game refuses a client inside the folder it keeps saves in):

    <data>/nucleus-client/
      state.json                  the active version, one waiting for the game to close, the last failure
      versions/<version>-<8 hex>/ one verified client each
      staging/, downloads/        an install in progress (removed on failure, Cancel or crash)

`<data>` is `%LOCALAPPDATA%\SSBM Nucleus` in a packaged build (`app/` in a source checkout). An install
never writes Play's saves, its `port-settings.ini` or the player's disc. The new version is switched to
only after every file matched and its `--print-info` answered with the feed's version; while a game runs
it waits and is switched to when the game closes. The version before it is removed once nothing runs
from it. A failure leaves the active version as it was, with the reason on the card.

A client folder picked by hand (Play, Settings, "Your own client folder") still wins while it is set.
Automatic updates compare version numbers. A managed 1.x test client is considered newer than
0.1.0, so use a fresh profile to verify the first public install.

## Publishing a client (owner)

For the first release, publish client `0.1.0` with `--min-app-version 0.10.0` and use
`--client-min-app-version 0.10.0` when signing or publishing the feed.

1. Build and pack the client in the client repository (`windows-build/client_release.py`, from a
   clean tree, both parts configured with `-DNUCLEUS_PUBLIC_BUILD=ON`): it writes
   `NucleusClient-<v>-win64.zip` and `NucleusClient-<v>-win64.manifest.json`.
2. Check it and see the commands (signs nothing, reads no credentials, uploads nothing):

       python tools/build/client_feed.py --zip <dir>\NucleusClient-<v>-win64.zip --manifest <dir>\NucleusClient-<v>-win64.manifest.json --min-app-version <X.Y.Z>

   It refuses another kind or file name, a sidecar whose `print_info` is not a release build, a ZIP that
   is not the sidecar's, a `git_dirty` build, or anything the app's own unpacker refuses, and writes
   `app/releases/client/windows/latest.unsigned.json`.
3. Sign and stage without uploading (prints the `aws s3 cp` commands, ZIP and sidecar first, feed last):

       python tools/build/release_to_r2.py --client-zip <zip> --client-manifest <sidecar> --client-min-app-version <X.Y.Z> --dry-run

4. Publish (uploads the ZIP and the sidecar, then `latest.json`, to `client/windows/` in the releases bucket):

       python tools/build/release_to_r2.py --client-zip <zip> --client-manifest <sidecar> --client-min-app-version <X.Y.Z> --require-upload

5. Check: `https://releases.ssbmnucleus.net/client/windows/latest.json` answers the new version.

## Play in stable builds

The only switch is `PLAY_IN_STABLE` in `app/backend/core/gates.py`. It is True starting in app 0.10.0.
With it True, `ship_guard.gate_ships('play')` is true on Windows build hosts, so `build.bat` builds the
Play frontend (`VITE_PLAY_PREVIEW`), `mex_backend.spec` freezes the `play` package, and `build.bat`
writes `releaseFeatures=play` into the packaged manifest (`ship_guard.py gate play --stable`), which
`electron/main.js` reads to open `NUCLEUS_PLAY`. Linux and macOS builds leave Play out.
The public source drop reads the same switch from the staged commit to include Unlocked's source.
