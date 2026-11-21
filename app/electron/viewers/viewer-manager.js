/**
 * Viewer Manager - Manages the embedded HSDRawViewer process
 * Uses Named Pipes for fast IPC instead of WebSocket
 */

const { spawn } = require('child_process');
const { viewerExecutable } = require('./viewer-executable');
const fs = require('fs');
const net = require('net');

class ViewerManager {
  constructor() {
    this.process = null;
    this.pipeName = null;
    this.pipeClient = null;
    this.messageBuffer = '';
    this.messageHandlers = new Map();
    this.isConnected = false;
    this.hwnd = null;
    // Track process state for fail-fast during pipe connection
    this._processExited = false;
    this._stderrChunks = [];
    this._stdoutTail = [];
    this.viewerSessionId = null;
    this._disconnectNotified = false;
  }

  /**
   * Generate a unique pipe name
   */
  generatePipeName() {
    return `HSDViewer_${process.pid}_${Date.now()}`;
  }

  /**
   * Get the path to HSDRawViewer.exe
   */
  getViewerPath(isDev) {
    return viewerExecutable({ isDev });
  }

  /**
   * Start the embedded viewer
   * @param {Object} options
   * @param {string} options.datFile - Path to the DAT file
   * @param {string} [options.sceneFile] - Optional path to scene.yml
   * @param {string} [options.ajFile] - Optional path to AJ file for animations
   * @param {string} [options.dataFile] - Optional fighter-data dat (ftData) for
   *   per-animation mesh-part visibility (Bowser shell on up-B, etc.)
   * @param {string} [options.logsPath] - Optional path for logs
   * @param {boolean} options.isDev - Whether running in development mode
   */
  async start(options) {
    const { datFile, sceneFile, ajFile, dataFile, logsPath, isDev } = options;

    // Stop any existing viewer
    if (this.process) {
      await this.stop();
    }

    // Reset state
    this._processExited = false;
    this._stderrChunks = [];
    this._stdoutTail = [];
    this.viewerSessionId = options.viewerSessionId || null;
    this._disconnectNotified = false;

    // Get viewer path
    const viewerPath = this.getViewerPath(isDev);
    console.log('[ViewerManager] Viewer path:', viewerPath);

    if (!fs.existsSync(viewerPath)) {
      throw new Error(`HSDRawViewer not found at: ${viewerPath}`);
    }

    // Generate unique pipe name
    this.pipeName = this.generatePipeName();
    console.log('[ViewerManager] Pipe name:', this.pipeName);

    // Build command arguments.
    // The C# side reads these POSITIONALLY: args[3]=logsPath, args[4]=sceneFile,
    // args[5]=ajFile. Pushing optionals conditionally would shift a later value
    // into an earlier slot whenever an earlier one is missing — e.g. a custom
    // character with no donor scene (sceneFile null) but a valid ajFile would
    // land the AJ in the scene slot, so the viewer parses the AJ as scene YAML
    // and loads zero animations. Always emit all three slots; the C# guards
    // (string.IsNullOrEmpty) treat '' as absent.
    // args[6]=dataFile (fighter-data dat) -> per-animation mesh-part visibility.
    const args = ['--embedded', this.pipeName, datFile,
                  logsPath || '', sceneFile || '', ajFile || '', dataFile || ''];

    console.log('[ViewerManager] Starting viewer with args:', args);

    // Spawn the viewer process
    this.process = spawn(viewerPath, args, {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: false // We need the window visible
    });

    this.process.stdout.on('data', (data) => {
      const text = data.toString().trim();
      console.log('[HSDViewer]', text);
      // Keep a short tail of output so startup errors can say how far the
      // viewer got (STAGE:* markers) instead of just "not ready".
      for (const line of text.split('\n')) {
        this._stdoutTail.push(line.trim());
        if (this._stdoutTail.length > 20) this._stdoutTail.shift();
      }
    });

    this.process.stderr.on('data', (data) => {
      const text = data.toString().trim();
      console.error('[HSDViewer Error]', text);
      this._stderrChunks.push(text);
    });

    this.process.on('close', (code) => {
      console.log('[ViewerManager] Viewer process exited with code:', code);
      this._processExited = true;
      this.notifyDisconnected(`Viewer process exited (${code})`);
      this.cleanup();
    });

    this.process.on('error', (err) => {
      console.error('[ViewerManager] Failed to start viewer:', err);
      this._processExited = true;
      this._stderrChunks.push(err.message);
      this.notifyDisconnected(err.message);
      this.cleanup();
    });

    // Wait for PIPE_READY signal from stdout, then connect. On any handshake
    // failure, kill the spawned process — otherwise it lingers as an orphan
    // window the user has to explain in a bug report.
    try {
      await this.waitForPipeReady();
      await this.connectToPipe();
    } catch (err) {
      await this.stop().catch(() => {});
      throw err;
    }

    return {
      pipeName: this.pipeName,
      hwnd: this.hwnd,
      connected: this.isConnected
    };
  }

  /**
   * Wait for the C# viewer to signal that it's created the named pipe.
   * Fails fast if the process exits before signaling.
   *
   * Readiness is judged by PROGRESS, not a stopwatch: the viewer prints a
   * STAGE:* marker at each startup step, and every stdout line resets a
   * 20-second inactivity timer. A slow machine (cold .NET start, antivirus
   * scanning the publish, weak GPU) keeps making progress and gets as long
   * as it needs up to a 3-minute cap; a genuine stall fails within 20s and
   * the error names the stage it died in.
   */
  waitForPipeReady() {
    const INACTIVITY_MS = 20000;
    const TOTAL_CAP_MS = 180000;

    return new Promise((resolve, reject) => {
      let resolved = false;
      let inactivityTimer = null;

      const finish = (fn, arg) => {
        if (resolved) return;
        resolved = true;
        clearTimeout(inactivityTimer);
        clearTimeout(totalTimer);
        this.process?.stdout?.removeListener('data', onData);
        fn(arg);
      };

      const failureDetail = () => {
        const stderr = this._stderrChunks.join('\n').trim();
        const tail = this._stdoutTail.join('\n').trim();
        const lastStage = [...this._stdoutTail].reverse()
          .find((l) => l.startsWith('STAGE:'));
        return (lastStage ? `\nLast startup stage reached: ${lastStage.slice(6)}` : '') +
               (tail ? `\n\nViewer output:\n${tail}` : '') +
               (stderr ? `\n\nViewer errors:\n${stderr}` : '');
      };

      const armInactivity = () => {
        clearTimeout(inactivityTimer);
        inactivityTimer = setTimeout(() => {
          finish(reject, new Error(
            `HSDRawViewer stopped responding during startup ` +
            `(no progress for ${INACTIVITY_MS / 1000}s)` + failureDetail()
          ));
        }, INACTIVITY_MS);
      };

      const totalTimer = setTimeout(() => {
        finish(reject, new Error(
          `HSDRawViewer did not become ready within ${TOTAL_CAP_MS / 1000} seconds` +
          failureDetail()
        ));
      }, TOTAL_CAP_MS);

      // Listen for PIPE_READY on stdout; any output counts as progress
      const onData = (data) => {
        if (resolved) return;
        armInactivity();
        const text = data.toString();
        if (text.includes('PIPE_READY')) {
          finish(resolve);
        }
      };
      this.process.stdout.on('data', onData);
      armInactivity();

      // Fail fast if process exits before signaling
      const onClose = (code) => {
        finish(reject, new Error(
          `HSDRawViewer crashed during startup (exit code ${code})` + failureDetail()
        ));
      };
      this.process.on('close', onClose);

      const onError = (err) => {
        finish(reject, new Error(`HSDRawViewer failed to launch: ${err.message}`));
      };
      this.process.on('error', onError);
    });
  }

  /**
   * Connect to the named pipe (called only after PIPE_READY)
   */
  async connectToPipe() {
    return new Promise((resolve, reject) => {
      const pipePath = `\\\\.\\pipe\\${this.pipeName}`;
      console.log('[ViewerManager] Connecting to pipe:', pipePath);

      let attempts = 0;
      const maxAttempts = 10; // Only need a few retries since we know the pipe exists
      let settled = false;

      const tryConnect = () => {
        if (settled) return;

        // Fail fast if process died
        if (this._processExited) {
          settled = true;
          const stderr = this._stderrChunks.join('\n').trim();
          reject(new Error(
            'HSDRawViewer process exited before pipe connection could be established' +
            (stderr ? `\n\nViewer output:\n${stderr}` : '')
          ));
          return;
        }

        attempts++;
        this.pipeClient = net.connect(pipePath, () => {
          if (!settled) {
            settled = true;
            console.log('[ViewerManager] Connected to pipe!');
            this.isConnected = true;
            this.setupPipeHandlers();
            resolve();
          }
        });

        this.pipeClient.on('error', (err) => {
          if (settled) return;
          if (attempts < maxAttempts) {
            setTimeout(tryConnect, 200);
          } else {
            settled = true;
            const stderr = this._stderrChunks.join('\n').trim();
            reject(new Error(
              `Failed to connect to viewer pipe after ${maxAttempts} attempts: ${err.message}` +
              (stderr ? `\n\nViewer output:\n${stderr}` : '')
            ));
          }
        });
      };

      tryConnect();
    });
  }

  /**
   * Set up pipe message handlers
   */
  setupPipeHandlers() {
    this.pipeClient.on('data', (data) => {
      this.messageBuffer += data.toString();

      // Process complete messages (newline-delimited JSON)
      let newlineIndex;
      while ((newlineIndex = this.messageBuffer.indexOf('\n')) !== -1) {
        const line = this.messageBuffer.substring(0, newlineIndex);
        this.messageBuffer = this.messageBuffer.substring(newlineIndex + 1);

        if (line.trim()) {
          try {
            const message = JSON.parse(line);
            this.handleMessage(message);
          } catch (err) {
            console.error('[ViewerManager] Failed to parse message:', line, err);
          }
        }
      }
    });

    this.pipeClient.on('close', () => {
      console.log('[ViewerManager] Pipe closed');
      this.isConnected = false;
      this.notifyDisconnected('Viewer pipe closed');
    });

    this.pipeClient.on('error', (err) => {
      console.error('[ViewerManager] Pipe error:', err);
      this.isConnected = false;
      this.notifyDisconnected(err.message);
    });
  }

  /**
   * Handle incoming message from viewer
   */
  handleMessage(message) {
    message = { ...message, viewerSessionId: this.viewerSessionId };
    console.log('[ViewerManager] Received:', message.type);

    // Store HWND from ready message
    if (message.type === 'ready') {
      this.hwnd = message.hwnd;
      console.log('[ViewerManager] Viewer ready, HWND:', this.hwnd);
    }

    // Notify any registered handlers
    const handlers = this.messageHandlers.get(message.type) || [];
    handlers.forEach(handler => handler(message));

    // Also notify 'all' handlers
    const allHandlers = this.messageHandlers.get('all') || [];
    allHandlers.forEach(handler => handler(message));
  }

  notifyDisconnected(error) {
    if (this._disconnectNotified) return;
    this._disconnectNotified = true;
    this.handleMessage({ type: 'disconnected', error });
  }

  /**
   * Register a message handler
   * @param {string} type - Message type to handle, or 'all' for all messages
   * @param {Function} handler - Handler function
   */
  onMessage(type, handler) {
    if (!this.messageHandlers.has(type)) {
      this.messageHandlers.set(type, []);
    }
    this.messageHandlers.get(type).push(handler);
  }

  /**
   * Remove a message handler
   */
  offMessage(type, handler) {
    const handlers = this.messageHandlers.get(type);
    if (handlers) {
      const index = handlers.indexOf(handler);
      if (index !== -1) {
        handlers.splice(index, 1);
      }
    }
  }

  /**
   * Send a message to the viewer
   * @param {Object} message - Message object to send
   */
  send(message) {
    if (!this.isConnected || !this.pipeClient) {
      console.error('[ViewerManager] Cannot send - not connected');
      return false;
    }

    try {
      const json = JSON.stringify(message) + '\n';
      this.pipeClient.write(json);
      return true;
    } catch (err) {
      console.error('[ViewerManager] Send error:', err);
      return false;
    }
  }

  /**
   * Send camera update
   */
  sendCamera(deltaRotX, deltaRotY, deltaZoom, deltaX, deltaY) {
    return this.send({
      type: 'camera',
      deltaRotX,
      deltaRotY,
      deltaZoom,
      deltaX,
      deltaY
    });
  }

  /**
   * Request animation list
   */
  getAnimList() {
    return this.send({ type: 'getAnimList' });
  }

  /**
   * Load animation by symbol
   */
  loadAnim(symbol) {
    return this.send({ type: 'loadAnim', symbol });
  }

  /**
   * Toggle animation playback
   */
  animToggle() {
    return this.send({ type: 'animToggle' });
  }

  /**
   * Pause animation playback
   */
  animPause() {
    return this.send({ type: 'animPause' });
  }

  /**
   * Set animation frame
   */
  animSetFrame(frame) {
    return this.send({ type: 'animSetFrame', frame });
  }

  /**
   * Resize/reposition viewer window
   */
  resize(x, y, width, height) {
    return this.send({ type: 'resize', x, y, width, height });
  }

  /**
   * Show viewer window
   */
  show() {
    return this.send({ type: 'show' });
  }

  /**
   * Hide viewer window
   */
  hide() {
    return this.send({ type: 'hide' });
  }

  /**
   * Set CSP mode (enables special camera for character select portraits)
   */
  setCspMode(enabled) {
    return this.send({ type: 'setCspMode', enabled });
  }

  /**
   * Set grid visibility
   */
  setGrid(enabled) {
    return this.send({ type: 'setGrid', enabled });
  }

  /**
   * Set background visibility
   */
  setBackground(enabled) {
    return this.send({ type: 'setBackground', enabled });
  }

  /**
   * Export current scene settings (camera, frame, animation)
   * Returns promise that resolves with scene data
   */
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

  /**
   * Stop the viewer
   */
  async stop() {
    console.log('[ViewerManager] Stopping viewer...');

    // Send close command
    if (this.isConnected) {
      this.send({ type: 'close' });
    }

    // Close pipe
    if (this.pipeClient) {
      this.pipeClient.destroy();
    }

    // Kill process if still running
    if (this.process && !this.process.killed) {
      this.process.kill();
    }

    this.cleanup();
    console.log('[ViewerManager] Viewer stopped');
  }

  /**
   * Clean up resources
   */
  cleanup() {
    this.process = null;
    this.pipeClient = null;
    this.pipeName = null;
    this.hwnd = null;
    this.isConnected = false;
    this.messageBuffer = '';
  }
}

module.exports = ViewerManager;
