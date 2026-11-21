#!/usr/bin/env node

const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');

const ROOT_DIR = path.resolve(__dirname, '..', '..', '..', 'app');  // the app/ folder
const ARTIFACTS_ROOT = path.join(ROOT_DIR, 'scratch', 'ingame', 'dolphin');
const INPUT_HELPER = path.join(__dirname, 'win-input.ps1');
const WINDOW_HELPER = path.join(__dirname, 'win-window.ps1');
const DEFAULT_SCENARIO = path.join(__dirname, 'scenarios', 'boot-and-hold-a.json');

function printHelp() {
  console.log(`Dolphin smoke driver

Usage:
  node tools/ingame/dolphin/driver.js --iso "C:\\path\\to\\game.iso" [options]

Options:
  --iso <path>                ISO to boot. Required unless --help is used.
  --dolphin <path>            Dolphin executable. Defaults to Slippi netplay if found.
  --scenario <path>           Scenario JSON. Default: tools/ingame/dolphin/scenarios/boot-and-hold-a.json
  --template-user-dir <path>  Template Dolphin User dir. Defaults to "<dolphin dir>\\User" when present.
  --run-dir <path>            Use an explicit artifact directory for this run.
  --audio-dump                Dump Dolphin DSP audio into the isolated run dir.
  --keep-open                 Leave Dolphin running after the scenario finishes.
  --dry-run                   Build the isolated config and print the launch plan without starting Dolphin.
  --help                      Show this message.

Notes:
  - This harness is Windows-only.
  - Input is sent with a PowerShell helper that focuses the Dolphin window and emits keyboard events.
  - Screenshots are captured from the Dolphin window into each run directory.
  - The temporary run copy forces a known GCPad1 keyboard mapping:
      A=X, B=Z, X=C, Y=S, Z=D, Start=ENTER, stick=arrow keys, L=Q, R=W
`);
}

function parseArgs(argv) {
  const result = {
    keepOpen: false,
    dryRun: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--help' || token === '-h') {
      result.help = true;
      continue;
    }
    if (token === '--keep-open') {
      result.keepOpen = true;
      continue;
    }
    if (token === '--dry-run') {
      result.dryRun = true;
      continue;
    }
    if (token === '--texture-dump') {
      result['texture-dump'] = true;
      continue;
    }
    if (token === '--audio-dump') {
      result['audio-dump'] = true;
      continue;
    }
    if (!token.startsWith('--')) {
      throw new Error(`Unexpected argument: ${token}`);
    }
    const key = token.slice(2);
    const value = argv[i + 1];
    if (!value || value.startsWith('--')) {
      throw new Error(`Missing value for --${key}`);
    }
    result[key] = value;
    i += 1;
  }

  return result;
}

function assertWindows() {
  if (process.platform !== 'win32') {
    throw new Error('tools/ingame/dolphin/driver.js currently only supports Windows.');
  }
}

function timestampSlug() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

function safeSlug(value) {
  return String(value || 'run')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64) || 'run';
}

function safeFileName(value) {
  return String(value || 'capture')
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, '-')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 100) || 'capture';
}

function ensureExists(targetPath, label) {
  if (!fs.existsSync(targetPath)) {
    throw new Error(`${label} does not exist: ${targetPath}`);
  }
}

function firstExisting(paths) {
  for (const candidate of paths) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function detectDefaultDolphin() {
  const appData = process.env.APPDATA || '';
  return firstExisting([
    process.env.SLIPPI_DOLPHIN_EXE,
    path.join(appData, 'Slippi Launcher', 'netplay', 'Slippi Dolphin.exe'),
    path.join(appData, 'Slippi Launcher', 'playback', 'Slippi Dolphin.exe'),
  ]);
}

function detectTemplateUserDir(dolphinExe) {
  if (!dolphinExe) {
    return null;
  }
  const siblingUserDir = path.join(path.dirname(dolphinExe), 'User');
  if (fs.existsSync(siblingUserDir) && fs.statSync(siblingUserDir).isDirectory()) {
    return siblingUserDir;
  }
  return null;
}

function parseIni(text) {
  const sections = new Map();
  let currentSection = '';
  sections.set(currentSection, new Map());

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith(';') || line.startsWith('#')) {
      continue;
    }
    const sectionMatch = line.match(/^\[(.+?)\]$/);
    if (sectionMatch) {
      currentSection = sectionMatch[1];
      if (!sections.has(currentSection)) {
        sections.set(currentSection, new Map());
      }
      continue;
    }
    const keyMatch = line.match(/^([^=]+?)\s*=\s*(.*)$/);
    if (keyMatch) {
      sections.get(currentSection).set(keyMatch[1].trim(), keyMatch[2]);
    }
  }

  return sections;
}

function stringifyIni(sections) {
  const lines = [];
  let firstSection = true;

  for (const [sectionName, values] of sections.entries()) {
    if (sectionName !== '') {
      if (!firstSection) {
        lines.push('');
      }
      lines.push(`[${sectionName}]`);
      firstSection = false;
    }
    for (const [key, value] of values.entries()) {
      lines.push(`${key} = ${value}`);
    }
  }

  return `${lines.join(os.EOL)}${os.EOL}`;
}

function upsertIniValue(sections, sectionName, key, value) {
  if (!sections.has(sectionName)) {
    sections.set(sectionName, new Map());
  }
  sections.get(sectionName).set(key, value);
}

function writeIni(filePath, mutate) {
  const source = fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf8') : '';
  const sections = parseIni(source);
  mutate(sections);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, stringifyIni(sections), 'utf8');
}

function copyTemplateConfig(templateUserDir, targetUserDir) {
  const sourceConfigDir = templateUserDir ? path.join(templateUserDir, 'Config') : null;
  const targetConfigDir = path.join(targetUserDir, 'Config');
  fs.mkdirSync(targetConfigDir, { recursive: true });

  if (sourceConfigDir && fs.existsSync(sourceConfigDir)) {
    fs.cpSync(sourceConfigDir, targetConfigDir, { recursive: true });
  }
}

// Seed the Slippi login files the netplay build needs to boot straight into the
// game. Slippi/ holds user.json (the login file) plus the connect-code files;
// without it the build stops on its "Access instructions to log-in" gate and the
// Melee menus never load. Roster/stage unlocks are handled separately by the
// Slippi Gecko codes, so the GC memory card does not need to be seeded.
function copyTemplateUserData(templateUserDir, targetUserDir) {
  if (!templateUserDir) {
    return;
  }
  const source = path.join(templateUserDir, 'Slippi');
  if (!fs.existsSync(source)) {
    return;
  }
  const target = path.join(targetUserDir, 'Slippi');
  fs.mkdirSync(target, { recursive: true });
  fs.cpSync(source, target, { recursive: true });
}

function patchDolphinConfig(userDir, pipeName = 'slippibot1') {
  const dolphinIni = path.join(userDir, 'Config', 'Dolphin.ini');
  writeIni(dolphinIni, (sections) => {
    upsertIniValue(sections, 'Input', 'BackgroundInput', 'True');
    upsertIniValue(sections, 'Interface', 'ConfirmStop', 'False');
    upsertIniValue(sections, 'Interface', 'PauseOnFocusLost', 'False');
    upsertIniValue(sections, 'Display', 'Fullscreen', 'False');
    upsertIniValue(sections, 'Display', 'RenderWindowAutoSize', 'False');
    upsertIniValue(sections, 'Display', 'RenderWindowWidth', '1280');
    upsertIniValue(sections, 'Display', 'RenderWindowHeight', '960');
    // Port 1 is a Standard Controller driven over Slippi's named pipe; the
    // other ports are off so the CSS has exactly one (port-1) cursor. A CPU
    // opponent is added in-game via the port-4 "N/A door".
    upsertIniValue(sections, 'Core', 'SIDevice0', '6');
    upsertIniValue(sections, 'Core', 'SIDevice1', '0');
    upsertIniValue(sections, 'Core', 'SIDevice2', '0');
    upsertIniValue(sections, 'Core', 'SIDevice3', '0');
  });

  // Drive port 1 from Dolphin's always-open named pipe (\\.\pipe\<pipeName>;
  // slippibot1 by default). A 2nd instance (for the desync debugger) uses a
  // distinct name e.g. slippibot2 so the two emulators don't collide on the
  // global named pipe. Bindings mirror libmelee's controller profile: digital
  // buttons map to `Button <NAME>` and the sticks to `Axis MAIN/C X|Y +|-`, so
  // the pipe protocol (PRESS/RELEASE <btn>, SET MAIN <x> <y>, FLUSH) reaches it.
  const gcPadIni = path.join(userDir, 'Config', 'GCPadNew.ini');
  writeIni(gcPadIni, (sections) => {
    const p = 'GCPad1';
    sections.set(p, new Map()); // wipe any inherited keyboard mapping
    upsertIniValue(sections, p, 'Device', `Pipe/0/${pipeName}`);
    upsertIniValue(sections, p, 'Buttons/A', 'Button A');
    upsertIniValue(sections, p, 'Buttons/B', 'Button B');
    upsertIniValue(sections, p, 'Buttons/X', 'Button X');
    upsertIniValue(sections, p, 'Buttons/Y', 'Button Y');
    upsertIniValue(sections, p, 'Buttons/Z', 'Button Z');
    upsertIniValue(sections, p, 'Buttons/L', 'Button L');
    upsertIniValue(sections, p, 'Buttons/R', 'Button R');
    upsertIniValue(sections, p, 'Buttons/Start', 'Button START');
    upsertIniValue(sections, p, 'Buttons/Threshold', '50.0');
    upsertIniValue(sections, p, 'Main Stick/Up', 'Axis MAIN Y +');
    upsertIniValue(sections, p, 'Main Stick/Down', 'Axis MAIN Y -');
    upsertIniValue(sections, p, 'Main Stick/Left', 'Axis MAIN X -');
    upsertIniValue(sections, p, 'Main Stick/Right', 'Axis MAIN X +');
    upsertIniValue(sections, p, 'Main Stick/Radius', '100.0');
    upsertIniValue(sections, p, 'D-Pad/Up', 'Button D_UP');
    upsertIniValue(sections, p, 'D-Pad/Down', 'Button D_DOWN');
    upsertIniValue(sections, p, 'D-Pad/Left', 'Button D_LEFT');
    upsertIniValue(sections, p, 'D-Pad/Right', 'Button D_RIGHT');
    upsertIniValue(sections, p, 'C-Stick/Up', 'Axis C Y +');
    upsertIniValue(sections, p, 'C-Stick/Down', 'Axis C Y -');
    upsertIniValue(sections, p, 'C-Stick/Left', 'Axis C X -');
    upsertIniValue(sections, p, 'C-Stick/Right', 'Axis C X +');
    upsertIniValue(sections, p, 'C-Stick/Radius', '100.0');
    upsertIniValue(sections, p, 'Triggers/L', 'Button L');
    upsertIniValue(sections, p, 'Triggers/R', 'Button R');
    upsertIniValue(sections, p, 'Triggers/L-Analog', 'Axis L -+');
    upsertIniValue(sections, p, 'Triggers/R-Analog', 'Axis R -+');
    upsertIniValue(sections, p, 'Triggers/Threshold', '90.0');
    sections.set('GCPad3', new Map()); // drop the inherited port-3 keyboard cursor
  });
}

// Enable Dolphin's texture dump (and hires load) BEFORE boot, so a texture-pack
// run dumps every CSP placeholder it renders. GFX.ini is read once at startup,
// so this must be written into the isolated run User dir before Dolphin launches
// (the backend's start-listening also sets it, but that lands after boot). Mirrors
// backend set_dolphin_texture_settings: [Settings] DumpTextures / HiresTextures.
function patchGfxTextureSettings(userDir, { dump = true, hires = true } = {}) {
  const gfxIni = path.join(userDir, 'Config', 'GFX.ini');
  writeIni(gfxIni, (sections) => {
    upsertIniValue(sections, 'Settings', 'DumpTextures', dump ? 'True' : 'False');
    upsertIniValue(sections, 'Settings', 'HiresTextures', hires ? 'True' : 'False');
  });
}

function patchDspAudioDumpSettings(userDir, dumpDir) {
  fs.mkdirSync(dumpDir, { recursive: true });
  const dolphinIni = path.join(userDir, 'Config', 'Dolphin.ini');
  writeIni(dolphinIni, (sections) => {
    upsertIniValue(sections, 'General', 'DumpPath', dumpDir);
    upsertIniValue(sections, 'DSP', 'DumpAudio', 'True');
    upsertIniValue(sections, 'DSP', 'DumpAudioSilent', 'False');
  });
}

function readScenario(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8');
  const data = JSON.parse(raw);
  if (!Array.isArray(data.steps)) {
    throw new Error(`Scenario is missing a steps array: ${filePath}`);
  }
  return data;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function createLogger(runDir) {
  fs.mkdirSync(runDir, { recursive: true });
  const logFile = path.join(runDir, 'driver.log');
  return (message) => {
    const line = `[${new Date().toISOString()}] ${message}`;
    console.log(line);
    fs.appendFileSync(logFile, `${line}${os.EOL}`, 'utf8');
  };
}

function runHelper(action, pid, key, durationMs) {
  const args = [
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    INPUT_HELPER,
    '-ProcessId',
    String(pid),
    '-Action',
    action,
  ];

  if (key) {
    args.push('-Key', key);
  }
  if (durationMs !== undefined && durationMs !== null) {
    args.push('-DurationMs', String(durationMs));
  }

  const result = cp.spawnSync('powershell.exe', args, {
    cwd: ROOT_DIR,
    encoding: 'utf8',
  });

  if (result.status !== 0) {
    const stderr = (result.stderr || '').trim();
    const stdout = (result.stdout || '').trim();
    throw new Error(stderr || stdout || `PowerShell helper failed for action ${action}`);
  }
}

function runWindowHelper(action, pid, outputPath) {
  const args = [
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    WINDOW_HELPER,
    '-ProcessId',
    String(pid),
    '-Action',
    action,
  ];

  if (outputPath) {
    args.push('-OutputPath', outputPath);
  }

  const result = cp.spawnSync('powershell.exe', args, {
    cwd: ROOT_DIR,
    encoding: 'utf8',
  });

  if (result.status !== 0) {
    const stderr = (result.stderr || '').trim();
    const stdout = (result.stdout || '').trim();
    throw new Error(stderr || stdout || `PowerShell window helper failed for action ${action}`);
  }

  return (result.stdout || '').trim();
}

function captureWindow(child, runDir, name, log) {
  if (child.exitCode !== null) {
    throw new Error('Cannot capture a screenshot because Dolphin has already exited.');
  }

  const screenshotDir = path.join(runDir, 'screenshots');
  fs.mkdirSync(screenshotDir, { recursive: true });

  const targetPath = path.join(screenshotDir, `${safeFileName(name)}.png`);
  runWindowHelper('capture', child.pid, targetPath);
  log(`Captured screenshot: ${targetPath}`);
  return targetPath;
}

function captureWindowSafe(child, runDir, name, log) {
  try {
    return captureWindow(child, runDir, name, log);
  } catch (error) {
    log(`Screenshot capture skipped: ${error.message}`);
    return null;
  }
}

async function runScenario(child, scenario, runDir, log) {
  for (let index = 0; index < scenario.steps.length; index += 1) {
    const step = scenario.steps[index];
    if (child.exitCode !== null) {
      throw new Error(`Dolphin exited before step ${index + 1} completed.`);
    }

    const type = step.type;
    log(`Step ${index + 1}/${scenario.steps.length}: ${JSON.stringify(step)}`);

    if (type === 'wait') {
      await sleep(step.ms || 0);
      continue;
    }
    if (type === 'focus') {
      runHelper('focus', child.pid);
      continue;
    }
    if (type === 'tap') {
      runHelper('tap', child.pid, step.key, step.durationMs ?? 80);
      continue;
    }
    if (type === 'keyDown') {
      runHelper('keyDown', child.pid, step.key);
      continue;
    }
    if (type === 'keyUp') {
      runHelper('keyUp', child.pid, step.key);
      continue;
    }
    if (type === 'screenshot' || type === 'checkpoint') {
      const label = step.name || `step-${index + 1}`;
      captureWindow(child, runDir, label, log);
      continue;
    }

    throw new Error(`Unsupported step type: ${type}`);
  }
}

function killProcessTree(pid, log) {
  const result = cp.spawnSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
    cwd: ROOT_DIR,
    encoding: 'utf8',
  });
  if (result.status === 0) {
    log(`Stopped Dolphin process tree for PID ${pid}.`);
    return;
  }

  const stderr = (result.stderr || '').trim();
  const stdout = (result.stdout || '').trim();
  throw new Error(stderr || stdout || `Failed to stop Dolphin PID ${pid}`);
}

function buildRunDir(explicitRunDir, scenarioName) {
  if (explicitRunDir) {
    const resolved = path.resolve(ROOT_DIR, explicitRunDir);
    if (fs.existsSync(resolved) && fs.readdirSync(resolved).length > 0) {
      throw new Error(`Run directory already exists and is not empty: ${resolved}`);
    }
    return resolved;
  }

  return path.join(ARTIFACTS_ROOT, `${timestampSlug()}-${safeSlug(scenarioName)}`);
}

async function main() {
  assertWindows();

  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  if (!args.iso) {
    throw new Error('--iso is required.');
  }

  const dolphinExe = path.resolve(args.dolphin || detectDefaultDolphin() || '');
  if (!dolphinExe || !fs.existsSync(dolphinExe)) {
    throw new Error('Could not find a Dolphin executable. Pass --dolphin explicitly.');
  }

  const isoPath = path.resolve(args.iso);
  ensureExists(isoPath, 'ISO');
  ensureExists(INPUT_HELPER, 'PowerShell input helper');
  ensureExists(WINDOW_HELPER, 'PowerShell window helper');

  const scenarioPath = path.resolve(args.scenario || DEFAULT_SCENARIO);
  ensureExists(scenarioPath, 'Scenario');
  const scenario = readScenario(scenarioPath);

  const templateUserDir = args['template-user-dir']
    ? path.resolve(args['template-user-dir'])
    : detectTemplateUserDir(dolphinExe);

  if (templateUserDir) {
    ensureExists(templateUserDir, 'Template user dir');
  }

  const runDir = buildRunDir(args['run-dir'], scenario.name || path.basename(scenarioPath, '.json'));
  const log = createLogger(runDir);
  const userDir = path.join(runDir, 'User');

  fs.mkdirSync(runDir, { recursive: true });
  fs.mkdirSync(userDir, { recursive: true });
  fs.mkdirSync(path.join(runDir, 'screenshots'), { recursive: true });
  copyTemplateConfig(templateUserDir, userDir);
  copyTemplateUserData(templateUserDir, userDir);
  // --pipe-index N drives port 1 over \\.\pipe\slippibot<N> (default 1); a 2nd
  // instance uses 2 so two emulators don't fight over the same named pipe.
  const pipeIndex = args['pipe-index'] ? parseInt(args['pipe-index'], 10) : 1;
  patchDolphinConfig(userDir, `slippibot${pipeIndex}`);
  // --texture-dump: turn on texture dumping (+ hires load) for the texture-pack
  // harvest flow, written before boot so Dolphin picks it up this session.
  if (args['texture-dump']) {
    patchGfxTextureSettings(userDir, { dump: true, hires: true });
    log('Texture dump + hires load enabled in GFX.ini (texture-pack mode).');
  }
  if (args['audio-dump']) {
    patchDspAudioDumpSettings(userDir, path.join(runDir, 'Dump'));
    log('DSP audio dumping enabled in Dolphin.ini.');
  }

  const metadata = {
    createdAt: new Date().toISOString(),
    dolphinExe,
    isoPath,
    scenarioPath,
    templateUserDir,
    runDir,
    userDir,
    audioDump: !!args['audio-dump'],
    dryRun: args.dryRun,
  };

  fs.writeFileSync(path.join(runDir, 'run.json'), JSON.stringify(metadata, null, 2), 'utf8');

  log(`Run directory: ${runDir}`);
  log(`Dolphin executable: ${dolphinExe}`);
  log(`ISO: ${isoPath}`);
  log(`Scenario: ${scenarioPath}`);
  log(`Template user dir: ${templateUserDir || '<none>'}`);

  if (args.dryRun) {
    log('Dry run complete. Dolphin was not started.');
    return;
  }

  const dolphinArgs = ['-u', userDir, '-b', '-e', isoPath];
  log(`Launching Dolphin with args: ${JSON.stringify(dolphinArgs)}`);

  let child;
  try {
    child = cp.spawn(dolphinExe, dolphinArgs, {
      cwd: path.dirname(dolphinExe),
      windowsHide: false,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (error) {
    throw new Error(`Failed to launch Dolphin: ${error.message}`);
  }

  fs.writeFileSync(path.join(runDir, 'dolphin.pid'), `${child.pid}${os.EOL}`, 'utf8');
  child.stdout.on('data', (chunk) => {
    fs.appendFileSync(path.join(runDir, 'dolphin.stdout.log'), chunk);
  });
  child.stderr.on('data', (chunk) => {
    fs.appendFileSync(path.join(runDir, 'dolphin.stderr.log'), chunk);
  });

  let childExit = null;
  child.on('exit', (code, signal) => {
    childExit = { code, signal, exitedAt: new Date().toISOString() };
    fs.writeFileSync(path.join(runDir, 'dolphin.exit.json'), JSON.stringify(childExit, null, 2), 'utf8');
    log(`Dolphin exited with code=${code} signal=${signal}`);
  });

  try {
    await runScenario(child, scenario, runDir, log);
    captureWindowSafe(child, runDir, 'final', log);
    log('Scenario completed.');
  } catch (error) {
    log(`Scenario failed: ${error.message}`);
    captureWindowSafe(child, runDir, 'failure', log);
    if (child.exitCode === null) {
      killProcessTree(child.pid, log);
    }
    throw error;
  }

  if (!args.keepOpen && child.exitCode === null) {
    killProcessTree(child.pid, log);
  } else if (args.keepOpen) {
    log('Leaving Dolphin running because --keep-open was set.');
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
