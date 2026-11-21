"""An attached model waiting to be imported: how an ordinary chat's turn becomes a model import.

Read from the files themselves, never from the words alone: a model-like file the chat has not imported
yet, attached and asked about, makes the turn an import turn (``studio_import.turn_mode``'s ``waiting``).
Moved out of the recolor workflow's module (``randall/recolor/workflows.py``) on 2026-10-03.
"""
import os
import re
import zipfile

from shared import mod_files


# --- an attached model waiting to be imported --------------------------------
# "import this" with a Togetic zip attached went to the fast lane, which read it
# as a question about the word "import" and answered from the docs; the import
# only ran on the user's NEXT message (Randall eval, 2026-09-25). This is decided
# from the files themselves: an attached model-like file the chat has not
# imported yet plus a message that asks to act on it is an import turn. It is
# the only way an ordinary chat reaches import_model (its words never route
# there), so a .zip is opened to see what it holds: a costume pack (fighter
# DATs, no 3D model) is not a model.
MODEL_FILE_EXTENSIONS = frozenset({'.zip', *mod_files.MODEL_SUFFIXES})   # mod_files keeps the one list
_COSTUME_FILES = frozenset(('.dat', '.usd'))
_MODEL_ACTION = re.compile(r"\b(import\w*|put|make|turn|fit|use|add|convert|port|costume|skin|model|try|do it|go ahead)\b", re.I)
_STRONG_ACTION = re.compile(r"\b(import\w*|put|make|turn|fit|convert|port)\b", re.I)
_POINTS_AT_IT = re.compile(r"\b(this|it|that|these|them|one)\b", re.I)
_QUESTION = re.compile(r"^\s*(what|which|who|whose|when|where|why|how)\b", re.I)
_ASKS = re.compile(r"^\s*(is|are|was|were|does|do|did|has|have)\b.*\?\s*$", re.I | re.S)


def _costume_pack(item):
    """True for an attached .zip that holds costume files and no 3D model.

    Unreadable or unknown (not a chat file here) is not a costume pack: the
    file is treated as a model, as it always was."""
    try:
        path, _info = mod_files.resolve(item['file_id'])
        with zipfile.ZipFile(path) as archive:
            suffixes = {os.path.splitext(name)[1].lower() for name in archive.namelist()}
    except Exception:
        return False
    return bool(suffixes & _COSTUME_FILES) and not suffixes & (MODEL_FILE_EXTENSIONS - {'.zip'})


def _is_model_file(item):
    name = str((item or {}).get('name') or '')
    extension = str((item or {}).get('extension') or os.path.splitext(name)[1]).lower()
    if extension not in MODEL_FILE_EXTENSIONS:
        return False
    return extension != '.zip' or not _costume_pack(item)


def _consumed(receipt):
    """True when this import call used up its source: it is running, or it ran an import. A reply tagged with no
    project (refused, or the importer not set up) and an import the user stopped leave the file to try again."""
    result = receipt.get('result')
    if not isinstance(result, dict):
        return True
    tag = result.get('studio_import')
    if isinstance(tag, dict) and not tag.get('id'):
        return False
    return result.get('status') != 'cancelled'


def _asked_for_textures(receipts):
    """True when this chat's newest import_model call stopped to ask for the texture files its model names
    (import_job.textures_reply): the user's next message answers it ("go ahead without them", or a ZIP)."""
    calls = [r for r in receipts or () if isinstance(r, dict) and r.get('name') == 'import_model']
    result = calls[-1].get('result') if calls else None
    return isinstance(result, dict) and result.get('status') == 'needs_textures'


def models_waiting(attachments, receipts=()):
    """The attached model-like files this chat has not imported yet, oldest first (whatever the message says)."""
    # A model import (model_import/chat/studio_import.py) starts from import_model's `source`.
    imported = {str((r.get('arguments') or {}).get('source')) for r in receipts or ()
                if r.get('name') == 'import_model' and (r.get('arguments') or {}).get('source') and _consumed(r)}
    return [f for f in attachments or () if isinstance(f, dict) and f.get('file_id')
            and str(f['file_id']) not in imported and _is_model_file(f)]


def attached_model_waiting(user_text, attachments, receipts=()):
    """The newest attached model-like file not imported yet, when the message asks to act on it. -> dict or None"""
    text = (user_text or '').strip()
    if not text:
        return None
    waiting = models_waiting(attachments, receipts)
    if not waiting:
        return None
    # The import stopped to ask for its model's texture files: whatever the user says next ("yes, without them",
    # "nah", a ZIP) is its answer, an import turn (the card says what to do with it).
    if _asked_for_textures(receipts):
        return waiting[-1]
    # "what is this?" / "does it have a tail?" are questions; "can you import this?" and "do it" are not.
    if (_QUESTION.match(text) or _ASKS.match(text)) and not _STRONG_ACTION.search(text):
        return None
    short = len(re.findall(r"\w+", text)) <= 4
    if _MODEL_ACTION.search(text) or (short and _POINTS_AT_IT.search(text)):
        return waiting[-1]
    return None
