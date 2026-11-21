'use strict';

// The file dialogs' IPC with a stubbed dialog module: no native dialog ever opens here (they point at real folders).
const test = require('node:test');
const assert = require('node:assert/strict');
const { registerFileIpc, vaultBackupName } = require('../../app/electron/ipc/files');

function setup(reply) {
  const handlers = {};
  const shown = [];
  const mainWindow = { id: 'main' };
  registerFileIpc({
    handleTrustedIpc: (channel, fn) => { handlers[channel] = fn; },
    dialog: {
      showSaveDialog: async (window, options) => { shown.push({ window, options }); return reply; },
      showOpenDialog: async () => ({ canceled: true, filePaths: [] }),
    },
    shell: {},
    ctx: { mainWindow },
    links: {},
  });
  return { handlers, shown, mainWindow };
}

// Tester B8, 0.9.0 build 8: Export Vault was a Chromium download whose Save As dialog was titled with the backend URL,
// its token included.
test('Export Vault asks with its own titled dialog and a dated file name, never a URL', async () => {
  const f = setup({ canceled: false, filePath: 'C:\\Backups\\SSBM-Nucleus-Vault-2026-11-20.zip' });
  assert.equal(await f.handlers['save-vault-backup-dialog']({}), 'C:\\Backups\\SSBM-Nucleus-Vault-2026-11-20.zip');
  assert.equal(f.shown.length, 1);
  const { window, options } = f.shown[0];
  assert.equal(window, f.mainWindow);
  assert.equal(options.title, 'Export Vault');
  assert.match(options.defaultPath, /^SSBM-Nucleus-Vault-\d{4}-\d{2}-\d{2}\.zip$/);
  assert.deepEqual(options.filters, [{ name: 'Vault backup', extensions: ['zip'] }]);
  assert.doesNotMatch(JSON.stringify(options), /token|http|127\.0\.0\.1/i);
});

test('cancelling the Export Vault dialog answers null', async () => {
  assert.equal(await setup({ canceled: true, filePath: '' }).handlers['save-vault-backup-dialog']({}), null);
  assert.equal(await setup({ canceled: false, filePath: '' }).handlers['save-vault-backup-dialog']({}), null);
});

test('the suggested name is the local date', () => {
  assert.equal(vaultBackupName(new Date(2026, 10, 20, 23, 59)), 'SSBM-Nucleus-Vault-2026-11-20.zip');
  assert.equal(vaultBackupName(new Date(2027, 0, 5, 0, 1)), 'SSBM-Nucleus-Vault-2027-01-05.zip');
});
