const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { backendLaunch } = require('../../app/electron/runtime/backend-launch');

for (const platform of ['win32', 'linux', 'darwin']) {
  test(`${platform} packaged maintenance and app share the bundled backend`, () => {
    const spec = backendLaunch({ isDev: false, resourcesPath: '/fixture/resources', platform, exists: () => true });
    assert.equal(spec.command, path.join('/fixture/resources', 'backend', platform === 'win32' ? 'mex_backend.exe' : 'mex_backend'));
    assert.deepEqual(spec.args, []);
    assert.equal(spec.cwd, path.dirname(spec.command));
  });
}
test('development uses its own virtual environment and source entry point', () => {
  const spec = backendLaunch({ isDev: true, appRoot: '/fixture/app', platform: 'win32', exists: () => true });
  assert.equal(spec.command, path.join('/fixture/app', 'venv', 'Scripts', 'python.exe'));
  assert.deepEqual(spec.args, [path.join('/fixture/app', 'backend', 'app.py')]);
});
test('missing backend fails before any maintenance or server launch', () => {
  assert.throws(() => backendLaunch({ isDev: false, resourcesPath: '/missing', exists: () => false }), /Backend file not found/);
});
