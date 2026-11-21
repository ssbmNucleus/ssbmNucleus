const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { viewerExecutable } = require('../../app/electron/viewers/viewer-executable');

test('Windows streaming and fallback use the packaged executable and the fetched development build', () => {
  const options = { platform: 'win32', appRoot: path.resolve('app'), resourcesPath: path.resolve('resources') };
  assert.equal(viewerExecutable(options), path.join(options.resourcesPath, 'utility/HSDRawViewer/HSDRawViewer.exe'));
  assert.equal(viewerExecutable({ ...options, isDev: true }), path.join(options.appRoot, 'utility', 'hsdraw', 'win-x64', 'HSDRawViewer.exe'));
});

test('Linux and Mac resolve their own published renderer for development and packaged launches', () => {
  for (const [platform, directory, rid] of [['linux', 'hsdraw-linux', 'linux-x64'], ['darwin', 'hsdraw-mac', 'osx-arm64']]) {
    const options = { platform, appRoot: path.resolve('app'), resourcesPath: path.resolve('resources') };
    assert.equal(viewerExecutable({ ...options, isDev: true }), path.join(options.appRoot, 'utility', 'hsdraw', rid, 'hsdrawviewer'));
    assert.equal(viewerExecutable(options), path.join(options.resourcesPath, 'utility', directory, 'hsdrawviewer'));
  }
});
