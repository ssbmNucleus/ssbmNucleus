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

// 'Open project folder' (security review 11-22): a path that does not exist opened its parent whatever that was, and
// shell.openPath on a file runs it, so C:\x\tool.exe\missing ran C:\x\tool.exe.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { folderToOpen } = require('../../app/electron/ipc/files');
const UNC = String.raw`\\host\share\project.mexproj`;

function folderSetup() {
  const handlers = {};
  const opened = [];
  registerFileIpc({
    handleTrustedIpc: (channel, fn) => { handlers[channel] = fn; },
    dialog: {},
    shell: { openPath: async (target) => { opened.push(target); return ''; } },
    ctx: { mainWindow: {} },
    links: {},
  });
  return { open: (p) => handlers['open-project-folder']({}, p), opened };
}

test('Open project folder opens a folder, or the folder a project file or missing file is in', async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-open-folder-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const project = path.join(root, 'project.mexproj');
  fs.writeFileSync(project, '{}');
  const f = folderSetup();
  assert.deepEqual(await f.open(root), { success: true, path: root });
  assert.deepEqual(await f.open(project), { success: true, path: root });
  assert.deepEqual(await f.open(path.join(root, 'gone.mexproj')), { success: true, path: root });
  assert.deepEqual(f.opened, [root, root, root]);
});

test('Open project folder never hands a file to the shell, nor a relative or network path', async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-open-folder-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const tool = path.join(root, 'tool.exe');
  fs.writeFileSync(tool, 'MZ');
  const f = folderSetup();
  for (const asked of [path.join(tool, 'missing'), path.join(root, 'no', 'such', 'project.mexproj'),
    'relative/project.mexproj', UNC, '//host/share/project.mexproj', '', 42]) {
    const reply = await f.open(asked);
    assert.equal(reply.success, false, String(asked));
  }
  assert.deepEqual(f.opened, []);
  const looked = [];
  const recording = { statSync: (p) => { looked.push(p); throw new Error('no'); } };
  assert.equal(folderToOpen(UNC, recording), null);
  assert.equal(folderToOpen('//host/share/p.mexproj', recording), null);
  assert.deepEqual(looked, [], 'a network path is not even looked at');
});
