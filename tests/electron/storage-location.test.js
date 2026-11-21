'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { StorageLocationManager, createMigrationRunner, MARKER } = require('../../app/electron/storage/storage-location');

// The two "real" tests run the backend's own maintenance entry point, so they need a
// Python with the backend's requirements: NUCLEUS_TEST_PYTHON, else the checkout's
// app/venv (the venv every dev setup and build uses). Skipped only when neither exists.
const VENV = path.resolve(__dirname, '../../app/venv');
const TEST_PYTHON = process.env.NUCLEUS_TEST_PYTHON || [
  path.join(VENV, 'Scripts', 'python.exe'), path.join(VENV, 'bin', 'python'),
].find(candidate => require('node:fs').existsSync(candidate));

async function fixture(t, options = {}) {
  const parent = path.resolve(os.tmpdir());
  const root = path.join(parent, `nucleus-location-test-${crypto.randomUUID()}`);
  await fs.mkdir(root);
  t.after(async () => {
    assert.equal(path.dirname(root), parent);
    assert.ok(path.basename(root).startsWith('nucleus-location-test-'));
    await fs.rm(root, { recursive: true, force: true });
  });
  const source = path.join(root, 'original');
  await fs.mkdir(source);
  await fs.writeFile(path.join(source, 'account.json'), '{"identity":"private-test-account"}');
  const bootstrapDir = path.join(root, 'profile');
  const target = path.join(root, 'D drive with spaces 日本');
  const migrate = async ({ source, stage, onProgress }) => {
    onProgress({ phase: 'copying' });
    await fs.cp(source, stage, { recursive: true, errorOnExist: true });
    return { phase: 'verified', files: 1, bytes: 35 };
  };
  const config = { bootstrapDir, defaultRoot: source, migrate, ...options };
  return { root, source, target, bootstrapDir, config, manager: new StorageLocationManager(config) };
}

test('schedule survives shortcut/protocol style fresh construction; verified selection preserves original', async t => {
  const f = await fixture(t);
  await f.manager.prepareLaunch();
  const before = await fs.readFile(path.join(f.source, 'account.json'));
  await f.manager.schedule(f.target);
  assert.equal((await f.manager.status()).currentRoot, f.source);
  assert.equal(await fs.stat(f.target).catch(() => null), null);
  const cold = new StorageLocationManager(f.config);
  const env = await cold.prepareLaunch();
  assert.equal(env.NUCLEUS_DATA_ROOT, f.target);
  assert.equal(env.TEMP, path.join(f.target, 'scratch'));
  assert.equal(env.TMPDIR, env.TEMP);
  assert.deepEqual(await fs.readFile(path.join(f.source, 'account.json')), before);
  assert.deepEqual(await fs.readFile(path.join(f.target, 'account.json')), before);
  assert.equal((await cold.status()).previousRoot, f.source);
  assert.equal((await new StorageLocationManager(f.config).prepareLaunch()).NUCLEUS_DATA_ROOT, f.target);
});

test('same, nested, ancestor, profile and unrelated nonempty destinations are refused', async t => {
  const f = await fixture(t);
  for (const destination of [f.source, path.join(f.source, 'nested'), f.root, f.bootstrapDir]) {
    await assert.rejects(f.manager.schedule(destination));
  }
  await fs.mkdir(f.target);
  await fs.writeFile(path.join(f.target, 'unrelated'), 'keep');
  await assert.rejects(f.manager.schedule(f.target), /empty/);
  assert.equal(await fs.readFile(path.join(f.target, 'unrelated'), 'utf8'), 'keep');
});

test('migration failure retains active selection, source and partial copy; cancel is explicit', async t => {
  const f = await fixture(t, { migrate: async ({ stage }) => {
    await fs.mkdir(stage);
    await fs.writeFile(path.join(stage, 'partial'), 'partial');
    throw new Error('ENOSPC disk full');
  } });
  await f.manager.prepareLaunch();
  await f.manager.schedule(f.target);
  await assert.rejects(f.manager.prepareLaunch(), /disk full/);
  const status = await f.manager.status();
  assert.equal(status.currentRoot, f.source);
  assert.equal(status.pending.phase, 'failed');
  assert.equal(await fs.readFile(path.join(status.pending.stage, 'partial'), 'utf8'), 'partial');
  await assert.rejects(new StorageLocationManager(f.config).prepareLaunch(), /interrupted or failed/);
  await f.manager.cancel();
  assert.equal((await f.manager.prepareLaunch()).NUCLEUS_DATA_ROOT, f.source);
  assert.ok(await fs.stat(status.pending.stage));
});

test('selected missing drive and replaced library fail without recreating or falling back', async t => {
  const f = await fixture(t);
  await f.manager.prepareLaunch();
  await f.manager.schedule(f.target);
  await f.manager.prepareLaunch();
  const disconnected = path.join(f.root, 'disconnected');
  await fs.rename(f.target, disconnected);
  await assert.rejects(new StorageLocationManager(f.config).prepareLaunch());
  assert.equal(await fs.stat(f.target).catch(() => null), null);
  await fs.mkdir(f.target);
  await fs.writeFile(path.join(f.target, MARKER), JSON.stringify({ identity: 'different' }));
  await assert.rejects(new StorageLocationManager(f.config).prepareLaunch(), /another library/);
});

test('a previously selected default root is not recreated when missing', async t => {
  const f = await fixture(t);
  await f.manager.prepareLaunch();
  await fs.rename(f.source, path.join(f.root, 'missing-source'));
  await assert.rejects(new StorageLocationManager(f.config).prepareLaunch());
  assert.equal(await fs.stat(f.source).catch(() => null), null);
});

test('explicit rollback selects retained original and retains newer data too', async t => {
  const f = await fixture(t);
  await f.manager.prepareLaunch();
  await f.manager.schedule(f.target);
  await f.manager.prepareLaunch();
  await fs.writeFile(path.join(f.target, 'new-data'), 'later');
  await f.manager.rollback();
  assert.equal((await f.manager.prepareLaunch()).NUCLEUS_DATA_ROOT, f.source);
  assert.equal(await fs.readFile(path.join(f.target, 'new-data'), 'utf8'), 'later');
});

test('no success publication without verification and destination change is caught', async t => {
  const f = await fixture(t, { migrate: async ({ stage, target }) => {
    await fs.mkdir(stage);
    await fs.mkdir(target);
    await fs.writeFile(path.join(target, 'other'), 'unrelated');
    return { phase: 'verified' };
  } });
  await f.manager.schedule(f.target);
  await assert.rejects(f.manager.prepareLaunch(), /empty/);
  assert.equal((await f.manager.status()).currentRoot, f.source);
  assert.equal(await fs.readFile(path.join(f.target, 'other'), 'utf8'), 'unrelated');
  const g = await fixture(t, { migrate: async () => ({ phase: 'copying' }) });
  await g.manager.schedule(g.target);
  await assert.rejects(g.manager.prepareLaunch(), /did not verify/);
});

test('copy remains asynchronous and concurrent mutation requests are rejected', async t => {
  let release;
  const f = await fixture(t, { migrate: () => new Promise(resolve => { release = resolve; }) });
  await f.manager.schedule(f.target);
  const launch = f.manager.prepareLaunch();
  while (!release) await new Promise(resolve => setImmediate(resolve));
  assert.equal((await f.manager.status()).busy, true);
  await assert.rejects(f.manager.cancel(), /already running/);
  release({ phase: 'not-verified' });
  await assert.rejects(launch, /did not verify/);
});

test('malformed bootstrap and disabled development do not start migration', async t => {
  const f = await fixture(t);
  await fs.mkdir(f.bootstrapDir);
  await fs.writeFile(path.join(f.bootstrapDir, 'storage-location.json'), '{broken');
  await assert.rejects(f.manager.prepareLaunch());
  const g = await fixture(t, { disabledReason: 'Development checkout' });
  await assert.rejects(g.manager.schedule(g.target), /Development/);
  assert.deepEqual(await g.manager.prepareLaunch(), {});
});

test('linked destination parent is refused', async t => {
  const f = await fixture(t);
  const link = path.join(f.root, 'junction');
  try { await fs.symlink(f.source, link, process.platform === 'win32' ? 'junction' : 'dir'); }
  catch (error) { if (['EPERM', 'EACCES'].includes(error.code)) return t.skip('links unavailable'); throw error; }
  await assert.rejects(f.manager.schedule(path.join(link, 'destination')), /ordinary directory/);
});

test('failed bootstrap publication leaves original selected and verified destination intact', async t => {
  const f = await fixture(t);
  await f.manager.prepareLaunch();
  await f.manager.schedule(f.target);
  const rename = fs.rename;
  t.mock.method(fs, 'rename', async (source, destination) => {
    if (destination === f.manager.file) {
      const pendingWrite = JSON.parse(await fs.readFile(source, 'utf8'));
      if (pendingWrite.active.root === f.target) throw new Error('bootstrap write failure');
    }
    return rename(source, destination);
  });
  await assert.rejects(f.manager.prepareLaunch(), /bootstrap write failure/);
  assert.equal((await new StorageLocationManager(f.config).status()).currentRoot, f.source);
  assert.ok(await fs.stat(path.join(f.target, 'account.json')));
  assert.ok(await fs.stat(path.join(f.source, 'account.json')));
});

test('real maintenance entry point verifies and acknowledges activation without Flask startup',
  { skip: !TEST_PYTHON && 'no Python: set NUCLEUS_TEST_PYTHON or create app/venv' }, async t => {
    const f = await fixture(t, { migrate: createMigrationRunner({
      command: TEST_PYTHON,
      args: [path.resolve(__dirname, '../../app/backend/app.py')],
      env: { ...process.env, NUCLEUS_DATA_ROOT: 'Z:/must-not-be-opened-by-maintenance' },
    }) });
    await f.manager.prepareLaunch();
    await f.manager.schedule(f.target);
    const env = await f.manager.prepareLaunch();
    assert.equal(env.NUCLEUS_DATA_ROOT, f.target);
    assert.equal(await fs.readFile(path.join(f.target, 'account.json'), 'utf8'), '{"identity":"private-test-account"}');
  });

test('real worker failure is actionable and leaves current location selected',
  { skip: !TEST_PYTHON && 'no Python: set NUCLEUS_TEST_PYTHON or create app/venv' }, async t => {
    const f = await fixture(t, { migrate: createMigrationRunner({
      command: TEST_PYTHON,
      args: [path.resolve(__dirname, '../../app/backend/app.py')],
    }) });
    await fs.writeFile(path.join(f.source, 'corrupt.db'), 'not a database');
    await f.manager.schedule(f.target);
    await assert.rejects(f.manager.prepareLaunch(), /invalid SQLite header/);
    assert.equal((await f.manager.status()).currentRoot, f.source);
    assert.equal(await fs.stat(f.target).catch(() => null), null);
  });
