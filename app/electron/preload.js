const { contextBridge, ipcRenderer, webFrame, webUtils } = require('electron');

// This file runs directly in Electron's sandbox: require() cannot load local
// modules. Keep this small helper here so bridge initialization never depends
// on Node's CommonJS loader (including in an unpackaged development launch).
function deliverProtocolEnvelope(ipcRenderer, callback, envelope, logger = console) {
  return Promise.resolve()
    .then(() => callback(envelope.data))
    .then(() => ipcRenderer.invoke('protocol:ack', envelope.id))
    .catch((error) => {
      logger.error('[Protocol] Renderer handoff failed; leaving it queued for reload:', error);
    });
}

// Parse backend port from Electron's additionalArguments
const backendPortArg = process.argv.find(arg => arg.startsWith('--backend-port='));
const backendPort = backendPortArg ? parseInt(backendPortArg.split('=')[1], 10) : 5000;
// The backend token, and a SECOND secret for the endpoints that have to know a
// request came from this window rather than from anything that can reach the
// port (the backend token is printed to stdout at startup; this one is not, and
// is never served). Both come over IPC from the main process, which answers only
// the app's own page; never from the command line, which other local users can
// read on Linux (security review 11-19, L1).
let rendererSecrets = null;
try {
  rendererSecrets = ipcRenderer.sendSync('renderer:secrets');
} catch {
  rendererSecrets = null;
}
const backendToken = typeof rendererSecrets?.backendToken === 'string' ? rendererSecrets.backendToken : '';
const uiApprovalKey = typeof rendererSecrets?.uiApprovalKey === 'string' ? rendererSecrets.uiApprovalKey : '';

// The window has no title bar of its own: the OS draws the window buttons over
// the page's top-right corner and the app header is the drag region. Flagged
// on <html> before first paint so the header reserves that corner (App.css).
if (process.argv.includes('--titlebar-overlay')) {
  const flag = () => document.documentElement.setAttribute('data-titlebar', 'overlay');
  if (document.documentElement) flag();
  else window.addEventListener('DOMContentLoaded', flag, { once: true });
}

// Expose protected methods to the renderer process
contextBridge.exposeInMainWorld('electron', {
  /**
   * The port the Flask backend is running on (dynamic)
   */
  dolphinCapturePrepare: expectedSessionId => ipcRenderer.invoke('dolphin-capture:prepare', expectedSessionId),
  dolphinCaptureCheck: leaseId => ipcRenderer.invoke('dolphin-capture:check', leaseId),
  dolphinCaptureSeparate: leaseId => ipcRenderer.invoke('dolphin-capture:separate', leaseId),
  dolphinCaptureRelease: leaseId => ipcRenderer.invoke('dolphin-capture:release', leaseId),
  backendPort,
  backendToken,
  uiApprovalKey,

  /**
   * Get diagnostics about the bundled backend (startup error, recent stdout/stderr).
   * Used by error UIs to surface the real reason the backend isn't responding.
   * @returns {Promise<{startupError: string|null, output: string[], pid: number|null, alive: boolean, port: number|null, exit: {code: number|null, signal: string|null}|null}>}
   */
  getBackendDiagnostics: () => ipcRenderer.invoke('backend-diagnostics'),

  /**
   * Listen for the backend dying after startup (not during a quit).
   * @param {function} callback Called with {code, signal}
   * @returns {function} Cleanup function to remove listener
   */
  onBackendExited: (callback) => {
    const listener = (_event, data) => callback(data);
    ipcRenderer.on('backend:exited', listener);
    return () => ipcRenderer.removeListener('backend:exited', listener);
  },

  /** Quit and start Nucleus again (the backend-stopped screen's Restart). */
  relaunchApp: () => ipcRenderer.invoke('app:relaunch'),

  /**
   * Open a native file picker dialog to select a .mexproj file
   * @returns {Promise<string|null>} Full file path or null if canceled
   */
  openProjectDialog: () => ipcRenderer.invoke('open-project-dialog'),

  /**
   * Open a native file picker dialog to select a vanilla Melee ISO
   * @returns {Promise<string|null>} Full file path or null if canceled
   */
  openIsoDialog: () => ipcRenderer.invoke('open-iso-dialog'),

  /**
   * Open a multi-select ISO picker for batch scanning.
   * @returns {Promise<string[]>} Array of absolute file paths (empty if canceled)
   */
  openIsoMultiDialog: () => ipcRenderer.invoke('open-iso-multi-dialog'),

  // File.path was removed in Electron 32. Resolve selected/dropped files in
  // the sandbox preload, where Electron's supported webUtils API is available.
  getPathForFile: (file) => webUtils.getPathForFile(file),

  /**
   * Open a native save dialog for an exported ISO.
   * @param {string} defaultName Suggested filename (e.g. "MyBuild.iso")
   * @returns {Promise<string|null>} Chosen destination path or null if canceled
   */
  saveIsoDialog: (defaultName) => ipcRenderer.invoke('save-iso-dialog', defaultName),

  /**
   * Open the native save dialog for Settings > Export Vault (titled "Export Vault",
   * suggesting SSBM-Nucleus-Vault-<date>.zip).
   * @returns {Promise<string|null>} Chosen destination path or null if canceled
   */
  saveVaultBackupDialog: () => ipcRenderer.invoke('save-vault-backup-dialog'),

  /**
   * Open a native directory picker dialog
   * @returns {Promise<string|null>} Full directory path or null if canceled
   */
  selectDirectory: () => ipcRenderer.invoke('select-directory-dialog'),

  getStorageLocation: () => ipcRenderer.invoke('storage:status'),
  chooseStorageLocation: () => ipcRenderer.invoke('storage:choose'),
  scheduleStorageLocation: (destination) => ipcRenderer.invoke('storage:schedule', destination),
  cancelStorageLocation: () => ipcRenderer.invoke('storage:cancel'),

  /**
   * Open the containing folder for a project path.
   * @param {string} projectPath
   * @returns {Promise<{success: boolean, path?: string, error?: string}>}
   */
  openProjectFolder: (projectPath) => ipcRenderer.invoke('open-project-folder', projectPath),

  /**
   * Check if running in Electron
   * @returns {boolean} Always returns true
   */
  isElectron: true,

  /**
   * Open a URL in the system browser
   * @param {string} url
   * @returns {Promise<{success: boolean, error?: string}>}
   */
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  // ============================================
  // In-app updater
  // ============================================

  /**
   * Get the running app version (package.json version)
   * @returns {Promise<string>}
   */
  getAppVersion: () => ipcRenderer.invoke('update:get-version'),

  /**
   * Current page zoom factor (resolution-adaptive scaling set by main).
   * Embed positioning needs it to convert CSS px to physical px correctly.
   * @returns {number}
   */
  getZoomFactor: () => webFrame.getZoomFactor(),

  /**
   * Check the release server for a newer version.
   * @returns {Promise<{success: boolean, update?: {version, notes, url, size}|null, error?: string}>}
   */
  checkForUpdate: () => ipcRenderer.invoke('update:check'),

  /**
   * Result of the last update check (background or manual) without hitting
   * the network. `update` is null when up to date or never checked.
   * @returns {Promise<{update: object|null, checkedAt: number|null, error: string|null}>}
   */
  getUpdateStatus: () => ipcRenderer.invoke('update:status'),

  /**
   * Listen for successful manual or background update checks.
   * @param {function} callback Called with {version, notes, url, size}, or null when up to date
   * @returns {function} Cleanup function to remove listener
   */
  onUpdateAvailable: (callback) => {
    const listener = (event, data) => callback(data);
    ipcRenderer.on('update:available', listener);
    return () => ipcRenderer.removeListener('update:available', listener);
  },

  /**
   * System snapshot (electron/node/chrome versions, OS, arch, packaged flag)
   * bundled into bug reports.
   * @returns {Promise<object>}
   */
  getElectronDiagnostics: () => ipcRenderer.invoke('diag:get'),

  /**
   * How to start this app as a stdio MCP server for the user's own AI
   * (Settings > "Connect your own AI (MCP)").
   * @returns {Promise<{command: string, args: string[]}>}
   */
  getMcpLaunch: () => ipcRenderer.invoke('mcp:launch'),

  /**
   * Download the available update, verify it, launch the installer, and quit.
   * @returns {Promise<{success: boolean, error?: string}>}
   */
  installUpdate: () => ipcRenderer.invoke('update:install'),

  /**
   * The download main is running, if any (it outlives the Settings card).
   * @returns {Promise<{installing: boolean, received: number, total: number, error: string|null}>}
   */
  getUpdateInstallStatus: () => ipcRenderer.invoke('update:install-status'),

  /**
   * Listen for the end of an update download (any card's).
   * @param {function} callback Called with {success, error?}
   * @returns {function} Cleanup function to remove listener
   */
  onUpdateInstallDone: (callback) => {
    const listener = (event, data) => callback(data);
    ipcRenderer.on('update:install-done', listener);
    return () => ipcRenderer.removeListener('update:install-done', listener);
  },

  /**
   * Listen for update download progress
   * @param {function} callback Called with {received, total} in bytes
   * @returns {function} Cleanup function to remove listener
   */
  onUpdateProgress: (callback) => {
    const listener = (event, data) => callback(data);
    ipcRenderer.on('update:progress', listener);
    return () => ipcRenderer.removeListener('update:progress', listener);
  },

  /**
   * Listen for nucleus:// protocol imports
   * @param {function} callback Function called with {url, name} when import is triggered
   * @returns {function} Cleanup function to remove listener
   */
  onNucleusImport: (callback) => {
    const listener = (_event, envelope) =>
      deliverProtocolEnvelope(ipcRenderer, callback, envelope);
    ipcRenderer.on('nucleus-import', listener);
    // Return cleanup function
    return () => ipcRenderer.removeListener('nucleus-import', listener);
  },

  /**
   * Listen for the Patreon OAuth handoff (nucleus://patreon-link deep link)
   * @param {function} callback Called with {token, active, name}
   * @returns {function} Cleanup function to remove listener
   */
  onNucleusPatreon: (callback) => {
    const listener = (_event, envelope) =>
      deliverProtocolEnvelope(ipcRenderer, callback, envelope);
    ipcRenderer.on('nucleus-patreon', listener);
    return () => ipcRenderer.removeListener('nucleus-patreon', listener);
  },

  protocolRendererReady: () => ipcRenderer.invoke('protocol:renderer-ready'),

  copyImage: bytes => ipcRenderer.invoke('clipboard:write-image', bytes),

  // ============================================
  // Embedded Viewer API (Named Pipe IPC)
  // ============================================

  /**
   * Start the embedded 3D viewer
   * @param {Object} options
   * @param {string} options.datFile - Path to the DAT file
   * @param {string} [options.sceneFile] - Optional scene configuration
   * @param {string} [options.ajFile] - Optional animation archive
   * @param {string} [options.logsPath] - Optional logs directory
   * @returns {Promise<{pipeName: string, hwnd: number, connected: boolean}>}
   */
  viewerStart: (options) => ipcRenderer.invoke('viewer:start', options),

  /**
   * Stop the embedded viewer
   */
  viewerStop: (viewerSessionId) => ipcRenderer.invoke('viewer:stop', viewerSessionId),

  /**
   * Whether this session is still the running, connected viewer (another view's start replaces it)
   */
  viewerRunning: (viewerSessionId) => ipcRenderer.invoke('viewer:running', viewerSessionId),

  /**
   * Send a raw message to the viewer
   * @param {Object} message - Message object to send
   */
  viewerSend: (message) => ipcRenderer.invoke('viewer:send', message),

  /**
   * Send camera update to viewer
   */
  viewerCamera: (deltaRotX, deltaRotY, deltaZoom, deltaX, deltaY) =>
    ipcRenderer.invoke('viewer:camera', deltaRotX, deltaRotY, deltaZoom, deltaX, deltaY),

  /**
   * Request animation list from viewer
   */
  viewerGetAnimList: () => ipcRenderer.invoke('viewer:getAnimList'),

  /**
   * Load animation by symbol name
   */
  viewerLoadAnim: (symbol) => ipcRenderer.invoke('viewer:loadAnim', symbol),

  /**
   * Toggle animation playback
   */
  viewerAnimToggle: () => ipcRenderer.invoke('viewer:animToggle'),

  /**
   * Pause animation playback
   */
  viewerAnimPause: () => ipcRenderer.invoke('viewer:animPause'),

  /**
   * Set animation frame
   */
  viewerAnimSetFrame: (frame) => ipcRenderer.invoke('viewer:animSetFrame', frame),

  /**
   * Resize/reposition the viewer window
   */
  viewerResize: (x, y, width, height) => ipcRenderer.invoke('viewer:resize', x, y, width, height),

  /**
   * Show the viewer window
   */
  viewerShow: () => ipcRenderer.invoke('viewer:show'),

  /**
   * Hide the viewer window
   */
  viewerHide: () => ipcRenderer.invoke('viewer:hide'),

  /**
   * Set CSP mode (enables special camera for character select portraits)
   */
  viewerSetCspMode: (enabled) => ipcRenderer.invoke('viewer:setCspMode', enabled),

  /**
   * Set grid visibility
   */
  viewerSetGrid: (enabled) => ipcRenderer.invoke('viewer:setGrid', enabled),

  /**
   * Set background visibility
   */
  viewerSetBackground: (enabled) => ipcRenderer.invoke('viewer:setBackground', enabled),

  /**
   * Export current scene settings (camera, frame, animation)
   */
  viewerExportScene: () => ipcRenderer.invoke('viewer:exportScene'),

  /**
   * Listen for messages from the viewer
   * @param {function} callback Function called with message data
   * @returns {function} Cleanup function to remove listener
   *
   * Nothing is logged here: the viewer sends a message for every frame and state tick, and logging each one put
   * 1,405 lines in one session's console (0.9.0 smoke test). The renderer reports what it makes of them.
   */
  onViewerMessage: (callback) => {
    const listener = (event, data) => callback(data);
    ipcRenderer.on('viewer:message', listener);
    return () => ipcRenderer.removeListener('viewer:message', listener);
  },

  /**
   * Listen for JPEG frames composed inside the app on every platform.
   * @param {function} callback Called with JPEG bytes and session/frame metadata;
   * acknowledge an owned frame after decoding/drawing or discarding it.
   * @returns {function} Cleanup function to remove listener
   */
  onViewerFrame: (callback) => {
    const listener = (_event, frame, metadata) => callback(frame, metadata);
    ipcRenderer.on('viewer:frame', listener);
    return () => ipcRenderer.removeListener('viewer:frame', listener);
  },
  viewerFrameConsumed: (metadata) => ipcRenderer.invoke('viewer:frame-consumed', metadata)
});

// Log that preload script loaded successfully
console.log('[Preload] Electron API bridge initialized');
