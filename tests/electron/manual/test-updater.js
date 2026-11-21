// Quick harness: run updater.check() outside Electron against the live manifest.
//   node tests/electron/manual/test-updater.js [fakeVersion]   (from the repo root)
// A prerelease fakeVersion (e.g. 0.9.0-preview.7) is treated as a test build.
// It polls its secret preview manifest as well as the public one only when
// NUCLEUS_PREVIEW_CHANNEL holds the token, standing in for the packaged
// previewChannel that build.bat bakes into a real test build.
const Module = require('module');
const origLoad = Module._load;
Module._load = function (request, ...rest) {
  if (request === 'electron') {
    return {
      app: {
        getVersion: () => process.argv[2] || '0.2.0',
        getPath: () => require('os').tmpdir(),
        quit: () => console.log('(app.quit called)'),
      },
    };
  }
  if (request === '../../package.json' && process.env.NUCLEUS_PREVIEW_CHANNEL) {
    const manifest = origLoad.apply(this, [request, ...rest]);
    return { ...manifest, previewChannel: process.env.NUCLEUS_PREVIEW_CHANNEL };
  }
  return origLoad.apply(this, [request, ...rest]);
};

const updater = require('../../../app/electron/updates/updater');
updater.check()
  .then((update) => {
    console.log('check() result:', JSON.stringify(update, null, 2));
  })
  .catch((err) => {
    console.error('check() failed:', err.message);
    process.exit(1);
  });
