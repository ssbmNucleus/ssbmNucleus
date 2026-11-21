"""
extras_doctor.py -- triage "my extra doesn't look right in game" reports by
reading what is ACTUALLY in a project's target files, layer by layer.

    python devtools/extras_doctor.py --project My_Project-2 --char Bowser
    python devtools/extras_doctor.py --project My_Project-2 --char Bowser --extra bowser_fire_breath
    python devtools/extras_doctor.py --project "C:\\path\\to\\projectdir" --char Fox

For every extra configured for the character it reports, per layer:
  - the CURRENT bytes at the configured offset in the project file
  - whether they equal the config's vanilla value (VANILLA) or not (MODDED)
  - whether the offset still resolves IN-PLACE (context guard: neighborhood
    identical to the vanilla reference outside the extra's own color spans),
    was RELOCATED (file re-saved / layout shifted -- reports the new offset),
    or is UNRESOLVED (guard + relocation both failed: writes to this layer
    are being SKIPPED by the safety net)
  - for texture_recolor extras: the current dominant hue swatch vs vanilla,
    and whether the texel/palette region is byte-identical to vanilla

Reading the file settles the first triage question instantly: DID the install
write? If every layer reads MODDED with the mod's colors and the game still
shows the wrong color, the problem is COVERAGE (some other asset draws the
visible pixels -- route to a MAP mission / docs/dev/EXTRAS_MISSION_TEMPLATE.md);
if layers read VANILLA or UNRESOLVED, the problem is the INSTALL path.
Worked example: docs/dev/EXTRAS_AUDIT.md "Bowser breath_texture" row (blue fire
breath read fully MODDED but the game stayed orange -> the flame-body
texture, a different asset, was the missing coverage).

In-game ground truth (step 2 of the workflow) is a separate one-liner:
    python devtools/extras_audit.py --char Bowser --extra breath_texture
"""
import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]  # backend/
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.extra_lookup import get_extra_types, get_extra_type  # noqa: E402
import vault.extras.helpers as helpers  # noqa: E402
import vault.extras.relocate as relocate  # noqa: E402
from vault.extras.texture_recolor import read_current_dominant_color  # noqa: E402


def vanilla_ref(target_file):
    """Vanilla reference DAT for target_file. helpers.STORAGE_PATH is only
    set once the Flask app initializes -- standalone runs fall back to the
    repo's storage/test-base (same convention as extras_audit.py)."""
    for storage in (helpers.STORAGE_PATH, BACKEND_DIR.parent / 'storage'):
        if not storage:
            continue
        cand = relocate.vanilla_reference_path(str(storage), target_file)
        if cand:
            return cand
    return None


def resolve_project_dir(arg):
    p = Path(arg)
    if p.is_dir():
        return p
    appdata = Path(os.environ.get('LOCALAPPDATA', '')) / 'SSBM Nucleus' / 'projects' / arg
    if appdata.is_dir():
        return appdata
    sys.exit(f"project not found: {arg} (not a dir, and no "
             f"%LOCALAPPDATA%/SSBM Nucleus/projects/{arg})")


def find_dat(files_dir, target_file):
    hits = list(files_dir.rglob(target_file))
    return hits[0] if hits else None


def _layer_points(layer_id, info):
    """Yield (label, offset, write_len, block_kind) for each write point of a
    layer -- mirrors apply_hex_patches' write geometry."""
    fmt = info.get('format', 'RGBY')
    if 'records' in info:  # CF-multi
        for i, rec in enumerate(info['records']):
            if rec.get('color') is not None:
                yield f"{layer_id}[{i}]", rec['color'], 3, 'ptcl'
        return
    if 'offsets' in info:
        for i, off in enumerate(info['offsets']):
            label = f"{layer_id}[{i}]" if len(info['offsets']) > 1 else layer_id
            if fmt == 'CF':
                yield label, off + 2, 3, 'ptcl'
            elif fmt == '070707':
                yield label, off + 4, 3, 'model'
            else:
                yield label, off, 3, 'ptcl'
        return
    start = info.get('start')
    if start is None:
        return
    if fmt == 'CF':
        yield layer_id, start + 2, 3, 'ptcl'
    elif fmt == '070707':
        yield layer_id, start + 4, 3, 'model'
    elif 'size' in info:
        yield layer_id, start, info['size'], 'model'
    elif 'end' in info:
        # matrix region: report the first color entry (header 3B + vertex 1B)
        yield layer_id, start + 4, 3 if fmt == 'RGB' else 2, 'model'


def doctor_extra(char, cfg, files_dir, verbose):
    extra_id = cfg['id']
    target_file = cfg['target_file']
    dat = find_dat(files_dir, target_file)
    print(f"\n== {char} / {extra_id} ({target_file}) ==")
    if dat is None:
        print(f"  !! {target_file} not found under {files_dir}")
        return

    vanilla_path = vanilla_ref(target_file)
    if vanilla_path is None:
        print(f"  (no vanilla reference {target_file} found -- offset "
              f"resolution will be limited)")
    raw = dat.read_bytes()
    van = Path(vanilla_path).read_bytes() if vanilla_path else None

    if cfg.get('format') == 'texture_recolor':
        tex = dict(cfg['texture'])
        tex['_target_file'] = target_file
        swatch = read_current_dominant_color(dat, tex)
        v_swatch = cfg.get('vanilla', {}).get(cfg['properties'][0]['id'], '?')
        state = 'VANILLA' if (swatch or '').upper() == str(v_swatch).upper() else 'RECOLORED'
        print(f"  dominant swatch {swatch}  (vanilla {v_swatch})  -> {state}")
        if van is not None and 'images' in tex:
            ident = all(
                raw[int(im['palette'], 16) if isinstance(im['palette'], str) else im['palette']:
                    (int(im['palette'], 16) if isinstance(im['palette'], str) else im['palette']) + 0x200]
                == van[int(im['palette'], 16) if isinstance(im['palette'], str) else im['palette']:
                       (int(im['palette'], 16) if isinstance(im['palette'], str) else im['palette']) + 0x200]
                for im in tex['images'])
            print(f"  palette region byte-identical to vanilla: {ident}")
        return

    offsets = helpers.get_dynamic_offsets(dat, extra_id, cfg.get('offsets', {}))
    vanilla_map = cfg.get('vanilla', {})
    mask = helpers.compute_mask_spans(offsets)

    n_van = n_mod = n_shift = n_bad = 0
    for layer_id, info in offsets.items():
        v_hex = (vanilla_map.get(layer_id) or info.get('vanilla') or '').upper()
        for label, off, wlen, kind in _layer_points(layer_id, info):
            cur = raw[off:off + wlen].hex().upper()
            vb = bytes.fromhex(v_hex)[:wlen] if v_hex else None
            is_van = bool(vb) and cur == vb.hex().upper()

            res = relocate.resolve_write_offset(
                vanilla_path, str(dat), off, vb,
                extra_id=extra_id, layer_id=label, block_kind=kind,
                write_len=wlen, mask_spans=mask)
            if res.get('skip'):
                place, n_bad = 'UNRESOLVED (writes are skipped!)', n_bad + 1
            elif res.get('relocated'):
                place, n_shift = f"RELOCATED -> 0x{res['offset']:X}", n_shift + 1
            else:
                place = 'in-place'
            if is_van:
                n_van += 1
                state = 'VANILLA'
            else:
                n_mod += 1
                state = f"MODDED (vanilla {v_hex or '?'})"
            if verbose or not is_van or place != 'in-place':
                print(f"  {label:20s} @0x{off:05X}  {cur:<10s} {state:28s} [{place}]")
    print(f"  summary: {n_van} vanilla, {n_mod} modded, "
          f"{n_shift} relocated, {n_bad} unresolved")
    if n_bad:
        print("  !! UNRESOLVED layers mean installs silently skip them -- the file's")
        print("     layout diverged from vanilla beyond what relocation can prove.")


def main():
    ap = argparse.ArgumentParser(description="read what is actually installed "
                                             "in a project's extras offsets")
    ap.add_argument('--project', required=True,
                    help="project name under %%LOCALAPPDATA%%/SSBM Nucleus/projects, or a path")
    ap.add_argument('--char', required=True, help="extra_types character key, e.g. Bowser")
    ap.add_argument('--extra', help="one extra id (default: all for the character)")
    ap.add_argument('-v', '--verbose', action='store_true',
                    help="print every layer (default: only non-vanilla / problems)")
    args = ap.parse_args()

    proj = resolve_project_dir(args.project)
    files_dir = proj / 'files'
    if not files_dir.is_dir():
        sys.exit(f"no files/ dir under {proj}")
    print(f"project: {proj}")

    if args.extra:
        cfg = get_extra_type(args.char, args.extra)
        if not cfg:
            sys.exit(f"no extra '{args.extra}' configured for {args.char}")
        cfgs = [cfg]
    else:
        cfgs = get_extra_types(args.char)
        if not cfgs:
            sys.exit(f"no extras configured for {args.char}")

    for cfg in cfgs:
        if cfg.get('type') == 'model':
            continue  # model swaps have no color offsets to read
        doctor_extra(args.char, cfg, files_dir, args.verbose)


if __name__ == '__main__':
    main()
