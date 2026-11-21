import json
import zipfile
from urllib.parse import urlencode

import pytest

from randall.assistant import approvals, tools
from randall.website import website, website_posts
from tests.backend import website_site
from tests.backend.website_site import media
from randall.website.vault_presence import vault_status
from vault.importing.unified.protocol import import_handoff, parse_import_link


def test_approved_effect_link_uses_real_importer_and_persistent_ownership(vault, monkeypatch):
    from vault.importing.unified import effects
    from vault.routes.import_unified import routes
    import vault.importing.unified.archive as unified_archive
    monkeypatch.setattr(effects, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(unified_archive, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(effects, 'derive_modifications_from_dat',
                        lambda *args: {'primary': {'color': '0066FFFF'}})
    post = {'id': 123, 'title': 'Blue laser', 'tags': ['Effects', 'Fox', 'Laser'],
            'files': [{'id': 42, 'file_type': 'effects_dat', 'filename': 'EfFxData.dat', 'character': 'Fox'}]}
    website_site.install(monkeypatch, post)

    def rpc(name, args, *extra):
        if name == 'api_get_effect_types':
            return {'effect_types': [{'tag_name': 'Laser', 'characters': ['Fox', 'Falco']}]}
        return {}
    for _mod in (website, website_posts):
        monkeypatch.setattr(_mod, '_rpc', rpc)
    downloads = []
    def download(url, destination, **kwargs):
        downloads.append(url)
        with zipfile.ZipFile(destination, 'w') as archive:
            archive.writestr('EfFxData.dat', b'isolated effect fixture')
    monkeypatch.setattr(website, '_download', download)
    call = tools.prepare('download_website_mod', {'post_id': 123})
    plan = json.loads(call.plan)
    handoff = parse_import_link(plan['protocol_url'])
    assert handoff['filename'] == 'Fox_Default.zip'
    assert handoff['mod_type'] == 'effect' and handoff['effect_type'] == 'laser'
    assert 'approval' in tools.execute(call)['error']
    # Preparing the approval fetched the object into quarantine once; nothing
    # was imported without the grant.
    assert downloads == ['https://ssbmnucleus.net/api/posts/123/export-nucleus/42']
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    assert 'error' not in result, result
    assert downloads == ['https://ssbmnucleus.net/api/posts/123/export-nucleus/42']
    assert result['imported_count'] == 1
    effect = vault.read()['characters']['Fox']['extras']['laser'][0]
    assert vault.path('Fox', effect['model_file']).read_bytes() == b'isolated effect fixture'
    assert result['imported_effects'][0]['id'] == effect['id']
    assert vault_status([123]) == {'123': True}
    # A fresh approval uses the same explicit routing and skips the exact duplicate.
    retry = tools.prepare('download_website_mod', {'post_id': 123})
    second = tools.execute(retry, approvals.Grant(retry.fingerprint))
    assert second['skipped_count'] == 1 and second['imported_count'] == 0
    assert len(vault.read()['characters']['Fox']['extras']['laser']) == 1


def test_protocol_import_refuses_changed_source_and_unsafe_names(tmp_path):
    url = 'nucleus://import?' + urlencode({'url': 'https://media.ssbmnucleus.net/mod.zip', 'name': 'Fox_Default'})
    with pytest.raises(ValueError, match='source changed'):
        import_handoff(tmp_path / 'unused.zip', 'unused.zip', protocol_url=url,
                       expected_url='https://media.ssbmnucleus.net/other.zip')
    for invalid in ['nucleus://play?build=abc', url + '&name=duplicate',
                    'nucleus://import?' + urlencode({'url': 'file:///private', 'name': 'mod'}),
                    'nucleus://import?' + urlencode({'url': 'https://media.ssbmnucleus.net/mod.zip', 'name': '../outside'})]:
        with pytest.raises(ValueError):
            parse_import_link(invalid)
