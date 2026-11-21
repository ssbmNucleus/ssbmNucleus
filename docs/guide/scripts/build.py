#!/usr/bin/env python3
"""Assemble the guide: sections/*.md -> dist/guide.md, dist/guide.html (+ PDF if a browser is found).

Usage (from the repo root):
    app\\venv\\Scripts\\python docs\\guide\\scripts\\build.py            # md + html
    app\\venv\\Scripts\\python docs\\guide\\scripts\\build.py --pdf      # also print dist/guide.pdf via headless Chrome/Edge

The main HTML is self-contained: images are inlined as data URIs so the single
file can be posted anywhere. A second, split build is written to dist/site/ for
static hosts with per-file size limits. Missing images render as a labelled grey
box so a half-captured guide is still readable and the gaps are obvious.
"""
from __future__ import annotations

import argparse
import base64
import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

GUIDE = Path(__file__).resolve().parents[1]
SECTIONS = GUIDE / "sections"
IMG = GUIDE / "img"
DIST = GUIDE / "dist"

CSS = """
:root { --bg:#0f1420; --fg:#e8ecf3; --muted:#9aa3b5; --accent:#f5c518; --card:#171d2b; --line:#273043; }
@media print { :root { --bg:#fff; --fg:#111; --muted:#555; --card:#f4f4f4; --line:#ddd; } }
.embed-note { color:var(--muted); font-size:0.9em; }
@media print { .html-only { display:none; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 32px 24px 96px; }
h1 { font-size: 2.2em; margin: 1.6em 0 .4em; border-bottom: 2px solid var(--accent); padding-bottom:.2em; page-break-before: always; }
h1:first-of-type { page-break-before: avoid; margin-top:.4em; }
h2 { font-size: 1.45em; margin: 1.6em 0 .4em; }
h3 { font-size: 1.15em; margin: 1.3em 0 .3em; color: var(--accent); }
p, li { max-width: 72ch; }
a { color: var(--accent); }
code { background: var(--card); padding: .1em .35em; border-radius: 4px; font-size: .92em; }
blockquote { border-left: 3px solid var(--accent); margin: 1em 0; padding: .3em 1em; color: var(--muted); background: var(--card); border-radius: 0 6px 6px 0; }
figure { margin: 1.2em 0; }
figure img { max-width: 100%; border-radius: 8px; border: 1px solid var(--line); display:block; }
figcaption { color: var(--muted); font-size: .9em; margin-top: .4em; }
.missing { display:flex; align-items:center; justify-content:center; height: 220px; border: 2px dashed var(--line); border-radius: 8px; color: var(--muted); font-family: ui-monospace, monospace; background: var(--card); }
.phone-row { display:flex; gap:14px; margin:1.4em 0; align-items:flex-start; }
.phone-row figure { flex:1 1 0; min-width:0; margin:0; }
.phone-row img { width:100%; height:auto; border-radius:14px; }
.phone-row figcaption { text-align:center; font-size:.85em; margin-top:.5em; }
@media (max-width:620px) { .phone-row { flex-wrap:wrap; } .phone-row figure { flex:1 1 45%; } }
nav.toc { background: var(--card); border:1px solid var(--line); border-radius: 8px; padding: 12px 20px; margin: 1em 0 2em; }
nav.toc ol { margin: .3em 0; padding-left: 1.4em; }
hr { border: 0; border-top: 1px solid var(--line); margin: 2.5em 0; }
"""

IMG_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)")
LINK_RE = re.compile(r"\]\((?P<target>\d\d-[a-z-]+\.md)(#[^)]*)?\)")
# ":::phones" ... ":::" — a row of phone screenshots. Full width each, a 390x844
# capture is a wall of pixels; side by side they read as a set of phones.
PHONES_RE = re.compile(r"^:::phones[ \t]*\n(?P<body>.*?)^:::[ \t]*$", re.S | re.M)


def section_files() -> list[Path]:
    return sorted(p for p in SECTIONS.glob("*.md"))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def image_figure(src: str, alt: str, *, embedded: bool) -> str:
    path = (SECTIONS / src).resolve()
    if path.exists():
        image_src = (
            f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}"
            if embedded else f"img/{path.name}"
        )
        return (
            f'<figure><img src="{image_src}" alt="{html.escape(alt)}">'
            f"<figcaption>{html.escape(alt)}</figcaption></figure>"
        )
    return f'<figure><div class="missing">missing: {html.escape(path.name)}</div><figcaption>{html.escape(alt)}</figcaption></figure>'


def md_to_html(md: str) -> str:
    """Render Markdown. Uses python-markdown when present, otherwise a small built-in converter."""
    try:
        import markdown  # type: ignore

        return markdown.markdown(md, extensions=["fenced_code", "tables", "sane_lists", "toc"],
                                 extension_configs={"toc": {"slugify": lambda value, separator: slug(value)}})
    except ImportError:
        return _mini_markdown(md)


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _mini_markdown(md: str) -> str:
    out: list[str] = []
    para: list[str] = []
    list_tag: str | None = None

    def flush_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            close_list()
            continue
        if line.startswith("<figure") or line.startswith("<hr") or line.startswith("<nav") or line.startswith('<div class="'):
            flush_para(); close_list(); out.append(line); continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_para(); close_list()
            level = len(m.group(1)); text = m.group(2)
            out.append(f'<h{level} id="{slug(text)}">{_inline(text)}</h{level}>')
            continue
        if line.startswith(">"):
            flush_para(); close_list()
            out.append(f"<blockquote>{_inline(line.lstrip('> '))}</blockquote>")
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            flush_para()
            if list_tag != "ol":
                close_list(); out.append("<ol>"); list_tag = "ol"
            out.append(f"<li>{_inline(m.group(2))}</li>")
            continue
        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            flush_para()
            if list_tag != "ul":
                close_list(); out.append("<ul>"); list_tag = "ul"
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue
        if line == "---":
            flush_para(); close_list(); out.append("<hr>"); continue
        para.append(line.strip())
    flush_para(); close_list()
    return "\n".join(out)


def build(pdf: bool, strict: bool = False) -> None:
    DIST.mkdir(exist_ok=True)
    files = section_files()
    combined_md: list[str] = []
    body: list[str] = []
    site_body: list[str] = []
    site_images: set[Path] = set()
    missing: list[str] = []
    broken_sections: list[str] = []

    for f in files:
        md = f.read_text(encoding="utf-8")
        combined_md.append(md.strip() + "\n")
        # cross-section links -> in-page anchors (the H1 slug of the target file)
        def relink(m: re.Match) -> str:
            target = SECTIONS / m.group("target")
            if not target.exists():
                broken_sections.append(m.group("target"))
            title = target.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip() if target.exists() else m.group("target")
            return f"](#{slug(title)})"
        md = LINK_RE.sub(relink, md)

        def figure_for(src: str, alt: str, *, embedded: bool) -> str:
            path = (SECTIONS / src).resolve()
            if not path.exists():
                missing.append(path.name)
            elif not embedded:
                site_images.add(path)
            return image_figure(src, alt, embedded=embedded)

        def swap(m: re.Match, *, embedded: bool) -> str:
            return "\n" + figure_for(m.group("src"), m.group("alt"), embedded=embedded) + "\n"

        def phone_row(m: re.Match, *, embedded: bool) -> str:
            # emitted on one line: a raw HTML block is left alone, but anything
            # sitting on its own line inside it gets reparsed as Markdown
            shots = "".join(figure_for(i.group("src"), i.group("alt"), embedded=embedded)
                            for i in IMG_RE.finditer(m.group("body")))
            return f'\n<div class="phone-row">{shots}</div>\n'

        def render(text: str, *, embedded: bool) -> str:
            text = PHONES_RE.sub(lambda m: phone_row(m, embedded=embedded), text)
            return md_to_html(IMG_RE.sub(lambda m: swap(m, embedded=embedded), text))

        body.append(render(md, embedded=True))
        site_body.append(render(md, embedded=False))
        body.append("<hr>")
        site_body.append("<hr>")

    def document(parts: list[str]) -> str:
        return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>SSBM Nucleus Guide</title><style>{CSS}</style></head><body><main>"
        + "\n".join(parts)
        + "</main></body></html>"
        )

    doc = document(body)
    ids = set(re.findall(r'\bid="([^"]+)"', doc))
    broken_anchors = sorted(set(re.findall(r'href="#([^"]+)"', doc)) - ids)
    if strict and (missing or broken_sections or broken_anchors):
        raise SystemExit(f"[build] incomplete guide: missing images={missing}; "
                         f"missing chapters={broken_sections}; broken anchors={broken_anchors}")
    (DIST / "guide.md").write_text("\n".join(combined_md), encoding="utf-8")
    out_html = DIST / "guide.html"
    out_html.write_text(doc, encoding="utf-8")
    print(f"[build] {len(files)} sections -> {out_html} ({out_html.stat().st_size // 1024} KB)")
    site_dir = DIST / "site"
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_img = site_dir / "img"
    site_img.mkdir(parents=True)
    site_html = site_dir / "index.html"
    site_html.write_text(document(site_body), encoding="utf-8")
    for path in sorted(site_images):
        shutil.copy2(path, site_img / path.name)
    print(f"[build] static site -> {site_html} ({len(site_images)} images)")
    if missing:
        print(f"[build] {len(missing)} image(s) missing:")
        for name in sorted(set(missing)):
            print(f"         - {name}")

    if pdf:
        browser = next(
            (p for p in (
                shutil.which("chrome"), shutil.which("msedge"),
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/usr/bin/google-chrome", "/usr/bin/chromium",
            ) if p and Path(p).exists()),
            None,
        )
        if not browser:
            print("[build] no Chrome/Edge found; skipping PDF", file=sys.stderr)
            return
        out_pdf = DIST / "guide.pdf"
        subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={out_pdf}", out_html.resolve().as_uri()],
            check=False, timeout=180,
        )
        if out_pdf.exists():
            print(f"[build] PDF -> {out_pdf} ({out_pdf.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--strict", action="store_true", help="Fail for missing images or broken chapter links")
    args = ap.parse_args()
    build(args.pdf, strict=args.strict)
