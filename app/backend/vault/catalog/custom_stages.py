"""
Custom stages in the vault index (metadata.json["custom_stages"]): the reads
both the vault Custom Stages routes (vault/routes/custom_stages.py) and the
install routes (projects/routes/custom_stages.py) make, and the write the vault
routes and the ISO scan (vault/importing/custom_stage_scan.py) share. The list
mixes stage entries (keyed by slug) and folder rows.

No routes. Reading a stage package into the vault is
vault/importing/custom_stage_package.py.
"""

from core.metadata import load_metadata, save_metadata
from vault.importing.custom_stage_package import DEFAULT_META as _DEFAULT_META


def _read_metadata():
    # Delegates to the core.metadata DAL (the single seam the SQLite migration
    # swaps behind); keeps this module's historical 'custom_stages' default.
    data = load_metadata(default=dict(_DEFAULT_META))
    data.setdefault('custom_stages', [])
    return data


def _is_folder(item):
    return isinstance(item, dict) and item.get('type') == 'folder'


def _find_stage_entry(metadata, slug):
    return next((s for s in metadata.get('custom_stages', [])
                 if not _is_folder(s) and s.get('slug') == slug), None)


def _write_metadata(data):
    # DAL write is atomic (temp + os.replace); pairs with metadata_lock /
    # metadata_transaction at the mutation sites to prevent lost updates.
    save_metadata(data)
