'use strict';

// File and folder pickers, revealing a project folder, and opening an
// external link in the system browser.
const fs = require('fs');
const path = require('path');

// Settings > Export Vault's suggested file name: SSBM-Nucleus-Vault-2026-11-20.zip (local date).
function vaultBackupName(now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `SSBM-Nucleus-Vault-${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}.zip`;
}

// The folder 'Open project folder' shows for a project path: the path itself when it is a folder, else its parent
// when that is a folder, else none. Never a file: shell.openPath on a file opens it with its program, and on an
// .exe runs it, so a path such as C:\x\tool.exe\missing must not reach it as C:\x\tool.exe. Only an absolute
// local path: a network one (\\host\share, //host/share) would be reached just by looking at it.
function folderToOpen(projectPath, fsImpl = fs) {
  if (!projectPath || typeof projectPath !== 'string' || !path.isAbsolute(projectPath)) return null;
  if (/^[\\/]{2}/.test(projectPath)) return null;
  const isFolder = (candidate) => {
    try { return fsImpl.statSync(candidate).isDirectory(); } catch { return false; }
  };
  if (isFolder(projectPath)) return projectPath;
  const parent = path.dirname(projectPath);
  return parent !== projectPath && isFolder(parent) ? parent : null;
}

function registerFileIpc({ handleTrustedIpc, dialog, shell, ctx, links }) {
  handleTrustedIpc('open-project-dialog', async () => {
    const result = await dialog.showOpenDialog(ctx.mainWindow, {
      properties: ['openFile'],
      filters: [
        { name: 'MEX Project', extensions: ['mexproj'] }
      ],
      title: 'Open MEX Project'
    });

    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }

    return result.filePaths[0];
  });

  handleTrustedIpc('open-iso-dialog', async () => {
    const result = await dialog.showOpenDialog(ctx.mainWindow, {
      properties: ['openFile'],
      filters: [
        { name: 'GameCube ISO', extensions: ['iso', 'gcm'] },
        { name: 'All Files', extensions: ['*'] }
      ],
      title: 'Select Vanilla Melee ISO (v1.02)'
    });

    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }

    return result.filePaths[0];
  });

  handleTrustedIpc('save-iso-dialog', async (event, defaultName) => {
    const result = await dialog.showSaveDialog(ctx.mainWindow, {
      title: 'Save Modded ISO',
      defaultPath: typeof defaultName === 'string' && defaultName ? defaultName : 'game.iso',
      filters: [
        { name: 'GameCube ISO', extensions: ['iso'] },
        { name: 'All Files', extensions: ['*'] }
      ]
    });

    if (result.canceled || !result.filePath) {
      return null;
    }

    return result.filePath;
  });

  // Where Export Vault saves the backup. The backend then writes it there (POST /storage/backup with
  // `destination`), so it never goes through a Chromium download, whose default Save As dialog was titled
  // with the download URL, backend token included. Asked before the backup is made: cancel and nothing is made.
  handleTrustedIpc('save-vault-backup-dialog', async () => {
    const result = await dialog.showSaveDialog(ctx.mainWindow, {
      title: 'Export Vault',
      defaultPath: vaultBackupName(),
      buttonLabel: 'Export',
      filters: [
        { name: 'Vault backup', extensions: ['zip'] }
      ]
    });

    if (result.canceled || !result.filePath) {
      return null;
    }

    return result.filePath;
  });

  handleTrustedIpc('open-iso-multi-dialog', async () => {
    const result = await dialog.showOpenDialog(ctx.mainWindow, {
      properties: ['openFile', 'multiSelections'],
      filters: [
        { name: 'GameCube ISO', extensions: ['iso', 'gcm'] },
        { name: 'All Files', extensions: ['*'] }
      ],
      title: 'Select ISOs to scan for new skins'
    });

    if (result.canceled || result.filePaths.length === 0) {
      return [];
    }

    return result.filePaths;
  });

  handleTrustedIpc('select-directory-dialog', async () => {
    const result = await dialog.showOpenDialog(ctx.mainWindow, {
      properties: ['openDirectory', 'createDirectory'],
      title: 'Select Project Output Directory'
    });

    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }

    return result.filePaths[0];
  });

  handleTrustedIpc('open-project-folder', async (event, projectPath) => {
    if (!projectPath || typeof projectPath !== 'string') {
      return { success: false, error: 'No project path provided' };
    }

    try {
      const targetPath = folderToOpen(projectPath);
      if (!targetPath) {
        return { success: false, error: 'The project folder is not there any more.' };
      }

      const errorMessage = await shell.openPath(targetPath);
      if (errorMessage) {
        return { success: false, error: errorMessage };
      }

      return { success: true, path: targetPath };
    } catch (err) {
      return { success: false, error: err.message };
    }
  });

  handleTrustedIpc('open-external', async (event, url) => {
    return links.openExternalSafely(url);
  });
}

module.exports = { registerFileIpc, vaultBackupName, folderToOpen };
