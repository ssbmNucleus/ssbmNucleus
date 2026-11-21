"""
Phase 3 rollout: dual-write canary. When the DB backend is active with
VAULT_DUAL_WRITE on, every save must ALSO mirror metadata.json so it stays a
live rollback backup (and path=-based JSON readers see current data). With
dual-write off, the JSON is left untouched. See docs/VAULT_SQLITE_MIGRATION.md.
"""
import json

import core.metadata as cm
import core.config as core_config
import core.vault as vaultmod


def test_db_dual_write_updates_both_stores(vault, monkeypatch):
    monkeypatch.setattr(core_config, 'VAULT_BACKEND', 'db')
    monkeypatch.setattr(core_config, 'VAULT_DUAL_WRITE', True)

    blob = {'bundles': [{'id': 'a'}], 'version': '1.0'}
    cm.save_metadata(blob)

    # DB (authoritative) has it...
    assert vaultmod.db_to_blob() == blob
    # ...and the metadata.json mirror is kept in sync.
    mirror = json.loads((vault.storage / 'metadata.json').read_text(encoding='utf-8'))
    assert mirror == blob


def test_db_without_dual_write_leaves_json_untouched(vault, monkeypatch):
    monkeypatch.setattr(core_config, 'VAULT_BACKEND', 'db')
    monkeypatch.setattr(core_config, 'VAULT_DUAL_WRITE', False)
    (vault.storage / 'metadata.json').write_text(json.dumps({'stale': True}), encoding='utf-8')

    cm.save_metadata({'bundles': [{'id': 'b'}]})

    assert vaultmod.db_to_blob() == {'bundles': [{'id': 'b'}]}       # DB updated
    mirror = json.loads((vault.storage / 'metadata.json').read_text(encoding='utf-8'))
    assert mirror == {'stale': True}                                 # JSON NOT mirrored


def test_db_reads_come_from_db_not_json_mirror(vault, monkeypatch):
    """Sanity: with dual-write on, reads are served from the DB (authoritative),
    not the JSON mirror."""
    monkeypatch.setattr(core_config, 'VAULT_BACKEND', 'db')
    monkeypatch.setattr(core_config, 'VAULT_DUAL_WRITE', True)
    blob = {'characters': {'Fox': {'skins': [{'id': 'a'}]}}, 'stages': {}}
    cm.save_metadata(blob)

    # corrupt the JSON mirror; DB read must be unaffected
    (vault.storage / 'metadata.json').write_text('{"corrupt": true}', encoding='utf-8')
    assert cm.load_metadata() == blob
