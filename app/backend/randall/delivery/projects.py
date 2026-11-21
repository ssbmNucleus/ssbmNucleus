"""Randall project actions over managed projects and exact vault costume IDs.

Only the existing MexCLI create/import-costumes operations are exposed. Project
selection is explicit and never changes the UI's active project during a tool.
"""
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from werkzeug.utils import secure_filename
from core import config, state
from core.hashing import sha256_file
from core.metadata import load_metadata
from mexcli.project import fighter_files
from shared.vanilla_extract.vanilla_refs import known_vanilla_iso


def _project_id(path):
    return hashlib.sha256(os.path.normcase(str(Path(path).resolve())).encode()).hexdigest()[:24]


def _project_files():
    root = config.PROJECTS_PATH.resolve()
    files = []
    if root.exists():
        for folder in sorted(root.iterdir()):
            if not folder.is_dir() or folder.is_symlink() or not folder.resolve().is_relative_to(root):
                continue
            candidates = sorted(folder.glob('*.mexproj'))
            preferred = folder / 'project.mexproj'
            if preferred.is_file():
                candidates = [preferred]
            if candidates and candidates[0].resolve().is_relative_to(root):
                files.append(candidates[0].resolve())
    active = state.get_current_project_path()
    if active and Path(active).is_file() and Path(active).resolve() not in files:
        files.append(Path(active).resolve())
    return files


def _resolve(project_id):
    if not isinstance(project_id, str):
        raise ValueError('Use a project ID returned by list_projects.')
    path = next((p for p in _project_files() if _project_id(p) == project_id), None)
    if path is None:
        raise ValueError('Project not found. List projects again.')
    return path


def _project(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    active = state.get_current_project_path()
    return {'id': _project_id(path), 'name': data.get('build', {}).get('name') or path.parent.name,
            'path': str(path), 'current': bool(active and Path(active).resolve() == path)}


def _fighters(path):
    rows = []
    for filename in fighter_files(path):
        if not filename.resolve().is_relative_to(path.parent) or not filename.stem.isdigit():
            raise ValueError('This project has an unsupported fighter layout.')
        fighter = json.loads(filename.read_text(encoding='utf-8-sig'))
        costumes = fighter.get('costumes', [])
        rows.append({'id': int(filename.stem), 'name': fighter.get('name', ''),
                     'costume_count': len(costumes)})
    return rows


def list_projects():
    with state.mexcli_lock:
        projects, unavailable = [], []
        for path in _project_files():
            try:
                projects.append(_project(path))
            except (OSError, ValueError):
                unavailable.append(path.parent.name)
        return {'projects': projects, 'unavailable': unavailable,
                'can_create': known_vanilla_iso() is not None}


def inspect_project(project_id, character=''):
    with state.mexcli_lock:
        path = _resolve(project_id)
        fighters = _fighters(path)
        result = {'projects': [_project(path)], 'fighters': fighters}
        if character:
            if not isinstance(character, str):
                raise ValueError('character must be a character name.')
            fighter = next((f for f in fighters if f['name'].casefold() == character.casefold()), None)
            if not fighter:
                raise ValueError('Character not found in this project.')
            stored = json.loads((path.parent / 'data/fighters' / f"{fighter['id']:03}.json").read_text(encoding='utf-8-sig'))
            result['costumes'] = [{'slot': i + 1, 'name': c.get('name', ''),
                                   'filename': c.get('file', {}).get('fileName', '')}
                                  for i, c in enumerate(stored.get('costumes', []))]
        return result


#: The app's own bookkeeping inside a build directory -- the cross-process build
#: lock and its recovery journal. They are not project content, and hashing them
#: made an approved install invalidate itself the moment the build session that
#: protects it was opened.
_NOT_PROJECT_CONTENT = ('.nucleus-build.lock', '.nucleus-build-journal')


def _snapshot(path):
    rows = []
    for file in sorted(path.parent.rglob('*')):
        if file.is_symlink() or not file.resolve().is_relative_to(path.parent):
            raise ValueError('Projects with linked files are not supported by Randall.')
        if file.relative_to(path.parent).parts[0] in _NOT_PROJECT_CONTENT:
            continue
        if file.is_file():
            stat = file.stat()
            rows.append((str(file.relative_to(path.parent)), stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def prepare_create(args):
    from randall.assistant.vault_items import _text
    name = _text(args['name'], 'name', 80)
    folder = secure_filename(name)
    if not folder:
        raise ValueError('Choose a project name containing letters or numbers.')
    iso = known_vanilla_iso()
    if not iso:
        raise ValueError('Set your vanilla Melee ISO in Settings before creating a project.')
    iso = iso.resolve()
    stat = iso.stat()
    destination = config.PROJECTS_PATH.resolve() / folder
    suffix = 2
    while destination.exists():
        destination = config.PROJECTS_PATH.resolve() / f'{folder}-{suffix}'
        suffix += 1
    plan = {'name': name, 'directory': str(destination), 'iso': str(iso),
            'iso_size': stat.st_size, 'iso_modified': stat.st_mtime_ns}
    return plan, {'project_action': 'create', 'title': f'Create {name}?',
                  'project_name': name, 'base_name': 'Vanilla Melee',
                  'confirm_label': 'Create project'}


def apply_create(args, plan):
    with state.mexcli_lock:
        if prepare_create(args)[0] != plan:
            raise ValueError('The project destination or source ISO changed. Request a fresh review.')
        directory = Path(plan['directory'])
        directory.mkdir(parents=True, exist_ok=False)
        # Same native create operation as the Install page. No export command.
        result = subprocess.run([str(config.MEXCLI_PATH), 'create', plan['iso'],
                                 str(directory), plan['name']], capture_output=True, text=True,
                                cwd=config.PROJECT_ROOT, **config.get_subprocess_args())
        project = directory / 'project.mexproj'
        if result.returncode or not project.is_file():
            logging.getLogger(__name__).error('Randall project creation failed: %s\n%s', result.stdout, result.stderr)
            raise ValueError('Project creation failed. Check the Nucleus backend log before retrying.')
        from projects.install.required_codes import add_new_project_gecko_codes
        add_new_project_gecko_codes(project)  # what the Install page's new projects start with
        return {'project_action': 'created', 'project': _project(project), 'project_changed': True}


def _archive(character, skin):
    root = config.STORAGE_PATH.resolve()
    path = (root / character / skin.get('filename', skin['id'] + '.zip')).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != '.zip':
        raise ValueError('A selected costume archive is unavailable.')
    return path


def prepare_install(args):
    from randall.assistant.vault_items import _skin, _item
    items = args['items']
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError('Choose between 1 and 50 vault costumes per installation.')
    with state.mexcli_lock:
        path = _resolve(args['project_id'])
        fighters = _fighters(path)
        data = load_metadata(default={})
        selected, sources, seen = [], [], set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {'character', 'skin_id'}:
                raise ValueError('Each costume needs an exact character and skin_id.')
            char, skin = _skin(data, item['character'], item['skin_id'])
            if skin.get('is_nana'):
                raise ValueError('Select the Ice Climbers costume; its paired Nana is included automatically.')
            pair = skin.get('paired_nana_id')
            entries = [(char, skin)]
            if pair:
                nana = next(((c, s) for c, info in data.get('characters', {}).items()
                             for s in info.get('skins', []) if s.get('id') == pair), None)
                if not nana:
                    raise ValueError('The paired Nana costume is missing from the vault.')
                entries.append(nana)
            for c, s in entries:
                if (c, s['id']) in seen:
                    continue
                seen.add((c, s['id']))
                fighter = next((f for f in fighters if (f['id'] == 11 if s.get('is_nana') or s['id'] == pair
                                else f['name'].casefold() == c.casefold())), None)
                if not fighter:
                    raise ValueError(f'{c} is not in this project. Randall currently installs standard vault costumes.')
                source = _archive(c, s)
                sources.append({'character': c, 'skin_id': s['id'], 'fighter': fighter['id'],
                                'path': str(source), 'sha256': sha256_file(source)})
                selected.append(_item(c, s))
        plan = {'project': _project(path), 'snapshot': _snapshot(path), 'sources': sources, 'items': selected}
        # The active UI selection is irrelevant to the approved target.
        plan['project'].pop('current', None)
        return plan, {'project_action': 'install', 'title': f"Install into {plan['project']['name']}?",
                      'project_name': plan['project']['name'], 'items': selected,
                      'confirm_label': f"Install {len(selected)} costume{'s' if len(selected) != 1 else ''}"}


def apply_install(args, plan):
    from mexcli.project import MexManager, MexManagerError
    from falcon_neutralize import convert_falcon_zip
    with state.mexcli_lock:
        if prepare_install(args)[0] != plan:
            raise ValueError('The project or selected costumes changed. Request a fresh install review.')
        path = _resolve(args['project_id'])
        with tempfile.TemporaryDirectory(prefix='randall-install-') as scratch:
            manifest, converted = {}, []
            try:
                for index, source in enumerate(plan['sources']):
                    copy = Path(scratch) / f'{index}.zip'
                    shutil.copyfile(source['path'], copy)
                    if sha256_file(copy) != source['sha256']:
                        raise ValueError('A costume changed while preparing the installation. Request a fresh review.')
                    install = copy
                    if source['character'] == 'C. Falcon':
                        neutral = convert_falcon_zip(copy)
                        if neutral:
                            converted.append(neutral)
                            install = neutral
                    manifest.setdefault(str(source['fighter']), []).append(str(install))
                mex = MexManager(str(config.MEXCLI_PATH), str(path))
                try:
                    result = mex.import_costumes(manifest)
                except MexManagerError as exc:
                    raise ValueError(f'Project installation failed. Inspect the project before retrying: {exc}') from exc
            finally:
                for temporary in converted:
                    Path(temporary).unlink(missing_ok=True)
                state.reload_mex_manager()
        failed = result.get('totalFailed', 0)
        return {'project_action': 'installed', 'project': plan['project'], 'project_changed': True,
                'installed_count': result.get('totalImported', 0), 'failed_count': failed,
                'per_fighter': result.get('perFighter', {}),
                'installed_items': plan['items'] if not failed else [],
                **({'error': f'{failed} costume(s) could not be installed. Inspect the project before retrying.'} if failed else {})}
