"""A model import's finish: CSP portrait, stock icon, and a vault costume that installs.

Randall's ``import_model`` (``chat/import_job.py``) saves through it, by the same importer every other
vault costume goes through (``vault.importing.unified.characters.import_character_costume``): the DAT is
packed as a one-member costume archive named for its costume code, imported as a NEW vault costume with a fresh CSP
(`shared.rendering.costume_assets.build_csp_and_stock` renders the portrait with the
fighter's own CSP camera and animation, then derives the stock icon from it)
and a Slippi check. Nothing existing is renamed or replaced.

`installable` is measured, not assumed: the vault archive is read back, and
(by default) installed into a throwaway m-ex project with the same MexCLI
`import-costume` the app's install uses. The project is deleted afterwards.

`storage_root` points every vault write at another storage folder (tests and
sandboxes). It patches module-level storage paths process-wide for the
duration of the call, so it must not run beside a live app backend.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from core.hashing import sha256_bytes

NOT_SUPPORTED = {
    'Ice Climbers': 'Ice Climbers costumes are a Popo/Nana pair; finishing a pair is not supported yet.',
    'Nana': 'Ice Climbers costumes are a Popo/Nana pair; finishing a pair is not supported yet.',
    'Popo': 'Ice Climbers costumes are a Popo/Nana pair; finishing a pair is not supported yet.',
}
GAME_AND_WATCH = 'Mr. Game & Watch'
GAW_SIDECAR = 'gaw.json'       # the member the vault importer and MexCLI read G&W's slot colours from


class FinishError(ValueError):
    """A located, plain-language refusal or failure."""


class NotSupportedYet(FinishError):
    pass


@contextmanager
def vault_storage(root):
    """Point the vault (metadata, costume zips, CSP/stock files, test-build
    scratch) at `root` for the duration. None = the configured storage."""
    if root is None:
        yield None
        return
    import core.config as config
    import core.metadata as metadata
    from vault.importing.unified import characters
    from projects.install import test_build
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    patches = [(config, 'STORAGE_PATH', root), (config, 'VAULT_BACKEND', 'json'),
               (config, 'VAULT_DB_PATH', root / 'vault.db'), (config, 'VAULT_DUAL_WRITE', False),
               (metadata, 'METADATA_FILE', root / 'metadata.json'),
               (characters, 'STORAGE_PATH', root), (test_build, 'TEST_BUILD_DIR', root / 'test-builds')]
    saved = [(module, name, getattr(module, name, None)) for module, name, _ in patches]
    try:
        for module, name, value in patches:
            setattr(module, name, value)
        yield root
    finally:
        for module, name, value in saved:
            setattr(module, name, value)


def costume_code(fighter, slot):
    """(canonical name, 'Pl<XX><color>') for a vanilla slot; slot None = 0."""
    from shared.modellab.fighter_catalog import _canonical, _CHAR_TO_CODE
    from core.constants import VANILLA_CSS_COLOR_ORDER
    name = _canonical(fighter)
    if name in NOT_SUPPORTED:
        raise NotSupportedYet(NOT_SUPPORTED[name])
    code, colors = _CHAR_TO_CODE.get(name), VANILLA_CSS_COLOR_ORDER.get(name)
    if not code or not colors:
        raise FinishError(f'"{fighter}" is not a vanilla fighter; only vanilla fighters can be finished here.')
    slot = 0 if slot is None else slot
    if type(slot) is not int or not 0 <= slot < len(colors):
        raise FinishError(f'{name} has costume slots 0..{len(colors) - 1}; slot {slot!r} is not one.')
    return name, f'Pl{code}{colors[slot]}', slot


def _clean_name(name):
    if not isinstance(name, str) or not name.strip():
        raise FinishError('Give the costume a name.')
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 80 or any(c in name for c in '\x00/\\'):
        raise FinishError('The costume name must be at most 80 characters, without slashes.')
    return name


def save_to_vault(dat_bytes, character, code, name, *, slippi_fix=False, source='model_import_v2', project=None):
    """Import through the unified importer as a NEW costume. Returns the
    metadata entry and its archive path. ``project``: the import's folder the
    costume came from, kept on the record (``model_import.project``).

    Mr. Game & Watch's costume colour is not in his DAT: the game paints every
    material with the slot's fill (m-ex's GawColors row), black unless a
    ``gaw.json`` sidecar says otherwise. An import draws its own textures, so its
    archive carries a white fill (``core.gaw_colors.import_sidecar``): the vault
    keeps it, colours the portrait and stock with it, and MexCLI's
    import-costume adds that slot's GawColors row from it."""
    from core import config
    from core.metadata import load_metadata, metadata_lock, metadata_transaction
    from vault.importing.unified.characters import import_character_costume
    member = code + '.dat'
    unique = f'{name} {uuid.uuid4().hex[:12]}'
    scratch_parent = Path(config.STORAGE_PATH) / 'scratch'
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='finish-', dir=scratch_parent) as scratch:
        archive = Path(scratch) / 'costume.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
            out.writestr(member, dat_bytes)
            if character == GAME_AND_WATCH:
                from core.gaw_colors import import_sidecar
                out.writestr(GAW_SIDECAR, json.dumps(import_sidecar()))
        info = dict(character=character, dat_file=member, costume_code=code, csp_file=None, stock_file=None)
        with metadata_lock:
            before = {s['id'] for s in load_metadata(default={}).get('characters', {}).get(character, {}).get('skins', [])}
            result = import_character_costume(str(archive), info, 'costume.zip', auto_fix=bool(slippi_fix),
                                              custom_name=unique)
            if not result.get('success'):
                raise FinishError('The vault import failed: ' + str(result.get('error') or 'no reason given'))
            skin_id = result['skin_id']
            if skin_id in before:
                raise FinishError('The vault import did not create a new costume; nothing was renamed.')
            with metadata_transaction(default={}) as metadata:
                for skin in metadata.get('characters', {}).get(character, {}).get('skins', []):
                    if skin['id'] == skin_id:
                        skin.update(name=name, color=name, model_import=dict(
                            source=source, **({'project': str(project)} if project else {})))
                        entry = dict(skin)
                        break
                else:
                    raise FinishError(f'The imported costume {skin_id} is missing from the vault metadata.')
    return entry, Path(config.STORAGE_PATH) / character / entry['filename']


def check_archive(archive, dat_bytes, code, *, allow_changed=False):
    """The vault archive holds exactly this DAT as its costume, plus CSP/stock."""
    problems = []
    try:
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            dats = [n for n in names if n.lower().endswith(('.dat', '.usd'))]
            if len(dats) != 1:
                problems.append(f'the archive holds {len(dats)} costume files, not one')
            elif not dats[0].startswith(code):
                problems.append(f'the costume file {dats[0]} is not named for {code}')
            else:
                stored = z.read(dats[0])
                if stored != dat_bytes and not allow_changed:
                    problems.append('the stored costume differs from the DAT given '
                                    '(the importer changed its bytes)')
            for asset in ('csp.png', 'stc.png'):
                if asset not in names:
                    problems.append(f'the archive has no {asset}')
    except (OSError, zipfile.BadZipFile) as exc:
        problems.append(f'the archive cannot be read: {exc}')
    return problems


def install_check(archive, character, vanilla_iso=None, log=None):
    """Install the vault archive into a throwaway m-ex project exactly as the
    app does (MexCLI import-costume). Returns a receipt dict."""
    from core.config import MEXCLI_PATH
    from projects.install.test_build import create_temp_project, MexManager
    if vanilla_iso is None:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        vanilla_iso = known_vanilla_iso()
    if not vanilla_iso or not Path(vanilla_iso).is_file():
        return dict(checked=False, ok=None, reason='no vanilla ISO is configured, so no install was tried')
    t0 = time.monotonic()
    proj_dir, proj = create_temp_project(str(vanilla_iso), log=log or (lambda m: None))
    try:
        mex = MexManager(str(MEXCLI_PATH), str(proj))
        before = (mex.get_fighter_by_name(character) or {}).get('costumeCount')
        result = mex.import_costume(character, str(archive))
        total = result.get('totalCostumes') if isinstance(result, dict) else None
        ok = bool(isinstance(result, dict) and result.get('success', True) and total
                  and (before is None or int(total) == int(before) + 1))
        return dict(checked=True, ok=ok, costumes_before=before, costumes_after=total,
                    new_slot=int(total) - 1 if total else None, seconds=round(time.monotonic() - t0, 1),
                    reason=None if ok else f'MexCLI import-costume answered {result!r}')
    except Exception as exc:
        return dict(checked=True, ok=False, seconds=round(time.monotonic() - t0, 1),
                    reason=f'MexCLI import-costume failed: {type(exc).__name__}: {exc}')
    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)


def finish(dat_path, fighter, name, *, slot=None, out_dir, storage_root=None, check_install=True,
           slippi_fix=False, vanilla_iso=None, log=None, project=None, source='model_import_v2'):
    """Save an imported costume DAT to the vault with a CSP and a stock icon.

    Returns dict(csp=path, stock=path, vault={...}, installable=bool,
    notes=[...], install={...}, seconds=float). `slot` is the vanilla costume
    slot the costume is filed under (default: the neutral costume, 0).
    Ice Climbers raise NotSupportedYet (Zelda, Sheik and Kirby import alone; the pair and the hats stay vanilla). `slippi_fix`
    lets the importer apply its Slippi fix to the stored copy (off by default:
    the vault then holds exactly the DAT that was tested). ``project``: the import's folder,
    recorded on the vault record as ``model_import.project``;
    ``source``: the record's ``model_import.source`` label.
    """
    t0 = time.monotonic()
    character, code, slot = costume_code(fighter, slot)
    name = _clean_name(name)
    dat = Path(dat_path)
    if not dat.is_file():
        raise FinishError(f'The costume DAT is missing: {dat}')
    data = dat.read_bytes()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    notes = []
    from shared.mod_files import dat_roots
    roots = dat_roots(dat)
    if not any(r.endswith('_Share_joint') for r in roots):
        raise FinishError('The DAT has no fighter costume joint root (*_Share_joint); it is not a costume file.')
    with vault_storage(storage_root):
        from core import config
        entry, archive = save_to_vault(data, character, code, name, slippi_fix=slippi_fix, source=source,
                                       project=project)
        folder = Path(config.STORAGE_PATH) / character
        csp_src, stock_src = folder / f"{entry['id']}_csp.png", folder / f"{entry['id']}_stc.png"
        csp = stock = None
        if csp_src.is_file():
            csp = out_dir / 'csp.png'
            shutil.copyfile(csp_src, csp)
        else:
            notes.append('No CSP portrait could be rendered; the vault card has no picture.')
        if stock_src.is_file():
            stock = out_dir / 'stock.png'
            shutil.copyfile(stock_src, stock)
        else:
            notes.append('No stock icon could be made.')
        if entry.get('stock_source') in ('vanilla', 'vanilla_default'):
            notes.append("The stock icon is the vanilla fighter's own icon: none could be derived "
                         'from this model.')
        if not entry.get('slippi_safe'):
            notes.append('The Slippi check says this DAT needs its Slippi fix (slippi_safe is false), '
                         'so it may desync on Slippi online. It was stored unchanged; finish with '
                         'slippi_fix=True, or use the vault Slippi fix, to store the fixed copy.')
        stored_changed = False
        if slippi_fix:
            with zipfile.ZipFile(archive) as z:
                member = next(n for n in z.namelist() if n.lower().endswith(('.dat', '.usd')))
                stored_changed = z.read(member) != data
            if stored_changed:
                notes.append('The Slippi fix changed the stored copy; the vault DAT differs from the '
                             'one tested in game.')
        if 'mexCostume' in roots:
            notes.append('The DAT carries m-ex costume extensions; it needs an m-ex build.')
        problems = check_archive(archive, data, code, allow_changed=slippi_fix)
        notes += [f'Vault archive: {p}.' for p in problems]
        install = dict(checked=False, ok=None, reason='not requested')
        if check_install and not problems:
            install = install_check(archive, character, vanilla_iso=vanilla_iso, log=log)
            if install.get('checked') and not install.get('ok'):
                notes.append('The install check failed: ' + str(install.get('reason')))
            elif not install.get('checked'):
                notes.append('The install check did not run: ' + str(install.get('reason')))
        installable = not problems and (install.get('ok') is True or not check_install)
        vault = dict(character=character, skin_id=entry['id'], name=name, costume_code=code, slot=slot,
                     archive=str(archive), dat_sha256=sha256_bytes(data), stored_dat_changed=stored_changed, csp_source=entry.get('csp_source'),
                     stock_source=entry.get('stock_source'), slippi_safe=entry.get('slippi_safe'),
                     storage=str(config.STORAGE_PATH), project=str(project) if project else None)
    return dict(csp=str(csp) if csp else None, stock=str(stock) if stock else None, vault=vault,
                installable=bool(installable), install=install, notes=notes,
                seconds=round(time.monotonic() - t0, 1))

