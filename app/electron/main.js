// Electron main process: composition only. It owns the per-launch secrets, the
// release gates handed to the backend, and the app lifecycle; the pieces live in
// runtime/, storage/, viewers/, protocol/, updates/, shell/ and ipc/ (map in
// docs/dev/ARCHITECTURE.md section 5). preload.js stays beside this file.
const { app, BrowserWindow, ipcMain, dialog, Menu, shell, screen, desktopCapturer, powerMonitor, clipboard, nativeImage, ClipboardItem } = require('electron');
const path = require('path');

// `SSBM Nucleus.exe --mcp`: the user's own AI (Claude Code, Claude Desktop, Codex) starts this as a stdio MCP
// server. It only relays to the running app (starting one if needed), so it runs before the single-instance
// lock, windows, the updater and anything that prints: only JSON-RPC may reach its stdout (mcp/relay.js,
// docs/dev/APP_MCP.md).
if (process.argv.includes('--mcp')) {
  if (process.env.NUCLEUS_USERDATA_DIR) app.setPath('userData', process.env.NUCLEUS_USERDATA_DIR);
  require('./mcp/relay').runElectronRelay({ app });
  return;
}

const crypto = require('crypto');
const mcpDiscovery = require('./mcp/discovery');
const { createBackendRuntime } = require('./runtime/backend');
const { createStorageHost } = require('./storage/storage-host');
const { createAppDolphinCapture } = require('./viewers/app-dolphin-capture');
const { createViewerHost } = require('./viewers/viewer-host');
const { createNucleusProtocol } = require('./protocol/nucleus-protocol');
const { createUpdateMonitor } = require('./updates/update-monitor');
const updater = require('./updates/updater');
const { removeSlippiLoginItem } = require('./shell/login-item');
const { createWindowShell } = require('./shell/window');
const { createExternalLinks } = require('./shell/external-links');
const { createTrustedIpc } = require('./ipc/trust');
const { registerFileIpc } = require('./ipc/files');
const { registerWindowIpc } = require('./ipc/window');
const { registerSystemIpc } = require('./ipc/system');
const { registerStorageIpc } = require('./ipc/storage');
const { registerUpdateIpc } = require('./ipc/updates');
const { registerViewerIpc } = require('./ipc/viewer');
const { registerProtocolIpc } = require('./ipc/protocol');

// Capture harnesses (the trailer repo's capture scripts) set this to run an isolated
// second instance beside a normal session: a separate userData dir scopes
// both the profile and the single-instance lock. Must run before any
// getPath('userData') consumer.
if (process.env.NUCLEUS_USERDATA_DIR) {
  app.setPath('userData', process.env.NUCLEUS_USERDATA_DIR);
}

const backendToken = crypto.randomBytes(32).toString('hex');
// A SECOND secret, for the endpoints that record a decision made in the window
// (build-change approval, the MCP's questions). The backend token is printed to
// the backend's stdout at startup (that is how the test harness picks it up),
// so it cannot tell the window apart from anything else holding it. This one
// goes to the window over IPC and to the backend's environment, and is never
// printed or served.
const uiApprovalKey = crypto.randomBytes(32).toString('hex');
// Shared main-process state. Every module that needs it receives this object
// and reads or writes it here, instead of reaching for another file's globals.
const ctx = {
  mainWindow: null,          // the one app window; shell/window.js sets and clears it
  backendPort: null,         // the port the backend announced; runtime/backend.js sets it
  backendToken,              // per-launch secret the renderer and helpers present
  trustedRendererUrl: null,  // the renderer origin (or index file) IPC and navigation trust
  isQuitting: false,         // a real quit is under way, so the backend's exit is not a crash
};

// Determine if we're in development or production
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
// app/ in a checkout, the asar root when packaged. Modules below electron/ get
// these paths from here rather than walking up from their own __dirname.
const appRoot = path.join(__dirname, '..');
const iconPath = path.join(appRoot, 'frontend', isDev ? 'public' : 'dist', 'icon.png');
const storageHost = createStorageHost({ app, dialog, BrowserWindow, isDev,
  appRoot, resourcesPath: process.resourcesPath });
let storageStartup = false;

const { isTrustedRendererUrl, isTrustedIpcSender, handleTrustedIpc } = createTrustedIpc({ ipcMain, ctx });
const dolphinCapture = createAppDolphinCapture({ desktopCapturer, ctx, isTrustedIpcSender });
const links = createExternalLinks({ shell, isDev });

// Windows toasts show the AppUserModelID's registered name — without this
// they say "electron.app.Electron". Must match build.appId so the installed
// shortcut (which electron-builder stamps with the same id) owns the toasts.
if (process.platform === 'win32') app.setAppUserModelId('com.ssbm.nucleus');

// Release gates: features that are BUILT but not publicly released are
// switched off for packaged builds here, and only here. Dev keeps full
// access. Every gate is default-ON in the backend and off only when its
// variable is exactly '0'.
//
// This list is the electron half of backend/core/gates.py — the table
// there carries the same set, and tests/backend/test_gates.py fails if
// the two drift apart. Add a gate in BOTH places or not at all.
//
// nucleOME itself (NUCLEUS_NUCLEOME) shipped in 0.7.0, the cloud Vault
// (NUCLEUS_VAULT — phone pairing + replay push, the Patreon offer) shipped
// in 0.7.2, and the assistant (NUCLEUS_ASSISTANT — Randall's chat and the app
// MCP) shipped in 0.9.0; all three are deliberately absent: the blueprints
// default to enabled, and premium surfaces still require Patreon entitlement.
// To hold the assistant back for a build again, put NUCLEUS_ASSISTANT back in
// this list AND set packaged_off=True for it in backend/core/gates.py; the
// preview opt-in below then opens it for previewFeatures packages, as it did
// for the 0.9.0 previews.
//
// The feature names in a packaged manifest's previewFeatures: build.bat writes a
// comma-separated string; a list is accepted too. Whole names only, so
// 'display' never opens 'play'. Mirrors backend/core/gates.py preview_features.
function packagedPreviewFeatures(value) {
  const list = typeof value === 'string' ? value.split(',') : Array.isArray(value) ? value : [];
  return new Set(list.filter((f) => typeof f === 'string' && f.trim()).map((f) => f.trim().toLowerCase()));
}

// backendEnvironment() is the backend child's environment; runtime/backend.js
// calls it at spawn time.
function backendEnvironment() {
  const PACKAGED_OFF_GATES = [
    // The Combo Video maker did not ship with nucleOME (unfinished; later
    // update). 404s /api/nucleome/combo-video; the viewer half is
    // COMBO_VIDEO_ENABLED in frontend/src/shared/config/features.js.
    'NUCLEUS_COMBO_VIDEO',
    // Randall (the coach/Analyst) is held back for now. 404s
    // /api/nucleome/coach/*; the viewer half is RANDALL_ENABLED in
    // frontend/src/shared/config/features.js (tab hidden, CoachPage chunk elided).
    'NUCLEUS_RANDALL',
    // Unlocked ships in Windows stable builds since 0.10.0. build.bat writes
    // releaseFeatures=play from the gate in backend/core/gates.py. A local Play
    // test build opens it through previewFeatures=play. With the gate closed,
    // /api/play/* returns 404 and the frontend omits Unlocked from the mode cycle.
    'NUCLEUS_PLAY',
    // Randall downloading ANY published mod (file_type 'other'). The three
    // published export types still download; everything else points at the
    // website's own download button. Held while the 2026-09-22 archive
    // security work is reviewed -- and NOT opened with the assistant, which
    // is why it is not in the exception list below.
    'NUCLEUS_ANY_MOD_DOWNLOAD',
    // Writing a prepared menu + code change INTO a managed build. Held while
    // the 2026-09-22 build-transaction review is closed out; with it at '0'
    // nucleus_api.builds.commit_change refuses before taking a lock and the
    // approval endpoint refuses to mint an authorization at all.
    'NUCLEUS_BUILD_COMMIT',
    // The three write paths behind the assistant. Every package opens the
    // assistant SURFACE (since 0.9.0; the coach stays off); these stay '0' in
    // every package, preview included, so nothing it does can commit into a
    // managed build, overwrite the file someone boots, or send a wish off
    // the machine. See docs/dev/PREVIEW-0.9.0.md.
    'NUCLEUS_BUILD_COMMIT',
    'NUCLEUS_DELIVERY',
    'NUCLEUS_WISH_SUBMIT',
  ];
  const backendEnv = { ...process.env };
  // The Python backend has no version of its own — hand it ours so
  // diagnostics.txt and bug reports carry the real app version.
  backendEnv.NUCLEUS_APP_VERSION = app.getVersion();
  backendEnv.NUCLEUS_BACKEND_TOKEN = backendToken;
  backendEnv.NUCLEUS_UI_APPROVAL_KEY = uiApprovalKey;
  if (!isDev) {
    // Explicitly marked preview packages open these gates, each by its own feature
    // name in the packaged manifest's previewFeatures (build.bat writes it from
    // NUCLEUS_PREVIEW_FEATURES; the tree's package.json never has it). The
    // assistant when it is held back (since 0.9.0 it is not in the list above, so
    // that entry changes nothing); Play for a local Play test build, which
    // build.bat packages only with a prerelease version. Mirrors
    // backend/core/gates.py PREVIEW_OPENS; test_preview_policy.py keeps them equal.
    // releaseFeatures is the stable half: build.bat writes it from gates.py
    // release_features() (Play on Windows since 0.10.0).
    const PREVIEW_OPENS = {
      NUCLEUS_ASSISTANT: 'assistant',
      NUCLEUS_PLAY: 'play',
    };
    const packaged = require('../package.json');
    const previewFeatures = packagedPreviewFeatures(packaged.previewFeatures);
    const releaseFeatures = packagedPreviewFeatures(packaged.releaseFeatures);
    for (const gate of PACKAGED_OFF_GATES) {
      // Everything else stays shut: the Tracker coach (NUCLEUS_RANDALL) and the
      // write paths are off in every package, preview included.
      const feature = PREVIEW_OPENS[gate];
      backendEnv[gate] = previewFeatures.has(feature) || releaseFeatures.has(feature) ? '1' : '0';
    }
    // Vault store: shipped builds default to the SQLite backend (migrated from
    // metadata.json on first launch, with a backup + round-trip validation and
    // JSON fallback on failure). Dual-write keeps metadata.json in sync as a
    // live rollback backup. Dev stays on JSON unless NUCLEUS_VAULT_DB=1 is set.
    // See docs/dev/VAULT_SQLITE_MIGRATION.md. Revert by setting NUCLEUS_VAULT_DB=0.
    if (backendEnv.NUCLEUS_VAULT_DB === undefined) {
      backendEnv.NUCLEUS_VAULT_DB = '1';
    }
  }

  return backendEnv;
}

// --- the Flask backend (runtime/backend.js) ----------------------------------
const backend = createBackendRuntime({
  app, dialog, clipboard, ctx, isDev, appRoot, resourcesPath: process.resourcesPath,
  environment: backendEnvironment,
  secrets: [backendToken, uiApprovalKey],
  // The backend died while the app runs: every screen would fail or spin, so
  // the window shows one "backend stopped" screen instead.
  onExit: (exit) => {
    if (ctx.mainWindow && !ctx.mainWindow.isDestroyed())
      ctx.mainWindow.webContents.send('backend:exited', exit);
  },
});

// --- in-app updater (updates/) -----------------------------------------------
// Startup, Settings and wake/focus checks share one request and cached result.
const updateMonitor = createUpdateMonitor({
  check: () => updater.check(),
  notify: update => {
    if (ctx.mainWindow && !ctx.mainWindow.isDestroyed())
      ctx.mainWindow.webContents.send('update:available', update);
  }
});
app.on('will-quit', () => updateMonitor.stop());

// --- quitting ----------------------------------------------------------------
// Closing the window quits Nucleus; nothing keeps it running in the background.
// Registered before the backend's before-quit below, which may clear it again.
app.on('before-quit', () => { ctx.isQuitting = true; });

// --- the login item left by Friends' Slippi switch (shell/login-item.js) ------
app.whenReady().then(() => removeSlippiLoginItem({ app, isDev }));

// --- viewer, nucleus:// links, the window ------------------------------------
const viewerHost = createViewerHost({ ctx });
const protocol = createNucleusProtocol({ app, ctx, isDev, iconPath });
const windowShell = createWindowShell({
  BrowserWindow, Menu, screen, ctx, isDev, appRoot,
  preloadPath: path.join(__dirname, 'preload.js'),
  iconPath,
  // Only the port goes on the renderer's command line. The two secrets go over
  // IPC ('renderer:secrets' below): a command line is readable by every local
  // user on Linux (security review 11-19, L1).
  rendererArguments: () => [
    `--backend-port=${ctx.backendPort || 5000}`,
  ],
  isTrustedRendererUrl, links, protocolHandoffs: protocol.handoffs, viewerHost, dolphinCapture,
});

// --- IPC (ipc/) --------------------------------------------------------------
// The window's backend token and approval key, asked for synchronously by
// preload.js as the page loads. Only the app's own page gets an answer.
ipcMain.on('renderer:secrets', (event) => {
  if (!isTrustedIpcSender(event)) {
    console.warn(`[Security] Refused renderer secrets to ${event?.senderFrame?.url || 'unknown origin'}`);
    event.returnValue = null;
    return;
  }
  event.returnValue = { backendToken, uiApprovalKey };
});
registerSystemIpc({ handleTrustedIpc, app, backend, clipboard, nativeImage, ClipboardItem, appRoot });
registerFileIpc({ handleTrustedIpc, dialog, shell, ctx, links });
registerWindowIpc({ handleTrustedIpc, app, ctx });
registerUpdateIpc({ handleTrustedIpc, app, ctx, updater, updateMonitor });
registerStorageIpc({ handleTrustedIpc, ctx, storageHost });
registerViewerIpc({ ipcMain, handleTrustedIpc, ctx, isDev, viewerHost, dolphinCapture });
registerProtocolIpc({ handleTrustedIpc, handoffs: protocol.handoffs });

// nucleus:// registration and macOS open-url, then the single-instance lock: a
// second launch focuses this one and forwards its nucleus:// URL.
protocol.registerClient();
const gotTheLock = protocol.claimSingleInstance();

// App lifecycle
app.whenReady().then(async () => {
  if (!gotTheLock) return;
  console.log('[Electron] App ready');
  storageStartup = true;
  const storageEnvironment = await storageHost.prepareLaunch();
  if (storageEnvironment === null) {
    storageHost.closeProgress();
    storageStartup = false;
    app.quit();
    return;
  }
  // Native helpers inherit the same scratch drive as the backend. Update
  // installers and relaunches start from the environment we were given.
  updater.setLaunchEnvironment(process.env);
  Object.assign(process.env, storageEnvironment);

  // Claim nucleus:// on Linux; not awaited (protocol/nucleus-protocol.js).
  protocol.registerLinuxHandler();

  // Start Flask backend and wait for port
  try {
    await backend.start();
    console.log(`[Electron] Backend ready on port ${ctx.backendPort}`);
    // Where `--mcp` relays (the user's own AI) find this backend; removed on quit.
    try {
      mcpDiscovery.writeDiscovery(mcpDiscovery.discoveryPath(app.getPath('userData')),
        { port: ctx.backendPort, token: backendToken, pid: process.pid });
    } catch (error) {
      console.error('[Electron] Could not write the MCP discovery file:', error.message);
    }
  } catch (err) {
    // A guessed port gives every screen a misleading network error and can
    // point at an unrelated process. Show the actual startup failure instead.
    await backend.discardFailedStart(err);
    storageHost.closeProgress();
    storageStartup = false;
    try {
      await backend.showStartupFailure(err);
    } finally {
      app.quit();
    }
    return;
  }

  await windowShell.createWindow();
  storageHost.closeProgress();
  storageStartup = false;

  // Passive update check: a dot on the Settings tab + a one-time banner tell
  // the user a release dropped without them clicking "Check for Updates".
  // Delayed so startup I/O settles first; repeated for long-lived sessions.
  // NUCLEUS_NO_UPDATE_CHECK=1 keeps tests/captures quiet.
  if (process.env.NUCLEUS_NO_UPDATE_CHECK !== '1') {
    updateMonitor.start();
    app.on('browser-window-focus', () => updateMonitor.checkIfDue());
    powerMonitor.on('resume', () => updateMonitor.checkIfDue());
  }

  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await windowShell.createWindow();
    }
  });

  // A nucleus:// URL this launch was started with (Windows and Linux argv).
  protocol.handleLaunchArgs();
});

app.on('window-all-closed', () => {
  if (storageStartup) return;
  // On macOS, keep app running unless explicitly quit
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', (event) => {
  if (storageHost.preparing) {
    event.preventDefault();
    ctx.isQuitting = false;
    return;
  }
  console.log('[Electron] Shutting down...');
  backend.stopForQuit(event);
});

// The backend is going away: `--mcp` relays must not find it any more (only this process's own file is removed).
app.on('will-quit', () => {
  mcpDiscovery.removeDiscovery(mcpDiscovery.discoveryPath(app.getPath('userData')), process.pid);
});

// Handle uncaught errors
process.on('uncaughtException', (error) => {
  console.error('[Electron] Uncaught exception:', error);
});
