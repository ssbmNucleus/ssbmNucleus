'use strict';

// Which URLs may leave the app for the system browser: HTTPS always, loopback
// HTTP in development only. Used by the window's open/navigation guards and by
// the open-external IPC.
function createExternalLinks({ shell, isDev }) {
  function isAllowedExternalUrl(rawUrl) {
    try {
      const parsed = new URL(rawUrl);
      if (parsed.protocol === 'https:') return true;
      return isDev && parsed.protocol === 'http:'
        && (parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost');
    } catch {
      return false;
    }
  }

  async function openExternalSafely(rawUrl) {
    if (!isAllowedExternalUrl(rawUrl)) {
      return { success: false, error: 'Only HTTPS URLs are allowed' };
    }
    await shell.openExternal(rawUrl);
    return { success: true };
  }

  return { isAllowedExternalUrl, openExternalSafely };
}

module.exports = { createExternalLinks };
