#!/bin/bash
# The public entry point for a macOS release build — the sibling of build.bat.
#
# Run locally with an unlocked login keychain, or through ci.py's SSH worker.
# The worker imports the Mac's own Developer ID .p12 into a temporary unlocked
# keychain and supplies CSC_KEYCHAIN/CSC_NAME (release_remote.py
# signing_keychain). A CSC_LINK/CSC_KEY_PASSWORD .p12 also passes the gate, but
# electron-builder's own keychain from it fails on macOS 27. SSH without either
# is rejected before building.
#
# What it does that build-macos.sh does not:
#   * refuses SSH builds without a configured temporary signing keychain
#   * refreshes venv-mac from requirements.txt, so a venv created before a new
#     dependency landed cannot silently ship without it (this is how xxhash and
#     scipy went missing on a build that looked fine)
#   * finds the App Store Connect key under ~/.apple-credentials and fills in
#     the notarisation variables, rather than making you remember three
#     exports
#   * writes a timestamped log, and copies the finished .dmg to the repo root
#
# Usage:
#     tools/build/build_mac.sh              # build, sign, notarise, staple
#     NOTARIZE=0 tools/build/build_mac.sh   # build + sign only (fast; not distributable)
#     tools/build/build_mac.sh --notarize   # notarise + staple a .dmg that already exists
#
# --notarize exists because signing and notarising fail for opposite reasons.
# Signing needs an unlocked login or temporary keychain. Notarising
# authenticates with a .p8 key file, so it works anywhere — including over ssh,
# and including on a build someone else already signed. A signed-but-
# unnotarised .dmg is REJECTED by Gatekeeper on every Mac but the one that
# built it, so this is the difference between an artifact and a download.
set -euo pipefail

# tools/build/ sits at the repo root; the app (package.json, venv-mac, dist-electron) is app/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_ROOT="$REPO_ROOT/app"
cd "$PROJECT_ROOT"

GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'

# --- 1. not over ssh -------------------------------------------------------
if [ -n "${SSH_CONNECTION:-}${SSH_TTY:-}${SSH_CLIENT:-}" ] \
    && [ "${1:-}" != "--notarize" ] && [ "${1:-}" != "--notarise" ] \
    && { [ -z "${CSC_NAME:-}" ] \
         || { [ ! -f "${CSC_KEYCHAIN:-}" ] && { [ ! -f "${CSC_LINK:-}" ] || [ -z "${CSC_KEY_PASSWORD:-}" ]; }; }; }; then
    echo -e "${RED}This is an ssh session.${NC}"
    echo "codesign cannot reach the private key of a Developer ID identity from"
    echo "one — the login keychain is locked outside a GUI session, and you get"
    echo "'errSecInternalComponent' partway through signing the app bundle."
    echo ""
    echo "Use ci.py's SSH builder with the local Developer ID .p12, or open"
    echo "Terminal on the Mac itself. If you only want to"
    echo "prove the pipeline (no signature, not distributable):"
    echo "    CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --mac -c.mac.identity=null"
    exit 1
fi

# --- 2. say what is about to be built --------------------------------------
VERSION=$(node -p "require('./package.json').version" 2>/dev/null || echo "?")
echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}SSBM Nucleus — macOS build ${VERSION}${NC}"
echo -e "${BLUE}================================${NC}"
if git rev-parse --git-dir >/dev/null 2>&1; then
    echo "  commit : $(git log --oneline -1)"
    echo "  branch : $(git rev-parse --abbrev-ref HEAD)"
    DIRTY=$(git status --porcelain -- . | wc -l | tr -d ' ')
    [ "$DIRTY" != "0" ] && echo -e "  ${YELLOW}note   : $DIRTY uncommitted change(s) under app/ — building them anyway${NC}"
fi
echo ""

# --- 3. the venv must match requirements.txt -------------------------------
# A venv-mac created before a dependency was added builds happily and ships
# without it. PyInstaller only warns, so the app is broken at runtime rather
# than at build time. Re-resolving costs seconds when nothing changed.
if [ -f venv-mac/bin/pip ]; then
    echo -e "${BLUE}[0/7] Refreshing venv-mac from requirements.txt...${NC}"
    if ! venv-mac/bin/pip install -q -r requirements.txt; then
        echo -e "${RED}✗ dependency install failed — fix that before building${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ dependencies current${NC}"
else
    echo "No venv-mac yet — build-macos.sh will create it."
fi
echo ""

# --- 4. notarisation credentials --------------------------------------------
# The key is a .p8 named AuthKey_<KEYID>.p8, so the key id comes from the
# filename. The issuer is a plain uuid and is not a secret; keep it beside the
# key in `issuer.txt` (or export NOTARY_ISSUER yourself).
load_notary_creds() {
    [ -n "${NOTARY_KEY:-}" ] && [ -n "${NOTARY_ISSUER:-}" ] && return 0
    CRED_DIR=$(ls -d "$HOME"/.apple-credentials/personal-* 2>/dev/null | head -1 || true)
    if [ -n "$CRED_DIR" ]; then
        KEY_FILE=$(ls "$CRED_DIR"/AuthKey_*.p8 2>/dev/null | head -1 || true)
        if [ -n "$KEY_FILE" ]; then
            export NOTARY_KEY="${NOTARY_KEY:-$KEY_FILE}"
            KEY_BASE=$(basename "$KEY_FILE" .p8)
            export NOTARY_KEY_ID="${NOTARY_KEY_ID:-${KEY_BASE#AuthKey_}}"
        fi
        if [ -z "${NOTARY_ISSUER:-}" ] && [ -f "$CRED_DIR/issuer.txt" ]; then
            NOTARY_ISSUER=$(tr -d '[:space:]' < "$CRED_DIR/issuer.txt")
            export NOTARY_ISSUER
        fi
    fi
    if [ -n "${NOTARY_KEY:-}" ] && [ -n "${NOTARY_ISSUER:-}" ]; then
        echo -e "${GREEN}✓ notary credentials found${NC} ($(basename "$NOTARY_KEY"), id ${NOTARY_KEY_ID})"
        return 0
    fi
    echo -e "${YELLOW}No notary credentials.${NC} The issuer uuid is on"
    echo "  appstoreconnect.apple.com → Users and Access → Integrations →"
    echo "  App Store Connect API. Save it once and this is automatic forever:"
    echo "      echo <issuer-uuid> > ${CRED_DIR:-~/.apple-credentials/personal-XXXX}/issuer.txt"
    return 1
}

# Notarise (and staple) a .dmg that already exists — no rebuild, no keychain.
notarize_only() {
    local dmg="${1:-}"
    [ -z "$dmg" ] && dmg=$(ls -t dist-electron/*.dmg "$PROJECT_ROOT"/*.dmg 2>/dev/null | head -1 || true)
    if [ -z "$dmg" ] || [ ! -f "$dmg" ]; then
        echo -e "${RED}No .dmg to notarise.${NC} Build one first, or pass a path."
        exit 1
    fi
    echo -e "${BLUE}Notarising $(basename "$dmg")${NC}"
    load_notary_creds || exit 1
    # Apple queues submissions; --wait blocks until a verdict. A timeout here
    # is NOT a rejection, and re-submitting would just queue a second copy.
    if ! xcrun notarytool submit "$dmg" --key "$NOTARY_KEY" --key-id "$NOTARY_KEY_ID"             --issuer "$NOTARY_ISSUER" --wait --timeout 20m; then
        echo -e "${RED}✗ notarisation did not complete.${NC} The submission is untouched —"
        echo "  resume with 'xcrun notarytool wait <id>', do not resubmit."
        exit 1
    fi
    # Stapling attaches the ticket so a first launch works with no network.
    xcrun stapler staple "$dmg"
    echo -e "${GREEN}✓ notarised and stapled${NC}"
    echo "Gatekeeper says:"
    spctl -a -vv -t install "$dmg" 2>&1 | sed 's/^/    /' || true
    exit 0
}

if [ "${1:-}" = "--notarize" ] || [ "${1:-}" = "--notarise" ]; then
    notarize_only "${2:-}"
fi

if [ "${NOTARIZE:-1}" != "0" ]; then
    load_notary_creds || echo -e "${YELLOW}  → the build will sign but skip notarisation${NC}"
fi
echo ""

# --- 5. build, logged ------------------------------------------------------
mkdir -p logs
LOG="logs/build_mac_$(date +%Y%m%d_%H%M%S).log"
echo "Full output → $LOG"
echo ""
set +e
bash "$SCRIPT_DIR/build-macos.sh" 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

if [ "$RC" -ne 0 ]; then
    echo ""
    echo -e "${RED}Build failed (exit $RC).${NC} Full log: $LOG"
    grep -nE "errSecInternalComponent|✗|ERROR|failedTask" "$LOG" | tail -5 | sed 's/^/    /' || true
    exit "$RC"
fi

# --- 6. hand back the artifact ---------------------------------------------
DMG=$(ls -t dist-electron/*.dmg 2>/dev/null | head -1 || true)
if [ -n "$DMG" ]; then
    cp -f "$DMG" "$PROJECT_ROOT/$(basename "$DMG")"
    echo ""
    echo -e "${GREEN}================================${NC}"
    echo -e "${GREEN}Build complete — ${VERSION}${NC}"
    echo -e "${GREEN}================================${NC}"
    echo "  $PROJECT_ROOT/$(basename "$DMG")"
    echo "  $(du -h "$DMG" | cut -f1)"
    echo ""
    # Gatekeeper's own verdict, which is the only one that matters. A build
    # that passes here still needs the quarantine test in the build-macos.sh
    # header before you trust it on someone else's Mac.
    echo "Gatekeeper says:"
    spctl -a -vv -t install "$DMG" 2>&1 | sed 's/^/    /' || true
    if spctl -a -t install "$DMG" 2>&1 | grep -q "Unnotarized"; then
        echo ""
        echo -e "${YELLOW}Signed, but NOT notarised — Gatekeeper blocks this on any other Mac.${NC}"
        echo "  Finish it without rebuilding:  tools/build/build_mac.sh --notarize"
    fi
else
    echo -e "${YELLOW}Build reported success but no .dmg was found in dist-electron/.${NC}"
    exit 1
fi
