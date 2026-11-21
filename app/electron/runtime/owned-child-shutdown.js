'use strict';

function terminateOwnedChild(child, options = {}) {
  if (!child || child.killed || child.exitCode != null || child.signalCode != null) return Promise.resolve();
  const platform = options.platform || process.platform;
  const isWine = options.isWine ?? Boolean(process.env.WINEPREFIX || process.env.WINE);
  const execFile = options.exec || require('child_process').exec;
  const killGroup = options.killGroup || process.kill.bind(process);
  const pid = Number(child.pid);
  if (!Number.isSafeInteger(pid) || pid <= 0) {
    return Promise.reject(new Error('Owned child has no valid PID'));
  }

  if (platform === 'win32' && !isWine) {
    return new Promise((resolve) => {
      execFile(`taskkill /F /T /PID ${pid}`, (error) => {
        if (error) {
          try { child.kill('SIGKILL'); } catch (_) { /* exact child already gone */ }
        }
        resolve();
      });
    });
  }

  try {
    killGroup(-pid);
  } catch (_) {
    try { child.kill('SIGKILL'); } catch (_) { /* exact child already gone */ }
  }
  return Promise.resolve();
}

module.exports = { terminateOwnedChild };
