const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { startupReport, showBackendStartupFailure } = require('../../app/electron/runtime/backend-startup-report');

const failure = {
  version: '0.8.3', error: new Error('Process exited with code 1'),
  output: ['Importing the numpy C-extensions failed.',
    'Original error was: DLL load failed while importing _multiarray_umath: Error en una rutina de inicialización de biblioteca de vínculos dinámicos (DLL).'],
  system: { platform: 'win32', release: '10.0.19045', arch: 'x64', cpu: 'Example CPU', memory: 8 * 1024 ** 3 },
};

test('reported NumPy crash retains the localized cause and host information', () => {
  const { message, report } = startupReport(failure);
  assert.match(message, /NumPy/);
  for (const text of ['0.8.3', '10.0.19045', 'x64', 'Example CPU', '8.0 GiB', 'inicialización', ...failure.output]) {
    assert.ok(report.includes(text));
  }
});

test('unrelated startup failures retain their cause without blaming NumPy', () => {
  const { message, report } = startupReport({ ...failure, output: ['Permission denied'] });
  assert.doesNotMatch(message, /NumPy/);
  assert.match(report, /Permission denied/);
});

test('reports remove backend secrets and native or slash-form home paths', () => {
  const { report } = startupReport({ ...failure, home: 'C:\\Users\\A.Person', secrets: ['local-token'],
    output: ['C:\\Users\\A.Person\\Temp\\numpy.pyd', 'C:/Users/A.Person/Temp/numpy.pyd', 'Token: local-token'] });
  assert.doesNotMatch(report, /A\.Person|local-token/);
  assert.match(report, /\[home\]/);
  assert.match(report, /\[redacted\]/);
});

test('startup failure saves a report and copies the same details without a backend', async () => {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), 'nucleus-startup-report-test-'));
  try {
    let options, copied;
    await showBackendStartupFailure({ ...failure,
      app: { getVersion: () => '0.8.3', getPath: () => folder },
      dialog: { showMessageBox: async value => { options = value; return { response: 0 }; } },
      clipboard: { writeText: value => { copied = value; } },
    });
    assert.equal(await fs.readFile(path.join(folder, 'backend-startup.log'), 'utf8'), copied);
    assert.match(copied, /_multiarray_umath/);
    assert.match(options.detail, /backend-startup\.log/);
    assert.equal(options.cancelId, 1);
  } finally {
    await fs.unlink(path.join(folder, 'backend-startup.log')).catch(() => {});
    await fs.rmdir(folder);
  }
});

test('a read-only log location still allows copying; Close leaves the clipboard alone', async () => {
  for (const response of [0, 1]) {
    let copied = false;
    await showBackendStartupFailure({ ...failure,
      app: { getVersion: () => '0.8.3', getPath: () => { throw new Error('read-only'); } },
      dialog: { showMessageBox: async options => {
        assert.match(options.detail, /could not be saved/);
        return { response };
      } },
      clipboard: { writeText: () => { copied = true; } },
    });
    assert.equal(copied, response === 0);
  }
});
