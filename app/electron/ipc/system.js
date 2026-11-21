'use strict';

const { stableExecutable } = require('../shell/stable-executable');

// Diagnostics for bug reports (backend state, system snapshot), the image
// clipboard, and the command that connects the user's own AI (MCP).
function registerSystemIpc({ handleTrustedIpc, app, backend, clipboard, nativeImage, ClipboardItem, appRoot }) {
  handleTrustedIpc('backend-diagnostics', async () => {
    return backend.diagnostics();
  });

  // System snapshot for bug reports (the renderer bundles it into the zip).
  handleTrustedIpc('diag:get', () => ({
    versions: process.versions,
    os: `${process.platform} ${require('os').release()}`,
    arch: process.arch,
    packaged: app.isPackaged,
    appVersion: app.getVersion(),
    userData: app.getPath('userData'),
  }));

  // Settings > "Connect your own AI (MCP)": how to start this app as a stdio MCP
  // server (main.js --mcp, docs/dev/APP_MCP.md). Installed, that is the exe
  // itself (on Linux the AppImage file, not its mount: shell/stable-executable.js);
  // in a checkout, electron.exe needs the app folder first.
  handleTrustedIpc('mcp:launch', () => ({
    command: stableExecutable(),
    args: app.isPackaged || !appRoot ? ['--mcp'] : [appRoot, '--mcp'],
  }));

  // "Copy image" on a picture Randall made. The renderer's navigator.clipboard
  // write is subject to a permission check; Electron's own clipboard is not.
  // Only image bytes cross, capped well above any preview render. Electron 44's
  // clipboard is the async web-style one (write takes ClipboardItems; there is no
  // writeImage), and it takes PNG, so a JPEG preview is converted first.
  handleTrustedIpc('clipboard:write-image', async (_e, bytes) => {
    if (!(bytes instanceof Uint8Array) || !bytes.length || bytes.length > 64 * 1024 * 1024) throw new Error('Not an image');
    const image = nativeImage.createFromBuffer(Buffer.from(bytes));
    if (image.isEmpty()) throw new Error('Not an image');
    await clipboard.write([new ClipboardItem({ 'image/png': new Blob([image.toPNG()], { type: 'image/png' }) })]);
    return true;
  });
}

module.exports = { registerSystemIpc };
