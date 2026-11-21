"""
Regression test for the metadata.json read-modify-write race that silently
dropped vault entries (the seeded Giga Bowser vanished when several custom
characters were imported at once). A multi-file drag fires many concurrent
/import/file requests on Flask's threaded server; without a lock + atomic write
their appends clobber each other. `_append_custom_character` must keep every
entry, including a pre-existing one.

custom_characters now routes its metadata IO through the core.metadata DAL, so
these tests drive the unified path via the `vault` fixture (which redirects the
DAL's metadata file at a temp vault).
"""
import threading

import vault.routes.custom_characters as cc
import vault.importing.custom_character_zip as cc_zip
import vault.catalog.custom_characters as cc_catalog


def test_concurrent_appends_keep_all_entries(vault):
    # pre-existing builtin entry (stands in for the seeded Giga Bowser)
    vault.write({
        'characters': {}, 'stages': {}, 'custom_stages': [],
        'custom_characters': [{'slug': 'giga-bowser', 'name': 'Giga Bowser', 'builtin': True}],
    })

    n = 24
    barrier = threading.Barrier(n)  # maximise overlap

    def worker(i):
        barrier.wait()
        cc_zip._append_custom_character({'slug': f'char-{i}', 'name': f'Char {i}', 'source': 'zip'})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = vault.read()
    slugs = {c['slug'] for c in data['custom_characters']}
    # the builtin survived AND all 24 concurrent appends landed — nothing lost
    assert 'giga-bowser' in slugs
    assert all(f'char-{i}' in slugs for i in range(n))
    assert len(data['custom_characters']) == n + 1


def test_write_is_atomic_valid_json(vault):
    cc_catalog._write_metadata({'custom_characters': [{'slug': 'x'}]})
    # readable as valid JSON and no leftover temp file
    assert vault.read()['custom_characters'][0]['slug'] == 'x'
    assert not (vault.storage / 'metadata.json.tmp').exists()
