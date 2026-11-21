#!/bin/bash
# Build script for Linux AppImage
# Run this in WSL or native Linux

set -e  # Exit on error

echo "================================"
echo "Melee Nexus Linux Build Script"
echo "================================"
echo ""

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "Warning: This script should be run on Linux or WSL"
fi

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# tools/build/ sits at the repo root; the app (package.json, venv, utility/) is app/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_ROOT="$REPO_ROOT/app"
cd "$PROJECT_ROOT"

echo -e "${BLUE}[1/5] Checking dependencies...${NC}"

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found. Install with: sudo apt install python3${NC}"
    exit 1
fi

# Create/activate virtual environment
if [ -f "venv/bin/activate" ]; then
    echo "Activating existing Linux virtual environment..."
    source venv/bin/activate
else
    echo "Creating Linux virtual environment..."
    python3 -m venv venv-linux
    source venv-linux/bin/activate
    echo "Installing Python dependencies..."
    pip install --upgrade pip
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    fi
    pip install pyinstaller pillow py7zr flask flask-cors
fi

# If we created venv-linux, use it
if [ -f "venv-linux/bin/activate" ]; then
    source venv-linux/bin/activate
    # ...and re-resolve requirements.txt every time, not only on the run that
    # created it. A venv-linux built before a dependency landed installs
    # nothing new here, PyInstaller only WARNS about the missing module, and
    # the AppImage ships broken at runtime instead of failing at build time.
    # This is exactly how xxhash went missing on macOS; the CI runner keeps its
    # workspace between builds, so it is the same trap with a longer fuse.
    echo "Refreshing venv-linux from requirements.txt..."
    pip install -q -r requirements.txt || {
        echo -e "${RED}Error: could not install requirements.txt into venv-linux${NC}"
        exit 1
    }
fi
VENV_PYTHON="$(command -v python)"

# Check for PyInstaller (should be in venv now)
if ! "$VENV_PYTHON" -c "import PyInstaller" &> /dev/null; then
    echo -e "${RED}Error: PyInstaller not found in venv. Try: pip install pyinstaller${NC}"
    exit 1
fi

# Check for Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}Error: node not found. Install with: sudo apt install nodejs npm${NC}"
    exit 1
fi

echo -e "${GREEN}✓ All dependencies found${NC}"
echo ""

# Step 1: Build Python Backend
echo -e "${BLUE}[2/5] Building Python backend with PyInstaller...${NC}"
"$VENV_PYTHON" -m PyInstaller "$REPO_ROOT/tools/build/mex_backend.spec" --clean --noconfirm
if [ -f "dist/mex_backend" ]; then
    echo -e "${GREEN}✓ Python backend built successfully${NC}"
else
    echo -e "${RED}✗ Python backend build failed${NC}"
    exit 1
fi
"$VENV_PYTHON" "$REPO_ROOT/tools/build/check_pyinstaller_warnings.py" build/mex_backend/warn-mex_backend.txt || {
    echo -e "${RED}PyInstaller warning inventory contains a new project-level missing import${NC}"; exit 1; }
SMOKE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/nucleus-build-smoke.XXXXXX") || {
    echo -e "${RED}Could not create isolated backend smoke-test directory${NC}"; exit 1; }
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
echo ""

# Step 2: Fetch the pinned prebuilt MexCLI + HSDRawHeadless for linux-x64.
# The m-ex / HSDLib source trees live in their own fork repos; each publishes
# self-contained builds as GitHub Releases, pinned by app/utility/*.manifest.json.
# mexcli, codes.gct and seed_codes.ini arrive together in the mex zip (seed_codes.ini,
# NOT codes.ini: a codes.ini beside mexcli would make `mexcli create` enable all 49
# codes on new projects).
echo -e "${BLUE}[3/5] Fetching MexCLI + HSDRawHeadless for linux-x64...${NC}"
"$VENV_PYTHON" "$REPO_ROOT/tools/build/fetch_native.py" all --platform linux-x64 || {
    echo -e "${RED}✗ could not fetch the native toolchain (see tools/build/fetch_native.py --help)${NC}"
    exit 1
}
# Clean the exact stage targets so removed assemblies cannot survive from an
# earlier build and silently enter the package.
rm -rf dist-backend/mex-linux dist-backend/hsdraw-linux
mkdir -p dist-backend
cp -a utility/mex/linux-x64 dist-backend/mex-linux
cp -a utility/hsdraw/linux-x64 dist-backend/hsdraw-linux
for f in mexcli codes.gct seed_codes.ini; do
    if [ ! -f "dist-backend/mex-linux/$f" ]; then
        echo -e "${RED}✗ $f missing from the fetched MexCLI — aborting.${NC}"
        exit 1
    fi
done
chmod +x dist-backend/mex-linux/mexcli
echo -e "${GREEN}✓ MexCLI staged (with codes.gct and seed_codes.ini)${NC}"
echo ""

echo -e "${BLUE}[4/5] Staging HSDRawHeadless (native CSP/model renderer)...${NC}"
if [ -f "dist-backend/hsdraw-linux/hsdrawviewer" ]; then
    chmod +x dist-backend/hsdraw-linux/hsdrawviewer
    echo -e "${GREEN}✓ HSDRawHeadless staged (native — no Wine needed)${NC}"
else
    echo -e "${RED}✗ hsdrawviewer missing from the fetched build. CSP/model rendering will not work.${NC}"
    exit 1
fi

# A checkout made from the Windows tree (the WSL build path) loses the execute
# bit on the tracked UnRAR binary; .rar imports need it back.
chmod +x utility/unrar-linux/unrar
echo ""

# Step 4: Build React Frontend
echo -e "${BLUE}[5/5] Building React frontend...${NC}"
# electron-builder is a ROOT devDependency, so a fresh clone needs the root
# install too -- without it, packaging dies with "electron-builder: not found"
# and the script only appeared to work because a root node_modules was lying
# around from a previous run.
# `npm ci`, UNCONDITIONALLY, and never `[ -d node_modules ] || install`.
# That guard only fires when node_modules is absent ENTIRELY, so a tree left
# over from before a dependency was added is silently accepted and the build
# dies later on an unresolved import -- which is exactly how qrcode-generator
# broke the first Linux and macOS builds of 0.7.0 while Windows, whose
# node_modules happened to be current, kept working. ci wipes the tree and
# installs the lockfile exactly, so a build machine cannot drift from the
# lockfile and cannot disagree with any other build machine.
echo "Installing root dependencies (electron-builder)..."
npm ci
cd frontend
echo "Installing frontend dependencies..."
npm ci
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
npm run build

if [ -d "dist" ]; then
    echo -e "${GREEN}✓ Frontend built successfully${NC}"
else
    echo -e "${RED}✗ Frontend build failed${NC}"
    exit 1
fi

cd "$PROJECT_ROOT"
echo ""

# Step 5: Stage, scrub, gate, then package with electron-builder
#
# electron-builder must NOT run from the working tree. It used to (npm run
# package:linux), and the shipped 0.7.0 AppImage carried 5.6 MB of retail
# costume DATs, 84 ripped effect frames and Randall's unreleased promo video --
# all of which build.bat had been stripping on Windows for months. Staging +
# scrubbing + the leak gate now come from tools/build/ship_guard.py and
# tools/build/ship_rules.json, the same two files build.bat and
# build-macos.sh use. Add rules THERE, never inline here.
echo -e "${BLUE}[6/6] Staging, scanning and packaging the AppImage...${NC}"

PACKAGE_STAGE="$PROJECT_ROOT/build-package-staging"
PACKAGE_OUTPUT="$PROJECT_ROOT/dist-electron"
GUARD="$SCRIPT_DIR/ship_guard.py"

"$VENV_PYTHON" "$GUARD" stage --platform linux --stage "$PACKAGE_STAGE" --project-root "$PROJECT_ROOT" || {
    echo -e "${RED}✗ staging failed — refusing to package${NC}"; exit 1; }

rm -rf "$PACKAGE_OUTPUT"

"$VENV_PYTHON" "$GUARD" scan --stage "$PACKAGE_STAGE" --backend "$PROJECT_ROOT/dist/mex_backend" --project-root "$PROJECT_ROOT" --report "$PROJECT_ROOT/ship-report.txt" || {
    echo -e "${RED}✗ ship guard failed — refusing to package. See above.${NC}"; exit 1; }

ELECTRON_VERSION=$(node -p "require('./node_modules/electron/package.json').version")
[ -n "$ELECTRON_VERSION" ] || { echo -e "${RED}✗ cannot determine Electron version${NC}"; exit 1; }

./node_modules/.bin/electron-builder --linux --projectDir "$PACKAGE_STAGE" --config.directories.output="$PACKAGE_OUTPUT" --config.electronVersion="$ELECTRON_VERSION"

rm -rf "$PACKAGE_STAGE"

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Build Complete!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

if [ -d "dist-electron" ]; then
    echo "AppImage location:"
    find dist-electron -name "*.AppImage" -type f
    echo ""
    echo "To run:"
    echo "  chmod +x <AppImage_file>"
    echo "  ./<AppImage_file>"
    echo ""
    echo "CSP/model rendering is native (hsdraw-linux) — Wine is NOT required."
    echo "Runtime dependency: xdelta3 (sudo apt install xdelta3) for patch"
    echo "creation/apply; no native xdelta3 is bundled yet."
else
    echo -e "${RED}Error: dist-electron directory not found${NC}"
    exit 1
fi
