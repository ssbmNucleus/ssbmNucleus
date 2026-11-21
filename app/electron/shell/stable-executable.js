'use strict';

// The path that starts this app again from outside it, after it has quit: the MCP setup snippet
// (ipc/system.js 'mcp:launch'), the relay's auto-launch (mcp/relay.js) and the Linux nucleus:// desktop
// entry (protocol/linux-protocol.js).
//
// Linux ships an AppImage. Inside a running one, process.execPath is its FUSE mount
// (/tmp/.mount_SSBM XXXXXX/ssbm-nucleus), which is gone when the app quits: a snippet copied from it
// pointed the user's AI at nothing (0.9.0 build 3 Linux smoke). The AppImage runtime sets $APPIMAGE to
// the image file itself, which stays, and $APPDIR to the mount. A process started from inside the app's
// own mount takes $APPIMAGE; one that only inherited it (a .deb build started from an AppImage'd
// terminal) keeps its execPath, which outside an AppImage is already stable.
//
// macOS gives the binary inside the bundle (/Applications/SSBM Nucleus.app/Contents/MacOS/SSBM Nucleus),
// stable while the bundle stays where it is; Windows gives the installed exe. Both are execPath.
const { posix } = require('path');

function inside(folder, file) {
  const relative = posix.relative(folder, file);
  return relative !== '' && !relative.startsWith('..') && !posix.isAbsolute(relative);
}

function stableExecutable({ env = process.env, execPath = process.execPath, platform = process.platform } = {}) {
  if (platform !== 'linux' || !env.APPIMAGE) return execPath;
  if (env.APPDIR && !inside(env.APPDIR, execPath)) return execPath;
  return env.APPIMAGE;
}

module.exports = { stableExecutable };
