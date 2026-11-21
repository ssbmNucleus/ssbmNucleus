"""
Regression tests for bundles metadata IO after routing it through the
core.metadata DAL. The critical property: writing the bundles list must NOT
clobber the sibling vault keys (custom_characters/stages/characters) that share
the same metadata store — the original reason these writes were locked.
"""
import threading

import vault.catalog.bundles as b


def test_load_bundles_empty_when_no_metadata(vault):
    assert b.load_bundle_metadata() == []


def test_save_bundles_preserves_other_vault_keys(vault):
    vault.write({'version': '1.0', 'characters': {'Fox': {'skins': []}},
                 'custom_characters': [{'slug': 'wolf'}], 'bundles': []})

    b.save_bundle_metadata([{'id': 'x'}])

    data = vault.read()
    assert data['bundles'] == [{'id': 'x'}]
    assert data['custom_characters'] == [{'slug': 'wolf'}]      # not clobbered
    assert data['characters'] == {'Fox': {'skins': []}}


def test_append_bundle_appends_and_preserves(vault):
    vault.write({'bundles': [{'id': 'a'}], 'custom_characters': [{'slug': 'wolf'}]})

    b._append_bundle({'id': 'b'})

    data = vault.read()
    assert [x['id'] for x in data['bundles']] == ['a', 'b']
    assert data['custom_characters'] == [{'slug': 'wolf'}]


def test_concurrent_bundle_appends_keep_all(vault):
    vault.write({'bundles': [], 'custom_characters': [{'slug': 'keep'}]})
    n = 16
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        b._append_bundle({'id': f'bundle-{i}'})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = vault.read()
    ids = {x['id'] for x in data['bundles']}
    assert all(f'bundle-{i}' in ids for i in range(n))
    assert len(data['bundles']) == n
    assert data['custom_characters'] == [{'slug': 'keep'}]      # sibling key intact
