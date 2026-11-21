'use strict';

// Run with Electron, not Node. This launches only a disposable hidden test
// window and loopback fixture; it never imports main.js or starts Flask.
const { app, BrowserWindow, ipcMain } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..', 'app');  // the app/ folder
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-preload-smoke-'));
app.setPath('userData', profile);
app.setPath('sessionData', profile);
app.disableHardwareAcceleration();
const token = 'synthetic-preload-smoke-token';
const verifiedPaths = [];
let window;
let server;
const timeout = setTimeout(() => finish(new Error('Preload smoke test timed out')), 30000);
let finished = false;

function finish(error) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  if (window && !window.isDestroyed()) window.destroy();
  if (server) server.close();
  if (error) console.error('PRELOAD_SMOKE_FAIL:', error.message);
  else console.log('PRELOAD_SMOKE_PASS: sandbox bridge, native IPC, missing-token rejection, authenticated ISO and Slippi checks');
  // Profile is disposable and its path is reported for exact cleanup after
  // Electron exits and releases Chromium's file handles.
  console.log('PRELOAD_SMOKE_PROFILE:', profile);
  if (process.env.NUCLEUS_PRELOAD_SMOKE_RESULT) {
    fs.writeFileSync(process.env.NUCLEUS_PRELOAD_SMOKE_RESULT, JSON.stringify({
      success: !error, error: error?.message || null, profile, verifiedPaths,
    }, null, 2), { flag: 'wx' });
  }
  app.exit(error ? 1 : 0);
}

app.whenReady().then(async () => {
  const modules = new Map([
    ['/src/shared/transport/api.js', path.join(root, 'frontend/src/shared/transport/api.js')],
    ['/src/shared/config/config.js', path.join(root, 'frontend/src/shared/config/config.js')],
  ]);
  server = http.createServer((req, res) => {
    if (modules.has(req.url)) {
      res.writeHead(200, { 'Content-Type': 'text/javascript' });
      res.end(fs.readFileSync(modules.get(req.url)));
      return;
    }
    if (req.url.startsWith('/api/')) {
      const authenticated = req.headers['x-nucleus-token'] === token;
      res.writeHead(authenticated ? 200 : 401, { 'Content-Type': 'application/json' });
      if (authenticated) verifiedPaths.push(req.url);
      res.end(JSON.stringify(authenticated
        ? { success: true, valid: true }
        : { success: false, error: 'Unauthorized' }));
      return;
    }
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end('<!doctype html><title>Disposable preload test</title>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  // The window's secrets come over IPC, as app/electron/main.js answers them (security L1).
  ipcMain.on('renderer:secrets', (event) => { event.returnValue = { backendToken: token, uiApprovalKey: '' }; });
  ipcMain.handle('select-directory-dialog', () => 'synthetic-directory');
  window = new BrowserWindow({
    show: false,
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      preload: process.env.NUCLEUS_PRELOAD_SMOKE_PATH || path.join(root, 'electron/preload.js'),
      additionalArguments: [`--backend-port=${port}`],
    },
  });
  window.webContents.on('preload-error', (_event, _file, error) => finish(error));
  await window.loadURL(`http://127.0.0.1:${port}/`);
  const result = await window.webContents.executeJavaScript(`(async () => {
    if (!window.electron) throw new Error('Desktop bridge missing');
    const { api } = await import('/src/shared/transport/api.js');
    const unauthenticated = await fetch('/api/mex/verify-iso', { method: 'POST' });
    const iso = await api.post('/verify-iso', { isoPath: 'synthetic.iso' });
    const slippi = await api.post('/settings/slippi-path/verify', { slippiPath: 'synthetic' });
    return {
      port: window.electron.backendPort,
      unauthenticatedStatus: unauthenticated.status,
      isoValid: iso.valid,
      slippiValid: slippi.valid,
      directory: await window.electron.selectDirectory(),
    };
  })()`);
  assert.deepEqual(result, {
    port, unauthenticatedStatus: 401, isoValid: true, slippiValid: true,
    directory: 'synthetic-directory',
  });
  assert.deepEqual(verifiedPaths, ['/api/mex/verify-iso', '/api/mex/settings/slippi-path/verify']);
  finish();
}).catch(finish);
