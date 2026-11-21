'use strict';

// The one embedded-viewer session the app runs, wired to the main window:
// helper messages and preview frames go to the renderer. The transport is the
// streaming manager unless NUCLEUS_VIEWER_TRANSPORT=embedded (Windows overlay).
const ViewerManager = require('./viewer-manager');
const StreamViewerManager = require('./stream-viewer-manager');
const { ViewerSession, viewerTransport } = require('./viewer-session');

function createViewerHost({ ctx }) {
  return new ViewerSession({
    createManager: () => viewerTransport() === 'embedded' ? new ViewerManager() : new StreamViewerManager(),
    onMessage: message => {
      if (ctx.mainWindow && !ctx.mainWindow.isDestroyed()) ctx.mainWindow.webContents.send('viewer:message', message);
    },
    onFrame: (buffer, metadata) => {
      if (!ctx.mainWindow || ctx.mainWindow.isDestroyed()) return false;
      ctx.mainWindow.webContents.send('viewer:frame', buffer, metadata);
      return true;
    },
  });
}

module.exports = { createViewerHost };
