'use strict';

const path = require('node:path');
const fs = require('node:fs');

// Both normal startup and offline storage maintenance must use this launcher.
function backendLaunch({ isDev, appRoot, resourcesPath, platform = process.platform, exists = fs.existsSync }) {
  const entry = isDev ? path.join(appRoot, 'backend', 'app.py')
    : path.join(resourcesPath, 'backend', platform === 'win32' ? 'mex_backend.exe' : 'mex_backend');
  if (!exists(entry)) throw new Error(`Backend file not found: ${entry}`);
  const command = isDev ? path.join(appRoot, 'venv', ...(platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python'])) : entry;
  if (!exists(command)) throw new Error(`Backend executable not found: ${command}`);
  return { command, args: isDev ? [entry] : [], cwd: path.dirname(entry) };
}

module.exports = { backendLaunch };
