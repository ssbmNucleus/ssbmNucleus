"""The game's pak, through `uetool` (this folder's C# console app on CUE4Parse; see uetool/Program.cs).

The tool is built once (`dotnet build -c Release` in uetool/: its NuGet packages, CUE4Parse and CUE4Parse-Conversion
1.2.2, must already be in the local NuGet cache; nothing is downloaded by the reader). It reads the pak with the
mappings dumped from the running game (`RIVALS2_USMAP`): Rivals 2 is cooked with unversioned properties, so without
them only file names can be read. Every read is kept under `<cache>` so that a second run of the reader reads
nothing from the pak again.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent / 'uetool'
EXE = HERE / 'bin' / 'Release' / 'net10.0' / ('uetool.exe' if os.name == 'nt' else 'uetool')
# where the tool finds things: from the environment only (the game's folder, given to the reader, sets the first)
NEEDED = {'RIVALS2_PAKS': "the game's install folder, the reader's first argument (or its Paks folder)",
          'OODLE_DLL': 'an oo2core_9_win64.dll already on the machine (another Unreal game\'s install may hold one)',
          'RIVALS2_USMAP': 'the mappings (.usmap) dumped from the running game (READERS.md, section 2)'}


def build():
    """The tool, built again when its source is newer than it (a mode added to Program.cs reaches the reader)."""
    src = HERE / 'Program.cs'
    if not EXE.is_file() or (src.is_file() and src.stat().st_mtime > EXE.stat().st_mtime):
        subprocess.run(['dotnet', 'build', '-c', 'Release'], cwd=HERE, check=True, capture_output=True)
    return EXE


class Pak:
    def __init__(self, game_dir=None, cache=None):
        """`game_dir`: the game's install folder (holding Rivals2/Content/Paks) or the Paks folder itself."""
        self.env = dict(os.environ)
        if game_dir:
            p = Path(game_dir)
            paks = p if p.name == 'Paks' else p / 'Rivals2' / 'Content' / 'Paks'
            self.env['RIVALS2_PAKS'] = str(paks)
        lost = [f'{name}: {what}' for name, what in NEEDED.items() if not self.env.get(name)]
        if lost:
            raise SystemExit('the Rivals 2 reader needs ' + '; '.join(lost))
        self.cache = Path(cache) if cache else None
        self._list = None
        build()

    def run(self, *args, env=None):
        r = subprocess.run([str(EXE), *args], capture_output=True, text=True, env=dict(self.env, **(env or {})),
                           encoding='utf-8', errors='replace')
        if r.returncode != 0:
            raise RuntimeError(f'uetool {" ".join(args)}: {r.stderr[-2000:] or r.stdout[-2000:]}')
        return r.stdout

    def files(self):
        """Every path in the pak."""
        if self._list is None:
            self._list = self.run('list', '/').splitlines()
        return self._list

    def find(self, name, under=''):
        """The package path (no extension) of a package by its file name (`ATT_Zet_Bair`), under a folder."""
        hits = [f[:-len('.uasset')] for f in self.files()
                if f.endswith('/' + name + '.uasset') and under in f]
        if not hits:
            raise KeyError(f'no package {name} under {under!r} in the pak')
        return sorted(hits, key=len)[0]

    def props(self, pkg):
        """The package's objects (uetool props) as Python. Kept in the cache."""
        key = self.cache / 'props' / (pkg.replace('/', '__') + '.json') if self.cache else None
        if key is not None and key.is_file():
            return json.loads(key.read_text('utf-8'))
        out = json.loads(self.run('props', pkg))
        if key is not None:
            key.parent.mkdir(parents=True, exist_ok=True)
            key.write_text(json.dumps(out), 'utf-8')
        return out

    def scripts(self, pkg):
        """Executable source, cached separately from props; never accept partially decoded bytecode."""
        key = self.cache / 'scripts' / (pkg.replace('/', '__') + '.json') if self.cache else None
        out = json.loads(key.read_text('utf-8')) if key is not None and key.is_file() else \
            json.loads(self.run('scripts', pkg))
        for function in out:
            code = function.get('ScriptBytecode') or []
            native = 'FUNC_Native' in function.get('FunctionFlags', '').split(' | ')
            if (code and code[-1].get('Token') != 'EX_EndOfScript') or (not code and not native):
                raise ValueError(f'{pkg}: incomplete bytecode for {function.get("Name")}')
        if key is not None:
            key.parent.mkdir(parents=True, exist_ok=True)
            key.write_text(json.dumps(out), 'utf-8')
        return out

    def animation_curves(self, pkgs):
        """Float curves, including tangents, in batches; absent curves remain explicit empty records."""
        out, missing = {}, []
        for pkg in pkgs:
            key = self.cache / 'curves' / (pkg.replace('/', '__') + '.json') if self.cache else None
            if key is not None and key.is_file():
                out[pkg] = json.loads(key.read_text('utf-8'))
            else:
                missing.append(pkg)
        for k in range(0, len(missing), 40):
            batch = missing[k:k + 40]
            records = json.loads(self.run('animation-curves', ','.join(batch)))
            if set(records) != set(batch):
                raise ValueError('animation-curves returned an incomplete batch')
            for pkg, record in records.items():
                if record.get('acl') and record.get('curves') is None:
                    from .acl import curve_tracks
                    record['curves'] = curve_tracks(record)
                    record['decoded_by'] = 'echo_rivals2.acl.curve_tracks'
                out[pkg] = record
                if self.cache is not None:
                    key = self.cache / 'curves' / (pkg.replace('/', '__') + '.json')
                    key.parent.mkdir(parents=True, exist_ok=True)
                    key.write_text(json.dumps(record), 'utf-8')
        for pkg, record in out.items():
            if record.get('curve_names') and record.get('curves') is None:
                raise ValueError(f'{pkg}: source curves were not decoded')
        return {pkg: out[pkg] for pkg in pkgs}

    def default(self, pkg):
        """The class default object's properties of a blueprint package (ATT_*, CD_*, PS_* ...), or the first object
        with properties."""
        objs = self.props(pkg)
        for o in objs:
            if o.get('Name', '').startswith('Default__'):
                return o.get('Properties') or {}
        return next((o.get('Properties') for o in objs if o.get('Properties')), {})

    def export(self, pkgs, out, psk=True):
        """Export packages (meshes, skeletons, clips, pictures) under `out` (their pak paths kept). -> {pkg: [files]}.
        Already exported files are not exported again."""
        out = Path(out)
        want = []
        for p in pkgs:
            stem = out / p
            if not any(stem.parent.glob(stem.name + '.*')):
                want.append(p)
        done = {}
        self.failed = getattr(self, 'failed', {})
        refused = []
        for k in range(0, len(want), 40):
            text = self.run('export', ','.join(want[k:k + 40]), str(out), env={'UE_MESH': 'psk'} if psk else None)
            for line in text.splitlines():
                if line.startswith('FAIL'):
                    pkg = line.split()[1].rsplit('.', 1)[0]
                    self.failed[pkg] = line.split('->', 1)[-1].strip()
                    refused.append(pkg)
        if refused:
            self.acl_clips(refused, out)
        for p in pkgs:
            stem = out / p
            done[p] = sorted(str(x) for x in stem.parent.glob(stem.name + '.*'))
        return done

    def acl_clips(self, pkgs, out):
        """Clips CUE4Parse refused because the ACL plugin compressed them (its decoder is a native library its
        NuGet package does not carry): their bytes through `uetool acl-raw`, decoded by acl.py into the .psa
        CUE4Parse would have written. A clip decoded leaves `failed`; one that is not ACL, or not a form acl.py
        reads, stays there with the reason. -> [decoded package]."""
        from . import acl
        where = (self.cache / 'acl') if self.cache else Path(out) / '_acl'
        made = []
        for k in range(0, len(pkgs), 40):
            self.run('acl-raw', ','.join(pkgs[k:k + 40]), str(where))
        for pkg in pkgs:
            rec_file = where / (pkg.rsplit('/', 1)[-1] + '.json')
            if not rec_file.is_file():
                continue
            rec = json.loads(rec_file.read_text('utf-8'))
            if rec.get('clip') != pkg or not rec.get('acl'):
                continue
            try:
                acl.to_psa(rec, Path(out) / (pkg + '.psa'))
            except acl.Unsupported as e:
                self.failed[pkg] = f'ACL: {e}'
                continue
            self.failed.pop(pkg, None)
            made.append(pkg)
        self.acl_decoded = getattr(self, 'acl_decoded', []) + made
        return made

    def raw(self, path, out):
        self.run('raw', path, str(out))
        return Path(out)
