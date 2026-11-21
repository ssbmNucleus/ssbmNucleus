'use strict';
const path = require('node:path');
const fs = require('node:fs');

function viewerExecutable({ isDev, platform = process.platform,
  appRoot = path.join(__dirname, '..', '..'), resourcesPath = process.resourcesPath,
  exists = fs.existsSync }) {
  if (platform === 'win32') {
    // Dev: the pinned prebuilt from tools/build/fetch_native.py (app/utility/hsdraw/win-x64).
    return isDev ? path.join(appRoot, 'utility', 'hsdraw', 'win-x64', 'HSDRawViewer.exe')
      : path.join(resourcesPath, 'utility', 'HSDRawViewer', 'HSDRawViewer.exe');
  }
  const directory = platform === 'darwin' ? 'hsdraw-mac' : 'hsdraw-linux';
  const rid = platform === 'darwin' ? 'osx-arm64' : 'linux-x64';
  return isDev ? path.join(appRoot, 'utility', 'hsdraw', rid, 'hsdrawviewer')
    : path.join(resourcesPath, 'utility', directory, 'hsdrawviewer');
}

module.exports = { viewerExecutable };
