'use strict';

// Lives in tools/ingame/; everything it tests is under <repo>/app.
const APP_ROOT = require('node:path').resolve(__dirname, '..', '..', 'app');
const appRequire = require('node:module').createRequire(require('node:path').join(APP_ROOT, 'package.json'));

// Run with Node: the wrapper launches only this disposable Electron fixture.
// Actual ImportFab, VaultImportSurface, IsoScanModal and sandboxed preload;
// real disk-backed Files, with the scanner API replaced by a loopback fixture.
// The scan is a shared job: the fixture answers /api/jobs like core/jobs.py, and
// fixtures/socket-stub.js stands in for the socket that pushes job records.
if (!process.versions.electron) {
  const { spawnSync } = require('node:child_process');
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  const child = spawnSync(appRequire('electron'), [__filename], {
    env, stdio: 'inherit', windowsHide: true,
  });
  if (child.error) console.error(child.error);
  process.exit(child.status ?? 1);
}

const { app, BrowserWindow, ipcMain } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { build } = require(path.join(APP_ROOT, 'frontend', 'node_modules', 'esbuild'));

const root = APP_ROOT;
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-iso-import-smoke-'));
app.setPath('userData', profile);
app.setPath('sessionData', profile);
app.disableHardwareAcceleration();
const token = 'iso-import-smoke-token';
const scans = [];
const checks = [];
const iso = path.join(profile, 'Melee test.iso');
const gcm = path.join(profile, 'Melee second.GCM');
const zip = path.join(profile, 'costume.zip');
for (const filename of [iso, gcm, zip]) fs.writeFileSync(filename, 'synthetic import fixture');
let window;
let server;
let finished = false;
let pickerCalls = 0;
let customScanError = false;
let skinScanError = false;
let holdSkin = false;
let skinCancelled = false;
let rejectCancel = false;
let holdCustom = false;
let customRequests = 0;
let releaseCustom;
let holdStart = false;
let releaseStart;
let candidates = {};
let importReply = { imported: 2, total_selected: 2, errors: [] };
let importStatus = 200;
let importRequests = [];
let holdImport = false;
let releaseImport;
let holdDelete = false;
let releaseDelete;
// Scan jobs by id: { held, cancelled, result, seq, sent }. A held job runs until
// it is cancelled; the others are done with the result the fixture had at start.
const jobs = new Map();
const SKIPPED_VAULT = [{ id: 'cool-fox', name: 'Cool Fox', character: 'Fox', csp_url: '/fixture-preview.png' }];

function jobRecord(id) {
  const job = jobs.get(id);
  const status = job.held ? job.cancelled ? 'cancelled' : 'running' : 'done';
  const stats = { existing: 1, vanilla: 123 };
  const record = { id, kind: 'iso_scan', status, progress: job.held ? 0.7 : 1, detail: '', error: null,
    extra: { phase: status === 'running' ? 'csp' : status, phase_current: 0, phase_total: 0, stats },
    result: status === 'done' ? job.result : null };
  const body = JSON.stringify(record);
  if (body !== job.sent) { job.sent = body; job.seq++; }
  return { ...record, seq: job.seq };
}
const timeout = setTimeout(() => finish(new Error('ISO import smoke timed out')), 60000);

function finish(error) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  if (window && !window.isDestroyed()) window.destroy();
  server?.close();
  const receipt = { success: !error, error: error?.stack || null,
    electron: process.versions.electron, profile, checks, scans };
  if (process.env.NUCLEUS_ISO_IMPORT_RESULT) {
    fs.writeFileSync(process.env.NUCLEUS_ISO_IMPORT_RESULT, JSON.stringify(receipt, null, 2), { flag: 'wx' });
  }
  console.log(error ? 'ISO_IMPORT_SMOKE_FAIL: ' + error.stack : 'ISO_IMPORT_SMOKE_PASS: ' + checks.join(', '));
  console.log('ISO_IMPORT_SMOKE_PROFILE:', profile);
  app.exit(error ? 1 : 0);
}

async function evaluate(source) {
  return window.webContents.executeJavaScript(source);
}

async function waitFor(source) {
  const deadline = Date.now() + 6000;
  while (Date.now() < deadline) {
    if (await evaluate(source)) return;
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  throw new Error(`Did not reach UI state: ${source}\n${await evaluate('document.body.innerText')}`);
}

async function waitForRequest(ready) {
  const deadline = Date.now() + 6000;
  while (!ready()) {
    if (Date.now() > deadline) throw new Error('Fixture request did not arrive');
    await new Promise(resolve => setTimeout(resolve, 10));
  }
}

async function selectFiles(files) {
  const { root: document } = await window.webContents.debugger.sendCommand('DOM.getDocument');
  const { nodeId } = await window.webContents.debugger.sendCommand('DOM.querySelector', {
    nodeId: document.nodeId, selector: '.import-fab input[type=file]',
  });
  await window.webContents.debugger.sendCommand('DOM.setFileInputFiles', { nodeId, files });
}

async function startAndComplete(expectedPaths) {
  const previous = scans.length;
  assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('.iso-scan-file-name'), e => e.title)`), expectedPaths);
  await evaluate(`document.querySelector('.iso-scan-actions .btn-save').click()`);
  await waitFor(`!!document.querySelector('[data-scan-complete]')`);
  assert.equal(scans.length, previous + 1);
  assert.deepEqual(scans[previous].iso_paths, expectedPaths);
}

app.whenReady().then(async () => {
  const socketStub = {
    name: 'fixture-socket',
    setup(bundle) {
      bundle.onResolve({ filter: /(^|\/)transport\/socket(\.js)?$/ },
        () => ({ path: path.join(__dirname, 'fixtures', 'socket-stub.js') }));
    },
  };
  await build({
    entryPoints: [path.join(__dirname, 'fixtures/iso-import.jsx')],
    outfile: path.join(profile, 'fixture.js'), bundle: true,
    nodePaths: [path.join(root, 'frontend/node_modules')],
    format: 'iife', platform: 'browser', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"production"' },
    plugins: [socketStub], logLevel: 'error',
  });
  server = http.createServer(async (req, res) => {
    if (req.url === '/fixture.js' || req.url === '/fixture.css') {
      res.writeHead(200, { 'Content-Type': req.url.endsWith('.js') ? 'text/javascript' : 'text/css' });
      return res.end(fs.readFileSync(path.join(profile, req.url.slice(1))));
    }
    if (req.url === '/fixture-preview.png') {
      res.writeHead(200, { 'Content-Type': 'image/png' });
      return res.end(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6iAAAAABJRU5ErkJggg==', 'base64'));
    }
    if (req.url === '/api/mex/scan-iso/mex-content') {
      customRequests++;
      const reply = () => {
        res.writeHead(customScanError ? 500 : 200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(customScanError ? { error: 'Unreadable custom content' } : {
          characters: { imported: ['Shulk', 'Little Mac', 'Incineroar'], skipped: ['Wolf'] },
        }));
      };
      if (holdCustom) releaseCustom = reply;
      else reply();
      return;
    }
    if (req.url === '/api/mex/custom-characters/list') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ characters: [{ name: 'Wolf', icon_url: '/fixture-preview.png' }] }));
    }
    if (req.url.startsWith('/api/mex/iso-scan/') || req.url === '/api/jobs' || req.url.startsWith('/api/jobs/')) {
      if (req.headers['x-nucleus-token'] !== token) {
        res.writeHead(401); return res.end('{}');
      }
      let data = '';
      for await (const chunk of req) data += chunk;
      if (req.url === '/api/jobs') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ jobs: [...jobs.keys()].map(jobRecord) }));
      }
      if (req.url.startsWith('/api/jobs/')) {
        const [id, action] = req.url.slice('/api/jobs/'.length).split('/').map(decodeURIComponent);
        if (!jobs.has(id)) { res.writeHead(404, { 'Content-Type': 'application/json' }); return res.end('{}'); }
        if (action === 'cancel') {
          res.writeHead(rejectCancel ? 503 : 200, { 'Content-Type': 'application/json' });
          if (rejectCancel) return res.end(JSON.stringify({ error: 'Temporary cancellation failure' }));
          skinCancelled = true;
          jobs.get(id).cancelled = true;
          return res.end(JSON.stringify({ success: true }));
        }
        res.writeHead(200, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify(action ? { success: true } : { job: jobRecord(id) }));
      }
      if (req.url.endsWith('/start') && skinScanError) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'Unreadable skin data' }));
      }
      if (req.method === 'DELETE') {
        const reply = () => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); };
        if (holdDelete) releaseDelete = reply;
        else reply();
        return;
      }
      if (req.url.endsWith('/import')) {
        importRequests.push(JSON.parse(data));
        const reply = () => {
          res.writeHead(importStatus, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify(importReply));
        };
        if (holdImport) releaseImport = reply;
        else reply();
        return;
      }
      if (req.url.endsWith('/start')) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        scans.push(JSON.parse(data));
        const id = `smoke-${scans.length}`;
        jobs.set(id, { held: holdSkin, cancelled: false, seq: 0, sent: null,
          result: { characters: candidates, stats: { existing: 1, vanilla: 123 }, skipped_vault: SKIPPED_VAULT } });
        if (holdStart) { releaseStart = () => res.end(JSON.stringify({ job_id: id })); return; }
        return res.end(JSON.stringify({ job_id: id }));
      }
      res.writeHead(404); return res.end('{}');
    }
    if (req.url !== '/') { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end('<!doctype html><title>ISO import test</title><link rel="stylesheet" href="/fixture.css"><div id="root"></div><script>localStorage.clear();localStorage.setItem("settings_master_volume","0")</script><script src="/fixture.js"></script>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  // The window's secrets come over IPC, as app/electron/main.js answers them (security L1).
  ipcMain.on('renderer:secrets', (event) => { event.returnValue = { backendToken: token, uiApprovalKey: '' }; });
  ipcMain.handle('open-iso-multi-dialog', () => ++pickerCalls === 1 ? [] : [iso]);
  window = new BrowserWindow({ show: false, width: 1000, height: 800,
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false,
      preload: process.env.NUCLEUS_ISO_IMPORT_PRELOAD_PATH || path.join(root, 'electron/preload.js'),
      additionalArguments: [`--backend-port=${port}`] },
  });
  window.webContents.on('preload-error', (_event, _file, error) => finish(error));
  window.webContents.debugger.attach('1.3');
  const reload = async () => {
    await window.loadURL(`http://127.0.0.1:${port}/`);
    await waitFor(`!!document.querySelector('.import-fab input[type=file]')`);
  };

  await reload();
  await selectFiles([iso]);
  // DOM.setFileInputFiles emits the native file-input change event.
  await waitFor(`!!document.querySelector('.iso-scan-modal')`);
  await startAndComplete([iso]);
  assert.equal(await evaluate(`document.querySelector('.import-fab input').value`), '');
  checks.push('Import picker -> scan with full disk path');
  assert.equal(await evaluate(`!!document.querySelector('.iso-report-header')`), false);
  assert.equal(await evaluate(`document.body.innerText.toLowerCase().includes('vanilla')`), false);
  await waitFor(`document.querySelector('.iso-vault-cards img')?.naturalWidth > 0`);
  assert.match(await evaluate(`document.querySelector('.iso-vault-section').textContent`), /Cool Fox/);
  checks.push('minimal results hide vanilla files and load already-in-vault skin portraits');

  await reload();
  // Populate a separate input, then drop its real File objects onto the app.
  await evaluate(`document.body.insertAdjacentHTML('beforeend', '<input id="drop-source" type="file" multiple>')`);
  const { root: doc } = await window.webContents.debugger.sendCommand('DOM.getDocument');
  const { nodeId } = await window.webContents.debugger.sendCommand('DOM.querySelector', { nodeId: doc.nodeId, selector: '#drop-source' });
  await window.webContents.debugger.sendCommand('DOM.setFileInputFiles', { nodeId, files: [gcm, iso, zip] });
  assert.equal(await evaluate(`document.querySelector('#drop-source').files[0].path === undefined`), true);
  await evaluate(`(() => {
    const data = new DataTransfer();
    for (const file of document.querySelector('#drop-source').files) data.items.add(file);
    document.body.dispatchEvent(new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: data }));
    document.body.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: data }));
  })()`);
  await waitFor(`!!document.querySelector('.iso-scan-modal')`);
  assert.deepEqual(await evaluate('window.importedFiles'), ['costume.zip']);
  await startAndComplete([gcm, iso]);
  checks.push('OS-file drop -> scan; mixed GCM/ISO/ZIP preserved; no File.path');

  await reload();
  assert.equal(await evaluate(`window.electron.getPathForFile(new File(['test'], 'missing.iso'))`), '');
  await evaluate(`(() => {
    const data = new DataTransfer();
    data.items.add(new File(['test'], 'missing.iso'));
    document.body.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: data }));
  })()`);
  await waitFor(`document.querySelector('[role=alert]')?.textContent.includes('Try Add ISOs')`);
  assert.equal(await evaluate(`document.querySelector('.iso-scan-actions .btn-save').disabled`), true);
  await evaluate(`document.querySelector('.iso-scan-actions .btn-cancel').click()`);
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(pickerCalls, 1);
  assert.equal(await evaluate(`!!document.querySelector('[role=alert]')`), true);
  await evaluate(`document.querySelector('.iso-scan-actions .btn-cancel').click()`);
  await waitFor(`!!document.querySelector('.iso-scan-file-name')`);
  assert.equal(await evaluate(`!!document.querySelector('[role=alert]')`), false);
  await startAndComplete([iso]);
  checks.push('missing path visibly recoverable; picker cancellation and retry');

  await reload();
  await selectFiles([iso]);
  await waitFor(`!!document.querySelector('.iso-scan-modal')`);
  await evaluate(`[...document.querySelectorAll('.iso-scan-targets label')].find(label => label.textContent.trim() === 'Custom characters').querySelector('input').click()`);
  await startAndComplete([iso]);
  await waitFor(`document.querySelector('.iso-vault-cards img')?.naturalWidth > 0`);
  assert.match(await evaluate(`document.querySelector('.iso-vault-section').textContent`), /Wolf/);
  assert.equal(await evaluate(`document.querySelectorAll('.iso-added-cards:not(.iso-vault-cards) .iso-added-card').length`), 3);
  checks.push('three custom additions remain visible with zero new skins');

  skinScanError = true;
  await reload();
  await selectFiles([iso]);
  await waitFor(`!!document.querySelector('.iso-scan-modal')`);
  await evaluate(`[...document.querySelectorAll('.iso-scan-targets label')].find(label => label.textContent.trim() === 'Custom characters').querySelector('input').click(); document.querySelector('.iso-scan-actions .btn-save').click()`);
  await waitFor(`!!document.querySelector('[data-scan-complete] [role=alert]')`);
  assert.equal(await evaluate(`document.querySelectorAll('.iso-added-cards:not(.iso-vault-cards) .iso-added-card').length`), 3);
  assert.match(await evaluate(`document.querySelector('[role=alert]').textContent`), /Character skin scan failed/);
  checks.push('skin scan failure preserves successful custom additions');

  customScanError = true;
  await reload();
  await selectFiles([iso]);
  await waitFor(`!!document.querySelector('.iso-scan-modal')`);
  await evaluate(`const targets = [...document.querySelectorAll('.iso-scan-targets label')]; for (const name of ['Character skins', 'Custom characters']) targets.find(label => label.textContent.trim() === name).querySelector('input').click(); document.querySelector('.iso-scan-actions .btn-save').click()`);
  await waitFor(`!!document.querySelector('[data-scan-complete]')`);
  assert.match(await evaluate(`document.querySelector('[role=alert]').textContent`), /Unreadable custom content/);
  checks.push('failed custom-only scan reports issues instead of empty success');

  customScanError = false; skinScanError = false; holdSkin = true; rejectCancel = true;
  await reload(); await selectFiles([iso]);
  await waitFor(`!!document.querySelector('.iso-scan-file-name')`);
  await evaluate(`document.querySelector('.iso-scan-actions .btn-save').click()`);
  await waitFor(`document.querySelector('.iso-progress-copy h2')?.textContent === 'Finishing scan'`);
  assert.equal(await evaluate(`document.body.innerText.includes('0/0') || document.body.innerText.includes('workers')`), false);
  await evaluate(`document.querySelector('.edit-modal-overlay').click()`);
  assert.equal(await evaluate(`!!document.querySelector('[data-scan-progress]')`), true);
  await evaluate(`document.querySelector('.iso-progress-footer button').click()`);
  await waitFor(`!!document.querySelector('.iso-progress-copy [role=alert]')`);
  assert.equal(await evaluate(`document.querySelector('.iso-progress-footer button').disabled`), false);
  rejectCancel = false;
  await evaluate(`document.querySelector('.iso-progress-footer button').click()`);
  await waitFor(`!!document.querySelector('.iso-scan-actions')`);
  checks.push('zero-preview display; outside click retains active scan; failed cancellation retries');

  skinCancelled = false; holdStart = true;
  await reload(); await selectFiles([iso]);
  await waitFor(`!!document.querySelector('.iso-scan-file-name')`);
  await evaluate(`document.querySelector('.iso-scan-actions .btn-save').click()`);
  await waitFor(`!!document.querySelector('[data-scan-progress]')`);
  await evaluate(`document.querySelector('.iso-progress-footer button').click()`);
  assert.equal(await evaluate(`document.querySelector('.iso-progress-footer button').disabled`), true);
  await waitForRequest(() => releaseStart);
  releaseStart(); holdStart = false;
  await waitFor(`!!document.querySelector('.iso-scan-actions')`);
  assert.equal(skinCancelled, true);
  checks.push('cancellation before job ID is queued and delivered');

  holdCustom = true;
  const previousCustom = customRequests, previousScans = scans.length;
  await reload(); await selectFiles([iso, gcm]);
  await waitFor(`!!document.querySelector('.iso-scan-file-name')`);
  await evaluate(`[...document.querySelectorAll('.iso-scan-targets label')].find(label => label.textContent.trim() === 'Custom characters').querySelector('input').click(); document.querySelector('.iso-scan-actions .btn-save').click()`);
  await waitFor(`document.querySelector('.iso-progress-copy h2')?.textContent === 'Importing custom characters'`);
  await evaluate(`document.querySelector('.iso-progress-footer button').click()`);
  assert.equal(await evaluate(`document.querySelector('.iso-progress-copy h2').textContent`), 'Finishing current import');
  await waitForRequest(() => releaseCustom);
  releaseCustom();
  await waitFor(`!!document.querySelector('[data-scan-complete]')`);
  assert.equal(customRequests, previousCustom + 1);
  assert.equal(scans.length, previousScans);
  assert.equal(await evaluate(`document.querySelectorAll('.iso-added-cards:not(.iso-vault-cards) .iso-added-card').length`), 3);
  checks.push('custom cancellation keeps current additions and skips remaining ISOs and skin scan');

  holdSkin = false; holdCustom = false; skinCancelled = false;
  candidates = { Fox: ['Nr', 'Gr'].map(color => ({ key: `fox-${color}`, costume_code: `PlFx${color}`,
    source_iso: iso, csp_url: '/fixture-preview.png' })) };
  const review = async () => {
    await reload(); await selectFiles([iso]);
    await waitFor(`!!document.querySelector('.iso-scan-file-name')`);
    await startAndComplete([iso]);
    await waitFor(`document.querySelectorAll('.iso-skin-card').length === 2`);
  };
  const captureSounds = () => evaluate(`window.cues = []; HTMLMediaElement.prototype.play = function () { window.cues.push(new URL(this.src).pathname); return Promise.resolve(); }; void 0`);
  const importButton = `document.querySelector('.iso-report-footer .btn-save')`;
  await review();
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.iso-report-footer button')].map(b => b.textContent.trim())`),
    ['Close without importing', 'Import & finish']);
  await evaluate(`document.querySelector('.edit-modal-overlay').click()`);
  assert.equal(await evaluate(`document.querySelectorAll('.iso-skin-card[aria-pressed=true]').length`), 2);
  await evaluate(`document.querySelector('.iso-review-toolbar button:last-child').click()`);
  assert.equal(await evaluate(`${importButton}.disabled`), true);
  await evaluate(`document.querySelector('.iso-review-toolbar button').click()`);
  holdDelete = true; releaseDelete = null;
  await captureSounds();
  await evaluate(`document.querySelector('.iso-report-footer .btn-cancel').click()`);
  await waitFor(`!document.querySelector('.iso-scan-modal')`);
  await waitForRequest(() => releaseDelete);
  assert.equal(importRequests.length, 0);
  assert.deepEqual(await evaluate('window.cues'), ['/vanilla/sounds/back.wav']);
  releaseDelete();
  checks.push('review has explicit import/close actions; outside click retains selection; close does not wait for cleanup');

  await review(); await captureSounds();
  holdImport = true; releaseImport = null; releaseDelete = null;
  await evaluate(`const button = ${importButton}; button.click(); button.click()`);
  await waitForRequest(() => releaseImport);
  await waitFor(`!!document.querySelector('[data-scan-progress]')`);
  await evaluate(`document.querySelector('.edit-modal-overlay').click()`);
  assert.equal(await evaluate(`!!document.querySelector('[data-scan-progress]')`), true);
  assert.deepEqual(importRequests, [{ keys: ['fox-Nr', 'fox-Gr'], auto_fix: true }]);
  releaseImport(); holdImport = false;
  await waitFor(`!document.querySelector('.iso-scan-modal')`);
  await waitForRequest(() => releaseDelete);
  assert.equal(await evaluate('window.refreshCalls'), 1);
  assert.deepEqual(await evaluate('window.cues'), ['/vanilla/sounds/start.wav', '/vanilla/sounds/big_achievement.wav']);
  releaseDelete(); holdDelete = false;
  checks.push('Import & finish saves once, refreshes, sounds, and closes with no extra Done screen or cleanup delay');

  await review();
  importReply = { imported: 1, total_selected: 1, errors: [] };
  await evaluate(`document.querySelector('.iso-skin-card').click()`);
  await waitFor(`document.querySelectorAll('.iso-skin-card[aria-pressed=true]').length === 1`);
  await evaluate(`${importButton}.click()`);
  await waitFor(`!document.querySelector('.iso-scan-modal')`);
  assert.deepEqual(importRequests.at(-1).keys, ['fox-Gr']);
  checks.push('only selected skins are imported before returning to vault');

  await review();
  importReply = { imported: 1, total_selected: 2, errors: [{ key: 'fox-Gr', error: 'Unreadable costume' }] };
  await captureSounds();
  await evaluate(`${importButton}.click()`);
  await waitFor(`!!document.querySelector('.iso-import-outcome')`);
  assert.match(await evaluate(`document.querySelector('.iso-import-outcome').textContent`), /1 character skin saved to vault/);
  assert.match(await evaluate(`document.querySelector('.iso-result-errors').textContent`), /Fox PlFxGr: Unreadable costume/);
  assert.equal(await evaluate(`document.querySelectorAll('.iso-added-cards:not(.iso-vault-cards) img').length`), 2);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.iso-report-footer button')].map(b => b.textContent.trim())`), ['Close']);
  assert.equal(await evaluate('window.refreshCalls'), 1);
  assert.deepEqual(await evaluate('window.cues'), ['/vanilla/sounds/start.wav', '/vanilla/sounds/error.wav']);
  checks.push('partial import retains portraits and named failures with an error cue and refreshed vault');

  await review();
  importStatus = 503; importReply = { error: 'Connection interrupted' };
  await evaluate(`${importButton}.click()`);
  await waitFor(`!!document.querySelector('.iso-import-outcome')`);
  assert.equal(await evaluate(`document.querySelector('.iso-import-outcome').textContent`), 'Import not confirmed');
  assert.match(await evaluate(`document.querySelector('.iso-result-errors').textContent`), /Connection interrupted/);
  assert.equal(await evaluate('window.refreshCalls'), 1);
  assert.equal(await evaluate(`document.body.innerText.includes('Scan failed')`), false);
  checks.push('failed import request is not a successful empty result or a mislabeled scan error');

  await review();
  importStatus = 200; importReply = {};
  await evaluate(`${importButton}.click()`);
  await waitFor(`document.querySelector('.iso-import-outcome')?.textContent === 'Import not confirmed'`);
  checks.push('malformed import response never reports success or dismisses results');

  await review();
  importReply = { imported: 2, total_selected: 2, errors: [] };
  await evaluate(`window.rejectRefresh = true; ${importButton}.click()`);
  await waitFor(`document.querySelector('.iso-scan-warning')?.textContent === 'Could not refresh the vault.'`);
  assert.equal(await evaluate(`document.querySelector('.iso-import-outcome').textContent`), '2 character skins saved to vault');
  const savedRequests = importRequests.length;
  await evaluate(`window.rejectRefresh = false; ${importButton}.click()`);
  await waitFor(`!document.querySelector('.iso-scan-modal')`);
  assert.equal(await evaluate('window.refreshCalls'), 2);
  assert.equal(importRequests.length, savedRequests);
  checks.push('refresh failure preserves confirmed saves; Refresh vault retries without another import');

  candidates = {};
  await reload(); await selectFiles([iso]);
  await waitFor(`!!document.querySelector('.iso-scan-file-name')`);
  await evaluate(`[...document.querySelectorAll('.iso-scan-targets label')].find(label => label.textContent.trim() === 'Custom characters').querySelector('input').click()`);
  await startAndComplete([iso]); await captureSounds();
  assert.equal(await evaluate(`${importButton}.textContent.trim()`), 'Done');
  await evaluate(`${importButton}.click()`);
  await waitFor(`!document.querySelector('.iso-scan-modal')`);
  assert.deepEqual(await evaluate('window.cues'), ['/vanilla/sounds/start.wav']);
  checks.push('already-saved custom content uses one Done confirmation and closes');
  finish();
}).catch(finish);
