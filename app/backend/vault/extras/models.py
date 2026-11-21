"""
Model extras engine: extract a model from a fighter DAT, import one back into
it, and copy the vanilla model back, with the HSDRawViewer CLI (gun and other
3D model replacements).
"""

import logging
import shutil
import subprocess
from pathlib import Path

import file_retry
from core.config import get_subprocess_args
from vault.extras import helpers

logger = logging.getLogger(__name__)


class ModelToolError(RuntimeError):
    """An HSDRawViewer model operation failed; the message is its reason."""


class ModelNotInDat(ModelToolError):
    """The DAT has no joint at the model path (e.g. a costume file was given
    where the fighter's PlXx.dat was expected)."""


def _failure_reason(result):
    """Why a `--model` run failed, in HSDRawViewer's own words.

    HSDRawViewer prints its errors on stdout ("ERROR: ..."), not stderr, so a
    message built from stderr alone was empty ("Model export failed: ").
    """
    lines = [line.strip() for line in (result.stdout or '').splitlines() if line.strip()]
    errors = [line[len('ERROR:'):].strip() for line in lines if line.startswith('ERROR:')]
    if errors:
        return errors[0]
    if (result.stderr or '').strip():
        return result.stderr.strip()
    if lines:
        return lines[-1]
    return f'HSDRawViewer exited with code {result.returncode} and printed nothing'


def _run_model_tool(cmd, action, timeout):
    """Run one `HSDRawViewer --model ...` command. It succeeded only when it
    exits 0 AND prints its SUCCESS line: older builds exit 0 on an operation
    they do not know."""
    if not helpers.HSDRAW_VIEWER_PATH:
        raise ModelToolError("HSDRawViewer path not configured")
    cmd = [str(helpers.HSDRAW_VIEWER_PATH), '--model', *[str(part) for part in cmd]]
    logger.info(f"Running model {action}: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                            **get_subprocess_args())
    if result.returncode != 0 or 'SUCCESS:' not in (result.stdout or ''):
        reason = _failure_reason(result)
        logger.error(f"Model {action} failed: {reason}\n{result.stdout}")
        error = ModelNotInDat if 'Could not find JOBJ at path' in reason else ModelToolError
        raise error(f"Model {action} failed: {reason}")
    logger.info(f"Model {action} output: {result.stdout}")
    return True


def model_extra_location(storage_char_dir, mod_id):
    """(folder, model_file) for a new model extra's exported model.

    Each model gets a folder of its own, ``models/<mod_id>/<mod_id>.dae``. The
    export writes the model's textures beside the .dae under fixed names
    (``Texture_0_CMP.png``...), so when every gun of a character shared
    ``models/``, exporting a second one overwrote the first one's textures.
    ``model_file`` is relative to the storage character's folder, as metadata
    stores it.
    """
    folder = Path(storage_char_dir) / 'models' / mod_id
    return folder, f"models/{mod_id}/{mod_id}.dae"


def remove_model_files(storage_char_dir, model_file, mod_id):
    """Delete a model extra's stored .dae and what its export wrote with it.

    A model in its own folder (model_extra_location) goes with that folder.
    One from before that layout (``models/<mod_id>.dae``) loses its .dae and
    ``.textures.json``; its textures stay, because another model of that era
    may be using the same file names.
    """
    path = Path(storage_char_dir) / model_file
    if path.parent.name == mod_id and path.parent.parent.name == 'models':
        if path.parent.is_dir():
            shutil.rmtree(path.parent)
            logger.info(f"Deleted model folder: {path.parent}")
        return
    for p in (path, path.with_name(path.name + '.textures.json')):
        if p.exists():
            p.unlink()
            logger.info(f"Deleted model file: {p}")


def extract_model_from_dat(dat_path, jobj_path, output_dae_path):
    """Extract a model from a DAT file using HSDRawViewer CLI.

    Args:
        dat_path: Path to the source .dat file
        jobj_path: Path within the DAT to the JOBJ (e.g., "ftDataFalco/Articles/Articles_1/Model_/RootModelJoint")
        output_dae_path: Path to save the exported .dae file

    Returns:
        True if successful; raises ModelToolError (ModelNotInDat when the DAT
        has no joint at jobj_path) on failure
    """
    return _run_model_tool(['export', dat_path, jobj_path, output_dae_path], 'export', 60)


def import_model_to_dat(dat_path, jobj_path, model_dae_path, output_dat_path):
    """Import a model into a DAT file using HSDRawViewer CLI.

    Args:
        dat_path: Path to the source .dat file
        jobj_path: Path within the DAT to the JOBJ
        model_dae_path: Path to the .dae model file to import
        output_dat_path: Path to save the modified .dat file

    Returns:
        True if successful, raises ModelToolError on failure
    """
    return _run_model_tool(['import', dat_path, jobj_path, model_dae_path, output_dat_path],
                           'import', 120)


def copy_model_between_dats(dat_path, jobj_path, source_dat_path, output_dat_path):
    """Put the model at jobj_path in source_dat_path, exactly as that file
    stores it, in place of dat_path's and save to output_dat_path
    (`HSDRawViewer --model copy`). With the vanilla reference as the source
    this is restore-vanilla: no model-format round trip, nothing re-encoded.

    Raises ModelToolError on failure.
    """
    return _run_model_tool(['copy', dat_path, jobj_path, source_dat_path, output_dat_path],
                           'copy', 60)


def restore_vanilla_model(dat_path, type_config):
    """Put the vanilla model back into the project's DAT (restore-vanilla for
    a model extra), copied from the vanilla reference of the same file. The
    rest of the DAT, other extras included, is kept.

    Raises ModelToolError when there is no vanilla reference or the copy fails;
    the project's DAT is then untouched.
    """
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    target_file = type_config['target_file']
    jobj_path = type_config.get('model_path')
    if not jobj_path:
        raise ModelToolError('Model path not configured for this extra type')
    reference = ensure_vanilla_ref(target_file)
    if reference is None:
        raise ModelToolError(f'No vanilla {target_file} to copy the model from '
                             '(set your vanilla Melee ISO in Settings first)')
    dat_path = Path(dat_path)
    temp_output = dat_path.with_name(f"{dat_path.stem}_temp{dat_path.suffix}")
    try:
        copy_model_between_dats(dat_path, jobj_path, reference, temp_output)
        file_retry.replace(str(temp_output), str(dat_path))
    finally:
        if temp_output.exists():
            temp_output.unlink()
