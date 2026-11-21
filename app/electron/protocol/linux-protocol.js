// Linux nucleus:// registration.
//
// Windows gets the scheme from the NSIS installer and macOS from
// CFBundleURLTypes in Info.plist, so `app.setAsDefaultProtocolClient` plus
// build.protocols is enough on both. Linux has neither hook:
//
//   * We ship an AppImage. An AppImage is portable by design -- it installs
//     nothing. The .desktop entry electron-builder generates from
//     build.protocols lives INSIDE the squashfs and is never copied to
//     ~/.local/share/applications, so the desktop database has no
//     x-scheme-handler/nucleus owner and the browser says "no application
//     available" for every Add to Nucleus / Patreon-link click.
//   * `app.setAsDefaultProtocolClient` is a silent no-op here: Electron
//     implements it as `xdg-settings set default-url-scheme-handler` and
//     derives the .desktop name from $CHROME_DESKTOP, which nothing sets for
//     us, so it bails before running xdg-settings and returns false.
//
// So we install the desktop entry ourselves, on every launch. Exec must point
// at $APPIMAGE (the real, stable path of the image) and NOT at process.execPath
// -- inside a running AppImage that is /tmp/.mount_XXXXXX/... , a FUSE mount
// that disappears the moment the app exits, which would leave a desktop entry
// that resolves to nothing.

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');
const { stableExecutable } = require('../shell/stable-executable');

const DESKTOP_ID = 'ssbm-nucleus.desktop';
const ICON_NAME = 'ssbm-nucleus';
const SCHEME = 'nucleus';

function dataHome() {
  const xdg = process.env.XDG_DATA_HOME;
  if (xdg && path.isAbsolute(xdg)) return xdg;
  return path.join(os.homedir(), '.local', 'share');
}

// Desktop-entry Exec quoting: reserved characters force a quoted argument, and
// inside one only " and \ are escaped (with a backslash).
function quoteExec(target) {
  if (!/[\s"'\\><~|&;$*?#()`]/.test(target)) return target;
  return `"${target.replace(/(["\\])/g, '\\$1')}"`;
}

// Best-effort; a missing helper binary is normal on a minimal system and must
// never take the app down with it.
function runQuiet(cmd, argv) {
  return new Promise((resolve) => {
    try {
      execFile(cmd, argv, { timeout: 10000 }, (err) => resolve(!err));
    } catch {
      resolve(false);
    }
  });
}

// Copy the app icon out of the asar so Icon= resolves after the AppImage
// unmounts. Returns the name to put in Icon=, or null to omit the key.
function installIcon(iconSource) {
  if (!iconSource) return null;
  try {
    const png = fs.readFileSync(iconSource);
    const dir = path.join(dataHome(), 'icons', 'hicolor', '512x512', 'apps');
    fs.mkdirSync(dir, { recursive: true });
    const dest = path.join(dir, `${ICON_NAME}.png`);
    let existing = null;
    try {
      existing = fs.readFileSync(dest);
    } catch {
      /* not installed yet */
    }
    if (!existing || !existing.equals(png)) fs.writeFileSync(dest, png);
    return ICON_NAME;
  } catch (err) {
    console.warn('[Nucleus Protocol] Could not install icon:', err.message);
    return null;
  }
}

function buildEntry(execTarget, iconName) {
  const lines = [
    '[Desktop Entry]',
    'Type=Application',
    'Name=SSBM Nucleus',
    'Comment=Costume and Stage Manager for Super Smash Bros. Melee',
    `Exec=${quoteExec(execTarget)} %u`,
    'Terminal=false',
    'Categories=Utility;',
    `MimeType=x-scheme-handler/${SCHEME};`,
    'StartupWMClass=SSBM Nucleus',
  ];
  if (iconName) lines.splice(4, 0, `Icon=${iconName}`);
  return `${lines.join('\n')}\n`;
}

/**
 * Install (or refresh) the desktop entry that owns nucleus:// on Linux.
 *
 * Safe to call on every launch and on every platform: it is a no-op off Linux
 * and when unpackaged, and it rewrites the entry only when the contents
 * actually changed -- which is what picks up an AppImage the user moved, or a
 * self-update that landed the image under a new name.
 *
 * @param {{ isPackaged: boolean, iconSource?: string }} opts
 * @returns {Promise<boolean>} whether the scheme should now be registered
 */
async function ensureLinuxProtocolHandler({ isPackaged, iconSource } = {}) {
  if (process.platform !== 'linux') return false;
  // A dev checkout would register the Electron binary plus a script path that
  // only makes sense from the repo; leave the user's real install alone.
  if (!isPackaged) return false;
  if (process.env.NUCLEUS_NO_PROTOCOL_REGISTER === '1') return false;

  // $APPIMAGE is set by the AppImage runtime to the image's own path. Outside
  // an AppImage (a .deb or an unpacked dir) execPath is already stable.
  const execTarget = stableExecutable();

  // Electron's own setAsDefaultProtocolClient/isDefaultProtocolClient read
  // this to find which .desktop file to hand xdg-settings.
  process.env.CHROME_DESKTOP = DESKTOP_ID;

  try {
    const appsDir = path.join(dataHome(), 'applications');
    fs.mkdirSync(appsDir, { recursive: true });
    const entryPath = path.join(appsDir, DESKTOP_ID);
    const entry = buildEntry(execTarget, installIcon(iconSource));

    let current = null;
    try {
      current = fs.readFileSync(entryPath, 'utf8');
    } catch {
      /* first run */
    }
    if (current === entry) {
      console.log('[Nucleus Protocol] Desktop entry already current:', entryPath);
      return true;
    }

    fs.writeFileSync(entryPath, entry, { mode: 0o644 });
    console.log(`[Nucleus Protocol] Installed ${entryPath} -> ${execTarget}`);

    // Rebuild the MIME cache so the browser can see the new handler, then make
    // it the default for the scheme. Both are best-effort: update-desktop-database
    // ships in desktop-file-utils and xdg-mime in xdg-utils, and neither is
    // guaranteed. Without them the entry is still discovered on the next login.
    await runQuiet('update-desktop-database', [appsDir]);
    await runQuiet('xdg-mime', ['default', DESKTOP_ID, `x-scheme-handler/${SCHEME}`]);
    return true;
  } catch (err) {
    console.error('[Nucleus Protocol] Linux registration failed:', err.message);
    return false;
  }
}

module.exports = { ensureLinuxProtocolHandler, DESKTOP_ID, buildEntry, quoteExec };
