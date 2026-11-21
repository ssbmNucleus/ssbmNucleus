'use strict';

// The path that starts the app again after it quits (app/electron/shell/stable-executable.js): the MCP setup
// snippet, the relay's auto-launch and the Linux desktop entry. 0.9.0 build 3 Linux smoke: the snippet named the
// AppImage's FUSE mount (/tmp/.mount_SSBM NP5P1cd/ssbm-nucleus), which is gone when the app quits.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');

const { stableExecutable } = require('../../app/electron/shell/stable-executable');

const MOUNT = '/tmp/.mount_SSBM NP5P1cd';
const IMAGE = '/home/tester/Apps/SSBM Nucleus-0.9.0.AppImage';
const MAC = '/Applications/SSBM Nucleus.app/Contents/MacOS/SSBM Nucleus';

function asPlatform(platform, fn) {
  const original = Object.getOwnPropertyDescriptor(process, 'platform');
  Object.defineProperty(process, 'platform', { value: platform, configurable: true });
  try {
    return fn();
  } finally {
    Object.defineProperty(process, 'platform', original);
  }
}

function withEnv(vars, fn) {
  const saved = {};
  for (const [key, value] of Object.entries(vars)) {
    saved[key] = process.env[key];
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  try {
    return fn();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

test('inside an AppImage it is the image file, never the mount', () => {
  const execPath = `${MOUNT}/ssbm-nucleus`;
  assert.equal(stableExecutable({ platform: 'linux', execPath, env: { APPIMAGE: IMAGE, APPDIR: MOUNT } }), IMAGE);
  assert.equal(stableExecutable({ platform: 'linux', execPath, env: { APPIMAGE: IMAGE } }), IMAGE,
    'a runtime that sets no APPDIR still gives the image');
});

test('outside an AppImage, and on macOS and Windows, it is the executable itself', () => {
  assert.equal(stableExecutable({ platform: 'linux', execPath: '/opt/SSBM Nucleus/ssbm-nucleus', env: {} }),
    '/opt/SSBM Nucleus/ssbm-nucleus', 'a .deb or an unpacked folder is already stable');
  assert.equal(stableExecutable({ platform: 'linux', execPath: '/opt/SSBM Nucleus/ssbm-nucleus',
    env: { APPIMAGE: '/home/u/Terminal.AppImage', APPDIR: '/tmp/.mount_TermXYZ' } }),
  '/opt/SSBM Nucleus/ssbm-nucleus', 'an APPIMAGE inherited from another AppImage is not ours');
  assert.equal(stableExecutable({ platform: 'linux', execPath: `${MOUNT}-other/ssbm-nucleus`,
    env: { APPIMAGE: IMAGE, APPDIR: MOUNT } }), `${MOUNT}-other/ssbm-nucleus`, 'a sibling folder is not inside');
  assert.equal(stableExecutable({ platform: 'darwin', execPath: MAC, env: {} }), MAC,
    'the binary inside the .app bundle');
  assert.equal(stableExecutable({ platform: 'win32', execPath: 'C:\\Program Files\\SSBM Nucleus\\SSBM Nucleus.exe',
    env: { APPIMAGE: IMAGE } }), 'C:\\Program Files\\SSBM Nucleus\\SSBM Nucleus.exe');
});

test('the MCP setup snippet names the AppImage on Linux', () => {
  const { registerSystemIpc } = require('../../app/electron/ipc/system');
  const handlers = {};
  registerSystemIpc({ handleTrustedIpc: (name, handler) => { handlers[name] = handler; }, app: { isPackaged: true } });
  const linux = asPlatform('linux', () => withEnv({ APPIMAGE: IMAGE, APPDIR: undefined }, () => handlers['mcp:launch']()));
  assert.deepEqual(linux, { command: IMAGE, args: ['--mcp'] });
  const windows = asPlatform('win32', () => withEnv({ APPIMAGE: undefined }, () => handlers['mcp:launch']()));
  assert.deepEqual(windows, { command: process.execPath, args: ['--mcp'] });
});

test('the relay starts the app from the AppImage, and runs itself from its own mount', t => {
  const { runElectronRelay } = require('../../app/electron/mcp/relay');
  const saved = { ...console };
  t.after(() => Object.assign(console, saved));    // runElectronRelay sends console output to stderr
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'nucleus-mcp-launch-'));
  t.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
  const app = {
    disableHardwareAcceleration: () => {}, commandLine: { appendSwitch: () => {} }, setPath: () => {},
    getPath: () => path.join(tmp, 'userData'), exit: () => {},
  };
  let spawned;
  asPlatform('linux', () => runElectronRelay({
    app, tmp, env: { APPIMAGE: IMAGE }, spawn: (...args) => { spawned = args; return new EventEmitter(); },
  }));
  const launch = JSON.parse(spawned[2].env.NUCLEUS_MCP_RELAY_LAUNCH);
  assert.equal(launch.command, IMAGE, 'the app it starts outlives this relay');
  assert.equal(spawned[0], process.execPath, 'the relay process itself ends with this one');
});
