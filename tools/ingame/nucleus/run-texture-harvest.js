#!/usr/bin/env node

/*
 * run-texture-harvest.js -- automate the texture-pack export's manual "scroll
 * every costume" step, and harvest the build-independent index -> dumped-filename
 * table that makes a later ZERO-BOOT export possible.
 *
 * Flow (one backend, one Dolphin boot):
 *   1. build a texture-pack ISO  (build-modded-iso.js --texture-pack): the backend
 *      swaps every CSP for a base-4 encoded 16x16 placeholder and writes
 *      output/<buildId>_texture_mapping.json (global index -> char/costume/CSP).
 *   2. boot that ISO into a KNOWN run dir with DumpTextures on (control.js
 *      --run-dir --texture-dump), reach the CSS (pipe.js gotocss).
 *   3. start-listening: the backend watches the run dir's Dump folder, decodes
 *      each dumped placeholder's index from its pixels, and copies the real CSP
 *      into Load/ named with the dumped filename (the actual texture pack).
 *   4. tex_scroll.py drives the CSS across every (character, costume) so Dolphin
 *      dumps every placeholder.
 *   5. the shared job cancel endpoint finalizes + persists dumped_filename per costume.
 *   6. harvest: merge {index -> filename, texHash, tlutHash} into a persistent,
 *      build-independent table (the same global index yields the same placeholder
 *      pixels -> same filename in EVERY build). Conflicts across builds are flagged
 *      (that would disprove build-independence).
 *
 * Offline mode (the payoff -- ZERO boot):
 *   node run-texture-harvest.js --offline [--compute] [--type ...] [--name <proj>]
 *   --offline builds a texture-pack ISO and names its entire texture pack via the
 *   backend's apply-offline endpoint -- no Dolphin, no scrolling. By default it
 *   uses the previously harvested table. With --compute it instead builds the
 *   table by PURE COMPUTATION (generate placeholder -> mexcli CI8/RGB5A3 encode ->
 *   XXH64 the bytes the way Dolphin does) -- so NO harvest is needed at all, and
 *   it covers any index range incl. Sheik. Validated bit-exact vs the harvest.
 *
 * Sheik (--sheik): the offline CSS can't render Sheik (the Zelda cell shows
 *   Zelda); the Slippi UNRANKED online CSS shows Sheik on that cell. So --sheik
 *   adds a brief, time-boxed online-CSS pass for Sheik's 5 indices (always holds
 *   B out before matchmaking pairs anyone) before the offline sweep. Gets 124/124.
 *
 * Usage:
 *   node run-texture-harvest.js [--type stress --count N] [--name <proj>]
 *                               [--limit N] [--no-place] [--dwell S]
 *                               [--sheik] [--offline] [--backend <url>] [--keep]
 */

const fs = require('fs');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..');
const VENV_PYTHON = path.join(REPO_ROOT, 'venv', 'Scripts', 'python.exe');
const VENV_PY_MELEE = path.join(HERE, 'melee_venv', 'Scripts', 'python.exe');
const BUILD = path.join(HERE, 'build-modded-iso.js');
const CONTROL = path.join(HERE, '..', 'dolphin', 'control.js');
const PIPE = path.join(HERE, '..', 'dolphin', 'pipe.js');
const TEX_SCROLL = path.join(HERE, 'tex_scroll.py');
const SHEIK_ONLINE = path.join(HERE, 'harvest_sheik_online.py');
const MANIFEST = path.join(HERE, '..', 'artifacts', 'nucleus', 'last-build.json');
const TABLE_PATH = path.join(HERE, '..', 'artifacts', 'nucleus', 'texture_filename_table.json');
const COMPUTED_TABLE_PATH = path.join(HERE, '..', 'artifacts', 'nucleus', 'texture_filename_table_computed.json');
const COMPUTE_TABLE = path.join(HERE, 'compute_texture_table.py');
const MAKE_COVER = path.join(HERE, 'make_cover.py');
const TEXPACK_RUNDIR = path.join(REPO_ROOT, 'tests', 'artifacts', 'dolphin', 'texpack-run');

const PIPE_READY_TIMEOUT_MS = 45000;
const MENU_WAIT_MS = 13000;

function log(msg) { console.log(`[harvest] ${msg}`); }
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function sleepSync(ms) { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); }

function parseArgs(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i += 1) {
    const t = argv[i];
    if (t.startsWith('--')) {
      const key = t.slice(2);
      const val = argv[i + 1];
      if (val === undefined || val.startsWith('--')) flags[key] = true;
      else { flags[key] = val; i += 1; }
    }
  }
  return flags;
}

function node(script, args, opts) {
  const res = spawnSync(process.execPath, [script, ...args], { stdio: 'inherit', ...opts });
  if (res.status !== 0) throw new Error(`${path.basename(script)} ${args.join(' ')} exited ${res.status}`);
}

// --- backend (kept alive across build + listen) -----------------------------

async function api(baseUrl, method, route, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const res = await fetch(`${baseUrl}${route}`, opts);
  const text = await res.text();
  let json;
  try { json = JSON.parse(text); } catch (e) { throw new Error(`${method} ${route} -> ${res.status}: ${text.slice(0, 300)}`); }
  return { status: res.status, json };
}

const BACKEND_LOG = path.join(HERE, '..', 'artifacts', 'nucleus', 'harvest-backend.log');

// Spawn the backend with stdio redirected to a FILE, not a pipe. We later run the
// build via spawnSync, which BLOCKS the Node event loop -- so a piped backend
// stdout would never get drained, its OS buffer (~64KB) would fill, and the
// backend would deadlock on write the moment it logs something large (e.g. the
// /sss/layout dump). A file fd is drained by the OS, so blocking spawnSync is safe.
// Read the port back from the log file rather than from a live stream.
function spawnBackend() {
  return new Promise((resolve, reject) => {
    if (!fs.existsSync(VENV_PYTHON)) { reject(new Error(`venv python not found at ${VENV_PYTHON}`)); return; }
    log(`starting dev backend (venv python _run_backend.py) -> ${BACKEND_LOG}`);
    fs.mkdirSync(path.dirname(BACKEND_LOG), { recursive: true });
    const logFd = fs.openSync(BACKEND_LOG, 'w');
    const proc = spawn(VENV_PYTHON, [path.join(HERE, '_run_backend.py')],
      { cwd: REPO_ROOT, windowsHide: true, stdio: ['ignore', logFd, logFd] });
    proc.on('error', reject);
    let done = false;
    const deadline = Date.now() + 30000;
    const poll = setInterval(() => {
      let text = '';
      try { text = fs.readFileSync(BACKEND_LOG, 'utf8'); } catch (e) { /* not yet */ }
      const m = text.match(/BACKEND_PORT:(\d+)/);
      if (m && !done) { done = true; clearInterval(poll); resolve({ proc, port: parseInt(m[1], 10) }); }
      else if (Date.now() > deadline && !done) {
        done = true; clearInterval(poll);
        reject(new Error(`backend no port within 30s; see ${BACKEND_LOG}`));
      }
    }, 400);
    proc.on('exit', (code) => { if (!done) { done = true; clearInterval(poll); reject(new Error(`backend exited (code ${code}) early; see ${BACKEND_LOG}`)); } });
  });
}

async function waitForReady(baseUrl) {
  for (let i = 0; i < 120; i += 1) {
    try { const { json } = await api(baseUrl, 'GET', '/api/mex/status'); if (json && json.connected) return; } catch (e) { /* retry */ }
    await sleep(500);
  }
  throw new Error('backend never became ready');
}

// --- bundle (.ssbm) creation ------------------------------------------------

// POST /bundle/export as multipart so we can embed a cover image. Node's global
// FormData/Blob drive fetch's multipart encoding; the backend reads request.form
// + request.files['image'].
async function createBundle(baseUrl, fields, coverPath) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  if (coverPath && fs.existsSync(coverPath)) {
    fd.append('image', new Blob([fs.readFileSync(coverPath)], { type: 'image/png' }), 'cover.png');
  }
  const res = await fetch(`${baseUrl}/api/mex/bundle/export`, { method: 'POST', body: fd });
  return res.json();
}

// The export runs in a background thread (WebSocket-only), so poll /bundle/list
// until the new bundle id lands (xdelta-diffing two ~1.4GB ISOs takes a minute+).
async function waitForBundle(baseUrl, bundleId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const { json } = await api(baseUrl, 'GET', '/api/mex/bundle/list');
      const b = (json.bundles || []).find((x) => x.id === bundleId);
      if (b && b.size > 0) return b;
    } catch (e) { /* retry */ }
    await sleep(2500);
  }
  return null;
}

function waitForPipeReady(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = spawnSync(process.execPath, [PIPE, 'neutral'], { stdio: 'ignore' });
    if (res.status === 0) return true;
    sleepSync(800);
  }
  return false;
}

// --- harvest table ----------------------------------------------------------

// tex1_16x16_<texHash>_<tlutHash>_<fmt>.png  ->  parts (tlutHash optional)
function parseDumpName(name) {
  const m = name.match(/^tex1_(\d+)x(\d+)_([0-9a-f]+)(?:_([0-9a-f]+))?_(\d+)\.(png|dds)$/i);
  if (!m) return null;
  return { w: +m[1], h: +m[2], texHash: m[3], tlutHash: m[4] || null, fmt: m[5], ext: m[6] };
}

function mergeIntoTable(mapping, buildLabel) {
  const table = fs.existsSync(TABLE_PATH) ? JSON.parse(fs.readFileSync(TABLE_PATH, 'utf8')) : { entries: {}, builds: [] };
  let added = 0, confirmed = 0, conflicts = 0;
  for (const c of (mapping.costumes || [])) {
    if (!c.matched || !c.dumped_filename) continue;
    const parsed = parseDumpName(c.dumped_filename);
    const rec = { filename: c.dumped_filename, ...(parsed || {}) };
    const key = String(c.index);
    const prev = table.entries[key];
    if (!prev) { table.entries[key] = rec; added += 1; }
    else if (prev.filename === rec.filename) { confirmed += 1; }
    else {
      conflicts += 1;
      console.log(`  [CONFLICT] index ${key}: ${prev.filename} (prior) != ${rec.filename} (${buildLabel})`);
      table.entries[key] = { ...rec, conflictWith: prev.filename };
    }
  }
  table.builds.push({ label: buildLabel, added, confirmed, conflicts, at: new Date().toISOString() });
  table.count = Object.keys(table.entries).length;
  fs.writeFileSync(TABLE_PATH, JSON.stringify(table, null, 2));
  return { added, confirmed, conflicts, total: table.count };
}

// --- main -------------------------------------------------------------------

async function main() {
  const flags = parseArgs(process.argv.slice(2));
  const projectName = (flags.name && flags.name !== true) ? flags.name : 'texpack-harvest';

  // 1. Backend (ours, kept alive through build + listen) ----------------------
  let backend = null, baseUrl;
  if (flags.backend && flags.backend !== true) { baseUrl = flags.backend.replace(/\/$/, ''); log(`using existing backend ${baseUrl}`); }
  else { backend = await spawnBackend(); baseUrl = `http://127.0.0.1:${backend.port}`; log(`backend on ${baseUrl}`); }

  const killBackend = () => { if (backend && !flags.keep) { try { backend.proc.kill(); } catch (e) { /* */ } } };

  try {
    await waitForReady(baseUrl);

    // 2. Build a texture-pack ISO (reuse our backend; build writes last-build.json)
    const buildArgs = ['--texture-pack', '--slippi', TEXPACK_RUNDIR, '--backend', baseUrl, '--name', projectName];
    for (const k of ['type', 'count', 'skip', 'mod', 'fighter', 'iso', 'mp-char', 'mp-stage', 'mp-menu', 'costume-fighter']) {
      if (flags[k] && flags[k] !== true) buildArgs.push(`--${k}`, flags[k]);
    }
    log(`building texture-pack ISO: build-modded-iso.js ${buildArgs.join(' ')}`);
    node(BUILD, buildArgs);

    const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
    if (!manifest.texturePack || !manifest.buildId) throw new Error('manifest is not a texture-pack build');
    log(`built ${path.basename(manifest.iso)} — buildId ${manifest.buildId}, ${manifest.placeholderCount} placeholders`);
    if (!manifest.placeholderCount) throw new Error('0 placeholders — texture-pack export produced no CSP mapping');

    // 2b. OFFLINE mode: name the whole pack from a table, no boot --------------
    // --compute: build the table by PURE COMPUTATION (no Dolphin, no harvest ever)
    // -- generate each placeholder, encode it (mexcli), and XXH64 the bytes the way
    // Dolphin does. Otherwise use the previously harvested table.
    if (flags.offline) {
      let tablePath = TABLE_PATH;
      if (flags.compute) {
        const maxIndex = manifest.placeholderCount - 1; // indices are contiguous 0..count-1
        log(`OFFLINE+COMPUTE: computing index->filename table for 0..${maxIndex} (pure math, no Dolphin)`);
        const py = fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : VENV_PY_MELEE;
        const c = spawnSync(py, [COMPUTE_TABLE, '--max', String(maxIndex), '--out', COMPUTED_TABLE_PATH], { stdio: 'inherit', cwd: HERE });
        if (c.status !== 0) throw new Error('compute_texture_table failed');
        tablePath = COMPUTED_TABLE_PATH;
      }
      if (!fs.existsSync(tablePath)) throw new Error(`--offline needs a table at ${tablePath} (harvest first, or pass --compute)`);
      log(`OFFLINE: naming texture pack from ${path.basename(tablePath)} (no boot, no scroll)`);
      const ap = await api(baseUrl, 'POST', '/api/mex/texture-pack/apply-offline',
        { buildId: manifest.buildId, slippiPath: TEXPACK_RUNDIR, tablePath });
      if (!ap.json.success) throw new Error(`apply-offline failed: ${JSON.stringify(ap.json)}`);
      log(`OFFLINE: matched ${ap.json.matched}/${ap.json.total} from table -> ${ap.json.texturePackPath}`);
      if (ap.json.missingFromTable && ap.json.missingFromTable.length) {
        log(`OFFLINE: ${ap.json.missingFromTable.length} indices not in table (need harvest/compute): ${ap.json.missingFromTable.join(', ')}`);
      }
      if (ap.json.copyFailed && ap.json.copyFailed.length) log(`OFFLINE: ${ap.json.copyFailed.length} copy-failed: ${ap.json.copyFailed.join(', ')}`);

      // 2c. BUNDLE: package the modded ISO (xdelta vs vanilla) + the named texture
      // pack + a cover image into a shareable .ssbm that shows up in the app's
      // Patches -> Bundles section (Install button).
      if (flags.bundle) {
        const bundleName = (flags['bundle-name'] && flags['bundle-name'] !== true) ? flags['bundle-name'] : 'NUCLEUS GENESIS';
        const subtitle = (flags.subtitle && flags.subtitle !== true) ? flags.subtitle : "Claude's first modpack · one of everything";
        const contents = manifest.contents || [];
        const desc = 'One of every mod type, assembled & verified by the Nucleus harness: '
          + contents.map((c) => c.label).join(' · ');
        const coverPath = path.join(path.dirname(MANIFEST), 'modpack-cover.png');
        const pyc = fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : VENV_PY_MELEE;
        log(`BUNDLE: rendering cover "${bundleName}"`);
        spawnSync(pyc, [MAKE_COVER, coverPath, bundleName, subtitle, JSON.stringify(contents)], { stdio: 'inherit', cwd: HERE });

        log('BUNDLE: creating .ssbm (xdelta patch vs vanilla + texture pack + cover)...');
        const resp = await createBundle(baseUrl, {
          name: bundleName,
          description: desc,
          buildName: projectName,
          vanillaIsoPath: manifest.builtFrom,
          exportedIsoPath: manifest.iso,
          texturePackPath: ap.json.texturePackPath,
        }, coverPath);
        if (!resp.success) throw new Error(`bundle export failed: ${JSON.stringify(resp)}`);
        log(`BUNDLE: export ${resp.export_id} running (diffing two ~1.4GB ISOs)...`);
        const b = await waitForBundle(baseUrl, resp.export_id, 6 * 60 * 1000);
        if (!b) throw new Error('bundle did not appear in /bundle/list within 6min');
        log(`BUNDLE READY: "${b.name}" — ${b.size_mb} MB, ${b.texture_count} HD portraits`);
        log(`  file: storage/bundles/${b.filename}  (id ${b.id})`);
        log('  -> appears in the app under Patches → Bundles (Install to test).');
      }
      return;
    }

    // 3. Boot into the KNOWN run dir with dumping on, reach the CSS ------------
    log('killing any running Dolphin');
    try { node(CONTROL, ['kill']); } catch (e) { /* none */ }
    if (fs.existsSync(TEXPACK_RUNDIR)) { log(`clearing run dir ${TEXPACK_RUNDIR}`); fs.rmSync(TEXPACK_RUNDIR, { recursive: true, force: true }); }
    log('launching texture-pack ISO (run-dir + texture-dump)');
    node(CONTROL, ['launch', '--iso', manifest.iso, '--run-dir', TEXPACK_RUNDIR, '--texture-dump']);
    log('waiting for Dolphin input pipe...');
    if (!waitForPipeReady(PIPE_READY_TIMEOUT_MS)) throw new Error('input pipe never appeared');
    log(`pipe up; waiting ${MENU_WAIT_MS / 1000}s for the menu`);
    sleepSync(MENU_WAIT_MS);
    // 4. Start the watcher BEFORE any CSP renders -----------------------------
    // (We're at the Online Play menu now -- the modded ISO's boot screen.)
    log('start-listening (watching the run dir Dump folder)');
    const sl = await api(baseUrl, 'POST', '/api/mex/texture-pack/start-listening',
      { buildId: manifest.buildId, slippiPath: TEXPACK_RUNDIR });
    if (!sl.json.success) throw new Error(`start-listening failed: ${JSON.stringify(sl.json)}`);
    const matchingJobId = sl.json.job_id;
    log(`texture matching job ${matchingJobId}`);
    const scrollPy = fs.existsSync(VENV_PY_MELEE) ? VENV_PY_MELEE : VENV_PYTHON;

    // 4a. SHEIK pass (opt-in --sheik): the offline CSS can't show Sheik (the
    // Zelda cell renders Zelda there); the UNRANKED online CSS renders Sheik on
    // that cell. So BEFORE leaving the online menu, briefly enter the online CSS,
    // dump Sheik's costumes, and hold-B out -- the pass is hard-time-boxed and
    // always exits before matchmaking pairs a real player.
    if (flags.sheik) {
      log('SHEIK pass: brief online-CSS entry to dump Sheik (Zelda box); exits before matchmaking');
      const sh = spawnSync(scrollPy, [SHEIK_ONLINE, manifest.mappingPath], { stdio: 'inherit', cwd: HERE });
      if (sh.status !== 0) log(`WARN: sheik online pass exited ${sh.status} (continuing)`);
    }

    // 4b. Offline CSS: sweep everything else --------------------------------
    node(PIPE, ['gotocss']);
    const scrollArgs = [TEX_SCROLL, manifest.mappingPath];
    if (flags.limit && flags.limit !== true) scrollArgs.push('--limit', flags.limit);
    if (flags['no-place']) scrollArgs.push('--no-place');
    if (flags.dwell && flags.dwell !== true) scrollArgs.push('--dwell', flags.dwell);
    if (flags.sheik) scrollArgs.push('--exclude', 'Sheik'); // Sheik handled by the online pass
    log(`scrolling CSS: tex_scroll.py ${path.basename(manifest.mappingPath)} ${scrollArgs.slice(2).join(' ')}`);
    const sweep = spawnSync(scrollPy, scrollArgs, { stdio: 'inherit', cwd: HERE });
    if (sweep.status !== 0) log(`WARN: tex_scroll exited ${sweep.status} (finalizing collected matches)`);

    // give the watcher a moment to drain the last dumps, then stop
    await sleep(2000);

    // 5. Stop + harvest -------------------------------------------------------
    log('finalizing texture matching');
    await api(baseUrl, 'POST', `/api/jobs/${matchingJobId}/cancel`, {});
    let matchingResult;
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      const status = await api(baseUrl, 'GET', `/api/jobs/${matchingJobId}`);
      const job = status.json.job;
      if (job.status === 'done') { matchingResult = job.result; break; }
      if (['failed', 'cancelled', 'interrupted'].includes(job.status)) {
        throw new Error(job.error || `Texture matching ${job.status}`);
      }
      await sleep(250);
    }
    if (!matchingResult) throw new Error('Texture matching did not finalize within 30 seconds');
    log(`matched ${matchingResult.matchedCount}/${matchingResult.totalCount} textures -> ${matchingResult.texturePackPath}`);

    const finalMapping = JSON.parse(fs.readFileSync(manifest.mappingPath, 'utf8'));
    const label = `${projectName}/${manifest.buildId} (added=${manifest.addedCostumes ?? '?'})`;
    const res = mergeIntoTable(finalMapping, label);
    log(`TABLE: +${res.added} new, ${res.confirmed} re-confirmed, ${res.conflicts} CONFLICTS — ${res.total} indices total`);
    log(`table -> ${TABLE_PATH}`);
    if (res.conflicts) log('WARNING: conflicts mean a given index produced different filenames across builds (NOT build-independent!)');
  } finally {
    try { node(CONTROL, ['kill']); } catch (e) { /* */ }
    killBackend();
  }
}

main().catch((err) => { console.error(`[harvest] ERROR: ${err.message}`); process.exitCode = 1; });
