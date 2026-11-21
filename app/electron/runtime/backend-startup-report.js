'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');

function startupReport({ version, error, output, secrets = [], home = os.homedir(),
  system = { platform: os.platform(), release: os.release(), arch: os.arch(),
    cpu: os.cpus()[0]?.model || 'Unknown', memory: os.totalmem() } }) {
  const raw = [error?.message || String(error), ...output].join('\n');
  const numpyFailure = /(?:numpy|_multiarray_umath)/i.test(raw) && /(?:DLL load failed|Importing the numpy C-extensions failed)/i.test(raw);
  const message = numpyFailure
    ? 'A bundled library (NumPy) could not load.'
    : 'Nucleus could not start its backend.';
  let report = [
    `Nucleus ${version} — backend startup failure`,
    `OS: ${system.platform} ${system.release} (${system.arch})`,
    `CPU: ${system.cpu}`,
    `Memory: ${(system.memory / 1024 ** 3).toFixed(1)} GiB`,
    '', raw,
  ].join('\n');
  // The backend can fail before its own report scrubber is available. Never
  // copy the authentication secret or the user's home directory into a report.
  for (const secret of secrets.filter(Boolean)) report = report.split(secret).join('[redacted]');
  if (home) {
    const escaped = home.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    report = report.replace(new RegExp(escaped, 'gi'), '[home]');
    report = report.split(home.replaceAll('\\', '/')).join('[home]');
  }
  return { message, report };
}

async function showBackendStartupFailure({ app, dialog, clipboard, error, output, secrets }) {
  const { message, report } = startupReport({ version: app.getVersion(), error, output, secrets });
  let detail = 'Copy the details when reporting this error.';
  try {
    // Keep one bounded failure report. This works even when Python never reaches
    // its logger, and does not need the user's vault or a working backend.
    const folder = app.getPath('logs');
    await fs.mkdir(folder, { recursive: true });
    const file = path.join(folder, 'backend-startup.log');
    await fs.writeFile(file, report, { encoding: 'utf8', mode: 0o600 });
    detail += `\n\nSaved to: ${file}`;
  } catch {
    detail += '\n\nThe report could not be saved. You can still copy it.';
  }
  const { response } = await dialog.showMessageBox({
    type: 'error', title: 'Nucleus could not start', message, detail,
    buttons: ['Copy details and close', 'Close'], defaultId: 0, cancelId: 1,
    noLink: true,
  });
  if (response === 0) clipboard.writeText(report);
}

module.exports = { startupReport, showBackendStartupFailure };
