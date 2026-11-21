from randall.assistant import store
from randall.website import vault_presence as presence


def test_persistent_links_survive_chat_deletion_and_follow_live_items(dual_backend):
    vault = dual_backend
    vault.write({'characters': {'Marth': {'skins': [{'id': 'green'}, {'id': 'black'}]}},
                 'stages': {'dreamland': {'variants': [{'id': 'lake'}]}}})
    receipt = {'website_mods': [{'post_id': 12}], 'imported_items': [{'character': 'Marth', 'id': 'green'}]}
    chat = store.save(None, [{'role': 'assistant', 'content': '', 'tools': [
        {'name': 'download_website_mod', 'result': receipt},
        {'name': 'download_website_mods', 'result': {'downloads': [
            {'post_id': 13, 'result': {'imported_stages': [{'folder': 'dreamland', 'id': 'lake'}]}},
            {'post_id': 14, 'result': {'error': 'Failed', 'imported_count': 0}}]}}]}])
    presence.recover_history()
    store.delete(chat)
    presence.recover_history()
    assert presence.vault_status([12, 13, 14]) == {'12': True, '13': True, '14': None}
    presence.record_import(12, {'imported_items': [{'character': 'Marth', 'id': 'black'}]})
    data = vault.read()
    data['characters']['Marth']['skins'] = [{'id': 'black', 'name': 'Renamed'}]
    data['stages']['dreamland']['variants'] = []
    vault.write(data)
    assert presence.vault_status([12, 13]) == {'12': True, '13': False}
    data['characters']['Marth']['skins'] = []
    vault.write(data)
    assert presence.vault_status([12]) == {'12': False}


def test_counts_and_matching_names_do_not_prove_ownership(vault):
    vault.write({'characters': {'Marth': {'skins': [{'id': 'unrelated', 'name': 'Kermit'}]}}})
    presence.record_import(15, {'imported_count': 1, 'skipped_count': 1})
    assert presence.vault_status([15]) == {'15': None}
    presence.record_import(15, {}, [{'kind': 'costume', 'owner': 'Marth', 'id': 'unrelated'}])
    assert presence.vault_status([15]) == {'15': True}


def test_status_endpoint_checks_ids_and_current_catalog(vault, monkeypatch):
    import importlib
    assistant_bp = importlib.import_module('randall.routes.assistant_bp')
    monkeypatch.setattr(assistant_bp.gates, 'enabled', lambda *_: True)
    vault.write({'characters': {'Link': {'skins': [{'id': 'cdi'}]}}})
    presence.record_import(123, {'imported_items': [{'character': 'Link', 'id': 'cdi'}]})
    client = vault.client(assistant_bp, 'assistant_bp')
    assert client.post('/api/assistant/website/vault-status', json={'post_ids': [123]}).json == {'in_vault': {'123': True}}
    for ids in [[], [True], ['123'], list(range(501))]:
        assert client.post('/api/assistant/website/vault-status', json={'post_ids': ids}).status_code == 400
