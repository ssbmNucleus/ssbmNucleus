'use strict';

// Up to 0.8.15, Friends had an "open Friends when you open Slippi" switch
// (Windows only). Turning it on wrote userData/open-with-slippi.json and
// registered Nucleus as a login item that started it with --minimized.
// Friends has been removed, so at the first packaged start after an update
// this takes the login item away and deletes the file. Without the file it
// does nothing, so the registry is only touched once.
const fs = require('fs');
const path = require('path');

function removeSlippiLoginItem({ app, isDev, platform = process.platform }) {
  if (isDev || platform !== 'win32') return;
  const file = path.join(app.getPath('userData'), 'open-with-slippi.json');
  if (!fs.existsSync(file)) return;
  try {
    app.setLoginItemSettings({ openAtLogin: false, args: ['--minimized'] });
  } catch { /* a registry refusal must not break startup; try again next time */ return; }
  try { fs.unlinkSync(file); } catch { /* removed next start */ }
}

module.exports = { removeSlippiLoginItem };
