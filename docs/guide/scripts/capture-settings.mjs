// Capture current Settings from a separate, real Electron app/profile/vault.
// The private runtime has its own Vite port handoff; no shared .vite-port changes.
// Usage: node docs/guide/scripts/capture-settings.mjs
import { cpSync, existsSync, mkdirSync, writeFileSync, symlinkSync, createWriteStream } from 'node:fs';
import { createRequire } from 'node:module';
import { userInfo } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';
import { createServer } from '../../../app/frontend/node_modules/vite/dist/node/index.js';
import react from '../../../app/frontend/node_modules/@vitejs/plugin-react/dist/index.js';

const guideDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');  // docs/guide
const root = resolve(guideDir, '..', '..', 'app');  // the app/ folder
const scratch = join(root, 'docs/guide/.capture');
const runtime = join(scratch, 'settings-runtime');
const output = join(guideDir, 'img');
const { _electron } = createRequire(join(root, 'package.json'))('playwright-core');
mkdirSync(join(runtime, 'frontend'), { recursive: true });
mkdirSync(join(output, '_raw'), { recursive: true });
cpSync(join(root, 'electron'), join(runtime, 'electron'), { recursive: true });
cpSync(join(root, 'package.json'), join(runtime, 'package.json'));
for (const name of ['backend', 'utility', 'venv', 'node_modules', 'tools', 'scripts']) {
  if (!existsSync(join(runtime, name))) symlinkSync(join(root, name), join(runtime, name), 'junction');
}
if (!existsSync(join(runtime, 'frontend/public'))) symlinkSync(join(root, 'frontend/public'), join(runtime, 'frontend/public'), 'junction');
process.env.VITE_SHIP_GATES = '1';
const vite = await createServer({ configFile: false, root: join(root, 'frontend'),
  cacheDir: join(scratch, 'settings-vite-cache'),
  plugins: [react()], base: './', server: { host: 'localhost', port: 43197, open: false,
    fs: { allow: [root] } },
  resolve: { alias: { '@storage': join(root, 'storage') } },
});
let app;
try {
  await vite.listen();
  const port = vite.httpServer.address().port;
  writeFileSync(join(runtime, 'frontend/.vite-port'), String(port));
  console.log(`[settings] isolated Vite port ${port}`);
  app = await _electron.launch({ executablePath: join(root, 'node_modules/electron/dist/electron.exe'),
    cwd: runtime, args: ['.'], timeout: 90000, env: { ...process.env,
      NUCLEUS_USERDATA_DIR: join(scratch, 'settings-profile'),
      NUCLEUS_STORAGE_DIR: join(scratch, 'storage'), NUCLEUS_NO_UPDATE_CHECK: '1',
      NUCLEUS_DISABLE_DEVTOOLS: '1',
      NUCLEUS_COMBO_VIDEO: '0', NUCLEUS_RANDALL: '0', NUCLEUS_ASSISTANT: '0',
    } });
  const log = createWriteStream(join(scratch, 'settings-capture.log'));
  app.process().stdout?.on('data', data => log.write(data));
  app.process().stderr?.on('data', data => log.write(data));
  const page = await app.firstWindow({ timeout: 90000 });
  page.on('dialog', d => d.dismiss());
  page.on('pageerror', e => console.log(`[page] ${e.message}`));
  await page.waitForLoadState('domcontentloaded');
  await app.evaluate(({ BrowserWindow }) => {
    const win = BrowserWindow.getAllWindows()[0];
    win.setResizable(true); win.setMinimumSize(640, 360); win.setContentSize(1600, 900);
  });
  await page.evaluate(() => {
    localStorage.setItem('settings_master_volume', '0');
    localStorage.setItem('nucleus_app_mode', 'nucleus');
  });
  await page.reload();
  await page.waitForSelector('.app-tabs, .first-run-overlay', { timeout: 90000 });
  if (await page.locator('.first-run-overlay').count()) {
    console.log('[settings] first-run setup shown');
    await page.screenshot({ path: join(output, '_raw/settings-setup.png') });
    // Existing profiles can dismiss setup; a fresh one completes the real extraction.
    const cancel = page.locator('.first-run-cancel-button');
    if (await cancel.count()) await cancel.click();
    else {
      await page.locator('.first-run-modal .btn-primary').first().click();
      await sleep(5000);
      const start = page.getByRole('button', { name: 'Start Setup', exact: true });
      if (await start.count()) await start.click();
      console.log('[settings] waiting for real setup extraction');
      await page.getByText('Setup Complete!', { exact: true }).waitFor({ timeout: 1200000 });
      await page.locator('.first-run-modal .btn-primary').first().click();
    }
  }
  const shot = async (id, selector) => {
    await sleep(1200);
    await page.addStyleTag({ content: '.debug-tier { display: none !important; }' });
    // Replace only identifying paths, never UI state or feature text.
    await page.evaluate(({ root, username }) => {
      const replace = value => value.split(root).join('C:\\Nucleus').split(username).join('you');
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) walker.currentNode.nodeValue = replace(walker.currentNode.nodeValue);
      for (const el of document.querySelectorAll('input,textarea')) el.value = replace(el.value || '');
    }, { root, username: process.env.USERNAME || userInfo().username });
    const target = selector ? page.locator(selector) : page;
    await target.screenshot({ path: join(output, `${id}.png`) });
    const viewport = await page.evaluate(() => ({ w: innerWidth, h: innerHeight, dpr: devicePixelRatio }));
    writeFileSync(join(output, `${id}.json`), JSON.stringify({ viewport,
      marks: [], crop: selector || null, captured: '2026-09-08', source: 'capture-settings.mjs; real isolated app, signed out' }, null, 2));
    console.log(`[settings] ${id}`);
  };
  await shot('02-tabs', 'header.app-header');
  await page.getByRole('button', { name: 'Install', exact: true }).click();
  await page.getByRole('button', { name: 'Create Project', exact: true }).waitFor();
  await shot('05-project-selector');
  await page.getByRole('button', { name: 'Create Project', exact: true }).click();
  await page.locator('.project-name-input').fill('Guide Build');
  await shot('05-project-name');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  for (const [label, id] of [['General','09-settings'], ['Files & setup','09-files-setup']]) {
    await page.getByRole('tab', { name: label, exact: true }).click();
    await shot(id);
  }
  await page.getByRole('tab', { name: 'General', exact: true }).click();
  await page.getByRole('button', { name: 'Report a Bug', exact: true }).click();
  await shot('11-bug-report');
  await page.keyboard.press('Escape');
  await page.reload();
  await page.waitForSelector('.brand-toggle');
  await page.locator('.brand-toggle').click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('tab', { name: 'Cloud', exact: true }).click();
  await page.getByRole('button', { name: 'Mobile setup guide', exact: true }).click();
  await shot('08-mobile-setup', '.vault-mobile-guide');
} catch (error) {
  if (app?.windows()[0]) await app.windows()[0].screenshot({ path: join(output, '_raw/settings-failed.png') }).catch(() => {});
  throw error;
} finally {
  // app.close operates on this exact Playwright-launched instance. No PID/name sweeps.
  if (app) await app.close();
  await vite.close();
}
