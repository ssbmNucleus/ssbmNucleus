// The guide's shot list. Each entry drives the app to a state and calls
// h.shot(id, opts). Image ids match the ../img/<id>.png references in
// sections/*.md — grep the sections when renaming.
//
// h = { page, sleep, tab, vaultMode, openCharacter, back, closeModals, reset,
//       hardReset, shot, SLOW, VANILLA_ISO, REPLAY_DIR }
// opts = { marks: [sel], boxes: [sel], crop: sel | {x,y,w,h}, pad, cropPad, settle }
//
// slow: true marks shots that take minutes (only run with --slow).

import { existsSync } from "node:fs";

const PROJECT = /Guide.Build/;
// Anything on the Tracker pages that names a real person or connect code.

async function openProject(h) {
  const { page } = h;
  await h.tab("Install");
  // Either the fighter list (project already open / auto-reopened) or the
  // project picker shows up; a project that is still loading shows neither.
  await page.waitForSelector(".fighters-list, .recent-project-details", { timeout: 120000 });
  if (await page.locator(".fighters-list").count()) return;
  await page.locator(".recent-project-details", { hasText: PROJECT }).first().click({ timeout: 8000 });
  await page.waitForSelector(".fighters-list", { timeout: 120000 });
  await h.sleep(1500);
}

// Stages view; the first time it offers to install the Dynamic Alternate
// Stages framework into the build — accept, that's what a user does too.
async function stagesMode(h) {
  await h.page.locator(".mex-panel .mode-toggle-btn", { hasText: "Stages" }).first().click({ timeout: 5000 });
  await h.sleep(1200);
  const prompt = h.page.locator(".das-install-prompt");
  if (await prompt.count()) {
    // DAS is installed automatically for app-created projects; only a project made
    // outside that flow (like the seeded one) shows this prompt, so no shot.
    await prompt.locator("button.btn-primary").first().click({ timeout: 5000 });
    // The install asks for confirmation in the app dialog (btn-save = Install).
    await h.page.locator(".app-dialog-buttons .btn-save, .confirm-dialog-buttons .btn-save").first().click({ timeout: 5000 });
    // "DAS framework installed successfully!" notice.
    await h.page.locator(".app-dialog-alert .btn-save").click({ timeout: 180000 }).catch(() => {});
    await h.page.waitForSelector(".mex-panel .fighter-item", { timeout: 180000 });
    await h.sleep(1500);
  }
}

// Installs show a blocking "Importing..." overlay; wait for it to go away.
async function waitForOverlay(h) {
  await h.sleep(1500);
  await h.page.getByText(/^Importing/).first().waitFor({ state: "detached", timeout: 300000 }).catch(() => {});
  await h.sleep(1500);
}

// Make sure we are in Tracker mode (a failed shot's hardReset lands in Nucleus mode).
async function tracker(h) {
  if (!(await h.page.locator(".brand-toggle--nucleome").count())) {
    await h.page.locator(".brand-toggle").click({ timeout: 5000 });
    await h.sleep(1200);
  }
}

async function pickFighter(h, name) {
  await h.page.locator(".fighter-item", { hasText: name }).first().click({ timeout: 5000 });
  await h.sleep(1200);
}

async function openEditModal(h, character) {
  await h.reset();
  await h.openCharacter(character);
  // The hover-revealed .btn-edit is gone (edit-modal rework): the card itself
  // opens the editor now. Hovering for a button that no longer exists was
  // costing every edit-modal shot a 30s timeout.
  const card = h.page.locator(".skin-card").first();
  await card.waitFor({ state: "visible", timeout: 15000 });
  await card.click({ timeout: 5000 });
  await h.page.waitForSelector(".edit-modal-body", { timeout: 10000 });
  await h.sleep(1200);
}

export const SHOTS = [
  // ---------------------------------------------------------------- 00 intro
  { id: "00-hero-vault", async run(h) {
    await h.reset();
    await h.shot("00-hero-vault");
  } },
  { id: "00-hero-tracker", async run(h) {
    await h.reset();
    await h.page.locator(".brand-toggle").click();
    await h.sleep(1200);
    await h.tab("Stats").catch(() => {});
    await h.shot("00-hero-tracker");
    await h.reset();
  } },

  // ---------------------------------------------------------------- 01 install
  { id: "01-setup-iso", async run(h) {
    // Already photographed by capture.mjs if the wizard ran at launch; this
    // path re-opens it from Settings for profiles where setup was complete.
    if (h.haveRaw("01-setup-iso")) return;
    await h.reset();
    await h.tab("Settings");
    // Settings is categorised now and keeps every panel mounted but `hidden`,
    // so the category has to be selected before its sections can be reached.
    await h.page.locator(".settings-category-button", { hasText: "Files & setup" }).click({ timeout: 5000 });
    await h.sleep(400);
    const sec = h.page.locator("section.settings-section", { hasText: "First-Time Setup" });
    await sec.scrollIntoViewIfNeeded();
    await sec.getByRole("button", { name: /run setup again/i }).first().click({ timeout: 5000 });
    // A ConfirmDialog now stands between that button and the wizard.
    await h.page.locator(".confirm-dialog-content .btn-save").click({ timeout: 5000 });
    await h.page.waitForSelector(".first-run-overlay", { timeout: 10000 });
    await h.shot("01-setup-iso", { settle: 1500 });
    await h.page.locator(".first-run-cancel-button").click({ timeout: 3000 }).catch(() => {});
    await h.reset();
  } },

  // ---------------------------------------------------------------- 02 basics
  { id: "02-tabs", async run(h) {
    await h.reset();
    await h.shot("02-tabs", { crop: "header.app-header", cropPad: 0, boxes: ["nav.app-tabs"], pad: 6 });
  } },
  { id: "02-import-fab", async run(h) {
    await h.reset();
    await h.shot("02-import-fab", { marks: [".import-fab"], pad: 14 });
  } },

  // ---------------------------------------------------------------- 03 getting mods
  { id: "03-drop-overlay", async run(h) {
    await h.reset();
    const dt = await h.page.evaluateHandle(() => {
      const d = new DataTransfer();
      d.items.add(new File([new Blob(["x"])], "cool-skin.zip", { type: "application/zip" }));
      return d;
    });
    await h.page.dispatchEvent("body", "dragenter", { dataTransfer: dt });
    await h.page.waitForSelector(".import-drop-overlay", { timeout: 4000 });
    await h.shot("03-drop-overlay", { settle: 500 });
    await h.page.dispatchEvent("body", "dragleave", { dataTransfer: dt }).catch(() => {});
    await h.hardReset();
  } },
  { id: "03-slippi-prompt", async run(h) {
    // a skin that fails the Slippi check → the Fix / Import-as-is prompt
    if (!h.UNSAFE_ZIP || !existsSync(h.UNSAFE_ZIP)) throw new Error("no unsafe zip (GUIDE_UNSAFE_ZIP)");
    await h.reset();
    await h.page.locator(".import-fab input[type=file]").setInputFiles(h.UNSAFE_ZIP);
    await h.page.waitForSelector(".import-dialog-callout-warning", { timeout: 120000 });
    await h.shot("03-slippi-prompt", { settle: 800 });
    await h.page.locator(".edit-modal-overlay .btn-cancel").first().click({ timeout: 3000 }).catch(() => {});
    await h.hardReset();
  } },
  { id: "03-iso-scan-results", slow: true, async run(h) {
    // Rips skins out of a real modded ISO; several minutes. Needs GUIDE_SCAN_ISO.
    const iso = h.SCAN_ISO;
    if (!iso) throw new Error("set GUIDE_SCAN_ISO to a modded .iso");
    await h.reset();
    await h.page.locator(".import-fab input[type=file]").setInputFiles(iso);
    await h.sleep(2500);
    await h.page.getByRole("button", { name: /scan|start/i }).first().click({ timeout: 5000 }).catch(() => {});
    await h.page.waitForSelector(".iso-scan-results", { timeout: 900000 });
    await h.shot("03-iso-scan-results", { settle: 1500 });
    await h.hardReset();
  } },

  // ---------------------------------------------------------------- 04 vault
  { id: "04-mode-toolbar", async run(h) {
    await h.reset();
    await h.shot("04-mode-toolbar", { crop: ".mode-switcher", cropPad: 40 });
  } },
  { id: "04-characters-grid", async run(h) {
    await h.reset();
    await h.shot("04-characters-grid");
  } },
  { id: "04-character-detail", async run(h) {
    await h.reset();
    await h.openCharacter("Marth");
    await h.shot("04-character-detail");
  } },
  { id: "04-edit-costume", async run(h) {
    await openEditModal(h, "Marth");
    await h.shot("04-edit-costume");
    await h.closeModals();
  } },
  { id: "07-badges", async run(h) {
    await openEditModal(h, "Fox");
    await h.shot("07-badges", { crop: ".edit-modal-slippi-section", cropPad: 20 });
    await h.closeModals();
  } },
  { id: "04-csp-manager", async run(h) {
    await openEditModal(h, "Fox");
    // The Portraits button is hover-revealed over the portrait (edit-modal rework).
    await h.page.locator(".edit-modal-csp-container").first().hover({ timeout: 5000 });
    await h.page.locator(".edit-modal-image-edit-btn", { hasText: "Portraits" }).first().click({ timeout: 5000 });
    await h.page.waitForSelector(".csp-manager-modal", { timeout: 10000 });
    await h.shot("04-csp-manager", { settle: 1500 });
    await h.page.locator(".csp-upload-close, .csp-manager-close").first().click({ timeout: 3000 }).catch(() => {});
    await h.closeModals();
  } },
  { id: "04-pose-manager", async run(h) {
    await h.reset();
    await h.openCharacter("Fox");
    await h.page.locator('.character-action-button[aria-label="Poses"]').click({ timeout: 5000 });
    await h.page.waitForSelector(".pm-modal--library, .pm-overlay", { timeout: 10000 });
    await h.shot("04-pose-manager", { settle: 2000 });
    await h.page.locator(".pm-close-btn").click({ timeout: 3000 }).catch(() => {});
    await h.reset();
  } },
  { id: "04-pose-editor", async run(h) {
    // Create New Pose mounts the native HSDRawViewer inside the modal, so this
    // is a desktop grab (same as the in-game test shots).
    await h.reset();
    await h.openCharacter("Fox");
    await h.page.locator('.character-action-button[aria-label="Poses"]').click({ timeout: 5000 });
    await h.page.waitForSelector(".pm-modal--library, .pm-overlay", { timeout: 10000 });
    await h.fitToScreen(1408, 792);
    await h.page.locator(".pm-create-card").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".pm-modal--create", { timeout: 15000 });
    await h.page.waitForSelector(".pm-anim-item", { timeout: 120000 });
    await h.page.locator(".pm-anim-item", { hasText: /AppealS?L|Appeal/ }).first().click({ timeout: 5000 }).catch(() => {});
    await h.sleep(4000);
    await h.shot("04-pose-editor", { desktop: true, settle: 0 });
    await h.fitToScreen(1600, 900);
    await h.page.locator(".pm-close-btn").click({ timeout: 3000 }).catch(() => {});
    await h.closeModals();
    await h.hardReset();
  } },
  { id: "04-pose-grid", async run(h) {
    // Fox's skins after batch-rendering them with the seeded "Taunt" pose
    // (.capture/seed_pose.py): every portrait in the grid shares it.
    await h.reset();
    await h.openCharacter("Fox");
    await h.page.waitForSelector(".skin-card img", { timeout: 15000 }).catch(() => {});
    await h.shot("04-pose-grid", { settle: 2500 });
    await h.reset();
  } },
  { id: "04-bulk-csp", async run(h) {
    await h.reset();
    // Vault-wide button on the characters home grid (top-right, like the
    // stages' Bulk Capture Screenshots).
    await h.page.locator(".bulk-capture-row .mode-btn", { hasText: "Bulk Retake CSPs" }).click({ timeout: 5000 });
    await h.page.waitForSelector(".bulk-capture-modal", { timeout: 10000 });
    await h.shot("04-bulk-csp", { settle: 1500 });
    await h.page.locator(".bulk-capture-modal button", { hasText: "Cancel" }).click({ timeout: 3000 }).catch(() => {});
    await h.reset();
  } },
  { id: "04-sound-packs", async run(h) {
    await h.reset();
    await h.openCharacter("Fox");
    await h.page.locator('.character-action-button[aria-label="Sounds"]').click({ timeout: 5000 });
    await h.page.waitForSelector(".sp-modal", { timeout: 10000 });
    await h.shot("04-sound-packs", { settle: 1500 });
    await h.page.locator(".sp-close-btn").click({ timeout: 3000 }).catch(() => {});
    await h.reset();
  } },
  { id: "04-skin-creator", async run(h) {
    await h.reset();
    await h.openCharacter("Fox");
    await h.page.locator(".create-mod-card").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".skin-creator-select", { timeout: 10000 });
    await h.sleep(800);
    await h.page.locator(".skin-creator-select .skin-card").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".skin-creator-modal", { timeout: 60000 });
    // wait for the 3D viewer to actually paint a frame
    await h.page.waitForSelector(".mv-container canvas, .mv-container img, .skin-creator-modal canvas", { timeout: 60000 }).catch(() => {});
    await h.shot("04-skin-creator", { settle: 15000 });
    await h.page.locator(".skin-creator-close").click({ timeout: 3000 }).catch(() => {});
    await h.hardReset();
  } },
  { id: "04-extras-editor", async run(h) {
    await h.reset();
    await h.openCharacter("Fox");
    await h.page.locator(".character-action-button--extras").click({ timeout: 5000 });
    await h.page.waitForSelector(".extras-page", { timeout: 10000 });
    await h.sleep(800);
    await h.page.locator(".extra-type-page-card", { hasText: /laser/i }).first()
      .or(h.page.locator(".extra-type-page-card").first()).click({ timeout: 5000 });
    await h.sleep(800);
    await h.page.locator(".create-extra-mod-card").click({ timeout: 5000 });
    // Older builds asked "Create New" first; the card now opens the editor directly.
    await h.page.getByRole("button", { name: "Create New", exact: true }).click({ timeout: 2000 }).catch(() => {});
    await h.page.waitForSelector(".laser-editor-modal, .gun-editor-modal, .edit-modal-body", { timeout: 20000 });
    await h.shot("04-extras-editor", { settle: 2500 });
    await h.closeModals();
    await h.hardReset();
  } },
  { id: "04-stages-grid", async run(h) {
    await h.reset();
    await h.vaultMode("Stages");
    await h.shot("04-stages-grid");
  } },
  { id: "04-stage-detail", async run(h) {
    await h.reset();
    await h.vaultMode("Stages");
    await h.page.locator(".stage-card", { hasText: "Battlefield" }).first().click({ timeout: 5000 });
    await h.page.waitForSelector(".character-detail", { timeout: 10000 });
    await h.shot("04-stage-detail", { settle: 1500 });
    await h.reset();
  } },
  { id: "04-stage-creator", async run(h) {
    await h.reset();
    await h.vaultMode("Stages");
    await h.page.locator(".stage-card", { hasText: "Battlefield" }).first().click({ timeout: 5000 });
    await h.page.waitForSelector(".character-detail", { timeout: 10000 });
    await h.sleep(800);
    // Create New Mod on a stage opens the creator straight on the vanilla stage.
    await h.page.locator(".create-mod-card").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".skin-creator-modal", { timeout: 60000 });
    await h.page.waitForSelector(".mv-container canvas, .mv-container img, .skin-creator-modal canvas", { timeout: 60000 }).catch(() => {});
    await h.shot("04-stage-creator", { settle: 15000 });
    await h.page.locator(".skin-creator-close").click({ timeout: 3000 }).catch(() => {});
    await h.hardReset();
  } },
  { id: "04-custom-characters", async run(h) {
    await h.reset();
    await h.page.locator(".custom-characters-gateway").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".custom-characters-grid .character-card:not(.skeleton-card)", { timeout: 15000 });
    await h.shot("04-custom-characters", { settle: 1500 });
    await h.reset();
  } },
  { id: "04-menus-grid", async run(h) {
    await h.reset();
    await h.vaultMode("Menus");
    // Character Select > Backgrounds is the fullest pane in the scratch vault.
    await h.page.locator(".vault-menus-group", { hasText: "Character Select" })
      .locator(".vault-menus-item", { hasText: "Backgrounds" }).first().click({ timeout: 5000 }).catch(() => {});
    await h.page.waitForSelector(".mmod-grid .mmod-card:not(.mmod-card--skeleton)", { timeout: 15000 }).catch(() => {});
    await h.shot("04-menus-grid", { settle: 1500 });
  } },
  { id: "04-patches-grid", async run(h) {
    await h.reset();
    await h.vaultMode("Patches");
    await h.shot("04-patches-grid", { settle: 1500 });
  } },

  // ---------------------------------------------------------------- 05 install tab
  { id: "05-project-selector", async run(h) {
    // Captures create "Guide_Build-N" projects over time; drop them from the
    // remembered list so the picker shows one build, then reload the tab.
    await h.page.evaluate(() => {
      for (const key of ["mex_external_projects", "mex_recent_projects", "mex_known_projects"]) {
        try {
          const raw = localStorage.getItem(key); if (!raw) continue;
          const list = JSON.parse(raw); if (!Array.isArray(list)) continue;
          localStorage.setItem(key, JSON.stringify(list.filter((p) => !/Guide_Build-\d/.test(JSON.stringify(p)))));
        } catch {}
      }
    });
    await h.reset();
    await h.tab("Install");
    await h.page.waitForSelector(".project-list-panel, .mex-panel", { timeout: 15000 });
    if (await h.page.locator(".fighters-list").count()) {
      await h.page.locator(".mex-panel .close-project-btn").click({ timeout: 5000 });
      await h.page.waitForSelector(".project-list-panel", { timeout: 15000 });
    }
    // Cosmetic: a dev machine has other projects lying around; show only ours.
    await h.page.evaluate((re) => {
      const rows = [...document.querySelectorAll(".recent-project-details")].map((d) => {
        let el = d;
        while (el.parentElement && el.parentElement.querySelectorAll(".recent-project-details").length === 1) el = el.parentElement;
        return el;
      });
      let kept = 0;
      for (const row of rows) { if (new RegExp(re).test(row.textContent)) kept++; else row.style.display = "none"; }
      const chip = document.querySelector(".project-list-count"); if (chip) chip.textContent = `${kept} project${kept === 1 ? "" : "s"}`;
    }, PROJECT.source);
    await h.shot("05-project-selector", { settle: 1200 });
  } },
  { id: "05-create-from-patch", async run(h) {
    // The "Create from a vault patch" square next to Create New Project opens a
    // picker listing the Vault's patches. Reached through Switch Project when a
    // build is already open.
    await h.tab("Install");
    await h.page.waitForSelector(".fighters-list, .project-btn-square", { timeout: 120000 });
    if (await h.page.locator(".fighters-list").count()) {
      await h.page.getByRole("button", { name: /switch project/i }).first().click({ timeout: 5000 });
      await h.page.waitForSelector(".project-btn-square", { timeout: 20000 });
    }
    await h.page.locator(".project-btn-square").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".patch-picker-item", { timeout: 20000 });
    await h.shot("05-create-from-patch", { settle: 1200, marks: [".patch-picker"], pad: 10 });
    await h.page.keyboard.press("Escape").catch(() => {});
    await h.page.locator(".project-name-modal-overlay").click({ position: { x: 4, y: 4 }, timeout: 2000 }).catch(() => {});
    await h.closeModals();
  } },
  { id: "05-project-name", async run(h) {
    await h.reset();
    await h.tab("Install");
    await h.page.waitForSelector(".project-list-panel, .mex-panel", { timeout: 15000 });
    if (await h.page.locator(".fighters-list").count()) {
      await h.page.locator(".mex-panel .close-project-btn").click({ timeout: 5000 });
      await h.page.waitForSelector(".project-list-panel", { timeout: 15000 });
    }
    await h.page.getByRole("button", { name: "Create Project", exact: true }).click({ timeout: 5000 });
    await h.page.waitForSelector(".project-name-modal", { timeout: 5000 });
    await h.page.locator("input.project-name-input").fill("My Netplay Build");
    await h.shot("05-project-name", { settle: 500 });
    await h.page.locator(".btn-cancel-modal").click({ timeout: 3000 }).catch(() => h.page.keyboard.press("Escape"));
  } },
  { id: "05-fighters-view", async run(h) {
    await openProject(h);
    await pickFighter(h, "Fox");
    await h.shot("05-fighters-view");
  } },
  { id: "05-install-selected", async run(h) {
    await openProject(h);
    await pickFighter(h, "Marth");
    const boxes = h.page.locator(".costume-list:not(.existing) .costume-card .costume-checkbox");
    const n = Math.min(await boxes.count(), 3);
    for (let i = 0; i < n; i++) await boxes.nth(i).click({ timeout: 3000 }).catch(() => {});
    await h.sleep(500);
    await h.shot("05-install-selected", { marks: [".btn-batch-import"], pad: 12 });
    // actually install them so later shots show a populated build
    await h.page.locator(".btn-batch-import").first().click({ timeout: 5000 }).catch(() => {});
    await waitForOverlay(h);
  } },
  { id: "05-team-colors", async run(h) {
    await openProject(h);
    await pickFighter(h, "Marth");
    await h.shot("05-team-colors", { crop: ".costume-list.existing", cropPad: 24, settle: 1500 });
  } },
  { id: "05-stages-view", async run(h) {
    await openProject(h);
    await stagesMode(h);
    await h.page.locator(".fighter-item", { hasText: /battlefield/i }).first().click({ timeout: 5000 }).catch(() => {});
    await h.sleep(1200);
    // Battlefield's two vault variants were installed by an earlier run (the
    // project persists); installing here again would just duplicate them.
    await h.shot("05-stages-view", { settle: 1500 });
  } },
  { id: "05-button-tokens", async run(h) {
    await openProject(h);
    await stagesMode(h);
    await h.page.locator(".fighter-item", { hasText: /battlefield/i }).first().click({ timeout: 5000 }).catch(() => {});
    await h.sleep(1200);
    await h.shot("05-button-tokens", { crop: ".costume-list.existing", cropPad: 24, boxes: [".button-tokens"], pad: 6 });
  } },
  { id: "05-stage-music", async run(h) {
    await openProject(h);
    await stagesMode(h);
    await h.page.locator(".fighter-item", { hasText: /battlefield/i }).first().click({ timeout: 5000 }).catch(() => {});
    await h.sleep(800);
    await h.page.locator(".btn-sound-pack").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".music-modal", { timeout: 10000 });
    await h.shot("05-stage-music", { settle: 1500 });
    await h.page.locator(".music-modal-close").click({ timeout: 3000 }).catch(() => {});
  } },
  { id: "05-menus-view", async run(h) {
    await openProject(h);
    await h.page.locator(".mex-panel .mode-toggle-btn", { hasText: "Menus" }).first().click({ timeout: 5000 });
    await h.sleep(2500);
    // Drill into Character Select Screen > Background so the installed mod and
    // the vault's choices are both on screen.
    await h.page.locator(".mex-panel .fighter-item", { hasText: "Character Select Screen" }).first().click({ timeout: 5000 }).catch(() => {});
    await h.sleep(1200);
    await h.page.locator(".mex-panel .fighter-item", { hasText: /^Background/ }).first().click({ timeout: 5000 }).catch(() => {});
    await h.page.waitForSelector(".mex-panel .costume-card.menu-mod-card", { timeout: 15000 }).catch(() => {});
    await h.shot("05-menus-view", { settle: 1500 });
    await h.page.locator(".mex-panel .mode-toggle-btn", { hasText: "Fighters" }).first().click({ timeout: 5000 }).catch(() => {});
  } },
  { id: "05-codes-manager", async run(h) {
    await openProject(h);
    await h.page.locator(".mex-panel .codes-btn").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".codes-mgr-body", { timeout: 10000 });
    await h.shot("05-codes-manager", { settle: 1500 });
    await h.page.getByRole("button", { name: "Close", exact: true }).last().click({ timeout: 3000 }).catch(() => {});
    await h.closeModals();
  } },

  // ---------------------------------------------------------------- 06 export
  { id: "06-export-dialog", async run(h) {
    await openProject(h);
    await h.page.getByRole("button", { name: "Close", exact: true }).last().click({ timeout: 1000 }).catch(() => {});
    await h.page.locator(".mex-panel .export-btn").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".iso-builder-modal", { timeout: 10000 });
    await h.shot("06-export-dialog", { settle: 1200 });
    await h.page.locator(".advanced-toggle").first().click({ timeout: 3000 });
    await h.sleep(600);
    await h.shot("06-export-advanced", { crop: ".export-option.has-advanced", cropPad: 16 });
    await h.page.locator(".iso-builder-modal .close-btn").click({ timeout: 3000 }).catch(() => {});
  } },
  { id: "06-export-done", slow: true, async run(h) {
    await openProject(h);
    await h.page.locator(".mex-panel .export-btn").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".iso-builder-modal", { timeout: 10000 });
    await h.page.locator("input#export-name").fill("my-build");
    await h.page.locator(".export-option", { hasText: "Export ISO" }).locator(".btn-option").click({ timeout: 5000 });
    await h.page.waitForSelector(".export-complete", { timeout: 1800000 });
    await h.shot("06-export-done", { settle: 1000 });
    await h.page.locator(".iso-builder-modal .close-btn").click({ timeout: 3000 }).catch(() => {});
  } },

  // ---------------------------------------------------------------- 08 tracker
  { id: "08-tracker-home", async run(h) {
    await h.reset();
    await h.page.locator(".brand-toggle").click();
    await h.sleep(1200);
    await h.tab("Replays");
    // The page shows a loading state before either the list or the empty
    // state; wait for one of them before deciding whether to scan.
    await h.page.waitForSelector(".replay-row, .replays-empty-path", { timeout: 30000 }).catch(() => {});
    if (await h.page.locator(".replays-empty-path").count()) {
      await h.page.locator(".replays-empty-path").fill(h.REPLAY_DIR);
      await h.page.locator(".replays-scan-btn").click({ timeout: 5000 });
      await h.page.waitForSelector(".replay-row", { timeout: 3600000 });
      await h.sleep(3000);
    }
    await h.shot("08-tracker-home", { crop: "header.app-header", cropPad: 0, marks: [".brand-toggle"], pad: 8 });
    await h.shot("08-replays", { settle: 1500 });
  } },
  { id: "08-share", async run(h) {
    await tracker(h); await h.tab("Replays");
    await h.page.locator(".share-link-wrap button").first().click({ timeout: 10000 });
    await h.page.waitForSelector(".share-menu", { timeout: 10000 });
    await h.shot("08-share", { settle: 800, marks: [".share-menu"], pad: 6 });
    await h.page.keyboard.press("Escape").catch(() => {});
  } },
  { id: "08-watch-lite", async run(h) {
    await tracker(h); await h.tab("Replays");
    await h.page.locator(".wl-trigger").first().click({ timeout: 10000 });
    await h.page.waitForSelector(".wl-modal", { timeout: 20000 });
    await h.shot("08-watch-lite", { settle: 4000 });
    await h.page.locator(".wl-close").click({ timeout: 3000 }).catch(() => {});
  } },
  { id: "08-combos", async run(h) {
    await tracker(h); await h.tab("Combos");
    await h.page.locator(".combos-scan-btn:not([disabled])").click({ timeout: 3000 }).catch(() => {});
    await h.page.locator(".combos-empty").waitFor({ state: "detached", timeout: 1800000 }).catch(() => {});
    await h.shot("08-combos", { settle: 2500 });
  } },
  { id: "08-stats", async run(h) {
    await tracker(h); await h.tab("Stats");
    await h.shot("08-stats", { settle: 3000 });
  } },
  { id: "08-tournaments", async run(h) {
    await tracker(h);
    // Linked start.gg identity lives in localStorage; GUIDE_STARTGG_SLUG seeds it.
    const slug = process.env.GUIDE_STARTGG_SLUG || "";
    if (slug) {
      await h.page.evaluate((v) => localStorage.setItem("nucleus.startgg.slug", v), slug);
      // Tournaments may already be mounted behind its tab and reads the slug on
      // mount. Reload so a one-shot capture reliably sees the seeded profile.
      await h.page.reload();
      await h.page.waitForSelector(".app-tabs", { timeout: 60000 });
      await h.sleep(1500);
      await tracker(h);
    }
    await h.tab("Tournaments");
    await h.sleep(slug ? 6000 : 0);
    await h.shot("08-tournaments", { settle: 2500 });
  } },
  { id: "08-vault-pairing", async run(h) {
    await tracker(h); await h.tab("Settings");
    // Same categorised-Settings problem as 01-setup-iso.
    await h.page.locator(".settings-category-button", { hasText: "Cloud" }).first()
      .click({ timeout: 5000 }).catch(() => {});
    await h.sleep(400);
    const sec = h.page.locator("section.cloud-hero");
    if (await sec.count()) { await sec.scrollIntoViewIfNeeded(); await h.sleep(600); await h.shot("08-vault-pairing", { crop: "section.cloud-hero", cropPad: 16, settle: 1200 }); }
    else await h.shot("08-vault-pairing", { settle: 1500 });
    await h.reset();
  } },

  // ---------------------------------------------------------------- 09 settings
  { id: "09-settings", async run(h) {
    await h.reset();
    await h.tab("Settings");
    await h.shot("09-settings", { settle: 1500 });
  } },

  // ---------------------------------------------------------------- 10 sharing
  { id: "02-upload", async run(h) {
    await h.reset();
    await h.page.locator("nav.app-tabs button.tab", { hasText: "Upload" }).click({ timeout: 5000, force: true });
    await h.sleep(800);
    await h.shot("02-upload", { settle: 800 });
    await h.page.keyboard.press("Escape").catch(() => {});
    await h.reset();
  } },

  // ---------------------------------------------------------------- 11 troubleshooting
  { id: "11-bug-report", async run(h) {
    await h.reset();
    await h.tab("Settings");
    const sec = h.page.locator("section.settings-section", { hasText: "Bug Report" }).first();
    await sec.scrollIntoViewIfNeeded();
    await sec.getByRole("button").first().click({ timeout: 5000 });
    await h.page.waitForSelector(".credits-modal-title", { timeout: 10000 });
    await h.shot("11-bug-report", { settle: 1200 });
    await h.closeModals();
    await h.reset();
  } },

  // ---------------------------------------------------------------- last: boots Dolphin, holds the workspace lock
  { id: "05-test-in-game", slow: true, async run(h) {
    // Boots the skin in an isolated Slippi Dolphin embedded in the app. The
    // Dolphin window is native, so these are desktop grabs, not page shots.
    await openEditModal(h, "Fox");
    // Desktop grabs need the whole window on screen; a 1440x900 laptop cannot
    // hold the 1600x900 capture window, so shrink it (same aspect) for these two.
    await h.fitToScreen(1408, 792);
    await h.page.getByRole("button", { name: "Test in Game", exact: true }).click({ timeout: 5000 });
    await h.sleep(25000);
    await h.shot("05-test-in-game", { desktop: true, settle: 0 });
    await h.sleep(50000);
    await h.shot("06-in-game", { desktop: true, settle: 0 });
    await h.fitToScreen(1600, 900);
    await h.page.getByText(/(PASS|CRASH|HUNG)|Test again/).first().waitFor({ timeout: 480000 }).catch(() => {});
    await h.page.getByRole("button", { name: "Close", exact: true }).last().click({ timeout: 3000 }).catch(() => {});
    await h.closeModals();
    await h.hardReset();
  } },
];
