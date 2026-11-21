'use strict';

// The window from the renderer's side: the restart button.
function registerWindowIpc({ handleTrustedIpc, app, ctx }) {
  // "Restart" on the backend-stopped screen. The renderer has the backend's
  // port and token baked in at load, so a fresh launch is the honest restart;
  // the new instance starts once this one has exited.
  handleTrustedIpc('app:relaunch', () => {
    ctx.isQuitting = true;
    app.relaunch();
    app.quit();
  });
}

module.exports = { registerWindowIpc };
