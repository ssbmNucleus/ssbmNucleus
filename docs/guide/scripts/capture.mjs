#!/usr/bin/env node
// Takes the guide's screenshots by driving the real Nucleus Electron app.
//
//   node docs/guide/scripts/capture.mjs [--only <substr>] [--slow] [--keep]
//
// Prerequisites (once): `app\venv\Scripts\python docs\guide\scripts\seed.py` to build the
// scratch vault + "Guide Build" project under docs/guide/.capture/. This script then:
//   1. spawns its own Vite (port 3031, VITE_SHIP_GATES=1 = the released surface),
//   2. launches Electron with an isolated profile + the scratch vault, the same
//      release gates the packaged app ships with, and no update check,
//   3. walks every shot in shots.mjs, writing docs/guide/img/_raw/<id>.png plus a
//      <id>.json sidecar with the boxes to highlight,
//   4. runs annotate.py so docs/guide/img/<id>.png carries the red rings.
//
// --only  substring filter on shot ids (e.g. --only 05-)
// --slow  include shots that need minutes (ISO scan, replay indexing, export)
// --keep  leave the app open after the run for poking around
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { SHOTS } from "./shots.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const NUCLEUS = resolve(__dirname, "..", "..", "..", "app");  // the app/ folder
const GUIDE_DIR = resolve(__dirname, "..");               // docs/guide
const { _electron: electron } = createRequire(join(NUCLEUS, "package.json"))("playwright-core");

const GUIDE = GUIDE_DIR;
const CAPTURE = join(GUIDE, ".capture");
const PROFILE = join(CAPTURE, "profile");
const STORAGE = join(CAPTURE, "storage");
const OUT = join(GUIDE, "img");
const RAW = join(OUT, "_raw");
const VITE_PORT = 3031;
const VITE_PORT_FILE = join(NUCLEUS, "frontend", ".vite-port");
const ELECTRON_EXE = join(NUCLEUS, "node_modules", "electron", "dist", "electron.exe");
const PYTHON = existsSync(join(NUCLEUS, "venv", "Scripts", "python.exe"))
  ? join(NUCLEUS, "venv", "Scripts", "python.exe") : "python";

const argValue = (flag) => { const i = process.argv.indexOf(flag); return i >= 0 ? process.argv[i + 1] : null; };
const ONLY = argValue("--only");
const SLOW = process.argv.includes("--slow");
const KEEP = process.argv.includes("--keep");

const VANILLA_ISO = process.env.GUIDE_VANILLA_ISO
  || "";
const SLIPPI_DIR = process.env.GUIDE_SLIPPI_DIR
  || join(process.env.APPDATA || "", "Slippi Launcher", "netplay");
// A SMALL replay folder (a few dozen games) — a full Slippi library takes hours
// to index. seed.py can fill docs/guide/.capture/replays from your real folder.
const REPLAY_DIR = process.env.GUIDE_REPLAY_DIR || join(CAPTURE, "replays");
const SCAN_ISO = process.env.GUIDE_SCAN_ISO
  || null;
const UNSAFE_ZIP = process.env.GUIDE_UNSAFE_ZIP || join(CAPTURE, "tmp", "purple-mario.zip");

// Personal strings to swap out of every screenshot (gitignored; see README).
const REDACT = (() => {
  const f = join(CAPTURE, "redact.json");
  const map = existsSync(f) ? JSON.parse(readFileSync(f, "utf8")) : {};
  if (process.env.USERNAME && !(process.env.USERNAME in map)) map[process.env.USERNAME] = "you";
  return map;
})();
let windowBounds = null; // screen-space content rect, for desktop grabs

if (!existsSync(STORAGE)) {
  console.error(`[guide] ${STORAGE} missing — run seed.py first`);
  process.exit(1);
}
mkdirSync(RAW, { recursive: true });
mkdirSync(PROFILE, { recursive: true });

// Release gates exactly as electron/main.js forces them in packaged builds, so
// nothing unreleased can appear in a guide image.
const SHIP_ENV = {
  NUCLEUS_COMBO_VIDEO: "0", NUCLEUS_RANDALL: "0",
};

// ---------- Vite ----------
try { unlinkSync(VITE_PORT_FILE); } catch {}
console.log(`[guide] starting Vite on :${VITE_PORT}`);
const vite = spawn("npm", ["run", "dev", "--", "--port", String(VITE_PORT), "--strictPort"], {
  cwd: join(NUCLEUS, "frontend"), shell: true, stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, VITE_SHIP_GATES: "1" },
});
vite.stderr.on("data", (d) => process.stderr.write(`[vite] ${d}`));

function killTree(pid) {
  if (!pid) return;
  if (process.platform === "win32") spawnSync("taskkill", ["/F", "/T", "/PID", String(pid)], { stdio: "ignore" });
  else { try { process.kill(-pid); } catch {} }
}

let app;
const results = [];
try {
  const t0 = Date.now();
  while (!existsSync(VITE_PORT_FILE) || readFileSync(VITE_PORT_FILE, "utf8").trim() !== String(VITE_PORT)) {
    if (Date.now() - t0 > 60000) throw new Error("Vite did not come up on the expected port");
    await sleep(250);
  }
  console.log("[guide] Vite ready; launching Electron");

  app = await electron.launch({
    args: ["."], cwd: NUCLEUS, executablePath: ELECTRON_EXE, timeout: 90000,
    env: {
      ...process.env, ...SHIP_ENV,
      NUCLEUS_USERDATA_DIR: PROFILE, NUCLEUS_STORAGE_DIR: STORAGE, NUCLEUS_NO_UPDATE_CHECK: "1",
      // Cold imports on slower Windows disks can exceed the app's normal
      // startup window; guide capture is unattended, so give it room to finish.
      NUCLEUS_BACKEND_STARTUP_TIMEOUT_MS: "180000",
    },
  });

  let page;
  // The window is created only after the Python backend reports its port.
  // Match the extended capture-only backend allowance above.
  for (const deadline = Date.now() + 180000; Date.now() < deadline && !page;) {
    page = app.windows().find((p) => p.url().startsWith(`http://localhost:${VITE_PORT}`));
    if (!page) await sleep(200);
  }
  if (!page) throw new Error(`Nucleus window not found: ${app.windows().map((p) => p.url()).join(", ")}`);
  page.setDefaultNavigationTimeout(120000);
  page.on("dialog", (d) => d.dismiss().catch(() => {}));
  page.on("pageerror", (err) => console.error(`[renderer] ${err.message}`));
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) console.log(`[renderer:${m.type()}] ${m.text().slice(0, 300)}`); });
  globalThis.__guidePage = page;

  // Fixed 1600x900 content area so every image has the same geometry.
  await app.evaluate(({ BrowserWindow }, port) => new Promise((done) => {
    const win = BrowserWindow.getAllWindows().find((w) => {
      try { return w.webContents.getURL().includes(`localhost:${port}`); } catch { return false; }
    });
    if (!win) return done(null);
    let n = 0;
    const fit = () => {
      try {
        if (win.webContents.isDevToolsOpened()) win.webContents.closeDevTools();
        win.setResizable(true); win.setMinimumSize(640, 360); win.setMaximumSize(0, 0);
        win.unmaximize(); win.setContentSize(1600, 900, false);
        const b = win.getBounds(); win.setBounds({ ...b, x: 0, y: 0 }, false);
      } catch {}
      if (++n >= 15) done(win.getContentBounds()); else setTimeout(fit, 100);
    };
    win.webContents.on("devtools-opened", fit);
    fit();
  }), VITE_PORT).then((b) => { windowBounds = b; });

  // Seed the renderer's persisted settings so no setup banner / volume / mode
  // surprises appear, then reload so App.jsx reads them at boot.
  const seedStorage = async () => {
    await page.evaluate(({ iso, slippi }) => {
      localStorage.setItem("nucleus_app_mode", "nucleus");
      localStorage.setItem("vanilla_iso_path", iso);
      if (slippi) localStorage.setItem("slippi_dolphin_path", slippi);
      localStorage.setItem("settings_master_volume", "0");
      localStorage.setItem("nucleus.share.noticeAck", "1");
    }, { iso: VANILLA_ISO, slippi: existsSync(SLIPPI_DIR) ? SLIPPI_DIR : null });
  };
  await page.waitForLoadState("domcontentloaded");
  await seedStorage();
  await page.reload();

  // If this profile/vault has never completed first-run setup the wizard is
  // fullscreen. Walk it (it auto-detects the ISO) and photograph it on the way —
  // those ARE the chapter-1 screenshots.
  await page.waitForSelector(".app-tabs, .first-run-overlay", { timeout: 60000 });
  if (await page.locator(".first-run-overlay").count()) {
    console.log("[guide] first-run wizard is up; walking through it");
    const rawShot = async (id) => {
      const viewport = await page.evaluate(() => ({ w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 }));
      await page.screenshot({ path: join(RAW, `${id}.png`) });
      writeFileSync(join(OUT, `${id}.json`), JSON.stringify({ viewport, marks: [], crop: null }, null, 2));
      console.log(`[guide]   ✓ ${id}`);
    };
    await sleep(1500);
    await rawShot("01-setup-welcome");
    // Welcome -> either the ISO picker (auto-detect failed) or straight into
    // extraction (auto-detect found the ISO and Slippi).
    await page.locator(".first-run-modal .btn-primary").first().click({ timeout: 5000 }).catch(() => {});
    await sleep(3000);
    if (await page.locator(".iso-selector").count()) {
      await rawShot("01-setup-iso");
      await page.locator(".first-run-modal .btn-primary", { hasText: "Start Setup" }).click({ timeout: 5000 });
      await sleep(5000);
    }
    await rawShot("01-setup-progress");
    await page.getByText("Setup Complete!").first().waitFor({ timeout: 1200000 });
    await sleep(800);
    await rawShot("01-setup-done");
    await page.locator(".first-run-modal .btn-primary").first().click({ timeout: 5000 }).catch(() => {}); // finish
    await page.getByRole("button", { name: /^dismiss$/i }).click({ timeout: 1500 }).catch(() => {});
  }
  await page.waitForSelector(".app-tabs", { timeout: 60000 });
  await page.addStyleTag({ content: ".debug-tier{display:none!important}" });
  await page.getByRole("button", { name: /^dismiss$/i }).click({ timeout: 1500 }).catch(() => {});
  await sleep(1500);

  // ---------- helpers handed to every shot ----------
  const h = {
    page, sleep, SLOW, VANILLA_ISO, REPLAY_DIR, SCAN_ISO, UNSAFE_ZIP, app,
    haveRaw: (id) => existsSync(join(RAW, `${id}.png`)),
    async tab(name) {
      await page.getByRole("button", { name, exact: true }).first().click({ timeout: 5000 });
      await sleep(700);
    },
    async vaultMode(name) {
      await page.locator(".mode-switcher .mode-btn", { hasText: name }).first().click({ timeout: 5000 });
      await sleep(900);
    },
    async openCharacter(name) {
      await page.locator(`.characters-grid .character-card:has(img[alt="${name}" i])`).first().click({ timeout: 6000 });
      await page.waitForSelector(".character-detail", { timeout: 10000 });
      await sleep(1200);
    },
    async back() {
      const b = page.locator(".back-button:visible").last();
      if (await b.count()) { await b.click({ timeout: 2000 }).catch(() => {}); await sleep(500); }
    },
    async closeModals() {
      for (const sel of [".first-run-cancel-button", ".edit-modal-close", ".pm-close-btn", ".sp-close-btn", ".sb-close-btn",
        ".laser-editor-close", ".music-modal-close", ".download-btn-close", ".al-close-btn", ".bulk-capture-close",
        ".iso-builder-modal .close-btn", ".modal-close", ".wl-close", ".tg-detail-close", ".credits-modal-close"]) {
        await page.locator(sel).last().click({ timeout: 400 }).catch(() => {});
      }
      await page.locator(".bulk-capture-modal button", { hasText: "Cancel" }).click({ timeout: 400 }).catch(() => {});
      await page.keyboard.press("Escape").catch(() => {});
      await sleep(300);
    },
    // Back to a known state: Nucleus mode, Vault tab, Characters grid.
    async reset() {
      await h.closeModals();
      for (let i = 0; i < 4; i++) await h.back();
      const inTracker = await page.locator(".brand-toggle--nucleome").count().catch(() => 0);
      if (inTracker) { await page.locator(".brand-toggle").click({ timeout: 3000 }).catch(() => {}); await sleep(900); }
      await h.tab("Vault").catch(() => {});
      await h.vaultMode("Characters").catch(() => {});
    },
    // Nuclear option for states without a close button (skin creator etc.).
    async hardReset() {
      await seedStorage();
      await page.reload();
      await page.waitForSelector(".app-tabs", { timeout: 60000 });
      await page.addStyleTag({ content: ".debug-tier{display:none!important}" });
      await sleep(1500);
    },
    // Take the screenshot. opts.marks = selectors to ring, opts.boxes = selectors
    // to outline, opts.crop = selector (or {x,y,w,h}) to crop to, opts.pad = px.
    // Swap personal strings (username in paths, connect code, display name)
    // in every text node, input value and title attribute before shooting.
    async redact() {
      if (!Object.keys(REDACT).length) return;
      await page.evaluate((map) => {
        const pairs = Object.entries(map);
        const swap = (s) => { for (const [k, v] of pairs) if (s.includes(k)) s = s.split(k).join(v); return s; };
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
        for (const n of nodes) { const s = swap(n.nodeValue); if (s !== n.nodeValue) n.nodeValue = s; }
        for (const el of document.querySelectorAll("input, textarea")) { const s = swap(el.value || ""); if (s !== el.value) el.value = s; }
        for (const el of document.querySelectorAll("[title], [placeholder]")) {
          for (const attr of ["title", "placeholder"]) { const cur = el.getAttribute(attr); if (cur) { const s = swap(cur); if (s !== cur) el.setAttribute(attr, s); } }
        }
      }, REDACT).catch(() => {});
    },
    // Grab the app window from the desktop (for natively embedded content).
    // Resize the content area (and pin the window to 0,0) for shots that must
    // fit a small screen -- desktop grabs include whatever overlaps the window.
    async fitToScreen(width, height) {
      await app.evaluate(({ BrowserWindow }, [port, w, h]) => {
        const win = BrowserWindow.getAllWindows().find((x) => { try { return x.webContents.getURL().includes(`localhost:${port}`); } catch { return false; } });
        if (!win) return;
        win.unmaximize(); win.setContentSize(w, h, false);
        const b = win.getBounds(); win.setBounds({ ...b, x: 0, y: 0 }, false);
      }, [VITE_PORT, width, height]).catch(() => {});
      await sleep(800);
    },
    async desktopGrab(outPath) {
      // Measure live: the window may have been resized since startup.
      const live = await app.evaluate(({ BrowserWindow }, port) => {
        const win = BrowserWindow.getAllWindows().find((x) => { try { return x.webContents.getURL().includes(`localhost:${port}`); } catch { return false; } });
        return win ? win.getContentBounds() : null;
      }, VITE_PORT).catch(() => null);
      const b = live || windowBounds || { x: 0, y: 0, width: 1600, height: 900 };
      const dpr = await page.evaluate(() => window.devicePixelRatio || 1);
      const bbox = [b.x, b.y, b.width, b.height].map((v) => Math.round(v * dpr));
      await app.evaluate(({ BrowserWindow }) => { for (const w of BrowserWindow.getAllWindows()) { try { w.show(); w.focus(); w.moveTop(); } catch {} } }).catch(() => {});
      await sleep(600);
      const r = spawnSync(PYTHON, [join(__dirname, "grab.py"), outPath, "--bbox", ...bbox.map(String)], { encoding: "utf8" });
      if (r.status !== 0) throw new Error(`desktop grab failed: ${r.stderr || r.stdout}`);
    },
    async shot(id, opts = {}) {
      await sleep(opts.settle ?? 600);
      await h.redact();
      const measure = async (sel) => {
        const loc = typeof sel === "string" ? page.locator(sel).first() : sel;
        const b = await loc.boundingBox({ timeout: 3000 }).catch(() => null);
        return b ? { x: b.x, y: b.y, w: b.width, h: b.height } : null;
      };
      const marks = [];
      for (const sel of opts.marks || []) { const b = await measure(sel); if (b) marks.push({ kind: "ring", box: b, pad: opts.pad ?? 10 }); else console.warn(`[guide]   no box for ${sel}`); }
      for (const sel of opts.boxes || []) { const b = await measure(sel); if (b) marks.push({ kind: "box", box: b, pad: opts.pad ?? 8 }); }
      // mask: pixelate EVERY element matching each selector (names, codes, avatars)
      for (const sel of opts.mask || []) {
        const boxes = await page.locator(sel).evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }).filter((r) => r.w > 0 && r.h > 0)).catch(() => []);
        for (const b of boxes) marks.push({ kind: "blur", box: b });
      }
      let crop = null;
      if (opts.crop) {
        const isBox = typeof opts.crop === "object" && "x" in opts.crop && "w" in opts.crop;
        crop = isBox ? opts.crop : await measure(opts.crop);
        if (crop && !isBox) {
          const p = opts.cropPad ?? 24;
          crop = { x: Math.max(0, crop.x - p), y: Math.max(0, crop.y - p), w: crop.w + 2 * p, h: crop.h + 2 * p };
        }
      }
      const viewport = await page.evaluate(() => ({ w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 }));
      if (opts.desktop) await h.desktopGrab(join(RAW, `${id}.png`));
      else await page.screenshot({ path: join(RAW, `${id}.png`), fullPage: false });
      writeFileSync(join(OUT, `${id}.json`), JSON.stringify({ viewport, marks, crop }, null, 2));
      console.log(`[guide]   ✓ ${id}${marks.length ? ` (${marks.length} mark)` : ""}${crop ? " [crop]" : ""}`);
    },
  };

  const wanted = ONLY ? ONLY.split(",").map((s) => s.trim()).filter(Boolean) : null;
  const active = SHOTS.filter((s) => (!wanted || wanted.some((w) => s.id.includes(w))) && (SLOW || !s.slow));
  console.log(`[guide] ${active.length} shot(s)`);
  for (const s of active) {
    console.log(`[guide] -> ${s.id}`);
    try {
      await s.run(h);
      results.push({ id: s.id, ok: true });
    } catch (err) {
      console.error(`[guide]   FAILED ${s.id}: ${err.message.split("\n")[0]}`);
      await page.screenshot({ path: join(RAW, `_failed-${s.id}.png`) }).catch(() => {});
      results.push({ id: s.id, ok: false, error: err.message.split("\n")[0] });
      await h.hardReset().catch(() => {});
    }
  }

  if (KEEP) { console.log("[guide] --keep: leaving the app open; Ctrl+C to exit"); await new Promise(() => {}); }
} catch (err) {
  console.error("[guide] fatal:", err);
  await globalThis.__guidePage?.screenshot({ path: join(RAW, "_fatal.png") }).catch(() => {});
  process.exitCode = 1;
} finally {
  if (app) { try { await Promise.race([app.close(), sleep(8000)]); } catch {} try { killTree(app.process()?.pid); } catch {} }
  killTree(vite.pid);
}

const failed = results.filter((r) => !r.ok);
console.log(`[guide] ${results.length - failed.length}/${results.length} shots ok${failed.length ? `; failed: ${failed.map((f) => f.id).join(", ")}` : ""}`);
const ann = spawnSync(PYTHON, [join(__dirname, "annotate.py"), OUT], { stdio: "inherit" });
if (ann.status !== 0) console.error("[guide] annotate.py failed");
setTimeout(() => process.exit(process.exitCode ?? (failed.length ? 2 : 0)), 500).unref();
