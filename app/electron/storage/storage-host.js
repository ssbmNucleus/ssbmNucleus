'use strict';

const path = require('node:path');
const { StorageLocationManager, createMigrationRunner, defaultDataRoot } = require('./storage-location');
const { backendLaunch } = require('../runtime/backend-launch');

function createStorageHost({ app, dialog, BrowserWindow, isDev, appRoot, resourcesPath, env = process.env,
  defaultRoot, migrate }) {
  let progressWindow = null;
  let preparing = false;
  let lastProgress = null;
  const override = ['NUCLEUS_STORAGE_DIR', 'NUCLEUS_DATA_ROOT', 'NUCLEUS_USERDATA_DIR'].find(key => env[key]);
  const manager = new StorageLocationManager({
    bootstrapDir: app.getPath('userData'),
    defaultRoot: defaultRoot || env.NUCLEUS_DATA_ROOT || (isDev ? appRoot : defaultDataRoot({ env })),
    disabledReason: isDev ? 'Data relocation is available in the installed app.'
      : override ? `Data relocation is unavailable while ${override} overrides the application profile.` : null,
    migrate: migrate || (options => createMigrationRunner({ ...backendLaunch({ isDev, appRoot, resourcesPath }), env })(options)),
    onProgress: progress => {
      lastProgress = progress;
      if (progressWindow && !progressWindow.isDestroyed()) progressWindow.webContents.send('storage:progress', progress);
    },
  });

  async function openProgress() {
    if (progressWindow && !progressWindow.isDestroyed()) return;
    progressWindow = new BrowserWindow({
      width: 540, height: 240, title: 'Moving Nucleus data', resizable: false,
      minimizable: true, maximizable: false, closable: false, show: false,
      autoHideMenuBar: true,
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true,
        preload: path.join(__dirname, 'storage-progress-preload.js') },
    });
    await progressWindow.loadFile(path.join(__dirname, 'storage-progress.html'));
    if (lastProgress) progressWindow.webContents.send('storage:progress', lastProgress);
    progressWindow.show();
    progressWindow.setProgressBar(2); // Indeterminate while scanning/verifying.
  }

  function closeProgress() {
    if (progressWindow && !progressWindow.isDestroyed()) progressWindow.destroy();
    progressWindow = null;
  }

  async function prepareLaunch() {
    preparing = true;
    try {
      for (;;) {
        try {
          const status = await manager.status();
          if (status.pending?.phase === 'scheduled') await openProgress();
          return await manager.prepareLaunch();
        } catch (error) {
          const status = await manager.status().catch(() => null);
          const recovery = status?.pending ? 'Cancel move and open original'
            : status?.previousRoot ? 'Use previous data folder' : null;
          const interrupted = status?.pending && status.pending.phase !== 'scheduled';
          const buttons = [...(interrupted ? [] : ['Retry']), ...(recovery ? [recovery] : []), 'Quit'];
          const result = await dialog.showMessageBox({
            type: 'error', title: 'Nucleus data is unavailable',
            message: 'Nucleus could not open the selected data location.',
            detail: `${error.message}\n\n` + (interrupted
              ? 'Cancel this move to reopen the original library. You can then schedule a new move to an empty folder. The partial copy is retained.'
              : 'Reconnect the drive or fix the folder access, then retry. No new library will be created elsewhere.')
              + (status?.previousRoot && !status.pending
                ? '\nUsing the previous folder reopens the retained copy; changes made since the move are not merged back.' : ''),
            buttons, defaultId: 0, cancelId: buttons.length - 1, noLink: true,
          });
          if (result.response === buttons.length - 1) return null;
          if (recovery && result.response === buttons.indexOf(recovery)) {
            try { if (status.pending) await manager.cancel(); else await manager.rollback(); }
            catch (recoveryError) { dialog.showErrorBox('Data recovery failed', recoveryError.message); }
          }
        }
      }
    } finally { preparing = false; }
  }

  // These endpoints schedule/cancel only. No active backend is copied or restarted.
  async function invoke(action, value, parent) {
    try {
      if (action === 'choose') {
        const result = await dialog.showOpenDialog(parent, { title: 'Choose the drive or parent folder for Nucleus data',
          properties: ['openDirectory', 'createDirectory'] });
        return { success: true, canceled: result.canceled, path: result.canceled ? null : result.filePaths[0] };
      }
      const result = action === 'schedule' ? await manager.schedule(value)
        : action === 'cancel' ? await manager.cancel() : await manager.status();
      return { success: true, ...result };
    } catch (error) { return { success: false, error: error.message }; }
  }

  return { prepareLaunch, closeProgress, invoke, get preparing() { return preparing; } };
}

module.exports = { createStorageHost };
