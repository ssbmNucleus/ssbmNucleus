'use strict';

// The app's Dolphin capture host: dolphin-capture.js's lease logic bound to the
// main window and to the authenticated backend, which alone names the capture
// target (the renderer never supplies one).
const { createDolphinCaptureHost } = require('./dolphin-capture');

function createAppDolphinCapture({ desktopCapturer, ctx, isTrustedIpcSender }) {
  // The renderer never supplies a capture target: ask our authenticated backend.
  function dolphinCaptureRequest(body) {
    return new Promise((resolve, reject) => {
      if (!ctx.backendPort) return reject(new Error('Backend is not ready'));
      const payload = body ? JSON.stringify(body) : null;
      const request = require('node:http').request({ hostname: '127.0.0.1', port: ctx.backendPort,
        path: '/api/mex/test-in-game/window/capture-target', method: payload ? 'POST' : 'GET',
        headers: { 'X-Nucleus-Token': ctx.backendToken, ...(payload ? {
          'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) } : {}) }
      }, response => {
        let text = '';
        response.on('data', chunk => {
          text += chunk;
          if (text.length > 16384) request.destroy(new Error('Capture response too large'));
        });
        response.on('error', reject);
        response.on('end', () => {
          if (response.statusCode !== 200) return reject(new Error('Capture target unavailable'));
          try { resolve(JSON.parse(text)); } catch (error) { reject(error); }
        });
      });
      request.setTimeout(3000, () => request.destroy(new Error('Capture target timed out')));
      request.on('error', reject);
      request.end(payload);
    });
  }

  return createDolphinCaptureHost({ desktopCapturer,
    isTrusted: event => !!ctx.mainWindow && !ctx.mainWindow.isDestroyed() &&
      event.sender === ctx.mainWindow.webContents && event.senderFrame === event.sender.mainFrame &&
      isTrustedIpcSender(event),
    readTarget: () => dolphinCaptureRequest(),
    presentTarget: (target, mode) => {
      if (mode === 'separate') return dolphinCaptureRequest({ sessionId: target.sessionId, hwnd: target.hwnd, mode });
      if (!ctx.mainWindow || ctx.mainWindow.isDestroyed()) return { found: false };
      const bytes = ctx.mainWindow.getNativeWindowHandle();
      const hwnd = bytes.length >= 8 ? bytes.readBigUInt64LE().toString() : String(bytes.readUInt32LE());
      return dolphinCaptureRequest({ sessionId: target.sessionId, hwnd: target.hwnd,
        mode, ownerHwnd: hwnd, ownerPid: process.pid });
    }
  });
}

module.exports = { createAppDolphinCapture };
