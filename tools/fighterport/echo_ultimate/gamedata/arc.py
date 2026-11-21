"""Pull named files out of a decrypted Ultimate data.arc through ArcExplorer's
smash_arc.dll (the same three calls as ../extract_arc.ps1, without its manifest).

Unlike that script this accepts archive paths with a colon (prebuilt:/..., the
game's real spelling; Windows file names cannot hold one) and writes them under
a safe name. Existing outputs are left alone.

Usage: python -m echo_ultimate.gamedata.arc <dump_root> <out_dir> <arc_path> [<arc_path> ...]
"""
import ctypes
import os
import sys

REGION = 2
_lib = None


def _load(dll):
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(str(dll))
        lib.arc_open.restype = ctypes.c_void_p
        lib.arc_open.argtypes = [ctypes.c_char_p]
        lib.arc_free.argtypes = [ctypes.c_void_p]
        lib.arc_str_to_hash40.restype = ctypes.c_uint64
        lib.arc_str_to_hash40.argtypes = [ctypes.c_char_p]
        lib.arc_extract_file_regional.restype = ctypes.c_uint8
        lib.arc_extract_file_regional.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_char_p, ctypes.c_uint32]
        _lib = lib
    return _lib


def extract(root, out_dir, paths, region=REGION):
    """Extract archive paths into out_dir. `root` is the dump folder holding
    romfs/data.arc and ArcExplorer/smash_arc.dll. Returns {path: local file or None}.
    Files already present are kept as they are."""
    root, out_dir = os.path.abspath(str(root)), os.path.abspath(str(out_dir))
    todo, result = [], {}
    for p in paths:
        target = os.path.abspath(os.path.join(out_dir, p.replace(':', ';')))
        if not target.startswith(out_dir + os.sep):
            raise ValueError(f'path escapes the output folder: {p}')
        if os.path.exists(target):
            result[p] = target
        else:
            todo.append((p, target))
    if not todo:
        return result
    lib = _load(os.path.join(root, 'ArcExplorer', 'smash_arc.dll'))
    arc = lib.arc_open(os.path.join(root, 'romfs', 'data.arc').encode('utf-8'))
    if not arc:
        raise OSError('could not open data.arc')
    try:
        for p, target in todo:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            rc = lib.arc_extract_file_regional(arc, lib.arc_str_to_hash40(p.encode('utf-8')),
                                               target.encode('utf-8'), region)
            if rc == 0:
                result[p] = target
            elif rc == 2:
                result[p] = None
            else:
                raise OSError(f'archive extraction failed ({rc}): {p}')
    finally:
        lib.arc_free(arc)
    return result


def listed(root, prefixes):
    """Archive paths that start with one of `prefixes`, from the dump's list of every path (Hashes_FullPath)."""
    prefixes, out = tuple(prefixes), []
    with open(os.path.join(str(root), 'Hashes_FullPath'), encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith(prefixes):
                out.append(line.strip())
    return out


def fighter_paths(paths, fighter):
    """Of a fighter's archive paths, the ones a port reads: every model and every model's clips as the first
    costume has them, and the parameter tables. (Other costumes differ in textures, fetched when asked for.)"""
    keep, base = [], f'fighter/{fighter}/'
    for p in paths:
        parts = p[len(base):].split('/') if p.startswith(base) else []
        if parts[:1] == ['param'] or (len(parts) == 4 and parts[0] in ('model', 'motion') and parts[2] == 'c00'):
            keep.append(p)
    return keep


def fetch_fighter(root, fighter):
    """Extract what a port reads for one fighter into <root>/gamedata. Returns how many files are there.
    A root with no archive whose fighter is already on the disk (a game written out in Ultimate's shapes by its
    own reader: fighter_port/source_game.py) has nothing to take out: its files on the disk are counted."""
    if not os.path.exists(os.path.join(str(root), 'Hashes_FullPath')):
        folder = os.path.join(str(root), 'gamedata', 'fighter', fighter)
        on_disk = sum(len(files) for _d, _s, files in os.walk(folder)) if os.path.isdir(folder) else 0
        return on_disk, on_disk
    paths = fighter_paths(listed(root, [f'fighter/{fighter}/']), fighter)
    got = extract(root, os.path.join(str(root), 'gamedata'), paths)
    return sum(1 for v in got.values() if v), len(paths)


def local(root, path):
    """Where an archive path is kept once it is out: under <root>/gamedata, a colon written as a semicolon."""
    return os.path.join(str(root), 'gamedata', path.replace(':', ';'))


def not_out(root, paths):
    """Of these archive paths, the ones not yet out of the archive (not on disk under <root>/gamedata)."""
    return [p for p in paths if not os.path.exists(local(root, p))]


def fighter_names(root):
    """Every fighter the archive has a folder for, by the name the port command takes (the folder's own)."""
    names = set()
    with open(os.path.join(str(root), 'Hashes_FullPath'), encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('fighter/'):
                parts = line.split('/', 3)
                if len(parts) > 3 and parts[2] == 'model':
                    names.add(parts[1])
    return sorted(names)


if __name__ == '__main__':
    for path, local in extract(sys.argv[1], sys.argv[2], sys.argv[3:]).items():
        print(f'{"ok" if local else "missing":8} {path}')
