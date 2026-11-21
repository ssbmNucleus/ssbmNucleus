const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  ensureLinuxProtocolHandler,
  DESKTOP_ID,
  buildEntry,
  quoteExec,
} = require('../../app/electron/protocol/linux-protocol');

function asPlatform(platform, fn) {
  const original = Object.getOwnPropertyDescriptor(process, 'platform');
  Object.defineProperty(process, 'platform', { value: platform, configurable: true });
  try {
    return fn();
  } finally {
    Object.defineProperty(process, 'platform', original);
  }
}

const asLinux = fn => asPlatform('linux', fn);

function withEnv(vars, fn) {
  const saved = {};
  for (const [k, v] of Object.entries(vars)) {
    saved[k] = process.env[k];
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  try {
    return fn();
  } finally {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

test('desktop entry claims the nucleus scheme and points at $APPIMAGE', async (t) => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-xdg-'));
  t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
  const appImage = '/home/tester/Apps/SSBM Nucleus.AppImage';

  await asLinux(() => withEnv(
    { XDG_DATA_HOME: dataDir, APPIMAGE: appImage, NUCLEUS_NO_PROTOCOL_REGISTER: undefined },
    () => ensureLinuxProtocolHandler({ isPackaged: true }),
  ));

  const entryPath = path.join(dataDir, 'applications', DESKTOP_ID);
  const entry = fs.readFileSync(entryPath, 'utf8');

  // Without this line no browser can resolve an Add to Nucleus click.
  assert.match(entry, /^MimeType=x-scheme-handler\/nucleus;$/m);
  // The URL has to reach argv, and the target has to survive the AppImage
  // unmounting -- so $APPIMAGE, never the /tmp/.mount_* execPath.
  assert.match(entry, /^Exec="\/home\/tester\/Apps\/SSBM Nucleus\.AppImage" %u$/m);
  assert.ok(!entry.includes('.mount_'));
});

test('re-running rewrites only when the AppImage path changed', async (t) => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-xdg-'));
  t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
  const entryPath = path.join(dataDir, 'applications', DESKTOP_ID);
  const run = (appImage) => asLinux(() => withEnv(
    { XDG_DATA_HOME: dataDir, APPIMAGE: appImage, NUCLEUS_NO_PROTOCOL_REGISTER: undefined },
    () => ensureLinuxProtocolHandler({ isPackaged: true }),
  ));

  await run('/opt/nucleus/old.AppImage');
  const first = fs.statSync(entryPath).mtimeMs;

  await run('/opt/nucleus/old.AppImage');
  assert.equal(fs.statSync(entryPath).mtimeMs, first, 'unchanged launch should not rewrite');

  await run('/opt/nucleus/new.AppImage');
  assert.match(fs.readFileSync(entryPath, 'utf8'), /^Exec=\/opt\/nucleus\/new\.AppImage %u$/m);
});

test('registration is skipped off Linux and in a dev checkout', async (t) => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-xdg-'));
  t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
  const entryPath = path.join(dataDir, 'applications', DESKTOP_ID);

  // Unpackaged: would otherwise register the bare electron binary.
  assert.equal(
    await asLinux(() => withEnv({ XDG_DATA_HOME: dataDir }, () => ensureLinuxProtocolHandler({ isPackaged: false }))),
    false,
  );
  // Windows/macOS have their own registration and must not touch XDG paths.
  for (const platform of ['win32', 'darwin']) {
    assert.equal(
      await asPlatform(platform, () => withEnv(
        { XDG_DATA_HOME: dataDir }, () => ensureLinuxProtocolHandler({ isPackaged: true }),
      )),
      false,
    );
  }
  assert.ok(!fs.existsSync(entryPath));
});

test('Exec quoting escapes only what the desktop-entry spec escapes', () => {
  assert.equal(quoteExec('/opt/nucleus/App.AppImage'), '/opt/nucleus/App.AppImage');
  assert.equal(quoteExec('/opt/my apps/App.AppImage'), '"/opt/my apps/App.AppImage"');
  assert.equal(quoteExec('/opt/a"b/App'), '"/opt/a\\"b/App"');
});

test('Icon= is omitted rather than left dangling when the source is missing', () => {
  const entry = buildEntry('/opt/nucleus/App.AppImage', null);
  assert.ok(!entry.includes('Icon='));
  assert.match(buildEntry('/opt/nucleus/App.AppImage', 'ssbm-nucleus'), /^Icon=ssbm-nucleus$/m);
});
