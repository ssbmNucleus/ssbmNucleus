#!/usr/bin/env node

/*
 * Interactive control harness for driving a *running* Slippi Dolphin one move
 * at a time. It is a thin convenience layer over the existing primitives:
 *   - win-input.ps1   focuses the window and emits keyboard events
 *   - win-window.ps1  captures a screenshot of the window
 *   - driver.js       boots an ISO into an isolated, logged-in User dir
 *
 * The point is to "feel around" the menus: send an input, screenshot, look at
 * the result, decide the next input -- instead of blind-scripting the analog
 * CSS cursor. Inputs are expressed as GameCube buttons (A/B/START/UP/...) and
 * mapped to the same keyboard keys driver.js binds to GCPad1.
 *
 * Usage:
 *   node tools/ingame/dolphin/control.js launch --iso "C:\\path\\game.iso"   boot + leave running
 *   node tools/ingame/dolphin/control.js status                              show PID + window title
 *   node tools/ingame/dolphin/control.js shot [--label name]                 screenshot only
 *   node tools/ingame/dolphin/control.js press <btn> [<btn> ...] [--ms N]    tap each, then screenshot
 *   node tools/ingame/dolphin/control.js tap <btn> [<btn> ...] [--ms N]      tap each, no screenshot
 *   node tools/ingame/dolphin/control.js hold <btn> --ms N                   press+hold one button N ms
 *   node tools/ingame/dolphin/control.js down <btn> | up <btn>               hold across calls
 *   node tools/ingame/dolphin/control.js kill                                stop Dolphin
 *
 * Buttons: A B X Y Z START | UP DOWN LEFT RIGHT (stick) | CUP CDOWN CLEFT CRIGHT
 *          (c-stick) | L R | DUP DDOWN DLEFT DRIGHT (d-pad). Unknown names are
 *          passed through to win-input.ps1 as a raw key (e.g. ENTER, LSHIFT, A).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');

const HERE = __dirname;
const ROOT_DIR = path.resolve(HERE, '..', '..', '..', 'app');  // the app/ folder
const INPUT_HELPER = path.join(HERE, 'win-input.ps1');
const WINDOW_HELPER = path.join(HERE, 'win-window.ps1');
const BATCH_HELPER = path.join(HERE, 'win-batch.ps1');
const DRIVER = path.join(HERE, 'driver.js');
const LIVE_DIR = path.join(ROOT_DIR, 'scratch', 'ingame', 'dolphin', 'live');
const SHOT_DIR = path.join(LIVE_DIR, 'screenshots');
const SESSION_FILE = path.join(LIVE_DIR, 'session.json');
const DOLPHIN_IMAGE = 'Slippi Dolphin.exe';

// GameCube button -> keyboard key, matching the GCPad1 binding in driver.js.
const BUTTON_TO_KEY = {
  A: 'X', B: 'Z', X: 'C', Y: 'S', Z: 'D', START: 'ENTER',
  UP: 'UP', DOWN: 'DOWN', LEFT: 'LEFT', RIGHT: 'RIGHT',
  CUP: 'I', CDOWN: 'K', CLEFT: 'J', CRIGHT: 'L',
  L: 'Q', R: 'W',
  DUP: 'T', DDOWN: 'G', DLEFT: 'F', DRIGHT: 'H',
};

function assertWindows() {
  if (process.platform !== 'win32') {
    throw new Error('tools/ingame/dolphin/control.js currently only supports Windows.');
  }
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function resolveKey(name) {
  const upper = String(name).trim().toUpperCase();
  return BUTTON_TO_KEY[upper] || name;
}

function safeFileName(value) {
  return String(value || 'shot')
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, '-')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'shot';
}

function readSession() {
  if (fs.existsSync(SESSION_FILE)) {
    try {
      return JSON.parse(fs.readFileSync(SESSION_FILE, 'utf8'));
    } catch (error) {
      return {};
    }
  }
  return {};
}

function writeSession(session) {
  fs.mkdirSync(LIVE_DIR, { recursive: true });
  fs.writeFileSync(SESSION_FILE, JSON.stringify(session, null, 2), 'utf8');
}

function listDolphinPids() {
  const res = cp.spawnSync('tasklist', ['/FI', `IMAGENAME eq ${DOLPHIN_IMAGE}`, '/FO', 'CSV', '/NH'], {
    encoding: 'utf8',
  });
  const out = (res.stdout || '').trim();
  if (!out || /No tasks/i.test(out)) {
    return [];
  }
  const pids = [];
  for (const line of out.split(/\r?\n/)) {
    const match = line.match(/^"[^"]*","(\d+)"/);
    if (match) {
      pids.push(parseInt(match[1], 10));
    }
  }
  return pids;
}

function isAlive(pid) {
  return pid ? listDolphinPids().includes(pid) : false;
}

// Find the Dolphin to talk to: explicit --pid, then a remembered+alive session
// PID, then the sole running Dolphin. Refuses to guess when several are open,
// and refuses to ADOPT a foreign Dolphin that another agent's harness owns
// (machine-wide lock at %LOCALAPPDATA%/SSBM Nucleus/harness-dolphin.lock).
function lockOwner() {
  try {
    const p = path.join(process.env.LOCALAPPDATA || '', 'SSBM Nucleus', 'harness-dolphin.lock');
    const info = JSON.parse(fs.readFileSync(p, 'utf8'));
    if (info.pid && cp.spawnSync('tasklist', ['/FI', `PID eq ${info.pid}`, '/FO', 'CSV', '/NH'],
        { encoding: 'utf8' }).stdout.includes(`"${info.pid}"`)) {
      return info;
    }
  } catch (e) { /* no lock or unreadable = unowned */ }
  return null;
}

function discoverPid(explicit) {
  if (explicit) {
    const pid = parseInt(explicit, 10);
    if (!isAlive(pid)) {
      throw new Error(`No running Dolphin with PID ${pid}.`);
    }
    return pid;
  }
  const session = readSession();
  if (session.pid && isAlive(session.pid)) {
    return session.pid;
  }
  const pids = listDolphinPids();
  if (pids.length === 1) {
    const owner = lockOwner();
    if (owner && owner.pid !== process.pid) {
      throw new Error(
        `The running Dolphin belongs to another agent (lock holder pid ${owner.pid}: ` +
        `${owner.purpose || '?'}). Not adopting it -- launch your own (it will queue), ` +
        'or pass --pid explicitly if it really is yours.');
    }
    return pids[0];
  }
  if (pids.length === 0) {
    throw new Error('No running "Slippi Dolphin.exe". Launch it first (control.js launch --iso ...).');
  }
  throw new Error(`Multiple Dolphin processes running (${pids.join(', ')}). Pass --pid <id>.`);
}

function runInput(action, pid, key, durationMs) {
  const args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', INPUT_HELPER, '-ProcessId', String(pid), '-Action', action];
  if (key) {
    args.push('-Key', key);
  }
  if (durationMs !== undefined && durationMs !== null) {
    args.push('-DurationMs', String(durationMs));
  }
  const res = cp.spawnSync('powershell.exe', args, { cwd: ROOT_DIR, encoding: 'utf8' });
  if (res.status !== 0) {
    throw new Error((res.stderr || res.stdout || `input helper failed (${action})`).trim());
  }
}

function nextShotPath(pid, label) {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const session = readSession();
  const seq = (session.shot || 0) + 1;
  session.shot = seq;
  session.pid = pid;
  writeSession(session);
  const seqStr = String(seq).padStart(4, '0');
  return path.join(SHOT_DIR, `${seqStr}-${safeFileName(label)}.png`);
}

// Single-process fast path: focus + tap each key + (optional) screenshot, with
// the native code compiled once and cached as a DLL by win-batch.ps1. Each key
// may carry a per-key hold as "KEY:ms" (see win-batch.ps1).
function runBatch(pid, keys, durationMs, outputPath, gapMs) {
  const args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', BATCH_HELPER, '-ProcessId', String(pid)];
  if (keys && keys.length) {
    args.push('-Keys', keys.join(','));
  }
  if (durationMs !== undefined && durationMs !== null) {
    args.push('-DurationMs', String(durationMs));
  }
  if (gapMs !== undefined && gapMs !== null) {
    args.push('-GapMs', String(gapMs));
  }
  if (outputPath) {
    args.push('-OutputPath', outputPath);
  }
  const res = cp.spawnSync('powershell.exe', args, { cwd: ROOT_DIR, encoding: 'utf8' });
  if (res.status !== 0) {
    throw new Error((res.stderr || res.stdout || 'win-batch helper failed').trim());
  }
}

// Resolve a token that may carry a per-key hold, e.g. "UP" or "UP:450", mapping
// the button name to its key while preserving the ":ms" suffix.
function resolveToken(token) {
  const idx = String(token).indexOf(':');
  if (idx === -1) {
    return resolveKey(token);
  }
  return `${resolveKey(token.slice(0, idx))}:${token.slice(idx + 1)}`;
}

function parseFlags(tokens) {
  const flags = {};
  const positional = [];
  for (let i = 0; i < tokens.length; i += 1) {
    const token = tokens[i];
    if (token.startsWith('--')) {
      const key = token.slice(2);
      const value = tokens[i + 1];
      if (value === undefined || value.startsWith('--')) {
        flags[key] = true;
      } else {
        flags[key] = value;
        i += 1;
      }
    } else {
      positional.push(token);
    }
  }
  return { flags, positional };
}

// -- machine-wide Dolphin lock (shared with backend/shared/ingame/dolphin_lock.py) --
const LOCK_PATH = path.join(process.env.LOCALAPPDATA || '', 'SSBM Nucleus', 'harness-dolphin.lock');

function pidAlive(pid) {
  if (!pid) return false;
  const out = cp.spawnSync('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'],
    { encoding: 'utf8' }).stdout || '';
  return out.includes(`"${pid}"`);
}

function waitForDolphinLock(purpose) {
  // Queue while another live process/Dolphin owns the lock; reclaim stale.
  const waitMs = 1000 * parseFloat(process.env.MELEE_DOLPHIN_LOCK_WAIT || '600');
  const deadline = Date.now() + waitMs;
  for (;;) {
    let owner = null;
    try { owner = JSON.parse(fs.readFileSync(LOCK_PATH, 'utf8')); } catch (e) { /* free */ }
    if (!owner || !pidAlive(owner.pid)) {
      try { fs.unlinkSync(LOCK_PATH); } catch (e) { /* already gone */ }
      return;
    }
    if (Date.now() >= deadline) {
      throw new Error(`Dolphin is in use by pid ${owner.pid} (${owner.purpose || '?'}) ` +
        `since ${owner.started_str || '?'} -- waited ${waitMs / 1000}s. ` +
        'Raise MELEE_DOLPHIN_LOCK_WAIT or try later.');
    }
    sleepSync(2000);
  }
}

function writeDolphinLock(dolphinPid, purpose) {
  // Owner pid = the DOLPHIN itself, so the lock expires exactly when the
  // emulator dies (control.js exits right after launch; its own pid would
  // go instantly stale).
  try {
    fs.mkdirSync(path.dirname(LOCK_PATH), { recursive: true });
    fs.writeFileSync(LOCK_PATH, JSON.stringify({
      pid: dolphinPid, purpose,
      started: Date.now() / 1000,
      started_str: new Date().toISOString().replace('T', ' ').slice(0, 19),
      argv0: 'tools/ingame/dolphin/control.js',
    }));
  } catch (e) { /* advisory -- never block the launch on lock IO */ }
}

function cmdLaunch(flags) {
  if (!flags.iso) {
    throw new Error('launch requires --iso "C:\\path\\game.iso".');
  }
  waitForDolphinLock(`control.js launch ${path.basename(String(flags.iso))}`);
  const scenario = flags.scenario || path.join(HERE, 'scenarios', 'boot-idle.json');
  const args = [DRIVER, '--iso', flags.iso, '--scenario', scenario, '--keep-open'];
  if (flags.dolphin) {
    args.push('--dolphin', flags.dolphin);
  }
  // Texture-pack harvest: boot into a KNOWN run dir (so the backend watcher can
  // find this Dolphin's Dump/Load folders) with texture dumping on from boot.
  if (flags['run-dir']) {
    args.push('--run-dir', flags['run-dir']);
  }
  if (flags['texture-dump']) {
    args.push('--texture-dump');
  }
  if (flags['audio-dump']) {
    args.push('--audio-dump');
  }

  // driver.js keeps its own process alive while Dolphin runs (it pipes Dolphin's
  // stdio and waits for the exit event), so we must NOT block on it -- spawn it
  // detached and return as soon as the Dolphin process itself appears, leaving
  // both running in the background so the menus can be driven interactively.
  // Dolphin occasionally just doesn't come up (Slippi update check, AV scan,
  // a transient hiccup), so retry the whole spawn a few times.
  const attempts = flags.attempts ? parseInt(flags.attempts, 10) : 3;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const before = new Set(listDolphinPids());
    console.log(`Launching via driver.js (boot-idle, --keep-open)${attempt > 1 ? ` [attempt ${attempt}]` : ''}...`);
    const child = cp.spawn(process.execPath, args, { cwd: ROOT_DIR, detached: true, stdio: 'ignore' });
    child.unref();

    const deadline = Date.now() + 30000;
    let pid = null;
    while (Date.now() < deadline) {
      const fresh = listDolphinPids().filter((p) => !before.has(p));
      if (fresh.length) {
        pid = fresh[fresh.length - 1];
        break;
      }
      sleepSync(500);
    }
    if (pid) {
      writeSession({ pid, shot: 0 });
      writeDolphinLock(pid, `control.js launch ${path.basename(String(flags.iso))}`);
      console.log(`Dolphin started (PID ${pid}); the game is booting (~13s to the menu).`);
      console.log('Drive it with: node tools/ingame/dolphin/control.js press <button>');
      return;
    }
    console.log(`Dolphin did not start within 30s (attempt ${attempt}/${attempts}).`);
    // kill any half-started Dolphin from this attempt before retrying
    for (const p of listDolphinPids().filter((p) => !before.has(p))) {
      cp.spawnSync('taskkill.exe', ['/PID', String(p), '/T', '/F'], { encoding: 'utf8' });
    }
  }
  throw new Error(`Dolphin did not start after ${attempts} attempts.`);
}

function cmdStatus(flags) {
  const pids = listDolphinPids();
  if (!pids.length) {
    console.log('No running Slippi Dolphin.');
    return;
  }
  const pid = discoverPid(flags.pid);
  const args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', WINDOW_HELPER, '-ProcessId', String(pid), '-Action', 'title'];
  const res = cp.spawnSync('powershell.exe', args, { cwd: ROOT_DIR, encoding: 'utf8' });
  const title = (res.stdout || '').trim();
  console.log(`Dolphin PID ${pid}${pids.length > 1 ? ` (of ${pids.join(', ')})` : ''}`);
  console.log(`Window title: ${title}`);
}

function cmdInputs(command, buttons, flags) {
  if (!buttons.length && command !== 'shot') {
    throw new Error(`${command} requires at least one button (e.g. ${command} A).`);
  }
  const pid = discoverPid(flags.pid);
  const ms = flags.ms !== undefined ? parseInt(flags.ms, 10) : undefined;

  // hold/down/up are rare and stay on the per-input helper.
  if (command === 'hold') {
    runInput('tap', pid, resolveKey(buttons[0]), ms !== undefined ? ms : 500);
    console.log(`OK (hold ${buttons[0]}) -> PID ${pid}`);
    return;
  }
  if (command === 'down') {
    runInput('keyDown', pid, resolveKey(buttons[0]));
    console.log(`OK (down ${buttons[0]}) -> PID ${pid}`);
    return;
  }
  if (command === 'up') {
    runInput('keyUp', pid, resolveKey(buttons[0]));
    console.log(`OK (up ${buttons[0]}) -> PID ${pid}`);
    return;
  }

  // tap / press / shot run as ONE batched PowerShell process (focus + taps +
  // optional screenshot) for speed.
  const gap = flags.gap !== undefined ? parseInt(flags.gap, 10) : undefined;
  const keys = buttons.map(resolveKey);
  if (command === 'tap') {
    runBatch(pid, keys, ms !== undefined ? ms : 90, null, gap);
    console.log(`OK (tap ${buttons.join(' ')}) -> PID ${pid}`);
    return;
  }
  const label = flags.label || (buttons.length ? buttons.join('-') : 'shot');
  const out = nextShotPath(pid, label);
  runBatch(pid, command === 'shot' ? [] : keys, ms !== undefined ? ms : 90, out, gap);
  console.log(out);
}

// --- Character select: pin-to-corner + grid-step targeting ------------------
//
// On the CSS the cursor accelerates and a long hold clamps it to the screen
// edge, so we pin to the top-left corner (above/left of Dr. Mario) and step in
// from there. Calibrated live: Down:STEP_MS lands one row in, each further
// Down:STEP_MS = one row, Right:STEP_MS = one column. So character (row, col)
// (1-indexed, top-left = Dr. Mario at 1,1) is reached with Down x row and
// Right x (col-1).
const PIN_MS = 900; // long hold so the cursor fully clamps to the wall
const HOME_DOWN_MS = 110; // drop from the top pin onto row 1 (Dr. Mario)
const HOME_RIGHT_MS = 60; // half-cell right nudge to center on Dr. Mario
const ROW_MS = 80; // hold for one further row (row 1 -> 2 -> 3)
const COL_MS = 110; // hold for one column (horizontal step)
const STEP_GAP = 120; // gap between steps so each is a discrete from-rest hop
// The top-left pin lands up-and-left of Dr. Mario, so to anchor ON Dr. Mario
// (1,1) we drop one row (Down:HOME_DOWN_MS) and nudge right by a half-cell
// (Right:HOME_RIGHT_MS). Every character is then counted FROM Dr. Mario:
// Down:ROW_MS x (row-1), Right:COL_MS x (col-1).

// name -> [row, col]. Aliases share a cell.
const CHAR_GRID = {
  drmario: [1, 1], doctormario: [1, 1], doc: [1, 1],
  mario: [1, 2],
  luigi: [1, 3],
  bowser: [1, 4],
  peach: [1, 5],
  yoshi: [1, 6],
  dk: [1, 7], donkeykong: [1, 7],
  falcon: [1, 8], captainfalcon: [1, 8], cf: [1, 8],
  ganondorf: [1, 9], ganon: [1, 9],
  falco: [2, 1],
  fox: [2, 2],
  ness: [2, 3],
  iceclimbers: [2, 4], ics: [2, 4], icies: [2, 4], popo: [2, 4],
  kirby: [2, 5],
  samus: [2, 6],
  zelda: [2, 7], sheik: [2, 7],
  link: [2, 8],
  younglink: [2, 9], yink: [2, 9], yl: [2, 9],
  pichu: [3, 1],
  pikachu: [3, 2], pika: [3, 2],
  jigglypuff: [3, 3], puff: [3, 3], jiggs: [3, 3],
  mewtwo: [3, 4], mew2: [3, 4],
  gameandwatch: [3, 5], gnw: [3, 5], gw: [3, 5], mrgameandwatch: [3, 5],
  marth: [3, 6],
  roy: [3, 7],
};

function normalizeName(name) {
  return String(name).toLowerCase().replace(/[^a-z0-9]/g, '');
}

function cmdChar(positional, flags) {
  const name = normalizeName(positional[0] || '');
  const cell = CHAR_GRID[name];
  if (!cell) {
    throw new Error(`Unknown character "${positional[0]}". Known: ${Object.keys(CHAR_GRID).sort().join(', ')}`);
  }
  const [row, col] = cell;
  const pid = discoverPid(flags.pid);
  const pinMs = flags.pin !== undefined ? parseInt(flags.pin, 10) : PIN_MS;
  const homeDownMs = flags.homedown !== undefined ? parseInt(flags.homedown, 10) : HOME_DOWN_MS;
  const homeRightMs = flags.homeright !== undefined ? parseInt(flags.homeright, 10) : HOME_RIGHT_MS;
  const rowMs = flags.row !== undefined ? parseInt(flags.row, 10) : ROW_MS;
  const colMs = flags.col !== undefined ? parseInt(flags.col, 10) : COL_MS;
  const gap = flags.gap !== undefined ? parseInt(flags.gap, 10) : STEP_GAP;

  // Anchor on Dr. Mario (1,1): pin to the top-left wall, drop one row, nudge
  // right a half-cell. Then step out to (row, col) counting from Dr. Mario.
  const keys = [`UP:${pinMs}`, `LEFT:${pinMs}`, `DOWN:${homeDownMs}`, `RIGHT:${homeRightMs}`];
  for (let i = 0; i < row - 1; i += 1) {
    keys.push(`DOWN:${rowMs}`);
  }
  for (let i = 0; i < col - 1; i += 1) {
    keys.push(`RIGHT:${colMs}`);
  }
  if (!flags.hover) {
    keys.push('X:60'); // A: lock the character in
  }

  const out = nextShotPath(pid, flags.label || `char-${name}`);
  runBatch(pid, keys, colMs, out, gap);
  console.log(out);
}

// Fire a whole sequence in one process at TAS-ish speed. Each token may carry a
// per-key hold, e.g. `seq LEFT:450 UP:450 DOWN DOWN RIGHT A` --ms 70 --gap 25.
function cmdSeq(tokens, flags) {
  if (!tokens.length) {
    throw new Error('seq requires a sequence, e.g. seq UP UP LEFT A');
  }
  const pid = discoverPid(flags.pid);
  const ms = flags.ms !== undefined ? parseInt(flags.ms, 10) : 70;
  const gap = flags.gap !== undefined ? parseInt(flags.gap, 10) : 25;
  const keys = tokens.map(resolveToken);
  const out = flags.noshot ? null : nextShotPath(pid, flags.label || 'seq');
  runBatch(pid, keys, ms, out, gap);
  console.log(out || `OK (seq ${tokens.length} inputs) -> PID ${pid}`);
}

function cmdKill(flags) {
  // Session-scoped by default: kill ONLY the Dolphin this harness launched
  // (session.json). A no-arg image-name sweep used to murder every agent's
  // emulator on the machine (and the app's embedded test window) whenever
  // any harness cleaned up -- pass --all if you truly mean machine-wide.
  let pids;
  if (flags.pid) {
    pids = [parseInt(flags.pid, 10)];
  } else if (flags.all) {
    pids = listDolphinPids();
  } else {
    const session = readSession();
    pids = session.pid && isAlive(session.pid) ? [session.pid] : [];
  }
  if (!pids.length) {
    console.log('No session-owned Slippi Dolphin to stop (use --all to sweep every Dolphin).');
    return;
  }
  for (const pid of pids) {
    cp.spawnSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { encoding: 'utf8' });
    console.log(`Stopped Dolphin PID ${pid}.`);
  }
}

function main() {
  assertWindows();
  const [command, ...rest] = process.argv.slice(2);
  const { flags, positional } = parseFlags(rest);

  switch (command) {
    case 'launch':
      cmdLaunch(flags);
      break;
    case 'status':
      cmdStatus(flags);
      break;
    case 'kill':
      cmdKill(flags);
      break;
    case 'shot':
    case 'press':
    case 'tap':
    case 'hold':
    case 'down':
    case 'up':
      cmdInputs(command, positional, flags);
      break;
    case 'seq':
      cmdSeq(positional, flags);
      break;
    case 'char':
      cmdChar(positional, flags);
      break;
    default:
      throw new Error(`Unknown command: ${command || '<none>'}. Try: launch | status | press | tap | hold | down | up | shot | seq | char | kill`);
  }
}

main();
