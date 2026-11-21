#!/usr/bin/env node

/*
 * build-modded-iso.js -- SSBM Nucleus build harness.
 *
 * Drives the Nucleus Flask backend's REST API (the same engine the desktop
 * app's UI calls) to produce a playable, modded Melee ISO end to end:
 *
 *   1. create a fresh project from a vanilla 1.02 ISO
 *   2. install a mod from the storage vault into that project, by --type:
 *        costume   -> POST /api/mex/import        (a fighter costume slot)
 *        character -> POST /custom-characters/install (a new m-ex roster slot)
 *        stage     -> POST /custom-stages/install  (a new stage)
 *   3. export a playable ISO
 *
 * It emits a manifest { iso, modType, ... } describing how to trigger the mod
 * in-game, so the match harness (run-modded-match.js) can boot, select it, and
 * observe for crashes.
 *
 * The backend runs standalone in DEV mode (venv Python, no Electron) and is
 * fully isolated from the installed app: dev mode roots all data in the repo
 * (projects/, storage/, output/), the app uses %LOCALAPPDATA%\SSBM Nucleus.
 *
 * Usage:
 *   node build-modded-iso.js [options]
 *     --type <kind>      costume | character | stage (default: costume)
 *     --mod <id>         specific vault item: costume id, or character/stage
 *                        slug or name (default: first slippi-safe of the type)
 *     --fighter <name>   for --type costume: which character (default: Fox)
 *     --iso <path>       vanilla 1.02 ISO to build from (default: working ISO)
 *     --name <project>   project name (default: harness-test)
 *     --backend <url>    use an already-running backend instead of spawning one
 *     --keep-backend     do not shut down a spawned backend on exit
 *     --keep-project     do not delete a pre-existing project dir first
 */

const net = require('net');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const VENV_PYTHON = path.join(REPO_ROOT, 'venv', 'Scripts', 'python.exe');
const STORAGE_DIR = path.join(REPO_ROOT, 'storage');
const OUTPUT_DIR = path.join(REPO_ROOT, 'output');
const PROJECTS_DIR = path.join(REPO_ROOT, 'projects');
const ARTIFACTS_DIR = path.join(REPO_ROOT, 'tests', 'artifacts', 'nucleus');
const DEFAULT_ISO = process.env.NUCLEUS_VANILLA_ISO
  || path.join(os.homedir(), 'projects', 'melee', 'working', 'melee-vanilla-v1.02-working.iso');
// The texture-pack harvest boots Dolphin into this fixed, KNOWN run dir (so the
// backend texture watcher polls the right Dump folder, and GFX dump is enabled
// before boot). slippiDolphinPath for the texture-pack export is this same dir.
const TEXPACK_RUNDIR = path.join(REPO_ROOT, 'tests', 'artifacts', 'dolphin', 'texpack-run');

function log(msg) {
  // eslint-disable-next-line no-console
  console.log(`[build] ${msg}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseArgs(argv) {
  const flags = {};
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
    }
  }
  return flags;
}

// --- HTTP -------------------------------------------------------------------

// Every /api/ route is behind require_backend_token() (backend/app.py). The
// backend uses NUCLEUS_BACKEND_TOKEN when set, otherwise generates one and
// announces it on stdout as BACKEND_TOKEN:<hex> -- the same channel it already
// uses for BACKEND_PORT. Without this header every call comes back 401, which
// is what "backend never became ready (/api/mex/status)" actually meant.
let backendToken = (process.env.NUCLEUS_BACKEND_TOKEN || '').trim();

async function api(baseUrl, method, route, body) {
  const opts = { method, headers: {} };
  if (backendToken) opts.headers['X-Nucleus-Token'] = backendToken;
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${baseUrl}${route}`, opts);
  const text = await res.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch (e) {
    throw new Error(`${method} ${route} -> ${res.status}, non-JSON: ${text.slice(0, 300)}`);
  }
  return { status: res.status, json };
}

// --- Backend lifecycle ------------------------------------------------------

// Spawn the dev backend, capture its output, resolve once it prints its port.
function spawnBackend() {
  return new Promise((resolve, reject) => {
    if (!fs.existsSync(VENV_PYTHON)) {
      reject(new Error(`venv python not found at ${VENV_PYTHON}`));
      return;
    }
    log('starting dev backend (venv python _run_backend.py)...');
    // _run_backend.py presents a fake-TTY stdin so flask-socketio's dev-server
    // guard (which aborts when stdin isn't a TTY -- the case under a Node spawn)
    // is satisfied, then runs the real app.py unchanged.
    const launcher = path.join(__dirname, '_run_backend.py');
    const proc = spawn(VENV_PYTHON, [launcher], {
      cwd: REPO_ROOT,
      windowsHide: true,
    });
    const tail = [];
    let port = null;
    let resolved = false;
    const onData = (chunk) => {
      const s = chunk.toString();
      for (const line of s.split(/\r?\n/)) {
        if (!line.trim()) continue;
        tail.push(line);
        if (tail.length > 80) tail.shift();
        const t = line.match(/BACKEND_TOKEN:(\S+)/);
        if (t) backendToken = t[1];
        const m = line.match(/BACKEND_PORT:(\d+)/);
        if (m && !port) port = parseInt(m[1], 10);
        // The backend prints the token only when it generated one, so a token
        // supplied through the environment must not make us wait for a line
        // that will never come.
        // backendToken is pre-seeded from NUCLEUS_BACKEND_TOKEN, so this is
        // already satisfied when the token came from the environment.
        if (port && backendToken && !resolved) {
          resolved = true;
          resolve({ proc, port, tail });
        }
      }
    };
    proc.stdout.on('data', onData);
    proc.stderr.on('data', onData);
    proc.on('error', reject);
    proc.on('exit', (code) => {
      if (!port) reject(new Error(`backend exited (code ${code}) before reporting a port:\n${tail.join('\n')}`));
    });
    setTimeout(() => {
      if (!resolved) reject(new Error(`backend did not report a port+token within 30s:\n${tail.join('\n')}`));
    }, 30000);
  });
}

async function waitForReady(baseUrl, tail) {
  let lastErr = 'no response';
  for (let i = 0; i < 120; i += 1) {
    try {
      const { json } = await api(baseUrl, 'GET', '/api/mex/status');
      if (json && json.connected) return json;
      lastErr = JSON.stringify(json);
    } catch (e) { lastErr = e.message; }
    await sleep(500);
  }
  const tailTxt = tail && tail.length ? `\n--- backend output ---\n${tail.join('\n')}` : '';
  throw new Error(`backend never became ready (/api/mex/status); last: ${lastErr}${tailTxt}`);
}

// --- Vault costume selection ------------------------------------------------

// Pick a slippi-safe costume for the fighter from the storage vault metadata.
function pickCostume(fighter, wanted) {
  const metaPath = path.join(STORAGE_DIR, 'metadata.json');
  const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
  const entry = (meta.characters || {})[fighter];
  const skins = entry && Array.isArray(entry.skins) ? entry.skins : [];
  if (!skins.length) throw new Error(`no vault costumes found for "${fighter}" in metadata.json`);

  let skin;
  if (wanted) {
    skin = skins.find((s) => s.id === wanted || s.filename === wanted || s.filename === `${wanted}.zip`);
    if (!skin) throw new Error(`requested costume "${wanted}" not found for ${fighter}`);
  } else {
    skin = skins.find((s) => s.slippi_safe && s.filename) || skins.find((s) => s.filename);
  }
  if (!skin || !skin.filename) throw new Error(`no usable costume for ${fighter}`);

  const diskPath = path.join(STORAGE_DIR, fighter, skin.filename);
  if (!fs.existsSync(diskPath)) throw new Error(`costume zip missing on disk: ${diskPath}`);
  // The /import endpoint resolves costumePath against the backend PROJECT_ROOT
  // (the repo root in dev), so a repo-relative POSIX-ish path is what it wants.
  const costumePath = `storage/${fighter}/${skin.filename}`;
  return { skin, costumePath };
}

// Pick a slug-based vault item (custom_characters / custom_stages) from
// metadata.json: the requested one by slug/name, else the first slippi-safe.
function pickFromMeta(key, wanted) {
  const meta = JSON.parse(fs.readFileSync(path.join(STORAGE_DIR, 'metadata.json'), 'utf8'));
  const list = meta[key] || [];
  if (!list.length) throw new Error(`no ${key} in vault metadata.json`);
  let item;
  if (wanted) {
    const w = String(wanted).toLowerCase();
    item = list.find((x) => x.slug === wanted || (x.name || '').toLowerCase() === w);
    if (!item) throw new Error(`requested ${key} "${wanted}" not found`);
  } else {
    item = list.find((x) => x.slippi_safe !== false) || list[0];
  }
  return item;
}

// --- CSS icon placement for custom fighters ---------------------------------

// m-ex's add-fighter leaves a new fighter's CSS icon at the default (0,0,0),
// which sits BELOW the roster grid in the port-panel zone -- so in-game the
// cursor can't hover+lock it (pressing A there toggles a port instead). This
// mirrors the app's "add it into the grid" step: move the new icon into a free
// roster slot (an empty bottom-row edge cell, which maps to a clean, lockable
// cursor position). Returns { x, y, index }: the icon's grid coordinate (the
// cursor target is (x, y - 3.5), validated) and its list index (== the in-game
// CSS grid index, used to confirm the hover).
async function placeCustomFighterIcon(baseUrl, fighterName) {
  const got = await api(baseUrl, 'GET', '/api/mex/menus/css/layout');
  const layout = got.json || {};
  const icons = layout.icons || [];
  if (!icons.length) throw new Error('css layout returned no icons');
  // The new fighter's icon: by name, else the unplaced one at (0,0), else last.
  let idx = icons.findIndex((ic) => (ic.fighterName || '') === fighterName);
  if (idx < 0) idx = icons.findIndex((ic) => Math.round(ic.x) === 0 && Math.round(ic.y) === 0);
  if (idx < 0) idx = icons.length - 1;
  // Free roster slots: the bottom row's empty edge cells (x = +/-28, y = 2),
  // which sit clear of the port panels; fall back to the upper-row edges.
  const key = (x, y) => `${Math.round(x)},${Math.round(y)}`;
  const occupied = new Set(icons.map((ic, i) => (i === idx ? null : key(ic.x, ic.y))));
  const candidates = [
    { x: -28.15, y: 2.0, z: -1.0 }, { x: 28.25, y: 2.0, z: -1.0 },
    { x: -28.15, y: 9.2, z: -1.0 }, { x: 28.25, y: 9.2, z: -1.0 },
    { x: -28.15, y: 16.4, z: -1.0 }, { x: 28.25, y: 16.4, z: -1.0 },
  ];
  const slot = candidates.find((c) => !occupied.has(key(c.x, c.y))) || candidates[0];
  icons[idx] = { ...icons[idx], x: slot.x, y: slot.y, z: slot.z };
  const post = await api(baseUrl, 'POST', '/api/mex/menus/css/layout',
    { template: layout.template, icons });
  if (!post.json || !post.json.success) {
    throw new Error(`css layout save failed: ${JSON.stringify(post.json)}`);
  }
  return { x: slot.x, y: slot.y, index: idx };
}

// --- SSS icon placement for custom stages -----------------------------------

// m-ex's add-stage puts a custom stage on a NEW page (e.g. "Custom") at the
// default (0,0,0). In-game you reach that page by pressing R (the m-ex SSS
// page-switch). We keep the stage on its own page (matching the app) but move
// its icon to a clear, reachable coordinate so the cursor can land + select it.
// Returns { page, x, y }: the page index to R-switch to, and the stage-cursor
// target (SSS layout coords ~= the in-game stage cursor, validated on the
// bottom-row legal stages).
async function placeCustomStageIcon(baseUrl, stageName) {
  const got = await api(baseUrl, 'GET', '/api/mex/menus/sss/layout');
  const layout = got.json || {};
  const pages = layout.pages || [];
  if (!pages.length) throw new Error('sss layout returned no pages');
  const iconsOf = (pg) => pg.icons || pg.stageIcons || [];
  // Locate the custom stage icon (by name, else the unplaced one at 0,0 on a
  // non-main page).
  let found = null;
  for (let pi = 0; pi < pages.length; pi += 1) {
    const icons = iconsOf(pages[pi]);
    let ii = icons.findIndex((ic) => (ic.stageName || '') === stageName);
    if (ii < 0 && pi > 0) ii = icons.findIndex((ic) => Math.round(ic.x) === 0 && Math.round(ic.y) === 0);
    if (ii >= 0) { found = { pi, ii }; break; }
  }
  if (!found) throw new Error(`could not find custom stage icon for "${stageName}"`);
  // A clear, reachable spot: the bottom-row legal-stage position (page 0's
  // Battlefield slot) -- same screen coords on any page, easy for the cursor.
  const slot = { x: 1.3, y: -9.1, z: 0.0 };
  const icons = iconsOf(pages[found.pi]);
  icons[found.ii] = { ...icons[found.ii], x: slot.x, y: slot.y, z: slot.z };
  const post = await api(baseUrl, 'POST', '/api/mex/menus/sss/layout', { pages });
  if (!post.json || !post.json.success) {
    throw new Error(`sss layout save failed: ${JSON.stringify(post.json)}`);
  }
  return { page: found.pi, x: slot.x, y: slot.y };
}

// --- SSS layout query (accurate stage-cursor coords) ------------------------

// The in-game stage cursor ~= the SSS icon coordinate, but a build's SSS layout
// can differ from libmelee's hardcoded vanilla targets (esp. Yoshi's Story,
// Fountain, Stadium) -- so selecting by the hardcoded coord mis-hits the wrong
// stage. Read the build's REAL layout (the SSS analog of the CSS icon fix) and
// map the 6 legal stages to their actual (x, y, page).
const SSS_LEGAL_NAMES = {
  Battlefield: 'battlefield', 'Final Destination': 'finaldestination',
  'Dream Land N64': 'dreamland', "Yoshi's Story": 'yoshisstory',
  'Pokemon Stadium': 'pokemonstadium', 'Fountain of Dreams': 'fountainofdreams',
};

async function queryStageLayout(baseUrl) {
  const got = await api(baseUrl, 'GET', '/api/mex/menus/sss/layout');
  const pages = (got.json && got.json.pages) || [];
  const layout = {};
  pages.forEach((pg, pi) => {
    for (const ic of (pg.icons || pg.stageIcons || [])) {
      const key = SSS_LEGAL_NAMES[ic.stageName];
      if (key && layout[key] === undefined) layout[key] = { x: ic.x, y: ic.y, page: pi };
    }
  });
  return layout;
}

// --- Bulk costume install (compression stress test) -------------------------

// Flatten the vault into a list of {fighter, costumePath} across all fighters,
// for installing many costumes at once (to stress CSP memory).
function allVaultCostumes() {
  const meta = JSON.parse(fs.readFileSync(path.join(STORAGE_DIR, 'metadata.json'), 'utf8'));
  const list = [];
  for (const [fighter, info] of Object.entries(meta.characters || {})) {
    for (const skin of (info.skins || [])) {
      if (skin.filename && fs.existsSync(path.join(STORAGE_DIR, fighter, skin.filename))) {
        list.push({ fighter, costumePath: `storage/${fighter}/${skin.filename}`, id: skin.id });
      }
    }
  }
  return list;
}

async function installManyCostumes(baseUrl, count, skip = 0) {
  const all = allVaultCostumes().slice(skip);
  let installed = 0;
  for (const c of all) {
    if (installed >= count) break;
    const r = await api(baseUrl, 'POST', '/api/mex/import', { fighter: c.fighter, costumePath: c.costumePath });
    if (r.json && r.json.success) {
      installed += 1;
      if (installed % 25 === 0) log(`  installed ${installed}/${count} costumes...`);
    }
  }
  return installed;
}

// --- Export wait ------------------------------------------------------------

// The export runs in a background thread and only reports done over SocketIO,
// which we don't speak. Instead poll the output file: a finished Melee ISO is
// ~1.4 GB, so "exists, > 0.8 GB, and size unchanged across two checks" is a
// reliable completion signal. Surface backend output on timeout.
async function waitForIso(isoPath, backendTail) {
  const MIN_BYTES = 800 * 1024 * 1024;
  const TIMEOUT_MS = 6 * 60 * 1000;
  const start = Date.now();
  let lastSize = -1;
  let stableSize = -1;
  while (Date.now() - start < TIMEOUT_MS) {
    await sleep(3000);
    let size = 0;
    try {
      size = fs.statSync(isoPath).size;
    } catch (e) {
      log('  ...waiting for ISO to appear');
      continue;
    }
    const mb = (size / 1024 / 1024).toFixed(0);
    if (size === lastSize && size >= MIN_BYTES) {
      if (size === stableSize) {
        log(`  ISO stable at ${mb} MB`);
        return size;
      }
      stableSize = size;
      log(`  ISO ${mb} MB (confirming stable)`);
    } else {
      log(`  ISO ${mb} MB (growing)`);
      stableSize = -1;
    }
    lastSize = size;
  }
  const tailTxt = backendTail ? `\n--- backend tail ---\n${backendTail.join('\n')}` : '';
  throw new Error(`export timed out after ${TIMEOUT_MS / 1000}s waiting for ${isoPath}${tailTxt}`);
}

// --- Main flow --------------------------------------------------------------

async function main() {
  const flags = parseArgs(process.argv.slice(2));
  const isoPath = flags.iso || DEFAULT_ISO;
  const fighter = flags.fighter || 'Fox';
  const projectName = flags.name || 'harness-test';
  const modType = (flags.type && flags.type !== true) ? flags.type : 'costume';
  // The specific mod to install: costume id (for costume), or slug/name (for
  // custom-character/custom-stage). --costume kept as an alias for back-compat.
  const wantedTarget = [flags.mod, flags.costume, flags.target].find((v) => v && v !== true) || null;

  if (!fs.existsSync(isoPath)) throw new Error(`vanilla ISO not found: ${isoPath}`);

  // 1. Backend ---------------------------------------------------------------
  let backend = null;
  let baseUrl;
  if (flags.backend && flags.backend !== true) {
    baseUrl = flags.backend.replace(/\/$/, '');
    log(`using existing backend at ${baseUrl}`);
  } else {
    backend = await spawnBackend();
    baseUrl = `http://127.0.0.1:${backend.port}`;
    log(`backend on ${baseUrl}`);
  }

  const cleanup = async () => {
    if (backend && !flags['keep-backend']) {
      log('shutting down spawned backend');
      try { backend.proc.kill(); } catch (e) { /* ignore */ }
    }
  };

  try {
    await waitForReady(baseUrl, backend && backend.tail);

    const setup = await api(baseUrl, 'GET', '/api/mex/setup/status');
    if (!setup.json.complete) {
      throw new Error(`backend setup not complete: ${JSON.stringify(setup.json)}`);
    }
    log('setup complete; backend ready');

    // 2. Create + open project (or just open, for --export-only re-exports) ---
    let projectPath;
    if (flags['export-only']) {
      // Re-export an EXISTING project at a new --compression, without re-creating
      // or re-installing -- for the compression sweep (same costumes, vary C).
      projectPath = path.join(PROJECTS_DIR, projectName, 'project.mexproj');
      if (!fs.existsSync(projectPath)) throw new Error(`--export-only: project not found at ${projectPath}`);
      log(`opening existing project "${projectName}" for re-export (no install)`);
    } else {
      const projDir = path.join(PROJECTS_DIR, projectName);
      if (fs.existsSync(projDir) && !flags['keep-project']) {
        log(`removing existing project dir ${projDir}`);
        fs.rmSync(projDir, { recursive: true, force: true });
      }
      log(`creating project "${projectName}" from ${path.basename(isoPath)}`);
      const created = await api(baseUrl, 'POST', '/api/mex/project/create', { isoPath, projectName });
      if (!created.json.success) throw new Error(`create failed: ${JSON.stringify(created.json)}`);
      projectPath = created.json.projectPath;
    }
    // create only writes the project; the manager (needed by import/export) is
    // loaded by an explicit open.
    log(`opening project ${path.basename(projectPath)}`);
    const opened = await api(baseUrl, 'POST', '/api/mex/project/open', { projectPath });
    if (!opened.json.success) throw new Error(`open failed: ${JSON.stringify(opened.json)}`);

    // 3. Install the mod (routed by --type) ----------------------------------
    // modInfo carries the mod type + how to trigger it in-game (for the match
    // harness): costume -> {fighter, colorIndex}; character -> {characterName}
    // (a new roster slot); stage -> {stageName} (pick it on stage select).
    let modInfo = { modType };
    if (flags['export-only']) {
      // no install -- just re-export the existing project at the new compression
    } else if (modType === 'costume') {
      const { skin, costumePath } = pickCostume(fighter, wantedTarget);
      log(`installing costume "${skin.id}" (${skin.costume_code}) onto ${fighter}`);
      const imported = await api(baseUrl, 'POST', '/api/mex/import', { fighter, costumePath });
      if (!imported.json.success) throw new Error(`import failed: ${JSON.stringify(imported.json)}`);
      // The import appends a costume slot -> it's the LAST entry, and that index
      // is the in-game X-cycle position (0 = default).
      const costumes = await api(baseUrl, 'GET', `/api/mex/fighters/${encodeURIComponent(fighter)}/costumes`);
      const list = (costumes.json && costumes.json.costumes) || [];
      const modCostume = list[list.length - 1] || {};
      const colorIndex = modCostume.index !== undefined ? modCostume.index : list.length - 1;
      log(`${fighter} now has ${list.length} costumes; mod at index ${colorIndex} (${modCostume.name || '?'})`);
      modInfo = { modType, fighter, colorIndex, costumeId: skin.id, costumeCode: skin.costume_code, costumeCount: list.length };
    } else if (modType === 'character') {
      const item = pickFromMeta('custom_characters', wantedTarget);
      log(`installing custom character "${item.name}" (${item.slug})`);
      const r = await api(baseUrl, 'POST', '/api/mex/custom-characters/install', { slug: item.slug });
      if (!r.json.success) throw new Error(`character install failed: ${JSON.stringify(r.json)}`);
      log(`added fighter "${item.name}" (${(r.json.costumeCount || item.costume_count || '?')} costumes)`);
      // Place its CSS icon into a real roster slot (add-fighter leaves it at
      // (0,0) in the port-panel zone, unselectable) -- the app's "add to grid".
      const cssIcon = await placeCustomFighterIcon(baseUrl, item.name);
      log(`placed ${item.name} CSS icon at grid slot (${cssIcon.x}, ${cssIcon.y}) [grid index ${cssIcon.index}]`);
      modInfo = { modType, characterName: item.name, characterSlug: item.slug, cssIcon };
    } else if (modType === 'stage') {
      const item = pickFromMeta('custom_stages', wantedTarget);
      log(`installing custom stage "${item.name}" (${item.slug})`);
      const r = await api(baseUrl, 'POST', '/api/mex/custom-stages/install', { slug: item.slug });
      if (!r.json.success) throw new Error(`stage install failed: ${JSON.stringify(r.json)}`);
      // Place its SSS icon onto page 0 at a free slot (add-stage puts it on a
      // separate "Custom" page at (0,0), which needs in-game page nav) so it's
      // selectable like a vanilla stage.
      const sssIcon = await placeCustomStageIcon(baseUrl, item.name);
      log(`placed stage "${item.name}" SSS icon at (${sssIcon.x}, ${sssIcon.y}) on page ${sssIcon.page}`);
      modInfo = { modType, stageName: item.name, stageSlug: item.slug, sssIcon };
    } else if (modType === 'das') {
      // Dynamic Alternate Stages: install the framework + one variant per legal
      // stage, each behind a HOLD button -- so ONE ISO crash-tests up to 6 stage
      // skins (hold the button on stage-select to load that stage's variant).
      const inst = await api(baseUrl, 'POST', '/api/mex/das/install', {});
      if (!inst.json.success) throw new Error(`das install failed: ${JSON.stringify(inst.json)}`);
      const meta = JSON.parse(fs.readFileSync(path.join(STORAGE_DIR, 'metadata.json'), 'utf8'));
      // stage code -> (vault folder, the name my stage selector uses)
      const DAS = {
        GrNBa: ['battlefield', 'battlefield'], GrNLa: ['final_destination', 'finaldestination'],
        GrSt: ['yoshis_story', 'yoshisstory'], GrOp: ['dreamland', 'dreamland'],
        GrPs: ['pokemon_stadium', 'pokemonstadium'], GrIz: ['fountain_of_dreams', 'fountainofdreams'],
      };
      // X/Y/Z have no stage-select function (A=select, B=back, R=m-ex page-
      // switch), so they're safe to HOLD while confirming the stage. Each stage
      // can carry several alternates -- one per button -- so --variants-per-stage
      // N installs N skins on each legal stage (N<=3). One ISO -> up to 18 skins.
      const BUTTONS = ['X', 'Y', 'Z'];
      const perStage = flags['variants-per-stage'] && flags['variants-per-stage'] !== true
        ? Math.min(parseInt(flags['variants-per-stage'], 10) || 1, BUTTONS.length) : 1;
      const only = (flags.stage && flags.stage !== true) ? flags.stage : null; // limit to one stage
      const dasVariants = [];
      for (const [code, [folder, selName]] of Object.entries(DAS)) {
        if (only && selName !== only) continue;
        const list = ((meta.stages || {})[folder] || {}).variants || [];
        // prefer slippi-safe, then fill with the rest; one variant per button
        const ordered = [...list].sort((a, b) => (b.slippi_safe ? 1 : 0) - (a.slippi_safe ? 1 : 0));
        const picks = ordered.slice(0, perStage);
        if (!picks.length) { log(`  no DAS variant in vault for ${folder}, skipping`); continue; }
        for (let k = 0; k < picks.length; k += 1) {
          const v = picks[k];
          const button = BUTTONS[k];
          const variantPath = `storage/das/${folder}/${v.filename}`;
          const imp = await api(baseUrl, 'POST', '/api/mex/das/import', { stageCode: code, variantPath });
          if (!imp.json.success) { log(`  das import failed (${folder}/${v.id}): ${JSON.stringify(imp.json)}`); continue; }
          const importedName = path.basename(imp.json.path || '', '.dat');
          const newName = `${importedName}(${button})`;
          const ren = await api(baseUrl, 'POST', '/api/mex/das/rename', { stageCode: code, oldName: importedName, newName });
          if (!ren.json.success) { log(`  das rename failed (${folder}/${v.id}): ${JSON.stringify(ren.json)}`); continue; }
          dasVariants.push({ stage: selName, stageCode: code, button, variant: v.name || v.id });
          log(`  DAS ${folder}: "${v.name || v.id}" -> hold ${button} on ${selName}`);
        }
      }
      if (!dasVariants.length) throw new Error('no DAS variants installed');
      // Attach each variant's REAL stage-cursor coordinate from the build's SSS
      // layout, so the selector lands on the right stage (not a libmelee guess).
      const stageLayout = await queryStageLayout(baseUrl);
      for (const v of dasVariants) {
        const sl = stageLayout[v.stage];
        if (sl) { v.x = sl.x; v.y = sl.y; v.page = sl.page; }
        else log(`  WARN: no SSS layout coord for ${v.stage}; will use vanilla target`);
      }
      modInfo = { modType, dasVariants, stageLayout };
    } else if (modType === 'effect') {
      // A character EFFECT/extra (e.g. Fox/Falco's blaster "gun" model, laser
      // colors, sword trails). Installed into the fighter's effect data; tested
      // by selecting the fighter and performing the move that uses it in-game.
      const effFighter = (flags.fighter && flags.fighter !== true) ? flags.fighter : 'Fox';
      const extraType = (flags.extra && flags.extra !== true) ? flags.extra : 'gun';
      const meta = JSON.parse(fs.readFileSync(path.join(STORAGE_DIR, 'metadata.json'), 'utf8'));
      const extras = ((((meta.characters || {})[effFighter] || {}).extras) || {})[extraType] || [];
      const mod = (wantedTarget && extras.find((x) => x.id === wantedTarget || x.name === wantedTarget)) || extras[0];
      if (!mod) throw new Error(`no "${extraType}" extra for ${effFighter} in the vault`);
      // Route like the app does (useExtras.js): color mods carry a
      // 'modifications' dict and go through the hex-patch install; only
      // true model extras (gun/sword .dae imports) use models/install.
      const isColorMod = !!mod.modifications;
      log(`installing ${effFighter} ${extraType} ${isColorMod ? 'colors' : 'model'} "${mod.name || mod.id}"`);
      const r = await api(baseUrl, 'POST',
        isColorMod ? '/api/mex/storage/extras/install' : '/api/mex/storage/models/install',
        { character: effFighter, extraType, modId: mod.id });
      if (!r.json.success) throw new Error(`effect install failed: ${JSON.stringify(r.json)}`);
      // The in-game move that exercises the effect: blaster (gun/laser) =
      // neutral-B, sword trail / phantasm = side-B, shine = down-B.
      const move = { sword: 'sideb', sideb: 'sideb', shine: 'downb' }[extraType] || 'neutralb';
      modInfo = { modType, fighter: effFighter, extraType, extraName: mod.name || mod.id, colorIndex: 0, move };
    } else if (modType === 'menu') {
      // CSS menu mods (cosmetic): a background, a door/portal image, or an icon
      // grid (replacement character portraits). All visible just by reaching the
      // CSS -- so the match harness boot-health-tests them + screenshots the CSS.
      const menuType = (flags.menu && flags.menu !== true) ? flags.menu : 'background';
      const dirs = { background: 'background', doors: 'doors', icon_grid: 'icon_grid' };
      const dir = dirs[menuType];
      if (!dir) throw new Error(`unknown --menu "${menuType}" (background | doors | icon_grid)`);
      const raw = JSON.parse(fs.readFileSync(path.join(STORAGE_DIR, 'menus', 'css', dir, 'metadata.json'), 'utf8'));
      const mods = Array.isArray(raw) ? raw : (raw.mods || []);
      const mod = (wantedTarget && mods.find((m) => m.id === wantedTarget || m.name === wantedTarget)) || mods[0];
      if (!mod) throw new Error(`no ${menuType} menu mod in the vault`);
      log(`installing ${menuType} menu mod "${mod.name || mod.id}"`);
      if (menuType === 'icon_grid') {
        // install returns the plan (which fighter icons to set); set each one.
        const plan = await api(baseUrl, 'POST', `/api/mex/menus/css/icon_grid/install/${mod.id}`);
        if (!plan.json.success) throw new Error(`icon_grid plan failed: ${JSON.stringify(plan.json)}`);
        let n = 0;
        for (const ic of (plan.json.icons || [])) {
          const r = await api(baseUrl, 'POST', `/api/mex/menus/css/icon_grid/install/${mod.id}/icon`,
            { character: ic.character, icon: ic.icon });
          if (r.json && r.json.success) n += 1;
          else log(`  icon failed (${ic.character}): ${JSON.stringify(r.json)}`);
        }
        log(`  installed ${n}/${(plan.json.icons || []).length} icons`);
      } else {
        const r = await api(baseUrl, 'POST', `/api/mex/menus/css/${dir}/install/${mod.id}`);
        if (!r.json.success) throw new Error(`${menuType} install failed: ${JSON.stringify(r.json)}`);
      }
      modInfo = { modType, menuType, menuName: mod.name || mod.id };
    } else if (modType === 'modpack') {
      // THE MODPACK -- one of EVERY mod type in a single ISO. A showcase build
      // that exercises the whole harness: a costume, a custom roster fighter, a
      // custom stage, a DAS stage skin, a character effect, and a CSS menu mod.
      // Reuses the same install helpers/endpoints as the single-type branches.
      const meta = JSON.parse(fs.readFileSync(path.join(STORAGE_DIR, 'metadata.json'), 'utf8'));
      const pick = (k, d) => (flags[k] && flags[k] !== true) ? flags[k] : d;
      const contents = [];
      log('assembling THE MODPACK (one of every mod type)...');

      // 1) COSTUME -- a fresh skin on a vanilla fighter
      try {
        const cf = pick('costume-fighter', 'Fox');
        const { skin, costumePath } = pickCostume(cf, pick('costume', null));
        const imp = await api(baseUrl, 'POST', '/api/mex/import', { fighter: cf, costumePath });
        if (!imp.json.success) throw new Error(JSON.stringify(imp.json));
        const cl = await api(baseUrl, 'GET', `/api/mex/fighters/${encodeURIComponent(cf)}/costumes`);
        const list = (cl.json && cl.json.costumes) || [];
        const colorIndex = list.length - 1;
        modInfo.costume = { fighter: cf, colorIndex, costumeId: skin.id };
        contents.push({ type: 'costume', label: `${cf} skin "${skin.id}"`, trigger: `pick ${cf}, costume slot ${colorIndex}` });
        log(`  [1/6] costume: ${cf} "${skin.id}" at color ${colorIndex}`);
      } catch (e) { log(`  [1/6] costume skipped: ${e.message}`); }

      // 2) CUSTOM CHARACTER -- a brand-new roster slot (placed into the grid)
      try {
        const ch = pickFromMeta('custom_characters', pick('mp-char', 'Sonic'));
        const r = await api(baseUrl, 'POST', '/api/mex/custom-characters/install', { slug: ch.slug });
        if (!r.json.success) throw new Error(JSON.stringify(r.json));
        const cssIcon = await placeCustomFighterIcon(baseUrl, ch.name);
        modInfo.character = { name: ch.name, slug: ch.slug, cssIcon };
        contents.push({ type: 'character', label: `new fighter ${ch.name}`, trigger: `CSS icon (${cssIcon.x.toFixed(0)},${cssIcon.y.toFixed(0)})` });
        log(`  [2/6] character: ${ch.name} at grid slot (${cssIcon.x.toFixed(1)},${cssIcon.y.toFixed(1)})`);
      } catch (e) { log(`  [2/6] character skipped: ${e.message}`); }

      // 3) CUSTOM STAGE -- a new stage (placed onto its own SSS page)
      try {
        const st = pickFromMeta('custom_stages', pick('mp-stage', "Peach's Castle 64"));
        const r = await api(baseUrl, 'POST', '/api/mex/custom-stages/install', { slug: st.slug });
        if (!r.json.success) throw new Error(JSON.stringify(r.json));
        const sssIcon = await placeCustomStageIcon(baseUrl, st.name);
        modInfo.customStage = { name: st.name, slug: st.slug, sssIcon };
        contents.push({ type: 'stage', label: `new stage ${st.name}`, trigger: `SSS page ${sssIcon.page}` });
        log(`  [3/6] stage: ${st.name} on SSS page ${sssIcon.page}`);
      } catch (e) { log(`  [3/6] stage skipped: ${e.message}`); }

      // 4) DAS STAGE SKIN -- a Battlefield reskin behind HOLD X
      try {
        const di = await api(baseUrl, 'POST', '/api/mex/das/install', {});
        if (!di.json.success) throw new Error(JSON.stringify(di.json));
        const variants = ((meta.stages || {}).battlefield || {}).variants || [];
        const ordered = [...variants].sort((a, b) => (b.slippi_safe ? 1 : 0) - (a.slippi_safe ? 1 : 0));
        const v = ordered[0];
        if (!v) throw new Error('no Battlefield DAS variant in vault');
        const imp = await api(baseUrl, 'POST', '/api/mex/das/import', { stageCode: 'GrNBa', variantPath: `storage/das/battlefield/${v.filename}` });
        if (!imp.json.success) throw new Error(JSON.stringify(imp.json));
        const importedName = path.basename(imp.json.path || '', '.dat');
        await api(baseUrl, 'POST', '/api/mex/das/rename', { stageCode: 'GrNBa', oldName: importedName, newName: `${importedName}(X)` });
        modInfo.das = { stage: 'battlefield', button: 'X', variant: v.name || v.id };
        contents.push({ type: 'das', label: `Battlefield skin "${v.name || v.id}"`, trigger: 'hold X choosing Battlefield' });
        log(`  [4/6] DAS: Battlefield "${v.name || v.id}" (hold X)`);
      } catch (e) { log(`  [4/6] DAS skipped: ${e.message}`); }

      // 5) EFFECT -- Fox's blaster "gun" model, fired with neutral-B
      try {
        const extras = ((((meta.characters || {}).Fox || {}).extras) || {}).gun || [];
        const mod = extras[0];
        if (!mod) throw new Error('no Fox gun extra in vault');
        const r = await api(baseUrl, 'POST', '/api/mex/storage/models/install', { character: 'Fox', extraType: 'gun', modId: mod.id });
        if (!r.json.success) throw new Error(JSON.stringify(r.json));
        modInfo.effect = { fighter: 'Fox', extraType: 'gun', name: mod.name || mod.id, move: 'neutralb' };
        contents.push({ type: 'effect', label: `Fox gun "${mod.name || mod.id}"`, trigger: 'neutral-B in a match' });
        log(`  [5/6] effect: Fox gun "${mod.name || mod.id}"`);
      } catch (e) { log(`  [5/6] effect skipped: ${e.message}`); }

      // 6) MENU -- a CSS background (kept to background, not icon_grid, so it
      //    doesn't fight the custom fighter's icon placement)
      try {
        const raw = JSON.parse(fs.readFileSync(path.join(STORAGE_DIR, 'menus', 'css', 'background', 'metadata.json'), 'utf8'));
        const mods = Array.isArray(raw) ? raw : (raw.mods || []);
        const want = pick('mp-menu', 'Holographic');
        const mod = mods.find((m) => (m.name || '').includes(want) || m.id === want) || mods[0];
        if (!mod) throw new Error('no CSS background in vault');
        const r = await api(baseUrl, 'POST', `/api/mex/menus/css/background/install/${mod.id}`);
        if (!r.json.success) throw new Error(JSON.stringify(r.json));
        modInfo.menu = { menuType: 'background', name: mod.name || mod.id };
        contents.push({ type: 'menu', label: `CSS background "${mod.name || mod.id}"`, trigger: 'visible on the character-select screen' });
        log(`  [6/6] menu: CSS background "${mod.name || mod.id}"`);
      } catch (e) { log(`  [6/6] menu skipped: ${e.message}`); }

      modInfo.modType = 'modpack';
      modInfo.contents = contents;
      log(`MODPACK assembled: ${contents.length}/6 mod types installed`);
      if (!contents.length) throw new Error('modpack installed nothing');
    } else if (modType === 'stress') {
      // Compression stress test: install N costumes across fighters (to push CSP
      // memory), then export at a chosen --compression. Used to find where the
      // online CSS crashes vs the auto-compression formula.
      const count = parseInt(flags.count, 10) || 50;
      const skip = parseInt(flags.skip, 10) || 0;
      log(`stress: installing ${count} costumes across the vault${skip ? ` (skip first ${skip})` : ''}...`);
      const n = await installManyCostumes(baseUrl, count, skip);
      log(`stress: installed ${n} costumes (added beyond vanilla)`);
      modInfo = { modType: 'stress', addedCostumes: n };
    } else {
      throw new Error(`unknown --type "${modType}" (expected: costume | character | stage | das | effect | menu | stress)`);
    }

    // Record the build's REAL stage-cursor coords for the 6 legal stages, so the
    // match harness selects stages accurately on any SSS layout (the SSS analog
    // of the CSS icon fix) -- not just for DAS.
    if (!modInfo.stageLayout) {
      modInfo.stageLayout = await queryStageLayout(baseUrl);
    }

    // 4. Export ISO ----------------------------------------------------------
    const comp = await api(baseUrl, 'GET', '/api/mex/recommended-compression');
    const recommended = (comp.json && comp.json.ratio) || 1.0;
    // --compression C overrides the auto ratio (for the compression sweep);
    // --color-smash matches the app's quality/memory tradeoff (default off).
    const ratio = (flags.compression && flags.compression !== true) ? parseFloat(flags.compression) : recommended;
    const colorSmash = !!flags['color-smash'];
    modInfo.compression = ratio;
    modInfo.recommendedCompression = recommended;
    modInfo.addedCostumes = (comp.json && comp.json.addedCostumes) !== undefined ? comp.json.addedCostumes : modInfo.addedCostumes;
    modInfo.colorSmash = colorSmash;
    const isoName = `${projectName}.iso`;
    const outIso = path.join(OUTPUT_DIR, isoName);
    if (fs.existsSync(outIso)) fs.rmSync(outIso, { force: true });
    // --texture-pack: export in texture-pack mode -- the backend swaps every CSP
    // for a base-4 encoded 16x16 placeholder and writes a <buildId>_texture_mapping
    // .json (global index -> character/costume/real CSP). Compression is skipped
    // (placeholders stay 16x16). The harvest then boots this ISO, scrolls the CSS,
    // and lets Dolphin reveal each placeholder's load filename.
    const texturePack = !!flags['texture-pack'];
    const slippiPath = (flags.slippi && flags.slippi !== true) ? flags.slippi : TEXPACK_RUNDIR;
    const exportBody = { filename: isoName, cspCompression: ratio, useColorSmash: colorSmash };
    if (texturePack) {
      exportBody.texturePackMode = true;
      exportBody.slippiDolphinPath = slippiPath;
    }
    log(`exporting ISO "${isoName}" (${texturePack ? 'TEXTURE-PACK mode' : `cspCompression ${ratio}, colorSmash ${colorSmash}`}, recommended ${recommended})`);
    const exp = await api(baseUrl, 'POST', '/api/mex/export/start', exportBody);
    if (!exp.json.success) throw new Error(`export start failed: ${JSON.stringify(exp.json)}`);
    const finalBytes = await waitForIso(outIso, backend && backend.tail);
    log(`export complete: ${outIso} (${(finalBytes / 1024 / 1024).toFixed(0)} MB)`);
    if (texturePack) {
      // The build_id is timestamp-derived in the backend and returned by start; the
      // mapping file lands at output/<buildId>_texture_mapping.json.
      const buildId = exp.json.buildId;
      if (!buildId) throw new Error(`texture-pack export returned no buildId: ${JSON.stringify(exp.json)}`);
      const mappingPath = path.join(OUTPUT_DIR, `${buildId}_texture_mapping.json`);
      // The export thread writes the mapping just before exporting; poll briefly.
      let mapOk = false;
      for (let i = 0; i < 20 && !mapOk; i += 1) { mapOk = fs.existsSync(mappingPath); if (!mapOk) await sleep(500); }
      if (!mapOk) throw new Error(`texture mapping not found at ${mappingPath}`);
      const map = JSON.parse(fs.readFileSync(mappingPath, 'utf8'));
      modInfo.texturePack = true;
      modInfo.buildId = buildId;
      modInfo.mappingPath = mappingPath;
      modInfo.slippiPath = slippiPath;
      modInfo.placeholderCount = (map.costumes || []).length;
      log(`texture-pack: buildId ${buildId}, ${modInfo.placeholderCount} placeholders, mapping ${mappingPath}`);
    }

    // 5. Manifest ------------------------------------------------------------
    const manifest = {
      iso: outIso,
      ...modInfo,
      projectName,
      builtFrom: isoPath,
      bytes: finalBytes,
    };
    fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
    const manifestPath = path.join(ARTIFACTS_DIR, 'last-build.json');
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
    log(`manifest -> ${manifestPath}`);
    // eslint-disable-next-line no-console
    console.log(`\nMANIFEST ${JSON.stringify(manifest)}`);
  } finally {
    await cleanup();
  }
}

main().catch(async (err) => {
  // eslint-disable-next-line no-console
  console.error(`[build] ERROR: ${err.message}`);
  process.exit(1);
});
