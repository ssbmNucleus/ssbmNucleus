const test = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');

function loadUpdater(app) {
  const originalLoad = Module._load;
  const updaterPath = require.resolve('../../app/electron/updates/updater');
  Module._load = function load(request, parent, isMain) {
    if (request === 'electron') return { app, shell: { openPath: async () => '' } };
    return originalLoad.call(this, request, parent, isMain);
  };
  delete require.cache[updaterPath];
  try {
    return require('../../app/electron/updates/updater');
  } finally {
    Module._load = originalLoad;
  }
}

const update = (version, hash = 'a'.repeat(64)) => ({
  version, notes: '', url: `https://releases.ssbmnucleus.net/${version}.exe`,
  sha256: hash, size: 10,
});

const fakeFs = (removed = []) => ({
  mkdtempSync: () => '/mock/update-dir',
  rmSync: (target) => removed.push(target),
  copyFileSync: () => {}, chmodSync: () => {}, renameSync: () => {},
});
// The file on disk is still the one whose checksum passed (the installer is hashed again before it starts).
const unchanged = () => 'a'.repeat(64);

test('install snapshots the selected manifest before awaiting download', async () => {
  const app = { isPackaged: true, getPath: () => '/mock', quit: () => {} };
  const updater = loadUpdater(app);
  const selected = update('1.2.3');
  updater._test.setCachedUpdateForTest(selected);
  let downloaded;
  let tracked;
  await updater.install(null, {
    platform: 'win32', fs: fakeFs(), app, hashFile: unchanged,
    downloadFile: async (url, _dest, size) => {
      downloaded = { url, size };
      updater._test.setCachedUpdateForTest(update('9.9.9', 'b'.repeat(64)));
      await Promise.resolve();
      return { sha256: selected.sha256, size };
    },
    trackCompletedUpdate: async (version) => { tracked = version; },
    spawnDetachedWithRetry: async () => {}, schedule: () => {},
  });
  assert.deepEqual(downloaded, { url: selected.url, size: selected.size });
  assert.equal(tracked, '1.2.3');
});

test('mac openPath error does not schedule quit and cleans download', async () => {
  const quits = [];
  const removed = [];
  const app = { isPackaged: false, getPath: () => '/mock', quit: () => quits.push('quit') };
  const updater = loadUpdater(app);
  await assert.rejects(
    updater._test.installSelected(update('1.2.3'), null, {
      platform: 'darwin', fs: fakeFs(removed), app, hashFile: unchanged,
      downloadFile: async () => ({ sha256: 'a'.repeat(64), size: 10 }),
      shellOpenPath: async () => 'LaunchServices denied the file',
      schedule: (fn) => quits.push(fn),
    }),
    /Could not open downloaded update/
  );
  assert.deepEqual(quits, []);
  assert.deepEqual(removed, ['/mock/update-dir']);
});

test('linux releases the single-instance lock before replacement spawn', async () => {
  const order = [];
  const app = {
    isPackaged: false, getPath: () => '/mock',
    releaseSingleInstanceLock: () => order.push('release'),
    requestSingleInstanceLock: () => order.push('reacquire'),
    quit: () => order.push('quit'),
  };
  const updater = loadUpdater(app);
  await updater._test.installSelected(update('1.2.3'), null, {
    platform: 'linux', appImage: '/apps/Nucleus.AppImage', fs: fakeFs(), app, hashFile: unchanged,
    downloadFile: async () => ({ sha256: 'a'.repeat(64), size: 10 }),
    spawnDetachedOnce: async () => { order.push('spawn'); },
    schedule: (fn, delay) => { order.push(`schedule:${delay}`); fn(); },
  });
  assert.deepEqual(order, ['release', 'spawn', 'schedule:0', 'quit']);
});

test('linux reacquires the lock when replacement spawn fails', async () => {
  const order = [];
  const app = {
    isPackaged: false, getPath: () => '/mock',
    releaseSingleInstanceLock: () => order.push('release'),
    requestSingleInstanceLock: () => order.push('reacquire'),
  };
  const updater = loadUpdater(app);
  await assert.rejects(updater._test.installSelected(update('1.2.3'), null, {
    platform: 'linux', appImage: '/apps/Nucleus.AppImage', fs: fakeFs(), app, hashFile: unchanged,
    downloadFile: async () => ({ sha256: 'a'.repeat(64), size: 10 }),
    spawnDetachedOnce: async () => { order.push('spawn'); throw new Error('denied'); },
    schedule: () => order.push('scheduled'),
  }), /denied/);
  assert.deepEqual(order, ['release', 'spawn', 'reacquire']);
});

test('linux without an AppImage keeps the verified download its message points to', async () => {
  const removed = [];
  const app = { isPackaged: false, getPath: () => '/mock' };
  const updater = loadUpdater(app);
  await assert.rejects(updater._test.installSelected(update('1.2.3'), null, {
    platform: 'linux', appImage: undefined, fs: fakeFs(removed), app,
    downloadFile: async () => ({ sha256: 'a'.repeat(64), size: 10 }),
  }), /download saved to .*replace the app manually/);
  assert.deepEqual(removed, []);
});

test('installers and relaunches start from the launch environment, not the managed root', async () => {
  const app = { isPackaged: false, getPath: () => '/mock' };
  const updater = loadUpdater(app);
  updater.setLaunchEnvironment({ HOME: '/home/tester', APPIMAGE: '/apps/Nucleus.AppImage' });
  const previous = process.env.NUCLEUS_DATA_ROOT;
  process.env.NUCLEUS_DATA_ROOT = '/managed/root';
  try {
    let options;
    const spawnImpl = (_exe, _args, opts) => {
      options = opts;
      const { EventEmitter } = require('node:events');
      const child = new EventEmitter();
      child.unref = () => {};
      process.nextTick(() => child.emit('spawn'));
      return child;
    };
    await updater._test.spawnDetachedWithRetry('/apps/Nucleus.AppImage', [], spawnImpl);
    assert.equal(options.env.NUCLEUS_DATA_ROOT, undefined);
    assert.equal(options.env.HOME, '/home/tester');
    assert.equal(options.detached, true);
  } finally {
    if (previous === undefined) delete process.env.NUCLEUS_DATA_ROOT;
    else process.env.NUCLEUS_DATA_ROOT = previous;
  }
});


test('the saved launch environment is a copy and preserves an explicit user data-root override', async () => {
  const updater = loadUpdater({ isPackaged: false, getPath: () => '/mock' });
  const launch = { NUCLEUS_DATA_ROOT: '/user-selected', APPIMAGE: '/apps/Nucleus.AppImage' };
  updater.setLaunchEnvironment(launch);
  launch.NUCLEUS_DATA_ROOT = '/managed-later';
  let environment;
  const spawn = (_exe, _args, options) => {
    environment = options.env;
    const child = new (require('node:events').EventEmitter)();
    child.unref = () => {};
    queueMicrotask(() => child.emit('spawn'));
    return child;
  };
  await updater._test.spawnDetachedWithRetry('/apps/Nucleus.AppImage', [], spawn);
  assert.equal(environment.NUCLEUS_DATA_ROOT, '/user-selected');
});

test('Linux manual-install fallback never keeps a download that failed verification', async () => {
  const removed = [];
  const app = { isPackaged: false, getPath: () => '/mock' };
  const updater = loadUpdater(app);
  await assert.rejects(updater._test.installSelected(update('1.2.3'), null, {
    platform: 'linux', appImage: undefined, fs: fakeFs(removed), app,
    downloadFile: async () => ({ sha256: 'b'.repeat(64), size: 10 }),
  }), /checksum verification/);
  assert.deepEqual(removed, ['/mock/update-dir']);
});

// Security review 11-22: the checksum was of the bytes as downloaded, and the completed-update report was awaited
// (up to 1.5 s) before the installer started, so a file swapped in that window started unverified.
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

test('a Windows installer that changed after its checksum passed is not started', async () => {
  const good = Buffer.from('the signed installer');
  const sha256 = crypto.createHash('sha256').update(good).digest('hex');
  const app = { isPackaged: true, getPath: () => os.tmpdir(), quit: () => {} };
  const updater = loadUpdater(app);
  let dest;
  const started = [];
  await assert.rejects(updater._test.installSelected({ ...update('1.2.3'), sha256, size: good.length }, null, {
    platform: 'win32', app, schedule: () => {},
    downloadFile: async (_url, destPath) => { dest = destPath; fs.writeFileSync(destPath, good); return { sha256 }; },
    trackCompletedUpdate: async () => { fs.writeFileSync(dest, 'a different program'); },
    spawnDetachedWithRetry: async (file) => { started.push(file); },
  }), /changed after it was verified/);
  assert.deepEqual(started, []);
  assert.equal(fs.existsSync(path.dirname(dest)), false, 'the download folder is removed');
});

test('an unchanged Windows installer starts, and a retry checks it again first', async () => {
  const good = Buffer.from('the signed installer');
  const sha256 = crypto.createHash('sha256').update(good).digest('hex');
  const app = { isPackaged: false, getPath: () => os.tmpdir(), quit: () => {} };
  const updater = loadUpdater(app);
  let dest;
  const calls = [];
  await updater._test.installSelected({ ...update('1.2.3'), sha256, size: good.length }, null, {
    platform: 'win32', app, schedule: () => {},
    downloadFile: async (_url, destPath) => { dest = destPath; fs.writeFileSync(destPath, good); return { sha256 }; },
    spawnDetachedWithRetry: async (file, args, spawnImpl, delays, beforeRetry) => {
      calls.push(file);
      beforeRetry();                                   // a retry of the same, unchanged file passes
      fs.writeFileSync(file, 'a different program');
      assert.throws(beforeRetry, /changed after it was verified/);
    },
  });
  assert.deepEqual(calls, [dest]);
  assert.equal(updater._test.hashFileSync(dest), crypto.createHash('sha256').update('a different program').digest('hex'));
  fs.rmSync(path.dirname(dest), { recursive: true, force: true });
});

test('a busy Windows installer is checked again before each retry', { skip: process.platform !== 'win32' }, async () => {
  const updater = loadUpdater({ isPackaged: false, getPath: () => '/mock' });
  const order = [];
  const busy = () => {
    const child = new (require('node:events').EventEmitter)();
    queueMicrotask(() => child.emit('error', Object.assign(new Error('busy'), { code: 'EBUSY' })));
    return child;
  };
  await assert.rejects(updater._test.spawnDetachedWithRetry('C:/x/update.exe', [], (...a) => {
    order.push('spawn');
    return busy(...a);
  }, [0, 0], () => { order.push('check'); throw new Error('changed after it was verified'); }),
  /changed after it was verified/);
  assert.deepEqual(order, ['spawn', 'check']);
});

test('macOS does not open, and Linux does not install, an update that changed after its checksum', async () => {
  const opened = [];
  const app = { isPackaged: false, getPath: () => '/mock', releaseSingleInstanceLock: () => opened.push('release') };
  const updater = loadUpdater(app);
  const changed = () => 'c'.repeat(64);
  await assert.rejects(updater._test.installSelected(update('1.2.3'), null, {
    platform: 'darwin', fs: fakeFs(), app, hashFile: changed,
    downloadFile: async () => ({ sha256: 'a'.repeat(64), size: 10 }),
    shellOpenPath: async (file) => { opened.push(file); return ''; },
  }), /changed after it was verified/);
  const removed = [];
  const renamed = [];
  const fsLinux = { ...fakeFs(removed), renameSync: (from, to) => renamed.push([from, to]) };
  await assert.rejects(updater._test.installSelected(update('1.2.3'), null, {
    platform: 'linux', appImage: '/apps/Nucleus.AppImage', fs: fsLinux, app,
    hashFile: (file) => (file.endsWith('.new') ? 'c'.repeat(64) : 'a'.repeat(64)),
    downloadFile: async () => ({ sha256: 'a'.repeat(64), size: 10 }),
    spawnDetachedOnce: async () => opened.push('spawn'),
  }), /changed after it was verified/);
  assert.deepEqual(opened, []);
  assert.deepEqual(renamed, [], 'the app is not replaced');
  assert.ok(removed.some((target) => target.endsWith('.Nucleus.AppImage.new')), 'the staged copy is removed');
});
