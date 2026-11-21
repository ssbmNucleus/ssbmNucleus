#!/usr/bin/env bash
# Boot an ISO, enter the online CSS, report healthy/crashed, kill Dolphin.
# Usage: online_test_iso.sh <iso-path>
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
ISO="${1:?usage: online_test_iso.sh <iso>}"
node tools/ingame/dolphin/control.js kill >/dev/null 2>&1
node tools/ingame/dolphin/control.js launch --iso "$ISO" >/dev/null 2>&1
for i in $(seq 1 30); do
  if node tools/ingame/dolphin/pipe.js neutral >/dev/null 2>&1; then break; fi
  sleep 2
done
sleep 13
DPID=$(node tools/ingame/dolphin/control.js status 2>/dev/null | grep -oE 'PID [0-9]+' | head -1 | grep -oE '[0-9]+')
printf '{"pid": %s, "shot": 0}' "$DPID" > app/scratch/ingame/dolphin/live/session.json
RESULT=$(tools/ingame/nucleus/melee_venv/Scripts/python.exe tools/ingame/nucleus/online_css_test.py 2>&1 | grep "ONLINE-CSS")
echo "$RESULT"
node tools/ingame/dolphin/control.js kill >/dev/null 2>&1
