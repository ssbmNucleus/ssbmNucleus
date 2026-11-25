"""Wrap ported data as a roster character and build a test ISO.

Uses the app's own clone packaging pieces (portraits, stock icons, CSS icon, name
banners) around a donor package whose data and animation files have been
replaced by the port's.

Costumes come from <work>/package/costumes/costumes.json when ultimate_recolors.py
has made it (any number, the game's own colours); otherwise the app's five tinted ones.
The fighter's own voice and sounds come from <work>/package/sound.zip when make_sounds.py
has made it; otherwise the donor's.

Usage (cwd app/backend, absolute paths: MexCLI runs from app/):
  python package_build.py art   <work> <Name> <donor> <body.dat>      # costumes + portraits (no port data needed)
  python package_build.py build <work> <Name> <donor> <body.dat> [<out.iso>]
"""
import copy
import io
import json
import shutil
import subprocess
import os
import sys
import _where  # noqa: E402
import zipfile
from pathlib import Path

sys.path.insert(0, str(_where.BACKEND))
from core.config import MEXCLI_PATH, PROJECT_ROOT, get_subprocess_args  # noqa: E402
from shared import mod_files  # noqa: E402
from shared.rendering.hitbox_elements import CHAR_PREFIXES  # noqa: E402
from vault.echo import clone, package  # noqa: E402
import mexcli.commands  # noqa: E402

phase, work, name, donor, body = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4], Path(sys.argv[5])
iso_out = Path(sys.argv[6]) if len(sys.argv) > 6 else None
prefix = CHAR_PREFIXES[donor]
pkg = work / 'package'
cos, art = pkg / 'costumes', pkg / 'art'
pkg.mkdir(exist_ok=True)

CSS_DIR = work / 'project' / 'assets' / 'css'
sys.path.insert(0, str(_where.HERE))
from roster_tile import roster_tile  # noqa: E402


# ---- costumes (cached)
listing = cos / 'costumes.json'
if listing.exists():
    rows = json.loads(listing.read_text('utf-8'))
else:
    codes = [c for c, _, _ in clone.COSTUMES]
    if not all((cos / f'{prefix}{c}.dat').exists() for c in codes):
        if cos.exists():
            import shutil
            shutil.rmtree(cos)
        cos.mkdir()
        base = cos / (prefix + 'Nr.dat')
        base.write_bytes(body.read_bytes())
        # 'neutral' tints only the unsaturated cloth and leaves skin, hair and coloured trim alone
        clone.recolor(base, cos, prefix, 'neutral', lambda label: print(' ', label, flush=True))
    rows = [{'code': c, 'name': label, 'file': f'{prefix}{c}.dat'} for c, label, _ in clone.COSTUMES]
paths = [cos / r['file'] for r in rows]

# ---- artwork (cached)
chain_file = pkg / 'chain.json'
chain = json.loads(chain_file.read_text('utf-8')) if chain_file.exists() else None
port_dir = work / os.environ.get('PORT_DIR', 'port')
final = port_dir / ('final_w' if chain else 'final')
own_rig = (work / 'rig' / 'lookup.json').is_file()
animation = None
if own_rig and (work / f'{donor}.zip').is_file():
    with zipfile.ZipFile(work / f'{donor}.zip') as archive:
        candidate = final / json.loads(archive.read('fighter.json'))['files']['animFile']
        if candidate.is_file():
            animation = candidate
art.mkdir(exist_ok=True)
artwork = []
for i, (path, row) in enumerate(zip(paths, rows)):
    files = {k: art / f'{i}_{k}.png' for k in ('csp', 'hd', 'stock')}
    if not all(f.exists() for f in files.values()):
        print('  rendering', row['name'], flush=True)
        if own_rig:
            from fighter_port.harness.port_art import render_assets
            made = render_assets(path, work, animation)
        else:
            made = clone.render_assets(path, donor)
        for k, f in files.items():
            f.write_bytes(made[k])
    artwork.append({k: f.read_bytes() for k, f in files.items()})
print('costumes and artwork ready:', [r['name'] for r in rows])
if phase == 'art':
    sys.exit(0)

# ---- fighter package
fighter_zip = pkg / f'{name}.zip'
donor_zip = (work / f'{donor}.zip').read_bytes()
# data files and costumes made for a weapon that bends go together, or not at all
port_report = json.loads((port_dir / 'report.json').read_text('utf-8'))
# a fighter with an effect file of its own: {'file', 'symbol'}; the file lies beside it
own_effects = json.loads((final / 'effects.json').read_text('utf-8')) if (final / 'effects.json').exists() else None
# files of the donor's package that the port brings its own of (the results screen's clips for a fighter on its own
# skeleton): {the package's file name: the file beside this list that takes its place}
replaced = json.loads((final / 'replace.json').read_text('utf-8')) if (final / 'replace.json').exists() else {}
# files the donor's package never had (the one-player intro card's and ending's clips): they go on the disc as they
# are, and the package's entry names their roots
extra = json.loads((final / 'extra.json').read_text('utf-8')) if (final / 'extra.json').exists() else {}
n_items = int(port_report.get('items') or 0)
own_sound = pkg / 'sound.zip'
print('port data from', final, chain or '', 'items', n_items, 'own sounds' if own_sound.exists() else "the donor's sounds")
with zipfile.ZipFile(io.BytesIO(donor_zip)) as z:
    fj = json.loads(z.read('fighter.json'))
    pl_name, aj_name = fj['files']['fighterDataPath'], fj['files']['animFile']
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for item in z.infolist():
            data = z.read(item.filename)
            if item.filename in (pl_name, aj_name):
                data = (final / item.filename).read_bytes()
            if item.filename in replaced:
                data = (final / replaced[item.filename]).read_bytes()
            if item.filename == 'sound.zip' and own_sound.exists():
                data = own_sound.read_bytes()           # a bank of its own name: installed beside the donor's, not in its place
            if item.filename == 'fighter.json' and n_items:
                # the port's own items (a projectile): one entry each; the code file fills in their functions
                meta = json.loads(data)
                calls = ('onSpawn onDestroy onPickup onDrop onThrow onGiveDamage onTakeDamage onEnterAir onReflect onClank '
                         'onUnk2 onHitShieldBounce onHitShieldDetermineDestroy onUnk3').split()
                meta['items'] = [dict({'name': f'{name} item {i}', 'states': [{'animID': 0, 'animationCallback': 0,
                                       'physicsCallback': 0, 'collisionCallback': 0}]}, **{c: 0 for c in calls})
                                 for i in range(n_items)]
                data = json.dumps(meta, indent=2).encode('utf-8')
            if item.filename == 'fighter.json' and chain:
                # the costume carries added joints (a weapon that bends): the fighter's joint count says so
                meta = json.loads(data)
                meta['boneDefinitions']['lookup']['boneCount'] = chain['joints']
                data = json.dumps(meta, indent=2).encode('utf-8')
            if item.filename == 'fighter.json' and own_effects:
                meta = json.loads(data)
                meta['files'].update(effectFile=own_effects['file'], effectSymbol=own_effects['symbol'])
                data = json.dumps(meta, indent=2).encode('utf-8')
            if item.filename == 'fighter.json':
                # Kirby copying the fighter. The donor's entries name the donor's own hat code, and that code reads
                # the DONOR's hat (m-ex's table of hats, at the donor's own place), which is only loaded when the
                # donor is in the match: with any other fighters the game stops as Kirby puts the hat on
                # ("fighter parts model num over", ftparts.c line 627; seen with every port, in a versus match
                # and at the start of a Classic fight against Kirby). Until a port brings a hat of its own, Kirby
                # gets nothing from it: with no entry the engine puts no hat on and keeps his own special.
                meta = json.loads(data)
                for key in [k for k in meta.get('functions', {}) if k.startswith('kirby')]:
                    meta['functions'][key] = 0
                data = json.dumps(meta, indent=2).encode('utf-8')
            if item.filename == 'fighter.json' and extra.get('fighter_files'):
                meta = json.loads(data)
                meta['files'].update(extra['fighter_files'])
                data = json.dumps(meta, indent=2).encode('utf-8')
            if item.filename == 'fighter.json' and (final / 'lookup.json').exists():
                # a fighter on its own skeleton brings its own table of which joint is which
                meta = json.loads(data)
                meta['boneDefinitions']['lookup'].update(json.loads((final / 'lookup.json').read_text('utf-8'))['editor_json'])
                data = json.dumps(meta, indent=2).encode('utf-8')
            zo.writestr(item, data)
        if own_effects:
            zo.writestr(own_effects['file'], (final / own_effects['file']).read_bytes())
roots = mod_files.dat_roots(body)
joints = [r for r in roots if r.startswith('Ply') and r.endswith('_joint') and 'matanim' not in r]
symbols = {'joint': joints[0], 'material': next((r for r in roots if r.endswith('_matanim_joint')), '')}
echo = dict(donor=donor, donor_prefix=prefix, name=name, short_name=name[:24], ops=[], animations=[],
            version=package.VERSION)
# costumes with the held weapons, when add_weapons.py has made them (artwork stays as rendered)
with_weapons = pkg / 'costumes_w'
if all((with_weapons / p.name).exists() for p in paths):
    paths = [with_weapons / p.name for p in paths]
    print('using costumes with weapons')


def team(colour):
    """The costume whose changed textures lean most to a team colour (0 when none stands out)."""
    shares = [(r.get('team') or {}).get(colour) for r in rows]
    if all(v is not None for v in shares):
        # how much of what changes between the costumes is this team's colour in each: the most, when it stands out
        most = max(range(len(rows)), key=lambda i: shares[i])
        return most if shares[most] >= 0.05 else 0
    tones = [r.get('tone') for r in rows]
    if not all(tones):
        return {'red': 1, 'blue': 2, 'green': 3}[colour] if len(rows) > 3 else 0
    import colorsys
    want = {'red': 0.0, 'green': 120.0, 'blue': 230.0}[colour]
    best, off = 0, 40.0                                 # within 40 degrees of the team's hue, and not grey
    for i, t in enumerate(tones):
        h, s, _ = colorsys.rgb_to_hsv(*(v / 255 for v in t))
        d = abs((h * 360 - want + 180) % 360 - 180)
        if s > 0.2 and d < off:
            best, off = i, d
    return best


def assemble(donor_bytes):
    """clone.assemble for any number of costumes."""
    materialized, _ = package.materialize(donor_bytes, echo)
    with zipfile.ZipFile(io.BytesIO(materialized)) as d:
        fighter = json.loads(d.read('fighter.json'))
        old = {Path((c.get('file') or {}).get('fileName', '')).stem + '.zip' for c in fighter.get('costumes', [])}
        members = {n: d.read(n) for n in d.namelist() if n not in old and n != 'fighter.json'}
    fighter['assets'] = {'cssIcon': 'css\\icon', 'resultBannerBig': 'rst\\big_banner', 'resultSmallBig': 'rst\\small_banner'}
    fighter.update(redCostumeIndex=team('red'), blueCostumeIndex=team('blue'), greenCostumeIndex=team('green'))
    game_file = port_dir / 'game.json'
    if game_file.exists():
        # a fighter that jumps off walls in its own game does here: Melee asks the roster entry, not the fighter
        # data (the game's word means the same for the fighters in both games: Mario, Fox, Samus, Sheik ... yes)
        wall = (json.loads(game_file.read_text('utf-8')).get('attributes') or {}).get('wall_jump_type')
        if isinstance(wall, bool):
            fighter['canWallJump'] = wall
    template = copy.deepcopy(fighter['costumes'][0])
    fighter['costumes'] = []
    loose = {'css_icon.png': roster_tile(artwork[0]['hd'], name, CSS_DIR) or clone.css_icon(artwork[0]['csp'])}
    members['icon.png'] = loose['css_icon.png']
    members['big_banner.png'] = clone.banner(echo['name'].upper(), (256, 28))
    members['small_banner.png'] = clone.banner(echo['short_name'].upper(), (120, 24))
    for i, (row, path, pic) in enumerate(zip(rows, paths, artwork)):
        stem = prefix + row['code']
        costume = copy.deepcopy(template)
        costume.update(name=row['name'], icon=None, csp=None, colorSmashGroup=-200 - i)
        costume['file'] = dict(fileName=stem + '.dat', visibilityIndex=0, jointSymbol=symbols['joint'],
                               materialSymbol=symbols.get('material', ''))
        fighter['costumes'].append(costume)
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(stem + '.dat', path.read_bytes())
            z.writestr('csp.png', pic['csp'])
            z.writestr('stc.png', pic['stock'])
        members[stem + '.zip'] = inner.getvalue()
        loose[f'csp_{i}.png'], loose[f'stock_{i}.png'] = pic['csp'], pic['stock']
        loose[f'costumes/{stem}_csp_hd.png'] = pic['hd']
    from fighter_port.port_receipt import package_members
    members.update(package_members(port_report, name))
    members['fighter.json'] = json.dumps(fighter, indent=2).encode()
    # The port's own C travels in the package (code/): the Vault keeps it with the fighter, and
    # the Melee Unlocked export builds the fighter's plugin from it
    # (app/backend/projects/install/melee_unlocked.py).
    if (work / 'code').is_dir():
        for src in sorted((work / 'code').glob('*.c')):
            members['code/' + src.name] = src.read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, data in members.items():
            z.writestr(n, data)
    return output.getvalue(), fighter, loose


data, fighter, loose = assemble(out.getvalue())
fighter_zip.write_bytes(data)
from fighter_port.port_receipt import package_members
for note_name, note_bytes in package_members(port_report, name).items():
    (pkg / note_name).write_bytes(note_bytes)
for rel, blob in loose.items():
    dest = pkg / 'assets' / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
print('fighter package:', fighter_zip, fighter_zip.stat().st_size, 'costumes', len(rows),
      'team colours', {k: fighter[k] for k in ('redCostumeIndex', 'blueCostumeIndex', 'greenCostumeIndex')})

if iso_out:
    # (a fighter of forms installs each form into the group's one project: PORT_PROJECT names it, and the link stage
    # exports the disc once every form is in, so PORT_NO_EXPORT stops this one before its export: forms_link.py)
    proj = Path(os.environ['PORT_PROJECT']) if os.environ.get('PORT_PROJECT') else work / 'project' / 'project.mexproj'
    listing = mexcli.commands.run_json(['list-fighters', proj])
    if any(f.get('name') == name for f in listing.get('fighters') or []):
        raise SystemExit(f'{name} is already in the test project; start from a fresh project')
    # the fighter's own series emblem (behind its damage, on the results screen): the series is added to the project
    # and the package's fighter is pointed at it before it goes in (else it keeps the donor's)
    emblem, series_file = pkg / 'series_icon.png', pkg / 'series.json'
    if emblem.exists() and series_file.exists():
        series_name = json.loads(series_file.read_text('utf-8'))['name']
        added = mexcli.commands.run_json(['add-series', proj, series_name, emblem]
                                         + ([pkg / 'series_emblem.obj'] if (pkg / 'series_emblem.obj').exists() else []))
        print('series:', {k: added.get(k) for k in ('success', 'seriesId', 'error')})
        if added.get('success') and 'seriesId' in added:
            with zipfile.ZipFile(fighter_zip) as z:
                members = {n: z.read(n) for n in z.namelist()}
            meta = json.loads(members['fighter.json'])
            meta['seriesID'] = added['seriesId']
            members['fighter.json'] = json.dumps(meta, indent=2).encode('utf-8')
            with zipfile.ZipFile(fighter_zip, 'w', zipfile.ZIP_DEFLATED) as z:
                for n, blob in members.items():
                    z.writestr(n, blob)
    r = subprocess.run([str(MEXCLI_PATH), 'add-fighter', str(proj), str(fighter_zip)], capture_output=True,
                       text=True, cwd=str(PROJECT_ROOT), **get_subprocess_args())
    print('add-fighter rc', r.returncode, (r.stdout or '')[-400:], (r.stderr or '')[-400:])
    for extra_name in extra.get('files') or []:
        shutil.copyfile(final / extra_name, proj.parent / 'files' / extra_name)
        print('added to the disc:', extra_name, (final / extra_name).stat().st_size, 'bytes')
    import re as _re
    print('sound calls pointed at the fighter\'s own bank:', _re.findall(r'"soundCallsRetargeted":\s*(\d+)', r.stdout or ''))
    if r.returncode:
        sys.exit(3)
    listing = mexcli.commands.run_json(['list-fighters', proj])
    print('in project:', next(f for f in listing['fighters'] if f.get('name') == name))
    fanfare, fanfare_file = pkg / 'victory_theme.hps', pkg / 'victory.json'
    if fanfare.exists() and fanfare_file.exists():
        # its own victory fanfare (else the donor's plays when it wins): added the way the app adds one
        music = mexcli.commands.run_json(['add-music', proj, fanfare, json.loads(fanfare_file.read_text('utf-8'))['name']])
        set_ = mexcli.commands.run_json(['set-fighter-music', proj, name, music['musicId']]) if music.get('success') and 'musicId' in music else {}
        print('victory fanfare:', {k: music.get(k) for k in ('success', 'musicId', 'error')}, {k: set_.get(k) for k in ('success', 'error')})
    said = pkg / 'announcer.wav'
    if said.exists():
        # the announcer says the fighter's own name (else the donor's call stays): added the way the app adds one
        got = mexcli.commands.run_json(['set-fighter-announcer', proj, name, said])
        print('announcer:', {k: got.get(k) for k in ('success', 'announcerCall', 'error')})
    if os.environ.get('PORT_NO_EXPORT'):
        print('installed; no disc made here (PORT_NO_EXPORT)')
        sys.exit(0)
    from mexcli.project import MexManager
    from core import iso_reads
    iso_out.parent.mkdir(parents=True, exist_ok=True)
    if iso_out.exists():
        raise SystemExit(f'{iso_out} exists; choose a new name')
    mgr = MexManager(str(MEXCLI_PATH), str(proj))
    res = mgr.export_iso(str(iso_out), progress_callback=lambda p, m: print(f'  export {p}% {m}', flush=True))
    print('export:', {k: res[k] for k in list(res)[:8]} if isinstance(res, dict) else res)
    iso_reads.ensure_padding(iso_out)
    print('iso:', iso_out, iso_out.stat().st_size)
