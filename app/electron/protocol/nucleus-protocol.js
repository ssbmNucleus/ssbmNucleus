'use strict';

// nucleus:// links: registering the scheme with the OS, the single-instance
// lock that turns a second launch into a link (or just "show the window"), and
// the handoff queue that delivers each link to the renderer until the renderer
// acknowledges it.
const path = require('path');
const { parseNucleusUrl, ProtocolHandoffQueue } = require('./protocol-handoff');
const { ensureLinuxProtocolHandler } = require('./linux-protocol');

function createNucleusProtocol({ app, ctx, isDev, iconPath }) {
  const handoffs = new ProtocolHandoffQueue((channel, envelope) => {
    if (!ctx.mainWindow || ctx.mainWindow.isDestroyed()) return;
    if (ctx.mainWindow.isMinimized()) ctx.mainWindow.restore();
    ctx.mainWindow.show();
    ctx.mainWindow.focus();
    ctx.mainWindow.webContents.send(channel, envelope);
  });

  // Handle nucleus:// URLs
  const handleNucleusUrl = async (url) => {
    // Don't log the raw URL for patreon-link — it carries the app token
    console.log('[Nucleus Protocol] Received URL:', url.replace(/token=[^&]+/, 'token=***'));

    const handoff = parseNucleusUrl(url, { allowLocalHttp: isDev });
    if (!handoff) return false;
    return handoffs.enqueue(handoff);
  };

  // Register nucleus:// protocol handler.
  //
  // This runtime call is only HALF the registration, and on its own it is not
  // enough outside Windows. The OS also has to be told at PACKAGE time:
  // electron-builder emits CFBundleURLTypes into Info.plist (macOS) and
  // MimeType=x-scheme-handler/nucleus into the .desktop entry (Linux) only when
  // build.protocols is declared in package.json — it was not, until 2026-08-19,
  // so the browser had no handler to hand a nucleus:// URL to and reported "no
  // apps available". That broke the website's Add to Nucleus button AND the
  // Patreon token handoff, which is the only way a patron's token reaches the
  // app. If you remove build.protocols, you re-break both.
  //
  // Linux needs a THIRD piece on top of those two, because we ship an AppImage
  // and an AppImage installs nothing: the .desktop entry with the MimeType line
  // stays sealed inside the image, so nothing ever claims x-scheme-handler/nucleus
  // and the browser reports "no application available". The call below is also a
  // silent no-op there (Electron routes it through xdg-settings and gives up
  // without $CHROME_DESKTOP). registerLinuxHandler(), run from whenReady, writes
  // the entry into ~/.local/share/applications itself.
  function registerClient() {
    if (process.defaultApp) {
      if (process.argv.length >= 2) {
        app.setAsDefaultProtocolClient('nucleus', process.execPath, [path.resolve(process.argv[1])]);
      }
    } else {
      app.setAsDefaultProtocolClient('nucleus');
    }

    // Handle protocol URLs on macOS/Linux (when app is already running)
    app.on('open-url', (event, url) => {
      event.preventDefault();
      handleNucleusUrl(url);
    });
  }

  // Handle protocol URLs on Windows (when app is already running or being
  // launched). Returns whether this process holds the single-instance lock;
  // without it the process quits.
  function claimSingleInstance() {
    const gotTheLock = app.requestSingleInstanceLock();
    if (!gotTheLock) {
      app.quit();
    } else {
      app.on('second-instance', (event, commandLine, workingDirectory) => {
        // A second launch means the user wants the app in front — whether from a
        // nucleus:// URL or plain "Nucleus" in the Start menu.
        if (ctx.mainWindow && !ctx.mainWindow.isDestroyed()) {
          if (ctx.mainWindow.isMinimized()) ctx.mainWindow.restore();
          ctx.mainWindow.focus();
        }

        // The nucleus:// URL is in commandLine
        const url = commandLine.find(arg => /^nucleus:\/\//i.test(arg));
        if (url) {
          handleNucleusUrl(url);
        }
      });
    }
    return gotTheLock;
  }

  // Claim nucleus:// on Linux (see registerClient). Deliberately not awaited
  // -- it shells out to update-desktop-database and xdg-mime, and startup must
  // not wait on either.
  function registerLinuxHandler() {
    ensureLinuxProtocolHandler({
      isPackaged: app.isPackaged,
      iconSource: iconPath,
    }).then((registered) => {
      // Now that $CHROME_DESKTOP points at our entry, Electron's own registration
      // can actually reach xdg-settings.
      if (registered) app.setAsDefaultProtocolClient('nucleus');
    }).catch((err) => {
      console.error('[Nucleus Protocol] Linux registration threw:', err.message);
    });
  }

  // Handle nucleus:// URL if app was launched with one. Linux delivers it in
  // argv exactly like Windows -- only macOS uses the 'open-url' event -- so
  // gating this on win32 silently dropped cold-start mod imports and Patreon
  // handoffs on Linux.
  function handleLaunchArgs() {
    if (process.platform !== 'darwin') {
      const url = process.argv.find(arg => /^nucleus:\/\//i.test(arg));
      if (url) {
        handleNucleusUrl(url);
      }
    }
  }

  return { handoffs, registerClient, claimSingleInstance, registerLinuxHandler, handleLaunchArgs };
}

module.exports = { createNucleusProtocol };
