"""Build the mobile vault client into a Cloudflare Pages site directory.

    python build.py <site_dir>            bundle + assemble index.html
    python build.py <site_dir> --assets   also (re)build packs/icons via
                                          vault_assets (backend must be import-
                                          able; icons need it RUNNING)

The site dir also holds the big static assets (packs/, stock/, stage/,
charmaps.json) built by tracker.cloud.vault_assets — they are identical for
every user and far too large for the repo, so they live only in the deploy dir.

Deploy: npx wrangler pages deploy <site_dir> --project-name nucleus-vault
(esbuild comes from app/frontend/node_modules; no other toolchain.)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.normpath(os.path.join(HERE, "..", "..", "app", "frontend"))
ESBUILD = os.path.join(VIEWER, "node_modules", ".bin",
                       "esbuild.cmd" if os.name == "nt" else "esbuild")
# The lazy item manifest can exceed cmd.exe's 8191-character command limit.
# Invoke the package's Node entry directly on Windows, without a batch shell.
ESBUILD_COMMAND = ([shutil.which("node") or "node",
                    os.path.join(VIEWER, "node_modules", "esbuild", "bin", "esbuild")]
                   if os.name == "nt" else [ESBUILD])

# slippi.gg's rank icons, shared with the desktop (frontend/src/tracker/assets/ranks/).
# Unlike packs/stock/stage these are in the repo and tiny, so they copy on
# every build rather than waiting for --assets and a running backend. Only the
# tiers `rankSrc` can name ship — rank_Hax.svg is not a tier anyone reaches.
RANKS_SRC = os.path.join(VIEWER, "src", "tracker", "assets", "ranks")
RANK_ICONS = [f"rank_{word}_{roman}.svg"
              for word in ("Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master")
              for roman in ("I", "II", "III")] + ["rank_Grand_Master.svg"]

CFG = {
    "supabaseUrl": "https://nttxcjrnqccogsibeqzz.supabase.co",
    # Publishable anon key — the viewer already ships it; RLS deny-all is what
    # actually protects the vault tables.
    "anonKey": (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6"
        "Im50dHhjanJucWNjb2dzaWJlcXp6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAyMDY3"
        "NTYsImV4cCI6MjA3NTc4Mjc1Nn0.5EJaMlem2rASzuttx1_PtwGd2cuyAOtM8VJmwwiEudo"
    ),
}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    site = os.path.abspath(sys.argv[1])
    os.makedirs(site, exist_ok=True)

    # Immutable collision + simulator payloads, one request for the played stage.
    # Keep old hashes: an already-open page may still refer to the prior build.
    stages_src = os.path.join(VIEWER, 'src', 'tracker', 'replays', 'data', 'stages')
    stages_out = os.path.join(site, 'stages')
    os.makedirs(stages_out, exist_ok=True)
    stage_files, stage_tables = {}, {}
    for name in sorted(os.listdir(stages_src)):
        if not name.endswith('.json') or not name[:-5].isdigit():
            continue
        with open(os.path.join(stages_src, name), 'rb') as f:
            payload = f.read()
        digest = hashlib.sha256(payload).hexdigest()[:12]
        hashed = f'{name[:-5]}.{digest}.json'
        with open(os.path.join(stages_out, hashed), 'wb') as f:
            f.write(payload)
        stage_files[name[:-5]] = f'stages/{hashed}'
        stage_tables[name[:-5]] = json.loads(payload)
        print(f'wrote stages/{hashed}  ({len(payload):,} bytes)')
    stage_define = f'--define:__STAGE_DATA_FILES__={json.dumps(stage_files, separators=(",", ":"))}'
    fighters_src = os.path.join(VIEWER, 'src', 'tracker', 'replays', 'data', 'fighters')
    fighters_out = os.path.join(site, 'fighters')
    os.makedirs(fighters_out, exist_ok=True)
    fighter_files = {}
    for name in sorted(os.listdir(fighters_src)):
        if not name.endswith('.json') or not name[:-5].isdigit():
            continue
        with open(os.path.join(fighters_src, name), 'rb') as f:
            payload = f.read()
        digest = hashlib.sha256(payload).hexdigest()[:12]
        hashed = f'{name[:-5]}.{digest}.json'
        with open(os.path.join(fighters_out, hashed), 'wb') as f:
            f.write(payload)
        fighter_files[name[:-5]] = f'fighters/{hashed}'
        print(f'wrote fighters/{hashed}  ({len(payload):,} bytes)')
    fighter_define = f'--define:__FIGHTER_DATA_FILES__={json.dumps(fighter_files, separators=(",", ":"))}'
    items_src = os.path.join(VIEWER, 'src', 'tracker', 'replays', 'data', 'items')
    items_out = os.path.join(site, 'items')
    os.makedirs(items_out, exist_ok=True)
    item_files = {}
    for name in sorted(os.listdir(items_src)):
        if not name.endswith('.json') or not name[:-5].isdigit():
            continue
        with open(os.path.join(items_src, name), 'rb') as f:
            payload = f.read()
        digest = hashlib.sha256(payload).hexdigest()[:12]
        hashed = f'{name[:-5]}.{digest}.json'
        with open(os.path.join(items_out, hashed), 'wb') as f:
            f.write(payload)
        item_files[name[:-5]] = f'items/{hashed}'
    item_define = f'--define:__ITEM_DATA_FILES__={json.dumps(item_files, separators=(",", ":"))}'
    # The hit sparks' per-fighter hitbox tables (~7 KB each), fetched for every replay.
    hits_src = os.path.join(VIEWER, 'src', 'tracker', 'replays', 'data', 'hits')
    hits_out = os.path.join(site, 'hits')
    os.makedirs(hits_out, exist_ok=True)
    hit_files = {}
    for name in sorted(os.listdir(hits_src)):
        if not name.endswith('.json') or not name[:-5].isdigit():
            continue
        with open(os.path.join(hits_src, name), 'rb') as f:
            payload = f.read()
        digest = hashlib.sha256(payload).hexdigest()[:12]
        hashed = f'{name[:-5]}.{digest}.json'
        with open(os.path.join(hits_out, hashed), 'wb') as f:
            f.write(payload)
        hit_files[name[:-5]] = f'hits/{hashed}'
    hit_define = f'--define:__HIT_DATA_FILES__={json.dumps(hit_files, separators=(",", ":"))}'

    # Only the offline artifact template embeds the full tables. Its separate
    # file is fetched at export time, never when opening a replay. An esbuild
    # injected module avoids Windows' command-line size limit for this data.
    inline_path = os.path.join(site, '_inline-stage-data.js')

    def bundle_js(entry, defines=()):
        path = os.path.join(site, "_bundle.js")
        subprocess.run([
            *ESBUILD_COMMAND, os.path.join(HERE, "src", entry),
            "--bundle", "--minify", "--format=iife",
            f"--outfile={path}",
            stage_define,
            fighter_define,
            item_define,
            hit_define,
            *defines,
        ], check=True)
        with open(path, encoding="utf-8") as f:
            js = f.read()
        os.remove(path)
        return js.replace("</script", "<\\/script")

    # A separate classic worker keeps raw replay parsing off the UI thread.
    # Hash the actual emitted bytes; the app stays a single inlined IIFE.
    worker_js = bundle_js("derive-worker.js")
    worker_bytes = worker_js.encode("utf-8")
    worker_digest = hashlib.sha256(worker_bytes).hexdigest()[:12]
    worker_name = f"derive-worker.{worker_digest}.js"
    with open(os.path.join(site, worker_name), "wb") as f:
        f.write(worker_bytes)
    worker_define = [f"--define:__DERIVE_WORKER_URL__={json.dumps('./' + worker_name)}"]
    print(f"wrote {os.path.join(site, worker_name)}  ({len(worker_bytes) / 1024:.0f} KB)")

    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    # The app version this vault build ships with. "Report this chat" sends it
    # (the report worker wants x.y.z); the phone has no version of its own.
    with open(os.path.join(HERE, "..", "..", "app", "package.json"), encoding="utf-8") as f:
        cfg = {**CFG, "version": json.load(f).get("version", "0.0.0")}
    html = (tpl.replace("__CFG__", json.dumps(cfg).replace("</", "<\\/"))
               .replace("__BUNDLE__", bundle_js("main.js", worker_define)))
    out = os.path.join(site, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out}  ({os.path.getsize(out) / 1024:.0f} KB)")

    # The share artifact template: viewer runtime baked in, __SHARE_B64__ left
    # for the client to fill at share time. Served as a static asset.
    with open(os.path.join(HERE, "share-template.html"), encoding="utf-8") as f:
        share_tpl = f.read()
    with open(inline_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('export const __INLINE_STAGE_DATA__ = ' + json.dumps(stage_tables, separators=(',', ':')))
        # Fighter tables are NOT inlined (27 x ~350 KB): share.js embeds only the
        # clip's own fighters into each artifact's payload.
    try:
        share_js = bundle_js("share-viewer.js", [f'--inject:{inline_path}'])
    finally:
        os.remove(inline_path)
    share_html = share_tpl.replace("__SHARE_RUNTIME__", share_js)
    share_out = os.path.join(site, "share-template.html")
    with open(share_out, "w", encoding="utf-8") as f:
        f.write(share_html)
    print(f"wrote {share_out}  ({os.path.getsize(share_out) / 1024:.0f} KB)")

    # The public /replay/<id> runtime. Unlike the artifact this is NOT inlined:
    # the Worker that serves ssbmnucleus.net/replay/* writes the HTML (it has to,
    # for the per-share unfurl tags) and points at this file through its asset
    # proxy, so the page and the runtime deploy independently.
    #
    # The filename carries a content hash because the Worker's asset proxy
    # caches for a day: a fixed name means a deploy ships and phones keep
    # running yesterday's runtime until the edge lets go (which is exactly what
    # happened). The Worker reads the current name from replay.manifest.json
    # (cached briefly), so hashed files can cache forever and never lie.
    # A raw .slp share is worked out in the same hashed derive worker the vault
    # uses; the page's <base href="/replay/_a/"> resolves it through the Worker.
    replay_js = bundle_js("public-viewer.js", worker_define)
    digest = hashlib.md5(replay_js.encode("utf-8")).hexdigest()[:10]
    runtime_name = f"replay.{digest}.js"
    for old in os.listdir(site):                 # superseded hashes don't pile up
        if old.startswith("replay.") and old.endswith(".js") and old != runtime_name:
            os.remove(os.path.join(site, old))
    for name in (runtime_name, "replay.js"):     # bare name kept as a fallback
        with open(os.path.join(site, name), "w", encoding="utf-8") as f:
            f.write(replay_js)
    with open(os.path.join(site, "replay.manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"runtime": runtime_name}, f)
    print(f"wrote {os.path.join(site, runtime_name)}  ({len(replay_js) / 1024:.0f} KB)")

    # Home-screen identity: manifest + baked icons (iOS needs opaque squares).
    shutil.copyfile(os.path.join(HERE, "manifest.webmanifest"),
                    os.path.join(site, "manifest.webmanifest"))
    icons = os.path.join(site, "icons")
    os.makedirs(icons, exist_ok=True)
    for name in os.listdir(os.path.join(HERE, "icons")):
        shutil.copyfile(os.path.join(HERE, "icons", name),
                        os.path.join(icons, name))
    # Root copy: iOS probes /apple-touch-icon.png blindly, and a root URL
    # distinct from the old icons/ one busts Safari's per-domain icon cache.
    shutil.copyfile(os.path.join(HERE, "icons", "apple-touch-icon.png"),
                    os.path.join(site, "apple-touch-icon.png"))
    print(f"wrote {icons} + manifest.webmanifest + /apple-touch-icon.png")

    ranks = os.path.join(site, "rank")
    os.makedirs(ranks, exist_ok=True)
    copied = 0
    for name in RANK_ICONS:
        src = os.path.join(RANKS_SRC, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(ranks, name))
            copied += 1
    print(f"wrote {ranks}  ({copied}/{len(RANK_ICONS)} rank icons)")

    if "--assets" in sys.argv:
        backend = os.path.normpath(os.path.join(HERE, "..", "..", "app", "backend"))
        sys.path.insert(0, backend)
        from tracker.cloud import vault_assets
        vault_assets.main([site])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
