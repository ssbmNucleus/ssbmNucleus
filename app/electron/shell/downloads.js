'use strict';

// Downloads the renderer starts with a link (a pack, an xdelta, a custom character, a mod file Randall made) go
// through Chromium's own Save As dialog. Left alone, that dialog is titled with the download's URL, and a backend
// URL carries the backend's token. This names the dialog after the file instead and opens it in Downloads.

const path = require('path');

const installed = new WeakSet();

/** `session`: the window's session; `downloadsDir()`: the folder the dialog opens in. Safe to call per window. */
function installDownloadDialog(session, downloadsDir) {
  if (!session || installed.has(session)) return;
  installed.add(session);
  session.on('will-download', (_event, item) => {
    const name = path.basename(String(item.getFilename() || 'download'));
    let defaultPath = name;
    try {
      const dir = downloadsDir();
      if (dir) defaultPath = path.join(dir, name);
    } catch { /* no Downloads folder known: the dialog's own default */ }
    item.setSaveDialogOptions({ title: `Save ${name}`, defaultPath });
  });
}

module.exports = { installDownloadDialog };
