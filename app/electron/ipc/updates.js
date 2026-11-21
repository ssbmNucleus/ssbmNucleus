'use strict';

// The in-app updater as Settings sees it: version, cached status, a check
// shared with the background monitor, and install with progress events.
// The download belongs to main, not to the Settings card: a card that unmounts
// mid-download and mounts again reads `update:install-status` and follows the
// same download instead of offering a second one.
function registerUpdateIpc({ handleTrustedIpc, app, ctx, updater, updateMonitor }) {
  let install = { installing: false, received: 0, total: 0, error: null };
  const send = (channel, payload) => {
    if (ctx.mainWindow && !ctx.mainWindow.isDestroyed()) {
      ctx.mainWindow.webContents.send(channel, payload);
    }
  };

  handleTrustedIpc('update:get-version', () => app.getVersion());

  handleTrustedIpc('update:status', () => updateMonitor.getStatus());

  handleTrustedIpc('update:check', () => updateMonitor.check());

  handleTrustedIpc('update:install-status', () => ({ ...install }));

  handleTrustedIpc('update:install', async () => {
    if (install.installing) return { success: false, error: 'Update already in progress' };
    install = { installing: true, received: 0, total: 0, error: null };
    try {
      await updater.install((received, total) => {
        install = { ...install, received, total };
        send('update:progress', { received, total });
      });
      install = { ...install, installing: false };
      send('update:install-done', { success: true });
      return { success: true };
    } catch (err) {
      console.error('[Updater] Install failed:', err.message);
      install = { installing: false, received: 0, total: 0, error: err.message };
      send('update:install-done', { success: false, error: err.message });
      return { success: false, error: err.message };
    }
  });
}

module.exports = { registerUpdateIpc };
