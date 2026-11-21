#!/usr/bin/env node
// Website screenshots for the guide: the download page and a mod post with its
// "Add to Nucleus" button. Uses the locally installed Chrome through
// playwright-core (channel: "chrome"), so no browser download is needed.
//
//   node docs/guide/scripts/capture-web.mjs [--site https://ssbmnucleus.net] [--post <url>]
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const NUCLEUS = resolve(__dirname, "..", "..", "..", "app");  // the app/ folder
const GUIDE_DIR = resolve(__dirname, "..");               // docs/guide
const { chromium } = createRequire(join(NUCLEUS, "package.json"))("playwright-core");
const OUT = join(GUIDE_DIR, "img");
const RAW = join(OUT, "_raw");
mkdirSync(RAW, { recursive: true });
const PYTHON = existsSync(join(NUCLEUS, "venv", "Scripts", "python.exe")) ? join(NUCLEUS, "venv", "Scripts", "python.exe") : "python";

const argValue = (f, d) => { const i = process.argv.indexOf(f); return i >= 0 ? process.argv[i + 1] : d; };
const SITE = argValue("--site", "https://ssbmnucleus.net").replace(/\/$/, "");
const POST = argValue("--post", null);
const SHARE_PATH = argValue("--share", "/replay/kgck9a61gy1s");
const MOBILE = argValue("--mobile", "https://tracker.ssbmnucleus.net");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
page.on("download", (d) => d.cancel().catch(() => {}));

async function shot(id, opts = {}) {
  const marks = [];
  for (const sel of opts.marks || []) {
    const loc = typeof sel === "string" ? page.locator(sel).first() : sel;
    const b = await loc.boundingBox({ timeout: 3000 }).catch(() => null);
    if (b) marks.push({ kind: "ring", box: { x: b.x, y: b.y, w: b.width, h: b.height }, pad: opts.pad ?? 12 });
    else console.warn(`[web]   no box for ${sel}`);
  }
  let clip;
  if (opts.region) {
    const b = await page.locator(opts.region).first().boundingBox();
    if (b) {
      clip = { x: Math.max(0, b.x - 20), y: Math.max(0, b.y - 20), width: b.width + 40, height: b.height + 40 };
      for (const mark of marks) { mark.box.x -= clip.x; mark.box.y -= clip.y; }
    }
  }
  await page.screenshot({ path: join(RAW, `${id}.png`), ...(clip ? { clip } : {}) });
  writeFileSync(join(OUT, `${id}.json`), JSON.stringify({ viewport: { w: clip?.width || 1600, h: clip?.height || 900, dpr: 1 }, marks, crop: null,
    captured: new Date().toISOString().slice(0, 10), source: page.url() }, null, 2));
  console.log(`[web]   ✓ ${id}`);
}

try {
  console.log("[web] download page");
  await page.goto(`${SITE}/download`, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(1500);
  const dl = page.getByTestId("nucleus-download").or(page.getByRole("link", { name: /windows|download/i }).first());
  await shot("01-download-page", { marks: [dl] });

  console.log("[web] mod post");
  if (POST) {
    await page.goto(POST, { waitUntil: "networkidle", timeout: 60000 });
  } else {
    await page.goto(SITE, { waitUntil: "networkidle", timeout: 60000 });
    // first post card that links to a post page
    const link = page.locator('a[href*="/post"]').first();
    await link.click({ timeout: 10000 });
    await page.waitForLoadState("networkidle");
  }
  await page.waitForTimeout(1500);
  const add = page.getByRole("button", { name: /add to nucleus/i }).or(page.getByRole("link", { name: /add to nucleus/i })).first();
  await add.scrollIntoViewIfNeeded({ timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(600);
  await shot("03-web-add-button", { marks: [add], pad: 14, region: '.mods-included-section' });

  // A public replay share link (the Download page's own demo replay).
  console.log("[web] share page");
  await page.goto(`${SITE}${SHARE_PATH}`, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(6000);
  await shot("08-share-page");

  // The phone companion, signed-out shell at phone size.
  console.log("[web] phone");
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const phoneShot = async (id) => {
    await phone.screenshot({ path: join(RAW, `${id}.png`) });
    writeFileSync(join(OUT, `${id}.json`), JSON.stringify({ viewport: { w: 390, h: 844, dpr: 2 }, marks: [], crop: null }, null, 2));
    console.log(`[web]   ✓ ${id}`);
  };
  await phone.goto(MOBILE, { waitUntil: "networkidle", timeout: 60000 });
  await phone.waitForTimeout(2500);
  await phoneShot("08-mobile-shell");
  await phone.close();
} catch (err) {
  console.error("[web] failed:", err.message.split("\n")[0]);
  process.exitCode = 1;
} finally {
  await browser.close();
}
spawnSync(PYTHON, [join(__dirname, "annotate.py"), OUT], { stdio: "inherit" });
