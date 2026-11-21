"""python -m echo_rivals2 <the game's install folder> <fighter> <root> [--only body|game|sound|identity]: write a Rivals 2 fighter in
the port's shapes under <root> (transcode.py: skeleton, costumes, clips) and its game data (gamedata.py: game.json)
beside them. <fighter> is the game's folder name under Content/Characters (Zetterburn); the port's name for it is
the same in lower case. Reads go through uetool (pak.py) and are kept in <root>/rivals2-cache.

The halves have an order: the game half MAKES each move part's clip (gamedata.py) over the raw clip the body half
wrote under the same stem, so after `--only body` run `--only game` again (else the driver meets the raw clips: the
forward tilt's came to 50,592 bytes of 32,768 and the driver stopped)."""
import json
import sys
import time
from pathlib import Path

from . import pak as pak_mod

SHORT = {'Zetterburn': 'Zet'}           # the game's three-letter name of each fighter (its files' prefix)


def short_of(p, fighter):
    if fighter in SHORT:
        return SHORT[fighter]
    cd = p.default(p.find(f'CD_{fighter}', f'Characters/{fighter}/'))
    return cd['AnimationsPrefix'].split('_')[1]


def main(argv=None):
    args = list(argv or sys.argv[1:])
    only = None
    if '--only' in args:
        i = args.index('--only')
        only = args[i + 1]
        del args[i:i + 2]
    game_dir, fighter, root = args[:3]
    import ssbh_data_py as ssbh
    t = time.time()
    root = Path(root)
    name = fighter.lower()
    cache = root / 'rivals2-cache'
    p = pak_mod.Pak(game_dir, cache)
    short = short_of(p, fighter)
    base = f'Rivals2/Content/Characters/{fighter}'
    exported = cache / 'export'
    if only in (None, 'body'):
        from . import palettes, transcode
        body = f'{base}/Skins/Default/SK_{short}_Default'
        clips = sorted(f[:-len('.uasset')] for f in p.files()
                       if f.startswith(base + '/') and f.endswith('.uasset') and f'/AN_{short}_' in f
                       and ('/Animation/' in f or '/Taunts/' in f))
        files = p.export([body] + clips, exported)
        mesh_props = next(o for o in p.props(body) if o.get('Type') == 'SkeletalMesh')
        mats = mesh_props['SkeletalMaterials'] if 'SkeletalMaterials' in mesh_props else \
            mesh_props['Properties'].get('SkeletalMaterials')
        materials = [m['Material']['ObjectPath'].rsplit('.', 1)[0] for m in mats]
        slots = [m['MaterialSlotName'] for m in mats]
        print(f"exported the body and {len(clips)} clips in {time.time() - t:.1f} s; "
              f"{len(getattr(p, 'acl_decoded', []))} of them ACL-compressed, decoded by acl.py; "
              f"not exported: {sorted(getattr(p, 'failed', {}))}")
        material_bakes = []
        costumes = palettes.costumes(p, short, materials, slots, exported, report=material_bakes)
        clip_files = {Path(c).name[len(f'AN_{short}_'):]: next(x for x in files[c] if x.endswith('.psa'))
                      for c in clips if any(x.endswith('.psa') for x in files[c])}
        body_file = next(x for x in files[body] if x.endswith('.psk'))
        cd = p.default(p.find(f'CD_{fighter}', f'Characters/{fighter}/'))
        speeds = {w: cd[w] for w, _way in transcode.TRAVEL.values() if isinstance(cd.get(w), (int, float))}
        summary, _sk = transcode.write(name, root, ssbh, dict(body=body_file, clips=clip_files, slots=slots,
                                                               speeds=speeds, material_bakes=material_bakes), costumes)
        print(f"{name}: {len(summary['joints'])} joints, {len(summary['stems'])} clips, {len(summary['costumes'])} "
              f"costumes, unit {summary['unit']:.4f}, height {summary['height_cm']:.1f} cm; {time.time() - t:.1f} s")
    if only in (None, 'game'):
        from . import gamedata
        data = gamedata.load(p, fighter, short, name, root)
        from . import article_models
        data['article_models'], data['article_model_limits'] = article_models.export(
            p, data.get('projectiles') or {}, name, short, root, data['unit'], ssbh)
        out = root / 'gamedata' / 'fighter' / name / 'game.json'
        out.write_text(json.dumps(data, indent=1, default=str), 'utf-8')
        print(f"the game data: {len(data['moves'])} moves, {len(data['melee_attributes'])} numbers -> {out}; "
              f'{time.time() - t:.1f} s')
    if only in (None, 'game', 'sound'):
        from . import sounds
        from core.media_tools import get_ffmpeg
        data = json.loads((root / 'gamedata' / 'fighter' / name / 'game.json').read_text('utf-8'))
        named = {s['name'] for e in data['moves'].values() for s in e.get('sounds') or []}
        receipt = sounds.write(game_dir, name, fighter, root, named, get_ffmpeg() or 'ffmpeg', pak=p)
        sounds.annotate(data, receipt)
        (root / 'gamedata' / 'fighter' / name / 'game.json').write_text(json.dumps(data, indent=1), 'utf-8')
        print(f'the sounds: {time.time() - t:.1f} s')
    if only in (None, 'game', 'sound', 'identity'):
        from . import identity
        from core.media_tools import get_ffmpeg
        identity.write(p, game_dir, name, fighter, short, root, get_ffmpeg() or 'ffmpeg')
        print(f'the identity: {time.time() - t:.1f} s')


if __name__ == '__main__':
    main()
