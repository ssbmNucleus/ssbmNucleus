// Check the built, self-contained guide in a fresh headless browser.
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { mkdirSync, readdirSync } from 'node:fs';

const guideDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');  // docs/guide
const root = resolve(guideDir, '..', '..', 'app');  // the app/ folder
const { chromium } = createRequire(join(root, 'package.json'))('playwright-core');
const output = join(root, 'docs/guide/.capture');
// One H1 per section file — counted, not hardcoded, so adding or
// dropping a chapter doesn't leave this failing on a correct build.
const expectedChapters = readdirSync(join(guideDir, 'sections'))
  .filter((name) => name.endsWith('.md')).length;
mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto(pathToFileURL(join(guideDir, 'dist/guide.html')).href);
  await page.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())));
  const checks = await page.evaluate(() => ({
    chapters: document.querySelectorAll('h1').length,
    images: document.images.length,
    brokenImages: [...document.images].filter(image => !image.naturalWidth).length,
    brokenLinks: [...document.querySelectorAll('a[href^="#"]')].filter(link => !document.getElementById(link.hash.slice(1))).length,
    placeholders: document.querySelectorAll('.missing').length,
  }));
  await page.getByRole('link', { name: 'Settings', exact: true }).first().click();
  await page.screenshot({ path: join(output, 'review-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('[id="9-settings"]').scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(output, 'review-mobile.png') });
  checks.mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  console.log(JSON.stringify(checks, null, 2));
  if (checks.chapters !== expectedChapters || checks.brokenImages || checks.brokenLinks || checks.placeholders || checks.mobileOverflow) {
    process.exitCode = 1;
  }
} finally {
  await browser.close();
}
