#!/usr/bin/env node

/*
 * Controller input to Slippi Dolphin's named pipe for port 1
 * (\\.\pipe\slippibot1 on Windows). The precise, focus-free channel.
 *
 * IMPORTANT Windows behavior (verified by logging): Dolphin reads ONE FLUSH
 * batch per pipe connection and then closes it. So each input "frame" must be
 * its own fresh connection, written immediately on connect. A button tap is
 * therefore TWO connections -- one to PRESS, one to RELEASE -- otherwise the
 * release is lost to the close and the button sticks. Likewise a stick tilt is
 * one connection to tilt and a second to re-center.
 *
 * Pipe protocol (newline-terminated): PRESS/RELEASE <BTN>, SET MAIN <x> <y>,
 * SET C <x> <y>, SET L|R <v>, FLUSH. Sticks 0.0-1.0, 0.5 = center; for the
 * control stick y=0.0 is UP, y=1.0 is DOWN, x=0.0 is LEFT, x=1.0 is RIGHT.
 *
 * Usage:
 *   node pipe.js tap A [--ms 50]              press then release (two frames)
 *   node pipe.js press A | node pipe.js release A
 *   node pipe.js tilt MAIN <x> <y> [--ms 100] tilt then re-center
 *   node pipe.js stick MAIN <x> <y>           tilt, leave held
 *   node pipe.js trig L <v>                    analog trigger 0..1
 *   node pipe.js neutral                       release all, center sticks
 *   node pipe.js frame "PRESS A" "FLUSH"       one raw connection/frame
 *
 * Buttons: A B X Y Z L R START D_UP D_DOWN D_LEFT D_RIGHT
 */

const net = require('net');

const BUTTONS = new Set(['A', 'B', 'X', 'Y', 'Z', 'L', 'R', 'START', 'D_UP', 'D_DOWN', 'D_LEFT', 'D_RIGHT']);
const BUTTON_ALIASES = { DUP: 'D_UP', DDOWN: 'D_DOWN', DLEFT: 'D_LEFT', DRIGHT: 'D_RIGHT' };

// --- Character-select targeting (pipe analog) -------------------------------
// Pin the cursor to a wall, drop onto the row, then step to the target column.
// The cursor ACCELERATES with distance, so the far columns of a row (next to
// the right wall) are a tiny timing target from the left pin -- the cursor is
// moving fast there and overshoots into the wall clamp. Those columns are
// instead reached from the RIGHT pin (clamp to the right wall, step LEFT a
// short, slow distance). See ROW_RIGHT. All hold-times are TUNABLE/calibrated.
const CSS = {
  PIN_MS: 1800,       // hold up-left to clamp to the top-left corner. Must be
                      // long enough to clamp from the OPPOSITE (bottom-right)
                      // corner -- the worst-case diagonal -- else the origin
                      // under-travels and everything shifts right.
  HOME_DOWN: 65,      // drop from the pin onto row 1 (centered)
  HOME_RIGHT: 55,     // nudge right onto column 1 -> Dr. Mario
  RPIN_MS: 1800,      // hold up-right to clamp to the top-right corner (worst-
                      // case diagonal from the bottom-left corner)
  RHOME_DOWN: 65,     // drop from the right pin onto row 1 -> rightmost char
  ROW_DOWN: { 1: 0, 2: 50 }, // extra down from row 1 to reach rows 1-2
  ROW3_DOWN: 55,      // final down-step from row 2 onto row 3 (see below)
  COL_BASE: 40,       // extra right for column 2
  COL_STEP: 93,       // extra right per column after 2 (~93ms/col measured)
  PACE: 180,          // ms between input frames (avoid the rapid-fire freeze)
  A_HOLD: 60,
  COLOR_BTN: 'X',     // button that cycles costume color on the CSS
};
// Per-row: columns reached from the RIGHT wall, with their left-step hold (ms).
// Columns not listed use the left-pin linear model (colRight). Top row: c9
// (Ganondorf) is the wall itself; c8 (Falcon) is one short step left.
const ROW_RIGHT = {
  1: { 9: 0, 8: 60 },  // Ganondorf (wall), C. Falcon
  2: { 9: 0, 8: 60 },  // Young Link (wall), Link
};
function colRight(col) {
  return col <= 1 ? 0 : CSS.COL_BASE + (col - 2) * CSS.COL_STEP;
}
function rightStep(row, col) {
  const r = ROW_RIGHT[row];
  return r && r[col] !== undefined ? r[col] : null;
}

// name -> [row, col], 1-indexed, top-left = Dr. Mario. Aliases share a cell.
const CHAR_GRID = {
  drmario: [1, 1], doc: [1, 1], mario: [1, 2], luigi: [1, 3], bowser: [1, 4],
  peach: [1, 5], yoshi: [1, 6], dk: [1, 7], donkeykong: [1, 7],
  falcon: [1, 8], captainfalcon: [1, 8], cf: [1, 8], ganondorf: [1, 9], ganon: [1, 9],
  falco: [2, 1], fox: [2, 2], ness: [2, 3], iceclimbers: [2, 4], ics: [2, 4],
  kirby: [2, 5], samus: [2, 6], zelda: [2, 7], sheik: [2, 7], link: [2, 8],
  younglink: [2, 9], yl: [2, 9],
  pichu: [3, 1], pikachu: [3, 2], pika: [3, 2], jigglypuff: [3, 3], puff: [3, 3],
  mewtwo: [3, 4], gameandwatch: [3, 5], gnw: [3, 5], marth: [3, 6], roy: [3, 7],
};

function resolveButton(name) {
  const upper = String(name).trim().toUpperCase();
  const mapped = BUTTON_ALIASES[upper] || upper;
  if (!BUTTONS.has(mapped)) {
    throw new Error(`Unknown button "${name}". Known: ${[...BUTTONS].join(', ')}`);
  }
  return mapped;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// One input frame: fresh connection, write all lines on connect, then close.
// Dolphin consumes one FLUSH batch per connection, so this is the unit of input.
function frame(port, lines) {
  const pipePath = `\\\\.\\pipe\\slippibot${port}`;
  return new Promise((resolve, reject) => {
    const sock = net.connect(pipePath);
    let settled = false;
    const finish = (err) => {
      if (settled) return;
      settled = true;
      if (err) reject(err);
      else resolve();
    };
    sock.on('connect', async () => {
      for (const line of lines) sock.write(`${line}\n`);
      await sleep(25); // let the bytes flush + be read for a frame before close
      sock.end();
      finish();
    });
    sock.on('error', (err) => finish(new Error(`pipe ${pipePath}: ${err.message}`)));
  });
}

// Tilt the control stick to (x,y), hold, then re-center -- each as its own
// frame, with PACE between so the controller state never freezes.
async function tiltHold(port, x, y, holdMs) {
  await frame(port, [`SET MAIN ${x} ${y}`, 'FLUSH']);
  await sleep(holdMs);
  await frame(port, ['SET MAIN 0.5 0.5', 'FLUSH']);
  await sleep(CSS.PACE);
}

async function tapButton(port, btn, holdMs) {
  await frame(port, [`PRESS ${btn}`, 'FLUSH']);
  await sleep(holdMs);
  await frame(port, [`RELEASE ${btn}`, 'FLUSH']);
  await sleep(CSS.PACE);
}

// Pin to the nearest wall -> drop onto the row -> step to the column ->
// A -> cycle costume color. Wall-adjacent columns (ROW_RIGHT) come from the
// right pin and step LEFT; all others come from the left pin and step RIGHT.
//
// Row 3 (the 7-wide bottom row) is center-shifted RIGHT by one column, so
// row-3 cN sits directly below row-2 c(N+1) (e.g. Pichu under Fox, Roy under
// Link). We therefore reuse the fully-calibrated row-2 targeting for column
// (col+1) and then take one short down-step (ROW3_DOWN) onto row 3.
async function selectChar(port, name, opts) {
  const key = String(name).toLowerCase().replace(/[^a-z0-9]/g, '');
  const cell = CHAR_GRID[key];
  if (!cell) {
    throw new Error(`Unknown character "${name}". Known: ${Object.keys(CHAR_GRID).sort().join(', ')}`);
  }
  let [row, col] = cell;
  let postDown = 0;
  if (row === 3) {
    postDown = opts.r3down !== undefined ? Number(opts.r3down) : CSS.ROW3_DOWN;
    row = 2;       // reuse the row-2 targeting, shifted one column right
    col += 1;
  }
  const rowDown = opts.row !== undefined ? Number(opts.row) : CSS.ROW_DOWN[row];
  // --col forces the left-pin path with an explicit right-step (calibration).
  const rstep = opts.col !== undefined ? null : rightStep(row, col);

  if (rstep !== null) {
    // Right-pin path: clamp to the top-right corner, drop onto the row, step left.
    const pin = opts.pin !== undefined ? Number(opts.pin) : CSS.RPIN_MS;
    const homeDown = opts.homedown !== undefined ? Number(opts.homedown) : CSS.RHOME_DOWN;
    const stepL = opts.rstep !== undefined ? Number(opts.rstep) : rstep;
    await tiltHold(port, '1.0', '1.0', pin);       // pin top-right
    await tiltHold(port, '0.5', '0.0', homeDown);  // down onto row 1 (-> rightmost char)
    if (rowDown > 0) await tiltHold(port, '0.5', '0.0', rowDown);
    if (stepL > 0) await tiltHold(port, '0.0', '0.5', stepL); // step left
  } else {
    // Left-pin path: clamp to the top-left corner, drop onto Dr. Mario, step right.
    const pin = opts.pin !== undefined ? Number(opts.pin) : CSS.PIN_MS;
    const homeDown = opts.homedown !== undefined ? Number(opts.homedown) : CSS.HOME_DOWN;
    const homeRight = opts.homeright !== undefined ? Number(opts.homeright) : CSS.HOME_RIGHT;
    const colR = opts.col !== undefined ? Number(opts.col) : colRight(col);
    await tiltHold(port, '0.0', '1.0', pin);       // pin top-left
    await tiltHold(port, '0.5', '0.0', homeDown);  // down onto row 1
    await tiltHold(port, '1.0', '0.5', homeRight); // right onto col 1 (Dr. Mario)
    if (rowDown > 0) await tiltHold(port, '0.5', '0.0', rowDown);
    if (colR > 0) await tiltHold(port, '1.0', '0.5', colR);
  }

  if (postDown > 0) await tiltHold(port, '0.5', '0.0', postDown); // row 2 -> row 3

  // Cycle the costume color while HOVERING (X cycles the token's color), then
  // lock it in with A. (After locking, X no longer cycles -- order matters.)
  const colorN = opts.color ? parseInt(opts.color, 10) : 0;
  for (let i = 0; i < colorN; i += 1) {
    await tapButton(port, CSS.COLOR_BTN, 50); // cycle costume color
  }
  if (!opts.hover) {
    await tapButton(port, 'A', CSS.A_HOLD); // lock the character + chosen color
  }
}

function neutralFrame(port) {
  const lines = [...BUTTONS].map((b) => `RELEASE ${b}`);
  lines.push('SET MAIN 0.5 0.5', 'SET C 0.5 0.5', 'SET L 0', 'SET R 0', 'FLUSH');
  return frame(port, lines);
}

// Full post-boot match start: from the Slippi "Online Play" submenu the ISO
// lands on, back out to the main menu, into VS Mode, add a CPU on port 2, pick
// our character + costume, choose a stage, and start. The menu waits are the
// proven recipe; booting the ISO (~13s) is the caller's responsibility. Works
// for both vanilla-Slippi and Nucleus-built modded ISOs (both land in Online
// Play). Returns once the match should be loading.
// From the post-boot Online Play submenu, back out to the main menu, into VS
// Mode, and onto the character-select screen. Shared by startMatch and the
// standalone `gotocss` command (used for boot-health checks of any mod).
async function navToCss(port) {
  await neutralFrame(port);
  await sleep(CSS.PACE);
  await tapButton(port, 'B', CSS.A_HOLD);          // out of Online Play...
  await tapButton(port, 'B', CSS.A_HOLD);          // ...back to the main menu
  await tapButton(port, 'D_DOWN', CSS.A_HOLD);     // down to VS Mode
  await tapButton(port, 'A', CSS.A_HOLD);
  await sleep(1500);                               // -> VS submenu (Melee)
  await tapButton(port, 'A', CSS.A_HOLD);
  await sleep(3000);                               // -> character select
}

async function startMatch(port, opts) {
  const char = opts.char || 'fox';
  const color = opts.color !== undefined ? opts.color : 0;
  await navToCss(port);
  if (!opts.nocpu) {
    // CPU opponent on port 2: its N/A door is just right of the port-1 spawn.
    await tiltHold(port, '1.0', '0.5', 150);
    await tapButton(port, 'A', CSS.A_HOLD);
    await sleep(CSS.PACE);
  }
  // Our character + costume (selectChar presses A to lock it in).
  await selectChar(port, char, { color });
  await sleep(400);
  // Start -> stage select. The stage cursor spawns below the grid, so tilt up
  // onto a stage, then confirm to start the match.
  await tapButton(port, 'START', CSS.A_HOLD);
  await sleep(1500);
  await tiltHold(port, '0.5', '1.0', 110);
  await tapButton(port, 'A', CSS.A_HOLD);
}

// Add a CPU on port 2 (its N/A door is just right of the port-1 spawn). A 2nd
// player is REQUIRED before you can lock your character in. Used as a discrete
// step so a closed-loop (memory-feedback) selector can do the character pick.
//
// ⚠️ For GAMEPLAY/crash testing do NOT use this CPU path — the CPU attacks you
// and moves the camera, ruining move/crash repros. Use the solo, no-CPU engine
// in backend/shared/ingame/ (memory-loads the match alone; template
// backend/devtools/research/fsm_crash_probe.py; docs backend/shared/ingame/README.md). This CPU step is
// only for testing the CSS/SSS UI itself.
async function cpuStep(port) {
  await tiltHold(port, '1.0', '0.5', 150);
  await tapButton(port, 'A', CSS.A_HOLD);
  await sleep(CSS.PACE);
}

// From a locked CSS (READY TO FIGHT): START -> stage select -> pick a stage.
// Leads with a neutral so that if this is the first input after a pipe handoff
// (closed-loop selector -> here), the sacrificial frame absorbs any dropped
// first-connection write and START itself lands reliably.
async function postStart(port) {
  await neutralFrame(port);
  await sleep(CSS.PACE);
  await tapButton(port, 'START', CSS.A_HOLD);
  await sleep(1500);
  await tiltHold(port, '0.5', '1.0', 110);
  await tapButton(port, 'A', CSS.A_HOLD);
}

// From a locked CSS: START -> stage select, then STOP (leave the cursor on the
// stage grid). This hands off to the closed-loop stage selector (melee_sss.py),
// which reads the cursor + hovered stage and picks the target stage itself --
// the stage analog of cpustep+cl_select. Ends with a neutral so the persistent
// pipe's first write isn't dropped on the handoff.
async function gotoStage(port) {
  await neutralFrame(port);
  await sleep(CSS.PACE);
  await tapButton(port, 'START', CSS.A_HOLD);
  await sleep(1800);                 // -> stage select; cursor spawns on the grid
  await neutralFrame(port);
}

function parseArgs(argv) {
  const flags = {};
  const positional = [];
  for (let i = 0; i < argv.length; i += 1) {
    const t = argv[i];
    if (t.startsWith('--')) {
      const key = t.slice(2);
      const val = argv[i + 1];
      if (val === undefined || val.startsWith('--')) {
        flags[key] = true;
      } else {
        flags[key] = val;
        i += 1;
      }
    } else {
      positional.push(t);
    }
  }
  return { flags, positional };
}

async function main() {
  const [command, ...rest] = process.argv.slice(2);
  const { flags, positional } = parseArgs(rest);
  const port = flags.port ? parseInt(flags.port, 10) : 1;
  const ms = flags.ms !== undefined ? parseInt(flags.ms, 10) : undefined;

  switch (command) {
    case 'tap': {
      const btn = resolveButton(positional[0]);
      await frame(port, [`PRESS ${btn}`, 'FLUSH']);
      await sleep(ms !== undefined ? ms : 50);
      await frame(port, [`RELEASE ${btn}`, 'FLUSH']);
      break;
    }
    case 'press':
      await frame(port, [`PRESS ${resolveButton(positional[0])}`, 'FLUSH']);
      break;
    case 'release':
      await frame(port, [`RELEASE ${resolveButton(positional[0])}`, 'FLUSH']);
      break;
    case 'tilt': {
      const stick = String(positional[0] || 'MAIN').toUpperCase();
      await frame(port, [`SET ${stick} ${positional[1]} ${positional[2]}`, 'FLUSH']);
      await sleep(ms !== undefined ? ms : 100);
      await frame(port, [`SET ${stick} 0.5 0.5`, 'FLUSH']);
      break;
    }
    case 'stick':
      await frame(port, [`SET ${String(positional[0]).toUpperCase()} ${positional[1]} ${positional[2]}`, 'FLUSH']);
      break;
    case 'trig':
      await frame(port, [`SET ${String(positional[0]).toUpperCase()} ${positional[1]}`, 'FLUSH']);
      break;
    case 'neutral': {
      const lines = [...BUTTONS].map((b) => `RELEASE ${b}`);
      lines.push('SET MAIN 0.5 0.5', 'SET C 0.5 0.5', 'SET L 0', 'SET R 0', 'FLUSH');
      await frame(port, lines);
      break;
    }
    case 'frame':
      await frame(port, positional);
      break;
    case 'char':
      await selectChar(port, positional[0], flags);
      break;
    case 'startmatch':
      await startMatch(port, {
        char: positional[0] || flags.char,
        color: flags.color !== undefined ? parseInt(flags.color, 10) : 0,
        nocpu: flags.nocpu,
      });
      break;
    case 'gotocss':
      await navToCss(port);
      break;
    case 'cpustep':
      await cpuStep(port);
      break;
    case 'poststart':
      await postStart(port);
      break;
    case 'gotostage':
      await gotoStage(port);
      break;
    default:
      throw new Error(`Unknown command: ${command || '<none>'}. Try: tap | press | release | tilt | stick | trig | neutral | frame | char | startmatch`);
  }
  console.log(`OK (${command} ${positional.join(' ')})`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
