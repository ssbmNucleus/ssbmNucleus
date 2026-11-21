const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { removeSlippiLoginItem } = require('../../app/electron/shell/login-item');

function fakeApp(dir) {
  const calls = [];
  return {
    calls,
    getPath: () => dir,
    setLoginItemSettings: (settings) => calls.push(settings),
  };
}

test('a 0.8.15 Slippi switch loses its login item and its file once', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'login-item-'));
  const file = path.join(dir, 'open-with-slippi.json');
  fs.writeFileSync(file, JSON.stringify({ on: true }));
  const app = fakeApp(dir);
  removeSlippiLoginItem({ app, isDev: false, platform: 'win32' });
  assert.deepEqual(app.calls, [{ openAtLogin: false, args: ['--minimized'] }]);
  assert.equal(fs.existsSync(file), false);
  removeSlippiLoginItem({ app, isDev: false, platform: 'win32' });
  assert.equal(app.calls.length, 1);
});

test('no file, dev, or another platform: the login items are left alone', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'login-item-'));
  const app = fakeApp(dir);
  removeSlippiLoginItem({ app, isDev: false, platform: 'win32' });
  fs.writeFileSync(path.join(dir, 'open-with-slippi.json'), '{"on":true}');
  removeSlippiLoginItem({ app, isDev: true, platform: 'win32' });
  removeSlippiLoginItem({ app, isDev: false, platform: 'linux' });
  assert.deepEqual(app.calls, []);
});
