const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { createStorageHost } = require('../../app/electron/storage/storage-host');

async function fixture(t, options = {}) {
  const parent = path.resolve(os.tmpdir());
  const root = path.join(parent, `nucleus-storage-host-${crypto.randomUUID()}`);
  await fs.mkdir(root);
  t.after(async () => {
    assert.equal(path.dirname(root), parent);
    assert.ok(path.basename(root).startsWith('nucleus-storage-host-'));
    await fs.rm(root, { recursive: true, force: true });
  });
  const original = path.join(root, 'original');
  await fs.mkdir(original);
  await fs.writeFile(path.join(original, 'fixture.txt'), 'library bytes');
  const events = [];
  const dialogs = [];
  class Window {
    constructor() { events.push('window'); this.dead = false; this.webContents = { send: () => events.push('progress') }; }
    async loadFile() { events.push('loaded'); }
    show() { events.push('shown'); }
    setProgressBar() {}
    isDestroyed() { return this.dead; }
    destroy() { this.dead = true; events.push('destroyed'); }
  }
  const target = path.join(root, 'new data');
  const config = {
    app: { getPath: () => path.join(root, 'profile') },
    dialog: { showMessageBox: async prompt => { dialogs.push(prompt); return { response: prompt.buttons.length - 1 }; },
      showErrorBox: () => {}, showOpenDialog: async () => ({ canceled: false, filePaths: [root] }) },
    BrowserWindow: Window, isDev: false, appRoot: root, resourcesPath: root, env: {}, defaultRoot: original,
    migrate: async ({ source, stage, onProgress }) => {
      events.push('copy');
      onProgress({ phase: 'copying' });
      await fs.cp(source, stage, { recursive: true });
      return { phase: 'verified' };
    }, ...options,
  };
  return { root, original, target, config, host: createStorageHost(config), events, dialogs };
}

test('UI schedules only; a subsequent launch shows progress before copying and returns selected env', async t => {
  const f = await fixture(t);
  await f.host.prepareLaunch();
  const scheduled = await f.host.invoke('schedule', f.target);
  assert.equal(scheduled.success, true);
  assert.equal(scheduled.currentRoot, f.original);
  assert.equal(f.events.includes('copy'), false);
  const cold = createStorageHost(f.config);
  const env = await cold.prepareLaunch();
  assert.equal(env.NUCLEUS_DATA_ROOT, f.target);
  assert.ok(f.events.indexOf('shown') < f.events.indexOf('copy'));
  assert.equal(await fs.readFile(path.join(f.original, 'fixture.txt'), 'utf8'), 'library bytes');
  cold.closeProgress();
  assert.ok(f.events.includes('destroyed'));
});

test('failed move returns no launch environment when user quits, retaining original and pending error', async t => {
  const f = await fixture(t, { migrate: async () => { throw new Error('disk full'); } });
  await f.host.prepareLaunch();
  await f.host.invoke('schedule', f.target);
  assert.equal(await f.host.prepareLaunch(), null);
  const status = await f.host.invoke('status');
  assert.equal(status.currentRoot, f.original);
  assert.equal(status.pending.phase, 'failed');
  assert.ok(f.dialogs[0].buttons.includes('Cancel move and open original'));
  assert.equal(f.dialogs[0].buttons.includes('Retry'), false, 'a retained failed stage cannot be retried in place');
  assert.equal(f.host.preparing, false);
  f.host.closeProgress();
});

test('explicit cancel recovery opens original; cancel alone never launches migration', async t => {
  const f = await fixture(t, { migrate: async () => { throw new Error('disk unavailable'); } });
  f.config.dialog.showMessageBox = async prompt => ({ response: prompt.buttons.indexOf('Cancel move and open original') });
  await f.host.prepareLaunch();
  await f.host.invoke('schedule', f.target);
  assert.equal((await f.host.prepareLaunch()).NUCLEUS_DATA_ROOT, f.original);
  assert.equal((await f.host.invoke('status')).pending, null);
  f.host.closeProgress();
});

test('development cannot schedule a checkout move or set a data override', async t => {
  const f = await fixture(t, { isDev: true });
  assert.deepEqual(await f.host.prepareLaunch(), {});
  const result = await f.host.invoke('schedule', f.target);
  assert.equal(result.success, false);
  assert.match(result.error, /installed app/);
  assert.equal(f.events.includes('copy'), false);
});
