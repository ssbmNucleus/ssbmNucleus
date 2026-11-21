'use strict';

// The main window: creation, navigation guards, renderer
// load (Vite in development, frontend/dist when packaged), display zoom, and
// the viewer / Dolphin capture cleanup tied to the window's lifetime.
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const ViewerManager = require('../viewers/viewer-manager');
const { installCapturePermissions } = require('../viewers/dolphin-capture');
const { installDownloadDialog } = require('./downloads');

async function getViteDevUrl(appRoot, maxWaitMs = 30000) {
  const portFile = path.join(appRoot, 'frontend', '.vite-port');
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    if (fs.existsSync(portFile)) {
      try {
        const port = parseInt(fs.readFileSync(portFile, 'utf8').trim(), 10);
        if (Number.isInteger(port) && port > 0) {
          return `http://localhost:${port}`;
        }
      } catch (err) {
        // Race with vite writing the file; try again.
      }
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  console.warn(`[Electron] Vite port file not found at ${portFile} after ${maxWaitMs}ms; falling back to localhost:3000`);
  return 'http://localhost:3000';
}

// The UI was designed on a 1440p display (2560 DIP wide). Scale the page so
// it occupies the same proportion of any screen: zoom = display width / 2560
// (OS DPI scaling is already folded into DIP widths, so a 4K monitor at 150%
// also lands on 1.0). Embed positioning (HSDRawViewer / Dolphin) converts
// coordinates zoom-aware in frontend/src/shared/viewer/screenRect.js.
const DESIGN_WIDTH_DIP = 2560;

// Flip to false to disable resolution-adaptive scaling and render at native
// zoom 1.0 on every display (the old fixed-px look).
const ADAPTIVE_ZOOM = false;

// `rendererArguments()` returns the renderer's command-line arguments (the port; secrets go over IPC) at the
// moment the window is created (the backend port is only known by then).
function createWindowShell({
  BrowserWindow, Menu, screen, ctx, isDev, appRoot, preloadPath, iconPath, rendererArguments,
  isTrustedRendererUrl, links, protocolHandoffs, viewerHost, dolphinCapture,
}) {
  const { isAllowedExternalUrl, openExternalSafely } = links;

  function applyDisplayZoom() {
    if (!ctx.mainWindow || ctx.mainWindow.isDestroyed()) return;
    if (!ADAPTIVE_ZOOM) {
      ctx.mainWindow.webContents.setZoomFactor(1);
      return;
    }
    const display = screen.getDisplayMatching(ctx.mainWindow.getBounds());
    const zoom = Math.min(1.6, Math.max(0.65, display.workAreaSize.width / DESIGN_WIDTH_DIP));
    ctx.mainWindow.webContents.setZoomFactor(zoom);
  }

  let zoomMoveTimer = null;

  async function createWindow() {
    const trailerCapture = process.env.NUCLEUS_TRAILER_CAPTURE === '1';
    // Remove the default menu bar
    Menu.setApplicationMenu(null);

    // Fit the display we are opening on. The old fixed 1400x900 default was
    // LARGER than a 1366x768 screen -- one of the commonest laptop panels -- so
    // the window opened oversized, the WM clamped it, and Maximize became a
    // visible no-op because there was nothing bigger to grow into. minHeight 768
    // made it worse: equal to the whole screen height, so once a titlebar and
    // panel were added the window could not fit vertically at all.
    //
    // workAreaSize excludes panels/docks, so this is the space actually usable.
    // Larger displays are unaffected: the min() keeps 1400x900 wherever it fits.
    const workArea = screen.getPrimaryDisplay().workAreaSize;
    const winWidth = Math.min(1400, workArea.width);
    const winHeight = Math.min(900, workArea.height);

    // Windows: no separate title bar. The app header is the title bar (it is
    // the drag region, see App.css) and the OS draws its own minimize /
    // maximize / close buttons over the page's top-right corner, so snap
    // layouts and the close handler below keep working. The renderer learns
    // about it from --titlebar-overlay and reserves that corner. macOS and
    // Linux keep their native frame.
    const overlayTitleBar = process.platform === 'win32' && !trailerCapture;

    ctx.mainWindow = new BrowserWindow({
      width: trailerCapture ? 1920 : winWidth,
      height: trailerCapture ? 1080 : winHeight,
      // Minimums must never exceed what this screen can show, or the window is
      // unresizable-in-practice on small panels.
      minWidth: trailerCapture ? 320 : Math.min(1024, winWidth),
      minHeight: trailerCapture ? 180 : Math.min(700, winHeight),
      frame: !trailerCapture,
      ...(overlayTitleBar ? {
        titleBarStyle: 'hidden',
        titleBarOverlay: { color: 'rgba(0, 0, 0, 0)', symbolColor: '#f5f5f5', height: 40 },
      } : {}),
      useContentSize: trailerCapture,
      backgroundColor: '#0d1929',
      webPreferences: {
        preload: preloadPath,
        contextIsolation: true,
        nodeIntegration: false,
        enableRemoteModule: false,
        sandbox: true,
        additionalArguments: [
          ...rendererArguments(),
          ...(overlayTitleBar ? ['--titlebar-overlay'] : []),
        ],
      },
      icon: iconPath,
    });

    ctx.mainWindow.webContents.setWindowOpenHandler(({ url }) => {
      if (isAllowedExternalUrl(url)) {
        void openExternalSafely(url).catch((err) => {
          console.error('[Security] Failed to open external URL:', err);
        });
      }
      return { action: 'deny' };
    });

    const preventUntrustedNavigation = (event, url) => {
      if (isTrustedRendererUrl(url)) return;
      event.preventDefault();
      if (isAllowedExternalUrl(url)) {
        void openExternalSafely(url).catch((err) => {
          console.error('[Security] Failed to open external URL:', err);
        });
      }
    };
    ctx.mainWindow.webContents.on('will-navigate', preventUntrustedNavigation);
    ctx.mainWindow.webContents.on('will-redirect', preventUntrustedNavigation);
    ctx.mainWindow.webContents.on('did-start-loading', () => protocolHandoffs.rendererGone());

    // Load the app
    if (isDev) {
      // Discover Vite's actual port (it writes frontend/.vite-port on startup).
      const viteUrl = await getViteDevUrl(appRoot);
      ctx.trustedRendererUrl = viteUrl;
      console.log(`[Electron] Loading Vite dev server at ${viteUrl}`);
      ctx.mainWindow.loadURL(viteUrl);
      if (process.env.NUCLEUS_DISABLE_DEVTOOLS !== '1') {
        ctx.mainWindow.webContents.openDevTools();
      }
    } else {
      // In production, load built files
      const indexPath = path.join(appRoot, 'frontend', 'dist', 'index.html');
      ctx.trustedRendererUrl = pathToFileURL(indexPath).toString();
      ctx.mainWindow.loadFile(indexPath);
    }

    // Resolution-adaptive zoom: on load, when dragged to another display, and
    // when a display's metrics change (resolution / DPI switches).
    ctx.mainWindow.webContents.on('did-finish-load', applyDisplayZoom);
    ctx.mainWindow.on('moved', () => {
      clearTimeout(zoomMoveTimer);
      zoomMoveTimer = setTimeout(applyDisplayZoom, 250);
    });
    screen.on('display-metrics-changed', applyDisplayZoom);

    ctx.mainWindow.webContents.on('render-process-gone', () => {
      viewerHost.stop().catch(error => console.error('[Viewer] Cleanup failed:', error.message));
    });
    ctx.mainWindow.webContents.on('did-start-navigation', (_event, _url, inPlace, mainFrame) => {
      if (mainFrame && !inPlace) viewerHost.stop().catch(error => console.error('[Viewer] Cleanup failed:', error.message));
    });
    installCapturePermissions(ctx.mainWindow.webContents.session, dolphinCapture);
    // A link download's Save As dialog is titled with its URL, and a backend URL carries the token.
    installDownloadDialog(ctx.mainWindow.webContents.session, () => require('electron').app.getPath('downloads'));
    ctx.mainWindow.webContents.on('did-start-navigation', (_event, _url, _inPlace, isMainFrame) => {
      if (isMainFrame) dolphinCapture.revoke();
    });
    ctx.mainWindow.webContents.on('render-process-gone', () => dolphinCapture.revoke());

    ctx.mainWindow.on('closed', () => {
      dolphinCapture.revoke();
      viewerHost.stop().catch(error => console.error('[Viewer] Cleanup failed:', error.message));
      protocolHandoffs.rendererGone();
      ctx.mainWindow = null;
    });

    // Track window state for embedded viewer visibility
    ctx.mainWindow.on('minimize', () => {
      if (viewerHost.manager) {
        viewerHost.manager.send({ type: 'hide' });
      }
    });

    ctx.mainWindow.on('restore', () => {
      if (viewerHost.manager instanceof ViewerManager) {
        viewerHost.manager.send({ type: 'show' });
      }
    });

    ctx.mainWindow.on('focus', () => {
      if (viewerHost.manager instanceof ViewerManager) {
        viewerHost.manager.send({ type: 'show' });
      }
    });

    ctx.mainWindow.on('blur', () => {
      // Don't hide on blur - only on minimize
      // This allows clicking other windows without losing the viewer
    });
  }

  return { createWindow };
}

module.exports = { createWindowShell };
