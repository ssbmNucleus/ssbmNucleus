'use strict';

// Which renderer may call the main process. Only the app's own renderer
// (ctx.trustedRendererUrl: the Vite origin in development, the packaged
// index.html file otherwise) gets an answer from a trusted IPC handler.
const path = require('path');
const { fileURLToPath } = require('url');

function createTrustedIpc({ ipcMain, ctx }) {
  function isTrustedRendererUrl(candidateUrl) {
    if (!ctx.trustedRendererUrl || typeof candidateUrl !== 'string') return false;
    try {
      const candidate = new URL(candidateUrl);
      const expected = new URL(ctx.trustedRendererUrl);
      if (expected.protocol === 'file:') {
        return candidate.protocol === 'file:'
          && path.normalize(fileURLToPath(candidate)) === path.normalize(fileURLToPath(expected));
      }
      return candidate.origin === expected.origin;
    } catch {
      return false;
    }
  }

  function isTrustedIpcSender(event) {
    const senderUrl = event?.senderFrame?.url || event?.sender?.getURL?.() || '';
    return isTrustedRendererUrl(senderUrl);
  }

  // ipcMain.handle, refusing every sender but the trusted renderer.
  function handleTrustedIpc(channel, listener) {
    ipcMain.handle(channel, (event, ...args) => {
      if (!isTrustedIpcSender(event)) {
        console.warn(`[Security] Rejected IPC '${channel}' from ${event?.senderFrame?.url || 'unknown origin'}`);
        throw new Error('Untrusted IPC sender');
      }
      return listener(event, ...args);
    });
  }

  return { isTrustedRendererUrl, isTrustedIpcSender, handleTrustedIpc };
}

module.exports = { createTrustedIpc };
