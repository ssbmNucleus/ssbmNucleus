'use strict';

// The embedded HSDRaw viewer (viewer:*) and Windows Test in Game capture
// (dolphin-capture:*). The capture channels use plain ipcMain.handle: the
// capture host makes its own, stricter check (main window, main frame,
// trusted origin) on every call.
const ViewerManager = require('../viewers/viewer-manager');

function registerViewerIpc({ ipcMain, handleTrustedIpc, ctx, isDev, viewerHost, dolphinCapture }) {
  ipcMain.handle('dolphin-capture:prepare', (event, expectedSessionId) => dolphinCapture.prepare(event, expectedSessionId));
  ipcMain.handle('dolphin-capture:check', (event, leaseId) => dolphinCapture.check(event, leaseId, { present: true }));
  ipcMain.handle('dolphin-capture:separate', (event, leaseId) => dolphinCapture.separate(event, leaseId));
  ipcMain.handle('dolphin-capture:release', (event, leaseId) => dolphinCapture.release(event, leaseId));

  handleTrustedIpc('viewer:start', async (_event, options) => {
    const result = await viewerHost.start({ ...options, isDev });
    const manager = viewerHost.manager;
    // Explicit Windows fallback only; the default preview is composed in canvas.
    if (manager instanceof ViewerManager && manager.viewerSessionId === result.viewerSessionId
        && ctx.mainWindow && !ctx.mainWindow.isDestroyed()) {
      const handle = ctx.mainWindow.getNativeWindowHandle();
      const owner = handle.length >= 8 ? handle.readBigUInt64LE(0) : BigInt(handle.readUInt32LE(0));
      manager.send({ type: 'setParent', hwnd: owner.toString() });
    }
    return result;
  });

  handleTrustedIpc('viewer:stop', (_event, viewerSessionId) => viewerHost.stop(viewerSessionId));
  handleTrustedIpc('viewer:running', (_event, viewerSessionId) => viewerHost.running(viewerSessionId));
  handleTrustedIpc('viewer:frame-consumed', (_event, metadata) => viewerHost.frames.consumed(metadata));

  handleTrustedIpc('viewer:send', async (event, message) => {
    if (viewerHost.manager) {
      return viewerHost.manager.send(message);
    }
    return false;
  });

  handleTrustedIpc('viewer:camera', async (event, deltaRotX, deltaRotY, deltaZoom, deltaX, deltaY) => {
    if (viewerHost.manager) {
      return viewerHost.manager.sendCamera(deltaRotX, deltaRotY, deltaZoom, deltaX, deltaY);
    }
    return false;
  });

  handleTrustedIpc('viewer:getAnimList', async () => {
    if (viewerHost.manager) {
      return viewerHost.manager.getAnimList();
    }
    return false;
  });

  handleTrustedIpc('viewer:loadAnim', async (event, symbol) => {
    if (viewerHost.manager) {
      return viewerHost.manager.loadAnim(symbol);
    }
    return false;
  });

  handleTrustedIpc('viewer:animToggle', async () => {
    if (viewerHost.manager) {
      return viewerHost.manager.animToggle();
    }
    return false;
  });

  handleTrustedIpc('viewer:animPause', async () => {
    if (viewerHost.manager) {
      return viewerHost.manager.animPause();
    }
    return false;
  });

  handleTrustedIpc('viewer:animSetFrame', async (event, frame) => {
    if (viewerHost.manager) {
      return viewerHost.manager.animSetFrame(frame);
    }
    return false;
  });

  handleTrustedIpc('viewer:resize', async (event, x, y, width, height) => {
    if (viewerHost.manager) {
      return viewerHost.manager.resize(x, y, width, height);
    }
    return false;
  });

  handleTrustedIpc('viewer:show', async () => {
    if (viewerHost.manager) {
      return viewerHost.manager.show();
    }
    return false;
  });

  handleTrustedIpc('viewer:hide', async () => {
    if (viewerHost.manager) {
      return viewerHost.manager.hide();
    }
    return false;
  });

  handleTrustedIpc('viewer:setCspMode', async (event, enabled) => {
    console.log('[Electron] setCspMode called with:', enabled);
    if (viewerHost.manager) {
      return viewerHost.manager.setCspMode(enabled);
    }
    return false;
  });

  handleTrustedIpc('viewer:setGrid', async (event, enabled) => {
    console.log('[Electron] setGrid called with:', enabled);
    if (viewerHost.manager) {
      return viewerHost.manager.setGrid(enabled);
    }
    return false;
  });

  handleTrustedIpc('viewer:setBackground', async (event, enabled) => {
    console.log('[Electron] setBackground called with:', enabled);
    if (viewerHost.manager) {
      return viewerHost.manager.setBackground(enabled);
    }
    return false;
  });

  handleTrustedIpc('viewer:exportScene', async () => {
    if (viewerHost.manager) {
      return viewerHost.manager.exportScene();
    }
    throw new Error('Viewer not running');
  });
}

module.exports = { registerViewerIpc };
