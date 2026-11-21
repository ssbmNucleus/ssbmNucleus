const DEFAULT_PAGE = "wiki/README.md";
const SAVE_ENDPOINT = "/__wiki_api/save";
const EDITABLE_EXTENSIONS = new Set([".md", ".txt", ".json"]);

const NAV_SECTIONS = [
  {
    title: "General Info",
    items: [
      { label: "Home", path: "wiki/README.md" },
      { label: "First-Run Setup", path: "wiki/First-Run-Setup.md" },
      { label: "Vault Vs Project", path: "wiki/Vault-Vs-Project.md" },
      { label: "Reporting A Bug", path: "wiki/Reporting-A-Bug.md" },
    ],
  },
  {
    title: "Importing Mods",
    items: [
      { label: "Manual Import", path: "wiki/Manual-Import.md" },
      { label: "One-Click Imports", path: "wiki/One-Click-Imports.md" },
      { label: "ISO Scanning", path: "wiki/ISO-Scanning.md" },
      {
        label: "Slippi Safety",
        path: "wiki/Slippi-Safety.md",
      },
    ],
  },
  {
    title: "Mod Types",
    items: [
      {
        label: "Character Mods",
        path: "wiki/Character-Mod-Workflow.md",
        children: [
          { label: "Ice Climbers Pairing", path: "wiki/Ice-Climbers-Pairing.md" },
          { label: "Captain Falcon Red Costume", path: "wiki/Captain-Falcon-Red-Costume.md" },
          { label: "CSPs And Poses", path: "wiki/CSP-And-Pose-Workflow.md" },
        ],
      },
      {
        label: "Stage Mods",
        path: "wiki/Stage-Mod-Workflow.md",
      },
      {
        label: "Effect Mods",
        path: "wiki/Extras-And-Effects-Workflow.md",
        children: [
          { label: "Fox And Falco Shared Effects", path: "wiki/Fox-And-Falco-Shared-Extras.md" },
        ],
      },
      { label: "Custom Characters", path: "wiki/Custom-Characters.md" },
      { label: "Custom Stages", path: "wiki/Custom-Stages.md" },
      { label: "Menus And Select Screens", path: "wiki/Menus-And-Select-Screen-Mods.md" },
      { label: "Sound Mods", path: "wiki/Sound-Mods.md" },
      { label: "Gecko Codes", path: "wiki/Gecko-Codes.md" },
    ],
  },
  {
    title: "In-App Tools",
    items: [
      { label: "Stats And Tournaments", path: "wiki/Stats-And-Tournaments.md" },
      { label: "Replays", path: "wiki/Replays.md" },
      { label: "Combos", path: "wiki/Combos.md" },
      { label: "Mobile Setup", path: "wiki/Mobile-Setup.md" },
      { label: "Skin Creator", path: "wiki/Skin-Creator.md" },
      { label: "Test In Game", path: "wiki/Test-In-Game.md" },
      { label: "Randall (Preview)", path: "wiki/Assistant.md" },
    ],
  },
  {
    title: "Build And Sharing",
    items: [
      { label: "Vault Backup And Restore", path: "wiki/Vault-And-Distribution-Workflow.md" },
      { label: "CSP Compression", path: "wiki/CSP-Compression.md" },
      { label: "Patches", path: "wiki/Patches.md" },
      { label: "Texture Pack Mode", path: "wiki/Texture-Pack-Mode.md" },
      { label: "Mod Bundles", path: "wiki/Mod-Bundles.md" },
    ],
  },
  {
    title: "Reference",
    items: [
      {
        label: "Melee Files Reference",
        path: "wiki/reference/new-414/Melee-Files.md",
      },
      {
        label: "Effect Offsets Reference",
        path: "wiki/reference/color-effects-reference/Effect-Offsets-Reference.md",
      },
    ],
  },
];

const navElement = document.getElementById("nav");
const pageTitleElement = document.getElementById("page-title");
const pagePathElement = document.getElementById("page-path");
const pageContentElement = document.getElementById("page-content");
const editorWorkspaceElement = document.getElementById("editor-workspace");
const editorPaneElement = document.getElementById("editor-pane");
const editorInputElement = document.getElementById("editor-input");
const editorStatusElement = document.getElementById("editor-status");
const editorMetaElement = document.getElementById("editor-meta");
const editorFileLabelElement = document.getElementById("editor-file-label");
const editToggleButton = document.getElementById("edit-toggle");
const editorCancelButton = document.getElementById("editor-cancel");
const editorSaveButton = document.getElementById("editor-save");

let currentPath = DEFAULT_PAGE;
let currentSource = "";
let currentPageExists = false;
let currentPageEditable = false;
let isEditing = false;
let isDirty = false;
let isSaving = false;
let suppressHashChange = false;

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function parseRoute() {
  const raw = window.location.hash.replace(/^#/, "");
  return raw ? decodeURIComponent(raw) : DEFAULT_PAGE;
}

function buildHash(path) {
  return `#${encodeURI(path)}`;
}

function buildFileUrl(path) {
  const encodedPath = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return `/${encodedPath}`;
}

function getExtension(path) {
  const dotIndex = path.lastIndexOf(".");
  return dotIndex >= 0 ? path.slice(dotIndex).toLowerCase() : "";
}

function isMarkdownPath(path) {
  return getExtension(path) === ".md";
}

function isTextPath(path) {
  return getExtension(path) === ".txt";
}

function isJsonPath(path) {
  return getExtension(path) === ".json";
}

function isPdfPath(path) {
  return getExtension(path) === ".pdf";
}

function isEditablePath(path) {
  return EDITABLE_EXTENSIONS.has(getExtension(path));
}

function humanizePath(path) {
  const filename = path.split("/").at(-1) || path;
  const basename = filename.replace(/\.[^.]+$/, "");

  if (basename.toUpperCase() === basename) {
    return basename;
  }

  return basename
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function getDefaultDraftSource(path) {
  if (isMarkdownPath(path)) {
    return `# ${humanizePath(path)}\n\n`;
  }

  if (isJsonPath(path)) {
    return "{\n  \n}\n";
  }

  return "";
}

function extractTitle(source, path) {
  if (isMarkdownPath(path)) {
    const titleMatch = source.match(/^#\s+(.+)$/m);
    if (titleMatch) {
      return titleMatch[1].trim();
    }
  }

  return path.split("/").at(-1) || path;
}

function normalizePath(basePath, targetPath) {
  if (
    /^https?:\/\//i.test(targetPath) ||
    targetPath.startsWith("mailto:") ||
    targetPath.startsWith("#")
  ) {
    return targetPath;
  }

  const baseSegments = basePath.split("/").slice(0, -1);
  const targetSegments = targetPath.startsWith("/")
    ? targetPath.slice(1).split("/")
    : [...baseSegments, ...targetPath.split("/")];
  const normalizedSegments = [];

  for (const segment of targetSegments) {
    if (!segment || segment === ".") {
      continue;
    }
    if (segment === "..") {
      normalizedSegments.pop();
      continue;
    }
    normalizedSegments.push(segment);
  }

  return normalizedSegments.join("/");
}

function navItemContainsPath(item, activePath) {
  if (item.path === activePath) {
    return true;
  }

  if (!Array.isArray(item.children)) {
    return false;
  }

  return item.children.some((child) => navItemContainsPath(child, activePath));
}

function renderNavItems(items, activePath, level = 0) {
  return items
    .map((item) => {
      const isActive = item.path === activePath;
      const hasChildren = Array.isArray(item.children) && item.children.length > 0;
      const hasActiveDescendant = hasChildren
        ? item.children.some((child) => navItemContainsPath(child, activePath))
        : false;
      const isExpanded = hasChildren && (isActive || hasActiveDescendant);

      const linkClasses = ["nav-link"];
      if (level > 0) {
        linkClasses.push("nav-link-child");
      }
      if (hasChildren) {
        linkClasses.push("nav-link-parent");
      }
      if (isActive) {
        linkClasses.push("active");
      } else if (hasActiveDescendant) {
        linkClasses.push("branch-active");
      }

      const childrenHtml =
        hasChildren
          ? `<ul class="nav-list nav-sublist${isExpanded ? " nav-sublist-expanded" : ""}">${renderNavItems(
              item.children,
              activePath,
              level + 1
            )}</ul>`
          : "";

      return `
        <li class="nav-item nav-item-level-${level}">
          <a class="${linkClasses.join(" ")}" href="${buildHash(item.path)}">${escapeHtml(item.label)}</a>
          ${childrenHtml}
        </li>
      `;
    })
    .join("");
}

function renderNav(activePath) {
  const sectionsHtml = NAV_SECTIONS.map((section) => {
    const itemsHtml = renderNavItems(section.items, activePath);

    return `
      <section class="nav-section">
        <h3 class="nav-section-title">${escapeHtml(section.title)}</h3>
        <ul class="nav-list">${itemsHtml}</ul>
      </section>
    `;
  }).join("");

  navElement.innerHTML = sectionsHtml;
}

function renderLink(label, href, activePath) {
  if (/^https?:\/\//i.test(href) || href.startsWith("mailto:")) {
    return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(
      label
    )}</a>`;
  }

  if (href.startsWith("#")) {
    return `<a href="${escapeHtml(href)}">${escapeHtml(label)}</a>`;
  }

  const resolvedPath = normalizePath(activePath, href);
  if (resolvedPath.endsWith(".md") || resolvedPath.endsWith(".txt")) {
    return `<a href="${buildHash(resolvedPath)}">${escapeHtml(label)}</a>`;
  }

  return `<a href="${buildFileUrl(resolvedPath)}" target="_blank" rel="noopener noreferrer">${escapeHtml(
    label
  )}</a>`;
}

function renderImage(alt, src, activePath) {
  const resolvedPath = normalizePath(activePath, src);
  return `<img src="${buildFileUrl(resolvedPath)}" alt="${escapeHtml(alt)}" />`;
}

function renderInline(text, activePath) {
  let working = text;
  const tokens = [];

  const stash = (html) => {
    const token = `@@TOKEN_${tokens.length}@@`;
    tokens.push(html);
    return token;
  };

  working = working.replace(/`([^`]+)`/g, (_, code) => {
    return stash(`<code>${escapeHtml(code)}</code>`);
  });

  working = working.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => {
    return stash(renderImage(alt, src, activePath));
  });

  working = working.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => {
    return stash(renderLink(label, href, activePath));
  });

  working = escapeHtml(working);
  working = working.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  working = working.replace(/\*([^*]+)\*/g, "<em>$1</em>");

  tokens.forEach((html, index) => {
    working = working.replace(`@@TOKEN_${index}@@`, html);
  });

  return working;
}

function renderMarkdown(markdown, activePath) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let inCodeBlock = false;
  let codeLanguage = "";
  let codeLines = [];
  let paragraphLines = [];
  let listType = null;
  let listItems = [];
  let quoteLines = [];

  const flushParagraph = () => {
    if (!paragraphLines.length) {
      return;
    }
    html += `<p>${renderInline(paragraphLines.join(" "), activePath)}</p>`;
    paragraphLines = [];
  };

  const flushList = () => {
    if (!listItems.length || !listType) {
      return;
    }
    const itemsHtml = listItems
      .map((item) => `<li>${renderInline(item, activePath)}</li>`)
      .join("");
    html += `<${listType}>${itemsHtml}</${listType}>`;
    listItems = [];
    listType = null;
  };

  const flushQuote = () => {
    if (!quoteLines.length) {
      return;
    }
    html += `<blockquote>${renderInline(quoteLines.join(" "), activePath)}</blockquote>`;
    quoteLines = [];
  };

  const flushCodeBlock = () => {
    const languageClass = codeLanguage ? ` class="language-${escapeHtml(codeLanguage)}"` : "";
    html += `<pre><code${languageClass}>${escapeHtml(codeLines.join("\n"))}</code></pre>`;
    codeLines = [];
    codeLanguage = "";
  };

  const flushAll = () => {
    flushParagraph();
    flushList();
    flushQuote();
  };

  for (const line of lines) {
    if (inCodeBlock) {
      if (line.startsWith("```")) {
        inCodeBlock = false;
        flushCodeBlock();
      } else {
        codeLines.push(line);
      }
      continue;
    }

    if (line.startsWith("```")) {
      flushAll();
      inCodeBlock = true;
      codeLanguage = line.slice(3).trim();
      continue;
    }

    if (!line.trim()) {
      flushAll();
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushAll();
      const level = headingMatch[1].length;
      const text = headingMatch[2].trim();
      html += `<h${level} id="${slugify(text)}">${renderInline(text, activePath)}</h${level}>`;
      continue;
    }

    if (/^(-{3,}|_{3,}|\*{3,})$/.test(line.trim())) {
      flushAll();
      html += "<hr />";
      continue;
    }

    const quoteMatch = line.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      quoteLines.push(quoteMatch[1]);
      continue;
    }

    if (quoteLines.length) {
      flushQuote();
    }

    const orderedListMatch = line.match(/^\d+\.\s+(.*)$/);
    const unorderedListMatch = line.match(/^[-*+]\s+(.*)$/);

    if (orderedListMatch || unorderedListMatch) {
      flushParagraph();
      const nextType = orderedListMatch ? "ol" : "ul";
      if (listType && listType !== nextType) {
        flushList();
      }
      listType = nextType;
      listItems.push((orderedListMatch || unorderedListMatch)[1]);
      continue;
    }

    if (listItems.length) {
      flushList();
    }

    paragraphLines.push(line.trim());
  }

  if (inCodeBlock) {
    flushCodeBlock();
  }

  flushAll();
  return html;
}

function renderSource(source, path) {
  if (isTextPath(path)) {
    return `<pre><code>${escapeHtml(source)}</code></pre>`;
  }

  if (isJsonPath(path)) {
    try {
      const parsed = JSON.parse(source);
      return `<pre><code class="language-json">${escapeHtml(JSON.stringify(parsed, null, 2))}</code></pre>`;
    } catch {
      return `<pre><code class="language-json">${escapeHtml(source)}</code></pre>`;
    }
  }

  return renderMarkdown(source, path);
}

function renderCurrentSource(source) {
  const title = extractTitle(source, currentPath);
  pageTitleElement.textContent = title;
  pagePathElement.textContent = currentPath;
  pageContentElement.innerHTML = renderSource(source, currentPath);
  document.title = `${title} | Melee Modding Wiki`;
}

function renderPdfPage(path) {
  const filename = path.split("/").at(-1) || path;
  const fileUrl = buildFileUrl(path);
  pageTitleElement.textContent = filename;
  pagePathElement.textContent = path;
  pageContentElement.innerHTML = `
    <div class="error-card">
      <p><strong>PDF files are opened directly</strong> instead of being rendered in the wiki viewer.</p>
      <p><a href="${escapeHtml(fileUrl)}" target="_blank" rel="noopener noreferrer">Open PDF</a></p>
    </div>
  `;
  document.title = `${filename} | Melee Modding Wiki`;
}

function renderMissingPage(path, errorMessage) {
  const filename = path.split("/").at(-1) || path;
  const canCreate = isEditablePath(path);

  pageTitleElement.textContent = filename;
  pagePathElement.textContent = path;
  pageContentElement.innerHTML = `
    <div class="error-card">
      <p><strong>Could not load:</strong> <code>${escapeHtml(path)}</code></p>
      ${
        canCreate
          ? "<p>This file does not exist yet. Click <strong>Edit Page</strong> to create it.</p>"
          : "<p>This route is read-only in the browser editor.</p>"
      }
      <p>Error: <code>${escapeHtml(errorMessage)}</code></p>
    </div>
  `;
  document.title = `${filename} | Melee Modding Wiki`;
}

function updateEditorMeta() {
  const value = editorInputElement.value || "";
  const lineCount = value ? value.split("\n").length : 0;
  const wordCount = value.trim() ? value.trim().split(/\s+/).length : 0;
  const lineLabel = lineCount === 1 ? "line" : "lines";
  const wordLabel = wordCount === 1 ? "word" : "words";

  editorFileLabelElement.textContent = currentPath;
  editorMetaElement.textContent = `${lineCount} ${lineLabel} | ${wordCount} ${wordLabel}`;
}

function setEditorStatus(message, tone) {
  editorStatusElement.textContent = message;
  editorStatusElement.dataset.tone = tone;
}

function syncEditorUi() {
  editorWorkspaceElement.classList.toggle("editor-active", isEditing);
  editorPaneElement.hidden = !isEditing;
  editToggleButton.hidden = isEditing;
  editorCancelButton.hidden = !isEditing;
  editorSaveButton.hidden = !isEditing;

  editToggleButton.disabled = !currentPageEditable || isSaving;
  editorCancelButton.disabled = isSaving;
  editorSaveButton.disabled = isSaving || !currentPageEditable || !isDirty;

  if (!isEditing) {
    editToggleButton.textContent = currentPageEditable
      ? currentPageExists
        ? "Edit Page"
        : "Create Page"
      : "Read Only";
  }

  if (isSaving) {
    setEditorStatus("Saving", "editing");
  } else if (isEditing && isDirty) {
    setEditorStatus("Unsaved Changes", "dirty");
  } else if (isEditing) {
    setEditorStatus("Editing", "editing");
  } else if (!currentPageEditable) {
    setEditorStatus("Read Only", "readonly");
  } else if (currentPageExists) {
    setEditorStatus("View Mode", "idle");
  } else {
    setEditorStatus("Ready to Create", "idle");
  }

  updateEditorMeta();
}

function beginEditing() {
  if (!currentPageEditable || isEditing) {
    return;
  }

  const initialDraft = currentPageExists ? currentSource : getDefaultDraftSource(currentPath);
  isEditing = true;
  editorInputElement.value = initialDraft;
  isDirty = initialDraft !== currentSource;
  renderCurrentSource(initialDraft);
  syncEditorUi();
  editorInputElement.focus();
  editorInputElement.setSelectionRange(initialDraft.length, initialDraft.length);
}

function stopEditing({ confirmIfDirty = true } = {}) {
  if (!isEditing) {
    return true;
  }

  if (confirmIfDirty && isDirty) {
    const shouldDiscard = window.confirm("Discard unsaved changes?");
    if (!shouldDiscard) {
      return false;
    }
  }

  isEditing = false;
  isSaving = false;
  isDirty = false;
  editorInputElement.value = currentSource;

  if (currentPageExists) {
    renderCurrentSource(currentSource);
  } else if (isPdfPath(currentPath)) {
    renderPdfPage(currentPath);
  } else {
    renderMissingPage(currentPath, "HTTP 404");
  }

  syncEditorUi();
  return true;
}

function handleEditorInput() {
  if (!isEditing) {
    return;
  }

  const draft = editorInputElement.value;
  isDirty = draft !== currentSource;
  renderCurrentSource(draft);
  syncEditorUi();
}

async function saveCurrentPage() {
  if (!isEditing || !currentPageEditable || isSaving) {
    return;
  }

  const draft = editorInputElement.value;
  isSaving = true;
  syncEditorUi();

  let saveError = null;

  try {
    const response = await fetch(SAVE_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        path: currentPath,
        content: draft,
      }),
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }

    currentSource = draft;
    currentPageExists = true;
    isDirty = false;
    renderCurrentSource(currentSource);
    renderNav(currentPath);
  } catch (error) {
    saveError = error;
  } finally {
    isSaving = false;
    syncEditorUi();
  }

  if (saveError) {
    setEditorStatus("Save Failed", "error");
    window.alert(`Could not save ${currentPath}\n\n${String(saveError.message || saveError)}`);
    return;
  }

  setEditorStatus("Saved", "success");
}

async function loadPage() {
  currentPath = parseRoute();
  currentPageExists = false;
  currentPageEditable = isEditablePath(currentPath);
  currentSource = "";

  renderNav(currentPath);
  pagePathElement.textContent = currentPath;
  pageTitleElement.textContent = "Loading...";
  pageContentElement.innerHTML = "<p>Loading wiki page...</p>";
  updateEditorMeta();
  syncEditorUi();

  if (isPdfPath(currentPath)) {
    currentPageEditable = false;
    renderPdfPage(currentPath);
    syncEditorUi();
    return;
  }

  try {
    const response = await fetch(buildFileUrl(currentPath), { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    currentSource = await response.text();
    currentPageExists = true;
    renderCurrentSource(currentSource);
  } catch (error) {
    renderMissingPage(currentPath, String(error.message || error));
  }

  syncEditorUi();
}

editToggleButton.addEventListener("click", beginEditing);
editorCancelButton.addEventListener("click", () => {
  stopEditing({ confirmIfDirty: true });
});
editorSaveButton.addEventListener("click", saveCurrentPage);
editorInputElement.addEventListener("input", handleEditorInput);

window.addEventListener("keydown", (event) => {
  if (!isEditing) {
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveCurrentPage();
    return;
  }

  if (event.key === "Escape") {
    event.preventDefault();
    stopEditing({ confirmIfDirty: true });
  }
});

window.addEventListener("beforeunload", (event) => {
  if (!isEditing || !isDirty) {
    return;
  }

  event.preventDefault();
  event.returnValue = "";
});

window.addEventListener("hashchange", async () => {
  if (suppressHashChange) {
    suppressHashChange = false;
    return;
  }

  const nextPath = parseRoute();
  if (isEditing && isDirty && nextPath !== currentPath) {
    const shouldDiscard = window.confirm("Discard unsaved changes and open a different page?");
    if (!shouldDiscard) {
      suppressHashChange = true;
      window.location.hash = buildHash(currentPath);
      return;
    }
  }

  if (isEditing) {
    stopEditing({ confirmIfDirty: false });
  }

  await loadPage();
});

loadPage();
