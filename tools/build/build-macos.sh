#!/bin/bash
# Build script for the macOS app (Apple Silicon).
# Mirrors build-linux.sh; see docs/dev/MACOS_BUILD.md.
#
# Signing: electron-builder signs with a "Developer ID Application" certificate
# if one is in the keychain. Without it you get an AD-HOC signature, which is
# enough to run the app locally but NOT to distribute -- Gatekeeper blocks a
# downloaded copy.
#
# Use build_mac.sh locally, or ci.py's SSH worker, which supplies a local .p12
# for electron-builder's temporary keychain. A bare SSH session cannot use a
# locked login keychain. Notarisation authenticates with a local .p8 key file.
#
# Notarisation (step 7) is opt-in and runs only if an App Store Connect API key
# is configured. Point NOTARY_KEY at the .p8 and set the two ids beside it:
#
#     export NOTARY_KEY=~/.apple-credentials/personal-69KVHG8DP6/AuthKey_XXXX.p8
#     export NOTARY_KEY_ID=XXXXXXXXXX
#     export NOTARY_ISSUER=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
#
# Skip it with NOTARIZE=0. The .p8 is a private key: keep it out of the repo.
# This script never handles an Apple ID password.

set -e

GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'

# tools/build/ sits at the repo root; the app (package.json, venv-mac, utility/) is app/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_ROOT="$REPO_ROOT/app"
cd "$PROJECT_ROOT"

echo -e "${BLUE}[1/7] Checking dependencies...${NC}"
for c in python3 node npm; do
    command -v $c >/dev/null || { echo -e "${RED}Error: $c not found${NC}"; exit 1; }
done
[ "$(uname -m)" = "arm64" ] || echo -e "${RED}Warning: not arm64; the mac target builds osx-arm64${NC}"
echo -e "${GREEN}✓ dependencies ok${NC}"

echo -e "${BLUE}[2/7] Python backend (PyInstaller)...${NC}"
# macOS system python is 3.9, which is too old -- the codebase uses `str | None`
# (3.10+). PyInstaller happily freezes a 3.9 backend anyway, and the failure only
# shows up as the packaged app dying at startup, so refuse it here instead.
PYBIN="${PYTHON:-python3}"
for c in python3.13 python3.12 python3.11 python3.10; do
    command -v "$c" >/dev/null && { PYBIN="$c"; break; }
done
PYVER=$("$PYBIN" -c 'import sys; print("%d%02d" % sys.version_info[:2])')
if [ "$PYVER" -lt 310 ]; then
    echo -e "${RED}Error: $PYBIN is $("$PYBIN" -V) -- 3.10+ required.${NC}"
    echo "  brew install python@3.12   (then re-run; delete venv-mac/ if it exists)"
    exit 1
fi
if [ -f "venv-mac/bin/activate" ]; then
    EXISTING=$(venv-mac/bin/python -c 'import sys; print("%d%02d" % sys.version_info[:2])' 2>/dev/null || echo 0)
    if [ "$EXISTING" -lt 310 ]; then
        echo "venv-mac is on an unsupported Python ($EXISTING) - recreating"
        rm -rf venv-mac
    fi
fi
if [ ! -f "venv-mac/bin/activate" ]; then
    echo "Creating venv from $PYBIN ($("$PYBIN" -V))"
    "$PYBIN" -m venv venv-mac
    source venv-mac/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    pip install pyinstaller
else
    source venv-mac/bin/activate
fi
VENV_PYTHON="$(command -v python)"
"$VENV_PYTHON" -m PyInstaller "$REPO_ROOT/tools/build/mex_backend.spec" --clean --noconfirm
[ -f "dist/mex_backend" ] || { echo -e "${RED}✗ backend build failed${NC}"; exit 1; }
"$VENV_PYTHON" "$REPO_ROOT/tools/build/check_pyinstaller_warnings.py" build/mex_backend/warn-mex_backend.txt || { echo -e "${RED}PyInstaller warning inventory contains a new project-level missing import${NC}"; exit 1; }
SMOKE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/nucleus-build-smoke.XXXXXX") || { echo -e "${RED}Could not create isolated backend smoke-test directory${NC}"; exit 1; }
cleanup_smoke_root() {
    [ -n "${SMOKE_ROOT:-}" ] && [ -d "$SMOKE_ROOT" ] && rm -rf -- "$SMOKE_ROOT"
}
trap cleanup_smoke_root EXIT
if ! NUCLEUS_BUILD_SMOKE_ROOT="$SMOKE_ROOT" ./dist/mex_backend --build-smoke-test; then
    echo -e "${RED}Frozen backend smoke test failed${NC}"
    exit 1
fi
cleanup_smoke_root
trap - EXIT
unset SMOKE_ROOT
echo -e "${GREEN}✓ backend built${NC}"

echo -e "${BLUE}[3/7] MexCLI + headless renderer (osx-arm64, prebuilt)...${NC}"
# The m-ex / HSDLib forks publish self-contained builds as GitHub Releases, pinned by
# app/utility/mex.manifest.json and hsdlib.manifest.json. mexcli, codes.gct and
# seed_codes.ini arrive together in the mex zip.
"$VENV_PYTHON" "$REPO_ROOT/tools/build/fetch_native.py" all --platform osx-arm64 || { echo -e "${RED}✗ could not fetch the native toolchain${NC}"; exit 1; }
rm -rf dist-backend/mex-mac dist-backend/hsdraw-mac
mkdir -p dist-backend
cp -a utility/mex/osx-arm64 dist-backend/mex-mac
cp -a utility/hsdraw/osx-arm64 dist-backend/hsdraw-mac
for f in mexcli codes.gct seed_codes.ini; do
    [ -f "dist-backend/mex-mac/$f" ] || { echo -e "${RED}✗ $f missing from the fetched MexCLI${NC}"; exit 1; }
done
chmod +x dist-backend/mex-mac/mexcli
echo -e "${GREEN}✓ MexCLI staged${NC}"

echo -e "${BLUE}[4/7] Headless renderer (osx-arm64)...${NC}"
[ -f "dist-backend/hsdraw-mac/hsdrawviewer" ] || { echo -e "${RED}✗ renderer missing from the fetched build${NC}"; exit 1; }
chmod +x dist-backend/hsdraw-mac/hsdrawviewer
# The bundled UnRAR is signed into the hardened-runtime .app, which the app
# cannot chmod afterwards — the execute bit has to be right before packaging.
chmod +x utility/unrar-mac/unrar
echo -e "${GREEN}✓ renderer staged (native Core-profile GL)${NC}"

echo -e "${BLUE}[5/7] React frontend...${NC}"
# See the long note in build-linux.sh. Two bugs lived in these two lines: the
# `[ -d node_modules ] ||` guard accepted a stale tree (missing qrcode-generator
# broke the first 0.7.0 mac build), and `cd frontend && [ -d ... ] || npm install`
# parses as `(cd && test) || install`, so a failed cd ran the install in the
# WRONG directory instead of aborting. Unconditional ci, and a cd that is
# checked on its own.
# NOTE: this script has no `set -e`, so every step here is checked by hand.
npm ci || { echo -e "${RED}root npm ci failed${NC}"; exit 1; }
cd frontend || { echo -e "${RED}cannot cd to frontend/${NC}"; exit 1; }
npm ci || { echo -e "${RED}viewer npm ci failed${NC}"; exit 1; }
# The assistant (Randall's chat + the app MCP) is in the bundle exactly when its
# release gate ships in this build (ship_guard.py gate: by default since 0.9.0).
# The stage verify refuses a bundle that disagrees with the gate. See build.bat.
if "$VENV_PYTHON" "$SCRIPT_DIR/ship_guard.py" gate assistant; then
    export VITE_ASSISTANT_PREVIEW=1
    # Randall's model import runs rigswap's package (utility/rigswap/app), which
    # ships with the assistant; its Python and Blender are a download the user
    # starts in Settings (utility/model_import_tools.json). This is a no-op when the
    # tree holds the pinned commit; building it needs a rigswap clone (RIGSWAP_REPO,
    # else ~/projects/rigswap) and a CPython 3.13 (fetch_rigswap.py finds or fetches one).
    "$VENV_PYTHON" "$SCRIPT_DIR/fetch_rigswap.py" || {
        echo -e "${RED}✗ could not build utility/rigswap/app (see tools/build/fetch_rigswap.py --help)${NC}"
        exit 1
    }
else
    unset VITE_ASSISTANT_PREVIEW
fi
npm run build || { echo -e "${RED}vite build failed${NC}"; exit 1; }
cd "$PROJECT_ROOT"
echo -e "${GREEN}✓ frontend built${NC}"

echo -e "${BLUE}[6/7] Staging, scanning and packaging (electron-builder --mac)...${NC}"
# electron-builder must NOT run from the working tree -- that is how the 0.7.0
# AppImage shipped retail costume DATs and Randall's unreleased promo video while
# build.bat had been stripping both on Windows for months. Staging, scrubbing and
# the leak gate live in tools/build/ship_guard.py + ship_rules.json, shared with
# build.bat and build-linux.sh. Add rules THERE, never inline here.
PACKAGE_STAGE="$PROJECT_ROOT/build-package-staging"
PACKAGE_OUTPUT="$PROJECT_ROOT/dist-electron"
GUARD="$SCRIPT_DIR/ship_guard.py"

"$VENV_PYTHON" "$GUARD" stage --platform mac --stage "$PACKAGE_STAGE" --project-root "$PROJECT_ROOT" || { echo -e "${RED}x staging failed - refusing to package${NC}"; exit 1; }

rm -rf "$PACKAGE_OUTPUT"

"$VENV_PYTHON" "$GUARD" scan --stage "$PACKAGE_STAGE" --backend "$PROJECT_ROOT/dist/mex_backend" --project-root "$PROJECT_ROOT" --report "$PROJECT_ROOT/ship-report.txt" || { echo -e "${RED}x ship guard failed - refusing to package. See above.${NC}"; exit 1; }

ELECTRON_VERSION=$(node -p "require('./node_modules/electron/package.json').version")
[ -n "$ELECTRON_VERSION" ] || { echo -e "${RED}x cannot determine Electron version${NC}"; exit 1; }

# ship_rules.json stages the entitlements at build-resources/entitlements.mac.plist
# in the stage, and `verify` fails the build if it is missing. electron-builder
# hands mac.entitlements to codesign as written, and codesign resolves a relative
# path against this shell's cwd (app/), not --projectDir, so pass the staged file's
# absolute path ("cannot read entitlement data" otherwise, first seen on 0.8.12).
ENTITLEMENTS="$PACKAGE_STAGE/build-resources/entitlements.mac.plist"
./node_modules/.bin/electron-builder --mac --projectDir "$PACKAGE_STAGE" --config.directories.output="$PACKAGE_OUTPUT" --config.electronVersion="$ELECTRON_VERSION" \
    --config.mac.entitlements="$ENTITLEMENTS" --config.mac.entitlementsInherit="$ENTITLEMENTS"

rm -rf "$PACKAGE_STAGE"

DMG=$(find dist-electron -maxdepth 1 -name "*.dmg" -type f 2>/dev/null | head -1)
echo -e "${GREEN}✓ packaged${NC}"
find dist-electron -maxdepth 1 \( -name "*.dmg" -o -name "*.zip" \) -type f 2>/dev/null

# ---------------------------------------------------------------------------
# [7/7] Notarisation.
#
# Signing alone is NOT enough for a download to open. Gatekeeper on a
# quarantined copy demands a notarisation ticket too, so an unnotarised build
# still shows "cannot be opened because Apple cannot check it for malicious
# software" on someone else's Mac -- while working perfectly on the Mac that
# built it, because that copy never got a quarantine bit. Test with:
#     xattr -w com.apple.quarantine "0081;0;;" <copy.dmg>
# ---------------------------------------------------------------------------
echo -e "${BLUE}[7/7] Notarisation...${NC}"

HAS_DEVID=$(security find-identity -v -p codesigning 2>/dev/null | grep -c "Developer ID Application" || true)

if [ "$HAS_DEVID" -eq 0 ]; then
    echo -e "${RED}SKIPPED: no 'Developer ID Application' certificate in the keychain.${NC}"
    echo "This build is ad-hoc signed: it runs on THIS Mac, but anyone who"
    echo "downloads it will be blocked by Gatekeeper. Note that 'Apple"
    echo "Development' certs do NOT count -- those only sign for your own"
    echo "devices. Create a Developer ID cert at developer.apple.com."
elif [ "${NOTARIZE:-1}" = "0" ]; then
    echo "SKIPPED: NOTARIZE=0."
elif [ -z "${NOTARY_KEY:-}" ] || [ -z "${NOTARY_KEY_ID:-}" ] || [ -z "${NOTARY_ISSUER:-}" ]; then
    echo "SKIPPED: signed, but no API key configured (see the header of this"
    echo "script). The .dmg is signed and will run locally; it is NOT yet"
    echo "distributable. Notarise later without rebuilding:"
    echo "    xcrun notarytool submit \"$DMG\" --key ... --key-id ... --issuer ... --wait"
    echo "    xcrun stapler staple \"$DMG\""
elif [ -z "$DMG" ]; then
    echo -e "${RED}SKIPPED: no .dmg found in dist-electron/.${NC}"
else
    echo "Submitting $(basename "$DMG") -- Apple scans every Mach-O inside, and"
    echo "this bundle carries two self-contained .NET runtimes plus Electron"
    echo "(~400 executables), so an hour is normal. Not stuck."

    NOTARY_ARGS=(--key "$NOTARY_KEY" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER")
    LOGF=$(mktemp)
    set +e
    xcrun notarytool submit "$DMG" "${NOTARY_ARGS[@]}" --wait --timeout 3h 2>&1 | tee "$LOGF"
    RC=${PIPESTATUS[0]}   # tee's status would otherwise mask notarytool's
    set -e
    SUB_ID=$(grep -Eio '[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}' "$LOGF" | head -1)
    rm -f "$LOGF"

    if [ "$RC" -eq 0 ]; then
        # Stapling attaches the ticket to the file so a first launch works even
        # with no network. Without it Gatekeeper has to phone home every time.
        xcrun stapler staple "$DMG"
        echo -e "${GREEN}✓ notarised and stapled${NC}"
        spctl -a -vv -t install "$DMG" 2>&1 | sed 's/^/    /' || true
    elif [ "$RC" -eq 124 ]; then
        # 124 is the WAIT timing out, not a rejection -- Apple is still
        # processing and the submission is untouched. Resume, do not resubmit.
        echo -e "${RED}✗ timed out waiting.${NC} The build is fine and still queued."
        echo "    xcrun notarytool wait $SUB_ID <key flags>"
        echo "    xcrun stapler staple \"$DMG\"     # once it says Accepted"
        exit 1
    else
        echo -e "${RED}✗ notarisation rejected.${NC} Per-file reasons:"
        echo "    xcrun notarytool log $SUB_ID <key flags>"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}Build complete.${NC}"
