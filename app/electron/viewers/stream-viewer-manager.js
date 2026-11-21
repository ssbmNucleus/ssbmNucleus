/** Native renderer in a separate process; JPEG preview frames are composed in
 * Electron on Windows, Linux and macOS. DAT editing stays in the native engine.
 */

const { spawn } = require('child_process');
const { randomBytes } = require('node:crypto');
const { viewerExecutable } = require('./viewer-executable');
const fs = require('fs');
const net = require('net');
const http = require('http');
const WebSocket = require('ws');

const STARTUP_TIMEOUT_MS = 40000;
const STREAM_FPS = 30; // JPEG frames over IPC; 60 is wasteful, 30 looks fine
// Between health polls while the renderer starts. A poll is one loopback GET that is
// refused instantly until the listener binds, so a short interval costs nothing; the
// 400 ms it was (copied from skinlab/session.py in bf7639d1d, no reason given) added
// up to 0.4 s, 0.2 s on average, to every viewer start, i.e. every workbench reload.
const HEALTH_POLL_MS = 100;

class StreamViewerManager {
  constructor(dependencies = {}) {
    this._spawn = dependencies.spawn || spawn;
    this._http = dependencies.http || http;
    this._WebSocket = dependencies.WebSocket || WebSocket;
    this._setTimeout = dependencies.setTimeout || setTimeout;
    this._clearTimeout = dependencies.clearTimeout || clearTimeout;
    this.process = null;
    this.ws = null;
    this.port = null;
    this.messageHandlers = new Map();
    this.isConnected = false;
    this.onFrame = null; // set by viewer-session.js: (buffer) => its frame relay
    this._processExited = false;
    this._stderrChunks = [];
    this._stdoutTail = [];
    this._startupCancel = null;
    this._pendingWs = null;
    // Synthetic animFrame ticker state (server sends no frame updates)
    this._anim = { playing: false, frame: 0, frameCount: 0, speed: 1 };
    this._animTimer = null;
    this._animLastTick = 0;
    this.viewerSessionId = null;
    this._disconnectNotified = false;
    this._serverAnimationTicks = false;
    this._hidden = false;
  }

  /**
   * Get the path to the headless hsdrawviewer binary
   */
  getViewerPath(isDev) {
    return viewerExecutable({ isDev });
  }

  /**
   * Find a free TCP port for the streaming server
   */
  _getFreePort() {
    return new Promise((resolve, reject) => {
      const srv = net.createServer();
      srv.once('error', reject);
      srv.listen(0, '127.0.0.1', () => {
        const port = srv.address().port;
        srv.close(() => resolve(port));
      });
    });
  }

  /**
   * Start the streaming viewer. Same options shape as ViewerManager.start.
   */
  async start(options) {
    const { datFile, sceneFile, ajFile, dataFile, logsPath, isDev } = options;

    if (this.process) {
      await this.stop();
    }

    this._processExited = false;
    this._stderrChunks = [];
    this._stdoutTail = [];

    this.viewerSessionId = options.viewerSessionId || null;
    this._disconnectNotified = false;

    this._sessionToken = randomBytes(32).toString('hex');
    this._serverAnimationTicks = false;
    this._hidden = false;
    const viewerPath = this.getViewerPath(isDev);
    console.log('[StreamViewer] Viewer path:', viewerPath);

    if (!fs.existsSync(viewerPath)) {
      throw new Error(`Native viewer not found at: ${viewerPath}`);
    }

    this.port = await this._getFreePort();

    // Positional args, same slot rules as the pipe viewer: always emit every
    // slot ('' = absent) so a missing earlier value can't shift a later one
    // into the wrong slot (see viewer-manager.js for the full war story).
    const args = ['--stream', String(this.port), datFile,
                  logsPath || '', sceneFile || '', ajFile || '', dataFile || ''];

    console.log('[StreamViewer] Starting with args:', args);

    this.process = this._spawn(viewerPath, args, { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
      env: { ...process.env, NUCLEUS_VIEWER_SESSION_TOKEN: this._sessionToken } });

    this.process.stdout.on('data', (data) => {
      const text = data.toString().trim();
      console.log('[hsdrawviewer]', text);
      // Older native builds report fatal startup exceptions on stdout.
      this._stdoutTail.push(text.slice(-4000));
      if (this._stdoutTail.length > 20) this._stdoutTail.shift();
    });
    this.process.stderr.on('data', (data) => {
      const text = data.toString().trim();
      console.error('[hsdrawviewer Error]', text);
      this._stderrChunks.push(text.slice(-4000));
      if (this._stderrChunks.length > 20) this._stderrChunks.shift();
    });
    this.process.on('close', (code) => {
      console.log('[StreamViewer] Process exited with code:', code);
      this._processExited = true;
      this.notifyDisconnected(`Viewer process exited (${code})`);
      this.cleanup();
    });
    this.process.on('error', (err) => {
      console.error('[StreamViewer] Failed to start:', err);
      this._processExited = true;
      this._stderrChunks.push(err.message);
      this.notifyDisconnected(err.message);
      this.cleanup();
    });

    try {
      await this._waitHttpReady();
      await this._connectWebSocket();
    } catch (err) {
      await this.stop().catch(() => {});
      throw err;
    }

    return { connected: this.isConnected, streaming: true, port: this.port };
  }

  /**
   * Poll the server's HTTP health endpoint until it answers (the server
   * binds the listener before GL init finishes, same wait session.py uses).
   */
  _waitHttpReady() {
    return new Promise((resolve, reject) => {
      const deadline = Date.now() + STARTUP_TIMEOUT_MS;
      let settled = false;
      let retryTimer = null;
      let activeRequest = null;

      const finish = (callback, value) => {
        if (settled) return;
        settled = true;
        if (retryTimer) this._clearTimeout(retryTimer);
        retryTimer = null;
        if (activeRequest) activeRequest.removeAllListeners?.();
        activeRequest = null;
        if (this._startupCancel === cancel) this._startupCancel = null;
        callback(value);
      };
      const cancel = () => {
        if (activeRequest) {
          activeRequest.removeAllListeners?.();
          activeRequest.destroy?.();
        }
        finish(reject, new Error('hsdrawviewer startup was cancelled'));
      };
      this._startupCancel = cancel;

      const retry = () => {
        if (settled || retryTimer) return;
        retryTimer = this._setTimeout(() => {
          retryTimer = null;
          poll();
        }, HEALTH_POLL_MS);
      };

      const poll = () => {
        if (settled) return;
        if (this._processExited) {
          const stderr = this._stderrChunks.join('\n').trim();
          const stdout = this._stdoutTail.join('\n').trim();
          finish(reject, new Error(
            'hsdrawviewer exited during startup' +
            (stdout ? `\n\nViewer output:\n${stdout}` : '') +
            (stderr ? `\n\nViewer errors:\n${stderr}` : '')
          ));
          return;
        }
        if (Date.now() > deadline) {
          finish(reject, new Error('hsdrawviewer did not become ready in time'));
          return;
        }
        // 'localhost', NOT '127.0.0.1'. StreamingServer.cs registers the
        // HttpListener prefix as http://localhost:<port>/, and HttpListener
        // routes on the HOST HEADER: a request to 127.0.0.1 carries
        // Host: 127.0.0.1:<port>, matches no prefix, and HttpListener answers
        // its own 404 before the handler runs. The poll below only accepts 200,
        // so it could never succeed -- the viewer started fine, bound its port
        // and initialised GL, then Electron sat there for the full 40s and
        // reported "hsdrawviewer did not become ready in time". That was every
        // model on every non-Windows machine; Windows uses ViewerManager and
        // never hit it.
        let attemptFinished = false;
        const completeAttempt = (ready) => {
          if (attemptFinished || settled) return;
          attemptFinished = true;
          activeRequest = null;
          if (ready) finish(resolve);
          else retry();
        };
        const req = this._http.get({ host: 'localhost', port: this.port, timeout: 1000,
          headers: { 'X-Nucleus-Viewer-Token': this._sessionToken } }, (res) => {
          res.resume();
          completeAttempt(res.statusCode === 200);
        });
        activeRequest = req;
        req.on('error', () => completeAttempt(false));
        req.on('timeout', () => {
          req.destroy();
          completeAttempt(false);
        });
      };
      poll();
    });
  }

  _connectWebSocket() {
    return new Promise((resolve, reject) => {
      // Same host-header reason as the health poll above: the listener prefix
      // is registered for localhost, so the upgrade request has to carry that
      // Host or HttpListener 404s it instead of accepting the WebSocket.
      const ws = new this._WebSocket(`ws://localhost:${this.port}/`, {
        headers: { 'X-Nucleus-Viewer-Token': this._sessionToken },
        handshakeTimeout: 10000, maxPayload: 128 * 1024 * 1024,
      });
      this._pendingWs = ws;
      let settled = false;

      const rejectStartup = (error) => {
        if (settled) return;
        settled = true;
        if (this._pendingWs === ws) this._pendingWs = null;
        reject(error);
      };

      ws.on('open', () => {
        if (settled) return;
        settled = true;
        if (this._pendingWs === ws) this._pendingWs = null;
        this.ws = ws;
        this.isConnected = true;
        console.log('[StreamViewer] WebSocket connected');
        // Throttle the frame stream before anything else
        this.send({ type: 'fps', value: STREAM_FPS });
        resolve();
      });

      ws.on('message', (data, isBinary) => {
        if (isBinary) {
          // Binary = JPEG frame
          if (this.onFrame) this.onFrame(data);
          return;
        }
        try {
          const message = JSON.parse(data.toString());
          this.handleMessage(message);
        } catch (err) {
          console.error('[StreamViewer] Failed to parse message:', err);
        }
      });

      ws.on('close', () => {
        console.log('[StreamViewer] WebSocket closed');
        this.isConnected = false;
        this._syncAnimTicker();
        this.notifyDisconnected('Streaming viewer WebSocket closed');
        rejectStartup(new Error('Streaming viewer WebSocket closed during startup'));
      });

      ws.on('error', (err) => {
        console.error('[StreamViewer] WebSocket error:', err.message);
        this.isConnected = false;
        this._syncAnimTicker();
        this.notifyDisconnected(err.message);
        if (!settled) {
          const stderr = this._stderrChunks.join('\n').trim();
          rejectStartup(new Error(
            `Failed to connect to streaming viewer: ${err.message}` +
            (stderr ? `\n\nViewer output:\n${stderr}` : '')
          ));
        }
      });
    });
  }

  /**
   * Handle incoming JSON message from the streaming server
   */
  handleMessage(message) {
    // Animation ticks arrive for every JPEG. Logging each one adds synchronous
    // console/file work to the hot path; lifecycle and command replies stay logged.
    if (message.type !== 'animFrame') console.log('[StreamViewer] Received:', message.type);

    if (message.type === 'capabilities') {
      this._serverAnimationTicks = message.animationTicks === true;
      this._syncAnimTicker();
    }
    if (message.type === 'animFrame' && Number.isFinite(message.frame)) {
      this._anim.frame = message.frame;
      if (Number.isFinite(message.frameCount)) this._anim.frameCount = message.frameCount;
      if (typeof message.playing === 'boolean') this._anim.playing = message.playing;
      if (Number.isFinite(message.speed)) this._anim.speed = message.speed;
      this._syncAnimTicker();
    }

    if (message.type === 'info') {
      // The pipe viewer signals 'ready' once its window exists; the renderer
      // keys its connected/loading state off that, so synthesize it here.
      if (message.animation) {
        this._anim.frameCount = message.animation.frameCount || 0;
        this._anim.frame = message.animation.currentFrame || 0;
        this._anim.playing = !!message.animation.playing;
        this._anim.speed = message.animation.speed || 1;
        this._syncAnimTicker();
      }
      this._dispatch(message);
      this._dispatch({ type: 'ready', streaming: true, width: message.width, height: message.height });
      return;
    }

    if (message.type === 'animLoaded' && message.success !== false && !message.error) {
      this._anim.frameCount = message.frameCount || 0;
      this._anim.frame = 0;
      this._anim.playing = true;
      this._syncAnimTicker();
    }

    this._dispatch(message);
  }

  _dispatch(message) {
    message = { ...message, viewerSessionId: this.viewerSessionId };
    const handlers = this.messageHandlers.get(message.type) || [];
    handlers.forEach((handler) => handler(message));
    const allHandlers = this.messageHandlers.get('all') || [];
    allHandlers.forEach((handler) => handler(message));
  }

  notifyDisconnected(error) {
    if (this._disconnectNotified) return;
    this._disconnectNotified = true;
    this._dispatch({ type: 'disconnected', error });
  }

  /**
   * Synthetic animFrame ticker: advance the frame counter locally while
   * playing so the renderer's scrubber moves. 4 updates/sec is plenty for
   * a progress indicator and keeps IPC chatter negligible.
   */
  _syncAnimTicker() {
    // Only while connected: a dead socket must not keep inventing frames.
    if (this.isConnected && !this._serverAnimationTicks && !this._hidden
        && this._anim.playing && this._anim.frameCount > 0) {
      if (this._animTimer) return;
      this._animLastTick = Date.now();
      this._animTimer = setInterval(() => {
        const now = Date.now();
        const dt = (now - this._animLastTick) / 1000;
        this._animLastTick = now;
        // Melee animations run at 60 fps * playback speed
        this._anim.frame = (this._anim.frame + dt * 60 * this._anim.speed) % this._anim.frameCount;
        this._dispatch({ type: 'animFrame', frame: this._anim.frame });
      }, 250);
    } else if (this._animTimer) {
      clearInterval(this._animTimer);
      this._animTimer = null;
    }
  }

  onMessage(type, handler) {
    if (!this.messageHandlers.has(type)) {
      this.messageHandlers.set(type, []);
    }
    this.messageHandlers.get(type).push(handler);
  }

  offMessage(type, handler) {
    const handlers = this.messageHandlers.get(type);
    if (handlers) {
      const index = handlers.indexOf(handler);
      if (index !== -1) handlers.splice(index, 1);
    }
  }

  /**
   * Send a message to the viewer, translating/filtering pipe-only messages.
   */
  send(message) {
    if (!this.isConnected || !this.ws) {
      console.error('[StreamViewer] Cannot send - not connected');
      return false;
    }

    switch (message.type) {
      case 'show':
      case 'hide':
        this._hidden = message.type === 'hide';
        this._syncAnimTicker();
        return this._sendRaw(message);
      // No native window positioning is needed for a canvas.
      case 'setParent':
        return true;
      case 'close':
        // Handled by stop(); the server has no 'close' command.
        return true;
      case 'resize': {
        // Screen-coords rect from the renderer -> render size for the server.
        // The renderer parks a collapsed placeholder at (-32000,-32000); for a
        // stream that's "nothing to show", not a real 64x64 render request.
        if (message.x <= -30000 || message.y <= -30000) return this.hide();
        if (!Number.isFinite(message.width) || !Number.isFinite(message.height)) return false;
        const scale = Math.min(1, 2048 / Math.max(message.width, message.height));
        const width = Math.max(2, Math.round(message.width * scale));
        const height = Math.max(2, Math.round(message.height * scale));
        return this._sendRaw({ type: 'resize', width, height });
      }
      case 'animToggle':
        this._anim.playing = !this._anim.playing;
        this._syncAnimTicker();
        return this._sendRaw(message);
      case 'animPause':
        this._anim.playing = false;
        this._syncAnimTicker();
        return this._sendRaw(message);
      case 'animPlay':
        this._anim.playing = true;
        this._syncAnimTicker();
        return this._sendRaw(message);
      case 'animSetFrame':
        this._anim.frame = message.frame || 0;
        return this._sendRaw(message);
      default:
        return this._sendRaw(message);
    }
  }

  _sendRaw(message) {
    try {
      this.ws.send(JSON.stringify(message));
      return true;
    } catch (err) {
      console.error('[StreamViewer] Send error:', err);
      return false;
    }
  }

  sendCamera(deltaRotX, deltaRotY, deltaZoom, deltaX, deltaY) {
    return this.send({ type: 'camera', deltaRotX, deltaRotY, deltaZoom, deltaX, deltaY });
  }

  getAnimList() {
    return this.send({ type: 'getAnimList' });
  }

  loadAnim(symbol) {
    return this.send({ type: 'loadAnim', symbol });
  }

  animToggle() {
    return this.send({ type: 'animToggle' });
  }

  animPause() {
    return this.send({ type: 'animPause' });
  }

  animSetFrame(frame) {
    return this.send({ type: 'animSetFrame', frame });
  }

  resize(x, y, width, height) {
    return this.send({ type: 'resize', x, y, width, height });
  }

  show() {
    return this.send({ type: 'show' });
  }

  hide() {
    return this.send({ type: 'hide' });
  }

  setCspMode(enabled) {
    return this.send({ type: 'setCspMode', enabled });
  }

  setGrid(enabled) {
    return this.send({ type: 'setGrid', enabled });
  }

  setBackground(enabled) {
    return this.send({ type: 'setBackground', enabled });
  }

  exportScene() {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.offMessage('sceneExported', handler);
        reject(new Error('Scene export timed out'));
      }, 5000);

      const handler = (message) => {
        clearTimeout(timeout);
        this.offMessage('sceneExported', handler);
        if (message.success) {
          resolve(message.scene);
        } else {
          reject(new Error(message.error || 'Scene export failed'));
        }
      };

      this.onMessage('sceneExported', handler);
      this.send({ type: 'exportScene' });
    });
  }

  async stop() {
    console.log('[StreamViewer] Stopping viewer...');

    if (this._animTimer) {
      clearInterval(this._animTimer);
      this._animTimer = null;
    }

    if (this.ws) {
      try { this.ws.close(); } catch (e) { /* already closed */ }
    }

    this._processExited = true;
    if (this._startupCancel) this._startupCancel();
    this._startupCancel = null;
    if (this._pendingWs) {
      try { this._pendingWs.close(); } catch (e) { /* already closed */ }
      this._pendingWs = null;
    }
    if (this.process && this.process.exitCode == null && !this.process.killed) {
      this.process.kill();
    }

    this.cleanup();
    console.log('[StreamViewer] Viewer stopped');
  }

  cleanup() {
    if (this._animTimer) {
      clearInterval(this._animTimer);
      this._animTimer = null;
    }
    this.process = null;
    this.ws = null;
    this.port = null;
    this.isConnected = false;
    this._anim = { playing: false, frame: 0, frameCount: 0, speed: 1 };
  }
}

module.exports = StreamViewerManager;
module.exports.HEALTH_POLL_MS = HEALTH_POLL_MS;
