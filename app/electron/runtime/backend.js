'use strict';

// The Flask backend as an owned child process: launch, the BACKEND_PORT
// handshake, the output ring buffer behind backend-diagnostics, the
// startup-failure dialog, and the graceful-then-forced shutdown on quit.
// main.js owns the child's environment (the release gates) and the secrets.
const { spawn } = require('child_process');
const http = require('http');
const { BackendPortParser } = require('./backend-port-parser');
const { backendLaunch } = require('./backend-launch');
const { showBackendStartupFailure } = require('./backend-startup-report');
const { terminateOwnedChild } = require('./owned-child-shutdown');

const BACKEND_OUTPUT_BUFFER_LINES = 80;

// environment(): the env the child is spawned with, built at spawn time.
// secrets: values removed from the startup-failure report.
// onExit({code, signal}): the backend died after startup while the app was not
// quitting. Nothing in the window can work after that, so main.js tells it.
// ctx.backendPort is written here once the backend announces its port.
function createBackendRuntime({ app, dialog, clipboard, ctx, isDev, appRoot, resourcesPath, environment, secrets,
  onExit = () => {}, spawnProcess = spawn }) {
  let pythonProcess = null;
  let backendStartupError = null;
  // Set once when the running backend dies outside a quit; read by diagnostics
  // so a window that reloads after the event still knows.
  let backendExit = null;
  const backendOutputBuffer = [];

  function recordBackendOutput(stream, text) {
    text.split(/\r?\n/).forEach((line) => {
      if (!line) return;
      backendOutputBuffer.push(`[${stream}] ${line}`);
      if (backendOutputBuffer.length > BACKEND_OUTPUT_BUFFER_LINES) {
        backendOutputBuffer.shift();
      }
    });
  }

  function start() {
    return new Promise((resolve, reject) => {
      console.log('[Electron] Starting Flask backend...');

      const { command: backendCmd, args: backendArgs, cwd: backendCwd } = backendLaunch({
        isDev, appRoot, resourcesPath,
      });

      // Spawn options with hidden window
      const spawnOptions = {
        cwd: backendCwd,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: environment()
      };

      // Hide CMD window on Windows
      if (process.platform === 'win32') {
        spawnOptions.windowsHide = true;
      } else {
        // Own a process GROUP on Unix. Shutdown signals -pythonProcess.pid, which
        // only reaches a group if the child is a group leader -- without this the
        // kill silently hits just the backend and leaves mexcli/hsdrawviewer
        // children (and the port they hold) behind. Observed on Linux: quitting
        // the app left the renderer alive still holding port 5000.
        spawnOptions.detached = true;
      }

      pythonProcess = spawnProcess(backendCmd, backendArgs, spawnOptions);

      let resolved = false;
      const stdoutPortParser = new BackendPortParser();
      const stderrPortParser = new BackendPortParser();

      const acceptReportedPort = (port, source = '') => {
        if (resolved) return;
        resolved = true;
        clearTimeout(timeout);
        ctx.backendPort = port;
        console.log(`[Electron] Flask backend running on port ${ctx.backendPort}${source}`);
        resolve(ctx.backendPort);
      };

      // Frozen extraction and a large library can exceed the old 15-second wait.
      const startupTimeoutMs = Math.max(
        60_000,
        Number.parseInt(process.env.NUCLEUS_BACKEND_STARTUP_TIMEOUT_MS || '60000', 10) || 60_000,
      );
      const timeout = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          console.error('[Electron] Timed out waiting for Flask backend port');
          reject(new Error(`The backend did not finish starting within ${Math.round(startupTimeoutMs / 1000)} seconds`));
        }
      }, startupTimeoutMs);

      pythonProcess.stdout.on('data', (data) => {
        const output = data.toString();
        console.log(`[Flask] ${output.trim()}`);
        recordBackendOutput('stdout', output);

        for (const port of stdoutPortParser.feed(output)) acceptReportedPort(port);
      });

      pythonProcess.stderr.on('data', (data) => {
        const errOutput = data.toString();
        console.error(`[Flask Error] ${errOutput.trim()}`);
        recordBackendOutput('stderr', errOutput);

        for (const port of stderrPortParser.feed(errOutput)) {
          acceptReportedPort(port, ' (from stderr)');
        }
      });

      pythonProcess.on('close', (code, signal) => {
        console.log(`[Flask] Process exited with code ${code}`);
        pythonProcess = null;
        if (!resolved) {
          resolved = true;
          clearTimeout(timeout);
          reject(new Error(`Flask process exited with code ${code} before reporting port`));
          return;
        }
        // stopForQuit is the only intended way the running backend ends.
        if (ctx.isQuitting) return;
        backendExit = { code, signal: signal || null };
        recordBackendOutput('exit', `Backend stopped (code ${code}${signal ? `, ${signal}` : ''})`);
        onExit(backendExit);
      });

      pythonProcess.on('error', (err) => {
        console.error('[Flask] Failed to start:', err);
        recordBackendOutput('error', err.message);
        if (!resolved) {
          resolved = true;
          clearTimeout(timeout);
          reject(err);
        }
      });
    });
  }

  // The backend-diagnostics IPC snapshot.
  function diagnostics() {
    return {
      startupError: backendStartupError,
      output: backendOutputBuffer.slice(),
      pid: pythonProcess ? pythonProcess.pid : null,
      alive: pythonProcess !== null && !pythonProcess.killed,
      port: ctx.backendPort,
      exit: backendExit,
    };
  }

  // After start() rejected: keep the reason for backend-diagnostics and stop
  // the child that never announced a port.
  async function discardFailedStart(err) {
    console.error('[Electron] Failed to start Flask backend:', err.message);
    backendStartupError = err.message;
    const failedChild = pythonProcess;
    pythonProcess = null;
    await terminateOwnedChild(failedChild).catch(error => console.error('[Backend] Cleanup failed:', error.message));
  }

  // The startup-failure dialog: saves a report and offers to copy it.
  function showStartupFailure(err) {
    return showBackendStartupFailure({ app, dialog, clipboard, error: err,
      output: backendOutputBuffer, secrets });
  }

  // One shutdown attempt against the backend. Resolves {deferred, operations}:
  // deferred=true means the backend answered 409 because a critical operation
  // (ISO export/save/download) is still in flight and exiting now would leave
  // the user a truncated file. Any error/timeout counts as NOT deferred -- the
  // backend is unreachable or already gone, so the caller proceeds to kill.
  function requestBackendShutdown() {
    return new Promise((resolve) => {
      const req = http.request({
        hostname: '127.0.0.1',
        port: ctx.backendPort || 5000,
        path: '/api/mex/shutdown',
        method: 'POST',
        headers: { 'X-Nucleus-Token': ctx.backendToken },
        timeout: 2000
      }, (res) => {
        let body = '';
        res.on('data', (chunk) => { body += chunk; });
        res.on('end', () => {
          let operations = [];
          try { operations = JSON.parse(body).operations || []; } catch (e) { /* not JSON */ }
          resolve({ deferred: res.statusCode === 409, operations });
        });
      });

      req.on('error', (err) => {
        console.log('[Electron] Shutdown request failed:', err.message);
        resolve({ deferred: false, operations: [] });
      });

      req.on('timeout', () => {
        console.log('[Electron] Shutdown request timed out');
        req.destroy();
        resolve({ deferred: false, operations: [] });
      });

      req.end();
    });
  }

  // The backend half of app 'before-quit'. While the child is alive this holds
  // the quit (event.preventDefault, synchronously), asks the backend to stop,
  // force-kills what is left, and quits again.
  async function stopForQuit(event) {
    // Kill Flask backend
    if (pythonProcess && !pythonProcess.killed) {
      event.preventDefault(); // Prevent immediate quit
      console.log('[Electron] Attempting graceful Flask shutdown...');

      try {
        // Poll while the backend defers (critical op in flight). Bounded: an
        // export can legitimately run long, but past the deadline we fall back
        // to the old force-kill rather than lingering forever.
        const deadline = Date.now() + 120000;
        for (;;) {
          const result = await requestBackendShutdown();
          if (!result.deferred) break;
          if (Date.now() >= deadline) {
            console.log('[Electron] Giving up on deferred shutdown:', result.operations);
            break;
          }
          console.log('[Electron] Shutdown deferred by backend:', result.operations);
          await new Promise(resolve => setTimeout(resolve, 1000));
        }

        // Give it a moment to shut down
        await new Promise(resolve => setTimeout(resolve, 1000));
      } catch (e) {
        console.log('[Electron] Could not reach shutdown endpoint:', e.message);
      }

      // Now force kill if still running
      if (pythonProcess && !pythonProcess.killed) {
        console.log('[Electron] Force killing Flask process...');

        const ownedChild = pythonProcess;
        terminateOwnedChild(ownedChild).catch((error) => {
          console.error('[Electron] Failed to terminate owned backend child:', error);
        }).finally(() => {
          pythonProcess = null;
          app.quit();
        });
      } else {
        pythonProcess = null;
        app.quit();
      }
    }
  }

  return { start, diagnostics, discardFailedStart, showStartupFailure, stopForQuit };
}

module.exports = { createBackendRuntime };
