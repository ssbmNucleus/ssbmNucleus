import io
import json
import zipfile
from pathlib import Path

import pytest
import requests
from urllib.parse import quote

from randall.assistant import approvals, tools
from randall.website import website, website_posts, website_search
from tests.backend import website_site
from tests.backend.website_site import counted, media
from tests.backend.window_key import WINDOW, as_the_window  # noqa: F401

pytestmark = pytest.mark.usefixtures('as_the_window')


def _zip_payload(members=(('PlMsBu.dat', b'\x00'),)):
    """A real, minimal ZIP -- what a download actually produces."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buffer.getvalue()


def _downloader(payload=None, log=None, after=None):
    """A `_download` double that writes real bytes into the quarantine path."""
    data = _zip_payload() if payload is None else payload

    def download(url, path, **kwargs):
        if log is not None:
            log.append(url)
        Path(path).write_bytes(data)
        if after is not None:
            after()
    return download


@pytest.fixture
def catalog(monkeypatch, vault):
    # These catalog/approval tests stub file IO; safety preflight has its own tests.
    from randall.website import website_safety
    monkeypatch.setattr(website_safety, 'inspect_archive',
                        lambda *args, **kwargs: {'unsafe_costumes': [], 'checked_count': 0,
                                                 'archive_hash': ''})
    post = {'id': 123, 'title': 'Blue Marth', 'author': 'Artist',
            'description': 'A costume', 'tags': ['Marth'], 'updated_at': 'v1',
            'zip_url': media('posts/123/files.zip'),
            'screenshots': [media('posts/123/preview%20image.png')],
            'files': [{'id': 42, 'filename': 'PlMsBu.dat', 'character': 'Marth',
                       'color': 'Blue', 'file_type': 'character_dat', 'file_url': media('posts/123/PlMsBu.dat')}],
            'archive_files': [{'filename': 'PlMsBu.dat', 'size': 1}]}
    site = website_site.install(monkeypatch, post, total=10)
    # Preparing an approval downloads into quarantine and identifies the bytes,
    # so every test needs a download that produces a real archive. Tests that
    # care about the transfer itself replace this.
    monkeypatch.setattr(website, '_download', _downloader())
    return post, site


def test_search_preview_pagination_and_fixed_catalog(catalog):
    post, site = catalog
    site.search = lambda params: ([post], 10, None if params.get('cursor') else 'QDY')
    result = website_search.search_website_mods('blue', 'Marth')
    assert result['website_total'] == 10 and result['next_cursor'] == 'QDY'
    assert site.calls[0] == ('/mods', {'limit': 6, 'sort': 'newest', 'order': 'desc',
                                       'q': 'blue', 'character': 'Marth'})
    card = result['website_mods'][0]
    assert card['image'] == 'https://media.ssbmnucleus.net/posts/123/preview%20image.png'
    assert card['author'] == 'Artist' and 'files' not in card
    assert card['creator'] == 'Artist' and card['credit'] == 'Artist' and 'original_source' not in card
    detail = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert detail['files'][0]['file_id'] == 42 and detail['files'][0]['can_download']
    assert detail['archive_entries'] == ['PlMsBu.dat']
    following = website_search.search_website_mods('blue', 'Marth', cursor=result['next_cursor'])
    assert site.calls[-1][1]['cursor'] == 'QDY' and following['next_cursor'] is None
    # A mod that is not public is a 404 from the API.
    post['hidden'] = True
    with pytest.raises(ValueError, match='publicly available'):
        website_posts.inspect_website_mod(123)


def test_cards_credit_the_creator_of_a_re_upload(catalog):
    post, site = catalog
    post.update(author='SSBM Textures', creator='mcromich', original_source='SSBM Textures',
                description='Moai.\n\nOriginally posted by mcromich on ssbmtextures.com on January 22, 2022')
    card = website_search.search_website_mods('moai')['website_mods'][0]
    assert (card['creator'], card['author'], card['credit']) == (
        'mcromich', 'SSBM Textures', 'mcromich (via SSBM Textures)')
    assert card['original_source'] == 'SSBM Textures'
    detail = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert detail['credit'] == 'mcromich (via SSBM Textures)'
    # Moved to the creator's own account: one name, still from SSBM Textures.
    post.update(author='Dewrion', creator='Dewrion')
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert (card['creator'], card['author'], card['credit']) == ('Dewrion', 'Dewrion', 'Dewrion')
    assert card['original_source'] == 'SSBM Textures'
    # Same name in another case is one person, and creator text is untrusted text like the rest.
    post.update(author='nova', creator='Nova\u202e', original_source=None)
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert (card['creator'], card['credit']) == ('Nova', 'Nova') and 'original_source' not in card


def test_cards_from_a_site_without_credit_fields_read_as_the_uploader(catalog):
    post, site = catalog
    site.legacy = True
    post.update(creator='ignored', original_source='ignored')
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert (card['creator'], card['author'], card['credit']) == ('Artist', 'Artist', 'Artist')
    assert 'original_source' not in card
    post.update(author='')
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert (card['creator'], card['author'], card['credit']) == ('Unknown author', 'Unknown author', 'Unknown author')


def test_author_filter_searches_the_creator_and_falls_back_on_an_older_site(catalog):
    post, site = catalog
    website_search.search_website_mods(author='mcromich')
    assert site.searches()[-1]['creator'] == 'mcromich' and 'author' not in site.searches()[-1]
    site.legacy = True
    result = website_search.search_website_mods(author='mcromich', cursor='QDM')
    first, retry = site.searches()[-2:]
    assert first['creator'] == 'mcromich' and 'author' not in first
    assert retry == {**{k: v for k, v in first.items() if k != 'creator'}, 'author': 'mcromich'}
    assert result['website_mods'][0]['credit'] == 'Artist'
    # Any other refusal is still an error.
    site.legacy = False
    site.search = lambda params: (_ for _ in ()).throw(ValueError('The mod website refused that request: nope.'))
    with pytest.raises(ValueError, match='nope'):
        website_search.search_website_mods(author='mcromich', cursor='QDM')
    assert 'author' not in site.searches()[-1]


def test_all_file_types_use_website_preview_when_individual_art_is_missing(catalog):
    post, _ = catalog
    for kind in ['stage_dat', 'xdelta', 'effect', 'unknown_future_type']:
        post['files'][0]['file_type'] = kind
        contents = website._contents(post)
        assert contents['mods'][0]['image'] == website_posts._card(post)['image']
        assert contents['mods'][0]['image_is_post']
    post['files'][0]['preview_url'] = media('specific.png')
    assert website._contents(post)['mods'][0]['image'].endswith('/specific.png')
    assert not website._contents(post)['mods'][0]['image_is_post']


def test_stage_receipt_resolves_exact_imports_and_refreshes_screenshot(catalog, vault, monkeypatch):
    from randall.assistant import store
    post, _ = catalog
    post['files'][0].update(filename='GrOp.dat', file_type='stage_dat', character=None)
    variant = {'id': 'lake', 'name': 'lake', 'screenshot_filename': 'lake shot.png'}
    vault.write({'characters': {}, 'stages': {'dreamland': {'variants': [variant, {'id': 'unrelated'}]}}})
    monkeypatch.setattr(website, '_download', _downloader())
    monkeypatch.setattr(website, '_import_archive', lambda *args, **kwargs: ({'success': True,
        'imported_count': 1, 'stages': [{'stage': 'Dreamland', 'variant': 'lake'}]}, 200))
    call = tools.prepare('download_website_mod', {'post_id': 123})
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    assert len(result['imported_stages']) == 1
    item = result['imported_stages'][0]
    assert item['id'] == 'lake' and item['image'] == '/storage/das/dreamland/lake%20shot.png'
    chat = store.save(None, [{'role': 'assistant', 'content': '', 'tools': [{'result': result}]}])
    variant['screenshot_filename'] = 'new.png'
    vault.write({'characters': {}, 'stages': {'dreamland': {'variants': [variant]}}})
    stored = store.get(chat)['messages'][0]['tools'][0]['result']['imported_stages'][0]
    assert stored['image'].endswith('/new.png') and not stored['unavailable']
    vault.write({'characters': {}, 'stages': {}})
    assert store.get(chat)['messages'][0]['tools'][0]['result']['imported_stages'][0]['unavailable']


@pytest.mark.parametrize('args', [{'cursor': ''}, {'cursor': 7}, {'cursor': 'a b'}, {'cursor': 'x' * 513},
                                  {'query': []}, {'character': 'x' * 161}, {'tags': ['a,b']}])
def test_search_rejects_invalid_arguments(args):
    with pytest.raises(ValueError):
        website_search.search_website_mods(**args)


@pytest.mark.parametrize('sort_by', website_search.SORT_FIELDS)
@pytest.mark.parametrize('sort_order', ['asc', 'desc'])
def test_full_search_filters_and_popularity(catalog, sort_by, sort_order):
    post, site = catalog
    post.update(like_count=14, download_count=900, created_at='2026-09-08')
    site.search = lambda params: ([post], 10, 'QDY')
    result = website_search.search_website_mods(query='blue', character='Marth', author='Artist',
        category='Character Costume', tags=['Blue'], exclude_tags=['Animelee'],
        sort_by=sort_by, sort_order=sort_order, limit=3, cursor='QDM')
    sort = {'created_at': 'newest', 'download_count': 'downloads', 'like_count': 'likes'}[sort_by]
    assert site.calls[-1] == ('/mods', {'limit': 3, 'sort': sort, 'order': sort_order,
        'q': 'blue', 'character': 'Marth', 'creator': 'Artist',
        'tags': 'Blue,Character Costume', 'exclude_tags': 'Animelee', 'cursor': 'QDM'})
    assert result['website_mods'][0]['like_count'] == 14
    assert result['website_mods'][0]['download_count'] == 900
    assert result['next_cursor'] == 'QDY'
    website_search.search_website_mods(**result['filters'], cursor=result['next_cursor'])
    assert site.calls[-1][1]['cursor'] == 'QDY' and site.calls[-1][1]['sort'] == sort


@pytest.mark.parametrize('args', [
    {'sort_by': 'trending'}, {'sort_order': 'random'}, {'limit': 0}, {'limit': 25},
    {'limit': True}, {'tags': 'Marth'}, {'tags': ['']}, {'tags': [None]},
    {'exclude_tags': ['x'] * 21}, {'category': 'Invented category'},
    {'category': 'Patch', 'exclude_tags': ['patch']}, {'author': []},
])
def test_invalid_filters_fail_before_network(monkeypatch, args):
    monkeypatch.setattr(website_posts, '_api', lambda *args: pytest.fail('must not request'))
    with pytest.raises(ValueError):
        website_search.search_website_mods(**args)


def test_gallery_and_agent_metadata(catalog):
    post, _ = catalog
    post['screenshots'].extend([media('second.png'), 'https://untrusted.test/image.png'])
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert len(card['images']) == 2
    assert card['description'] == 'A costume' and card['files'][0]['file_id'] == 42


def test_detail_preview_takes_counts_from_the_api_alone(catalog, monkeypatch):
    post, _ = catalog
    post.update(download_count=51, like_count=7)
    # The API always carries like_count, so a preview never asks the like RPC.
    for _mod in (website, website_posts):
        monkeypatch.setattr(_mod, '_rpc', lambda *args: pytest.fail('no RPC for a preview'))
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert card['like_count'] == 7 and card['download_count'] == 51


def test_hydrates_separate_csps_and_stock_in_nested_archives(tmp_path):
    import io
    import zipfile
    from PIL import Image
    from randall.website.website_artwork import hydrate_archive
    png = io.BytesIO(); Image.new('RGBA', (136, 188), 'green').save(png, format='PNG')
    archive = tmp_path / 'mod.zip'
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, 'w') as z:
        z.writestr('costumes/kermit PlMsGr.dat', b'unchanged-dat')
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('skins.zip', inner.getvalue())
        z.writestr('readme.txt', b'unchanged-readme')
    rows = [{'id': 1, 'filename': 'kermit PlMsGr.dat', 'file_type': 'character_dat',
             'csp_url': media('csp.png'), 'stock_url': media('stock.png')}]
    calls = []
    def download(url, path): calls.append(url); path.write_bytes(png.getvalue())
    assert hydrate_archive(archive, rows, download) == []
    with zipfile.ZipFile(archive) as z:
        assert z.read('readme.txt') == b'unchanged-readme'
        with zipfile.ZipFile(io.BytesIO(z.read('skins.zip'))) as skins:
            assert skins.read('costumes/kermit PlMsGr.dat') == b'unchanged-dat'
            assert skins.read('costumes/kermit PlMsGr_csp.png') == png.getvalue()
            assert skins.read('costumes/kermit PlMsGr_stc.png') == png.getvalue()
    assert len(calls) == 2
    assert hydrate_archive(archive, rows, lambda *args: pytest.fail('preserve existing art')) == []


def test_artwork_failures_are_reported_without_guessing(tmp_path):
    import zipfile
    from randall.website.website_artwork import hydrate_archive
    path = tmp_path / 'mod.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('a/PlMsGr.dat', b'one'); z.writestr('b/PlMsGr.dat', b'two')
    rows = [{'id': 1, 'filename': 'PlMsGr.dat', 'file_type': 'character_dat', 'csp_url': media('csp.png')}]
    warnings = hydrate_archive(path, rows, lambda *args: pytest.fail('ambiguous file'))
    assert 'could not be matched' in warnings[0]


@pytest.mark.parametrize('url', ['http://media.ssbmnucleus.net/a.zip', 'https://evil.test/a.zip',
                                'https://media.ssbmnucleus.net@evil.test/a.zip',
                                'https://media.ssbmnucleus.net:443/a.zip', 'file:///vault/a.zip'])
def test_untrusted_media_cannot_be_downloaded(catalog, url):
    post, _ = catalog
    post['download_url'] = url
    assert website_posts._media(url) is None
    with pytest.raises(ValueError, match='no supported website archive'):
        tools.prepare('download_website_mod', {'post_id': 123})


@pytest.mark.parametrize('url', [counted(124), counted(123, 42), counted(123) + '?file=1',
                                 'https://ssbmnucleus.net/api/public/v1/mods/123/download/',
                                 'https://media.ssbmnucleus.net/posts/123/files.zip'])
def test_only_the_counted_link_for_this_mod_is_downloaded(catalog, url):
    """The whole mod comes through ITS counted link; nothing else the record names."""
    post, _ = catalog
    post['download_url'] = url
    with pytest.raises(ValueError, match='no supported website archive'):
        tools.prepare('download_website_mod', {'post_id': 123})


def test_a_file_hidden_from_the_api_is_refused_with_its_reason(catalog):
    """The API leaves out files the site hides, so a known id can be missing."""
    with pytest.raises(ValueError, match='not listed on this mod.s public page'):
        website.prepare_download({'post_id': 123, 'file_id': 43})


def test_download_requires_exact_one_use_approval_and_cleans_temporary_files(catalog, monkeypatch):
    downloads, imports = [], []
    def download(url, path, **kwargs):
        downloads.append((url, path)); path.write_bytes(b'RAWDAT')
    def importer(path, title, **kwargs):
        with zipfile.ZipFile(path) as zf:
            imports.append(({name: zf.read(name) for name in zf.namelist()}, title))
        return {'success': True, 'imported_count': 1, 'skipped_count': 2, 'fixed_count': 1,
                'message': 'Imported 1 costume; skipped 2 already owned'}, 200
    monkeypatch.setattr(website, '_download', download)
    monkeypatch.setattr(website, '_import_archive', importer)
    call = tools.prepare('download_website_mod', {'post_id': 123, 'file_id': 42})
    # Preparing the approval fetches the object into quarantine and identifies
    # it, so the card can state what it IS. Nothing is imported until approval.
    assert len(downloads) == 1 and not imports
    preview = json.loads(call.preview)
    assert preview['detected']['sha256'] and preview['content_is_untrusted']
    assert preview['confirm_label'] == 'Download to vault'
    assert preview['website_mods'][0]['selected_file']['name'] == 'PlMsBu.dat'
    assert 'error' in tools.execute(call)
    grant = approvals.Grant(call.fingerprint)
    result = tools.execute(call, grant)
    assert result['vault_changed'] and result['imported_count'] == 1
    assert result['skipped_count'] == 2 and result['fixed_count'] == 1
    assert downloads[0][0] == 'https://ssbmnucleus.net/api/posts/123/export-nucleus/42'
    assert len(downloads) == 1          # the held object, not a second fetch
    # A raw published file reaches the importer wrapped under its PUBLISHED
    # name, not handed over as `mod.zip` for zipfile to choke on (finding 3).
    assert [title for _, title in imports] == ['Blue Marth']
    assert imports[0][0] == {'PlMsBu.dat': b'RAWDAT'}
    assert not downloads[0][1].parent.exists()
    assert 'error' in tools.execute(call, grant)
    assert len(downloads) == 1


def test_stale_approval_never_downloads_again(catalog, monkeypatch):
    """A post edited after the preview stops the import, and fetches nothing."""
    post, _ = catalog
    call = tools.prepare('download_website_mod', {'post_id': 123})
    post['files'][0]['file_url'] = media('replaced.dat')
    monkeypatch.setattr(website, '_download', lambda *args, **kw: pytest.fail('must not download'))
    monkeypatch.setattr(website, '_import_archive', lambda *a, **k: pytest.fail('must not import'))
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    assert 'changed while approval' in result['error']


def test_edit_during_download_never_imports(catalog, monkeypatch):
    post, _ = catalog
    # The edit lands while the object is being fetched for the approval card,
    # so the plan that was approved no longer describes the live post.
    monkeypatch.setattr(website, '_download',
                        _downloader(after=lambda: post.update(updated_at='v2')))
    call = tools.prepare('download_website_mod', {'post_id': 123})
    monkeypatch.setattr(website, '_import_archive', lambda *args, **kwargs: pytest.fail('must not import'))
    assert 'changed' in tools.execute(call, approvals.Grant(call.fingerprint))['error']


def test_model_cannot_inject_download_url_or_foreign_file(catalog):
    with pytest.raises(ValueError, match='Invalid tool arguments'):
        tools.prepare('download_website_mod', {'post_id': 123, 'url': 'https://evil.test/a'})
    for args in [{'post_id': True}, {'post_id': '123'}, {'post_id': 123, 'file_id': 99}]:
        with pytest.raises(ValueError):
            tools.prepare('download_website_mod', args)


@pytest.mark.parametrize('payload,expected_error,changed', [
    ({'success': True, 'imported_count': 1, 'failed': [{'name': 'other.zip', 'error': 'Unsupported'}]}, False, True),
    ({'success': True, 'imported_count': 0, 'skipped_count': 1}, False, False),
    ({'success': True, 'imported_count': 0}, True, False),
    ({'success': False, 'error': 'Unsupported archive'}, True, False),
])
def test_import_outcomes_are_not_overstated(catalog, monkeypatch, payload, expected_error, changed):
    monkeypatch.setattr(website, '_download', _downloader())
    monkeypatch.setattr(website, '_import_archive', lambda *args, **kwargs: (payload, 200))
    call = tools.prepare('download_website_mod', {'post_id': 123})
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    assert ('error' in result) == expected_error
    assert result['vault_changed'] == changed
    if payload.get('failed'):
        assert result['note'].startswith('Partially imported.')
        assert result['failed'] == payload['failed']


class Response:
    def __init__(self, status=200, headers=None, chunks=()):
        self.status_code, self.headers, self.chunks = status, headers or {}, chunks
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, *args): yield from self.chunks


def _redirect(location):
    return Response(302, {'Location': location})


def test_a_counted_download_follows_its_one_redirect_to_the_media_host(monkeypatch, tmp_path):
    """The counted link credits the creator, then redirects once to the zip."""
    requested = []
    replies = {counted(123): _redirect(media('posts/123/files.zip')),
               media('posts/123/files.zip'): Response(chunks=[b'PK', b'zip'])}
    def get(url, **kwargs):
        assert kwargs['allow_redirects'] is False
        assert kwargs['headers']['User-Agent'].startswith('SSBM-Nucleus/')
        requested.append(url)
        return replies[url]
    monkeypatch.setattr(website.requests, 'get', get)
    website._download(counted(123), tmp_path / 'mod.zip')
    assert requested == [counted(123), media('posts/123/files.zip')]
    assert (tmp_path / 'mod.zip').read_bytes() == b'PKzip'
    # One file's counted link works the same way.
    replies.update({counted(123, 42): _redirect(media('posts/123/PlMsBu.dat')),
                    media('posts/123/PlMsBu.dat'): Response(chunks=[b'DAT'])})
    website._download(counted(123, 42), tmp_path / 'one.dat')
    assert requested[-2:] == [counted(123, 42), media('posts/123/PlMsBu.dat')]
    assert (tmp_path / 'one.dat').read_bytes() == b'DAT'


@pytest.mark.parametrize('first,second', [
    (_redirect('https://evil.test/files.zip'), None),                    # off the media host
    (_redirect('http://media.ssbmnucleus.net/files.zip'), None),         # not HTTPS
    (_redirect('https://media.ssbmnucleus.net@evil.test/x.zip'), None),  # credentials trick
    (_redirect('/posts/123/files.zip'), None),                           # relative: same site, not media
    (_redirect(counted(123)), None),                                     # back to itself
    (_redirect(media('a.zip')), _redirect(media('b.zip'))),              # a second hop
])
def test_a_counted_download_never_goes_anywhere_else(monkeypatch, tmp_path, first, second):
    replies = [first, second]
    monkeypatch.setattr(website.requests, 'get', lambda url, **kwargs: replies.pop(0) or pytest.fail(url))
    with pytest.raises(ValueError, match='redirected elsewhere'):
        website._download(counted(123), tmp_path / 'mod.zip')
    assert not (tmp_path / 'mod.zip').exists()


@pytest.mark.parametrize('url', ['https://ssbmnucleus.net/api/posts/123/export-nucleus/42',
                                 'https://ssbmnucleus.net/api/public/v1/mods/123',
                                 counted(123) + '?file=42&x=1', counted(123) + '#frag',
                                 media('posts/123/files.zip')])
def test_no_other_link_may_redirect(monkeypatch, tmp_path, url):
    monkeypatch.setattr(website.requests, 'get',
                        lambda target, **kwargs: _redirect(media('a.zip')) if target == url else pytest.fail(target))
    with pytest.raises(ValueError, match='redirected elsewhere'):
        website._download(url, tmp_path / 'mod.zip')


@pytest.mark.parametrize('response,match', [
    (Response(302, {'Location': 'http://127.0.0.1/private'}), 'redirected elsewhere'),
    (Response(headers={'Content-Length': str(website.MAX_DOWNLOAD + 1)}), '256 MB'),
    (Response(chunks=[b'1234', b'5678']), 'size or time limit'),
])
def test_download_bounds_and_no_redirects(monkeypatch, tmp_path, response, match):
    def get(url, **kwargs):
        assert kwargs['allow_redirects'] is False
        return response
    monkeypatch.setattr(website.requests, 'get', get)
    monkeypatch.setattr(website, 'MAX_DOWNLOAD', 6)
    with pytest.raises(ValueError, match=match):
        website._download(website_posts.MEDIA + '/mod.zip', tmp_path / 'mod.zip')


def test_network_failure_is_actionable(monkeypatch, tmp_path):
    def fail(*args, **kwargs): raise requests.ConnectionError('offline')
    monkeypatch.setattr(website.requests, 'get', fail)
    with pytest.raises(ValueError, match='Nothing was imported'):
        website._download(website_posts.MEDIA + '/mod.zip', tmp_path / 'mod.zip')


def test_reuses_importer_with_skip_and_explicit_fix(monkeypatch, tmp_path):
    from vault.routes.import_unified import routes
    import vault.importing.unified.archive as unified_archive
    calls = []
    monkeypatch.setattr(unified_archive, '_import_single_archive', lambda *args, **kwargs: calls.append((args, kwargs)) or ({'success': True}, 200))
    archive = tmp_path / 'mod.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('PlMsBu.dat', b'\x00')
    website._import_archive(archive, 'My mod', slippi_action='fix')
    # A real ZIP passes through the shared normalizer unchanged.
    assert calls[0][0][0] == str(archive)
    assert {k: v for k, v in calls[0][1].items() if k != 'budget'} == {
        'slippi_action': 'fix', 'duplicate_action': 'skip', 'custom_title': 'My mod'}
    # One cumulative extraction budget travels with the import (finding 2).
    assert 'budget' in calls[0][1]


def test_download_waits_for_ui_approval_and_persists_receipt(catalog, vault, monkeypatch):
    from randall.assistant import engine, live_runs, store
    calls = []
    rounds = []
    def provider(*args):
        rounds.append(1)
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'download-call', 'function': {'name': 'download_website_mod',
                'arguments': json.dumps({'post_id': 123})}}]} if len(rounds) == 1 else
            {'role': 'assistant', 'content': 'Added to your vault.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    monkeypatch.setattr(website, '_download',
                        _downloader(after=lambda: calls.append('download')))
    monkeypatch.setattr(website, '_import_archive', lambda *args, **kwargs: ({'success': True, 'imported_count': 1}, 200))
    run = engine.start(None, 'Download this mod', {}, request_key='test-only')
    try:
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested': break
        # One fetch, into quarantine, to build the card. Nothing imported.
        assert calls == ['download']
        approval = store.get(run.chat_id)['messages'][-1]['tools'][0]['approval']
        assert approval['website_mods'][0]['post_id'] == 123
        assert approval['detected']['sha256'] and approval['content_is_untrusted']
        live_runs.decide_approval(run.chat_id, event['tool']['approval']['id'], 'approve')
        list(live_runs.stream(run))
        result = store.get(run.chat_id)['messages'][-1]['tools'][0]['result']
        assert calls == ['download'] and result['vault_changed']
    finally:
        live_runs.cancel(run.id)


def add_variants(post):
    post['files'] = [{**post['files'][0], 'id': 50 + index,
                      'filename': f'kermit PlMs{code}.dat', 'color': color}
                     for index, (code, color) in enumerate([('Gr', 'Green'), ('Nr', 'Default'), ('Re', 'Red')])]


@pytest.mark.parametrize('choice,ending', [('default', '/export-nucleus/51'), ('all', '/mods/123/download')])
def test_download_variant_choice_is_bound_and_replay_safe(catalog, vault, monkeypatch, choice, ending):
    from randall.assistant import engine, live_runs, store
    from randall.routes.assistant_bp import assistant_bp
    from flask import Flask
    post, _ = catalog
    add_variants(post)
    urls, rounds = [], []
    def provider(*args):
        rounds.append(1)
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'variant-call', 'function': {'name': 'download_website_mod',
                'arguments': json.dumps({'post_id': 123})}}]} if len(rounds) == 1 else
            {'role': 'assistant', 'content': 'Done.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    monkeypatch.setattr(website, '_download', _downloader(log=urls))
    monkeypatch.setattr(website, '_import_archive', lambda *args, **kwargs: ({'success': True, 'imported_count': 1}, 200))
    run = engine.start(None, 'Download Kermit', {}, request_key='test-only')
    try:
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested': break
        approval = event['tool']['approval']
        assert approval['default_choice'] == 'default'
        assert [option['id'] for option in approval['choices']] == ['default', 'all']
        # Both offered scopes were fetched into quarantine and identified, so
        # whichever the user picks is bound to bytes already on disk.
        assert len(urls) == 2
        app = Flask(__name__); app.register_blueprint(assistant_bp)
        client = app.test_client()
        route = f'/api/assistant/chats/{run.chat_id}/approvals/{approval["id"]}'
        assert client.post(route, headers=WINDOW, json={'decision': 'approve', 'choice': 'arbitrary'}).status_code == 400
        assert client.post(route, headers=WINDOW, json={'decision': 'approve'}).status_code != 200
        assert client.post(route, headers=WINDOW, json={'decision': 'approve', 'choice': choice}).status_code == 200
        list(live_runs.stream(run))
        # Both scopes were fetched to build the card; the approved one was
        # imported from its held bytes, so nothing was fetched again.
        assert len(urls) == 2 and any(url.endswith(ending) for url in urls)
        receipt = store.get(run.chat_id)['messages'][-1]['tools'][0]
        assert receipt['approval']['choice'] == choice
        assert receipt['status'] == 'done'
        assert client.post(route, headers=WINDOW, json={'decision': 'approve', 'choice': choice}).status_code == 200
        assert client.post(route, headers=WINDOW, json={'decision': 'approve', 'choice': 'all' if choice == 'default' else 'default'}).status_code == 409
        assert len(urls) == 2
    finally:
        live_runs.cancel(run.id)


def test_variant_shortcut_requires_unambiguous_family_and_rechecks_revision(catalog, monkeypatch):
    post, _ = catalog
    add_variants(post)
    call = tools.prepare('download_website_mod', {'post_id': 123})
    assert 'error' in tools.execute(call, approvals.Grant(call.fingerprint))
    assert 'choices' not in json.loads(tools.prepare('download_website_mod', {'post_id': 123, 'file_id': 50}).preview)
    post['files'][1]['filename'] = 'Different Costume PlMsNr.dat'
    assert 'choices' not in website.prepare_download({'post_id': 123})[1]
    monkeypatch.setattr(website, '_download', lambda *args, **kw: pytest.fail('Changed content must not download'))
    result = tools.execute(call, approvals.Grant(call.fingerprint, 'default'))
    assert 'changed' in result['error']


def test_direct_download_bypasses_llm_and_receipt_has_exact_csp_and_stock(catalog, vault, monkeypatch):
    from randall.assistant import engine, live_runs, store
    from randall.routes.assistant_bp import assistant_bp
    from flask import Flask
    monkeypatch.setattr(engine, '_provider', lambda *args: pytest.fail('A download button must never call the LLM'))
    downloaded = []
    monkeypatch.setattr(website, '_download',
                        _downloader(after=lambda: downloaded.append(True)))
    # (one fetch happens while the approval preview is built)
    def import_archive(*args, **kwargs):
        vault.write({'characters': {'Marth': {'skins': [
            {'id': 'new-skin', 'name': 'Blue Marth', 'costume_code': 'PlMsBu',
             'has_csp': True, 'has_stock': True},
            {'id': 'unrelated', 'name': 'Unrelated skin', 'has_csp': True}
        ]}}})
        return {'success': True, 'imported_count': 1, 'costumes': [{'character': 'Marth', 'id': 'new-skin'}]}, 200
    monkeypatch.setattr(website, '_import_archive', import_archive)
    app = Flask(__name__); app.register_blueprint(assistant_bp)
    client = app.test_client()
    assert client.post('/api/assistant/website/download', json={'post_id':123,'tool':'anything'}).status_code == 400
    response = client.post('/api/assistant/website/download', json={'post_id':123})
    assert response.status_code == 200
    data = response.get_json()
    run = live_runs.active_run(data['chat_id'])
    try:
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested': break
        # One fetch, into quarantine, to identify the object for the card.
        assert downloaded == [True]
        assert client.post('/api/assistant/website/download', json={'post_id':123}).status_code == 409
        live_runs.decide_approval(run.chat_id, event['tool']['approval']['id'], 'approve')
        list(live_runs.stream(run))
        messages = store.get(run.chat_id)['messages']
        assert len(messages) == 1 and messages[0]['content'] == ''
        result = messages[0]['tools'][0]['result']
        assert len(result['imported_items']) == 1
        item = result['imported_items'][0]
        assert item['id'] == 'new-skin' and item['variant'] == 'Blue'
        assert item['image'] == '/storage/Marth/new-skin_csp.png'
        assert item['stock_image'] == '/storage/Marth/new-skin_stc.png'
        assert downloaded == [True]
    finally:
        live_runs.cancel(run.id)


@pytest.mark.parametrize('file_id,url', [
    (None, counted(123)),
    (42, 'https://ssbmnucleus.net/api/posts/123/export-nucleus/42'),
])
def test_downloads_are_credited_by_the_link_they_use(catalog, monkeypatch, file_id, url):
    """A whole mod comes through the API's counted link, which credits the
    creator itself: there is no separate counter call to make, or to lose."""
    post, _ = catalog
    post['download_count'] = 10
    for _mod in (website, website_posts):
        monkeypatch.setattr(_mod, '_rpc', lambda *args, **kwargs: pytest.fail('no counter RPC'))
    urls = []
    monkeypatch.setattr(website, '_download', _downloader(log=urls))
    monkeypatch.setattr(website, '_import_archive', lambda *args, **kwargs: ({'success': True, 'imported_count': 0, 'skipped_count': 5}, 200))
    call = tools.prepare('download_website_mod', {'post_id': 123, **({'file_id': file_id} if file_id else {})})
    grant = approvals.Grant(call.fingerprint)
    result = tools.execute(call, grant)
    assert 'error' not in result
    assert urls == [url]                # fetched once, into quarantine, then held
    assert result['website_mods'][0]['download_count'] == 10
    assert 'error' in tools.execute(call, grant)
    assert urls == [url]


def test_failed_archive_transfer_reports_the_failure(catalog, monkeypatch):
    """A transfer that never completed is an error, not a download anybody made."""
    def fail(*args, **kwargs): raise ValueError('Transfer failed')
    monkeypatch.setattr(website, '_download', fail)
    with pytest.raises(ValueError, match='Transfer failed'):
        tools.prepare('download_website_mod', {'post_id': 123})


def test_large_pack_review_pages_and_searches_full_server_manifest(catalog, vault, monkeypatch):
    from randall.assistant import engine, live_runs
    from randall.routes.assistant_bp import assistant_bp
    from flask import Flask
    post, _ = catalog
    post['files'] = [{'id': 1000 + i, 'filename': f'Costume {i:04} PlMsNr.dat',
                      'character': 'Marth' if i < 800 else 'Fox', 'color': 'Default', 'file_type': 'character_dat'}
                     for i in range(1203)]
    post['archive_files'] = [{'filename': f'files/{i:04}.dat', 'size': 1000} for i in range(1203)]
    monkeypatch.setattr(engine, '_provider', lambda *args: pytest.fail('Review must not call the LLM'))
    # Building the approval DOES fetch each offered scope into quarantine,
    # so the card can state what the object is. Nothing is imported.
    fetched = []
    monkeypatch.setattr(website, '_download', _downloader(log=fetched))
    monkeypatch.setattr(website, '_import_archive',
                        lambda *a, **k: pytest.fail('Review must not import'))
    app = Flask(__name__); app.register_blueprint(assistant_bp)
    client = app.test_client()
    run = engine.start_download(None, 123)
    try:
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested': break
        approval = event['tool']['approval']
        assert approval['contents_summary']['mod_count'] == 1203
        assert approval['contents_summary']['file_count'] == 1203
        assert 'contents' not in approval
        route = f'/api/assistant/chats/{run.chat_id}/approvals/{approval["id"]}/files'
        first = client.get(route).get_json()
        assert len(first['items']) == 20 and first['next_offset'] == 20
        tail = client.get(route, query_string={'offset':1200}).get_json()
        assert len(tail['items']) == 3 and tail['next_offset'] is None
        found = client.get(route, query_string={'query':'Costume 1199'}).get_json()
        assert found['total'] == 1 and found['items'][0]['name'] == 'Costume 1199 PlMsNr.dat'
        assert client.get(route, query_string={'query':'Fox'}).get_json()['total'] == 403
        files = client.get(route, query_string={'kind':'files','query':'1199'}).get_json()
        assert files['items'][0]['name'] == 'files/1199.dat'
        assert client.get(route, query_string={'offset':-1}).status_code == 400
        assert client.get(route.replace(run.chat_id, 'a' * 32)).status_code == 409
        live_runs.decide_approval(run.chat_id, approval['id'], 'deny')
        list(live_runs.stream(run))
    finally:
        live_runs.cancel(run.id)


def test_direct_all_variants_review_preserves_card_scope(catalog, vault, monkeypatch):
    from randall.assistant import engine, live_runs
    post, _ = catalog
    add_variants(post)
    # Building the approval DOES fetch each offered scope into quarantine,
    # so the card can state what the object is. Nothing is imported.
    fetched = []
    monkeypatch.setattr(website, '_download', _downloader(log=fetched))
    monkeypatch.setattr(website, '_import_archive',
                        lambda *a, **k: pytest.fail('Review must not import'))
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert card['default_file_id'] == 51 and card['variant_count'] == 3
    run = engine.start_download(None, 123)
    try:
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested': break
        approval = event['tool']['approval']
        assert approval['default_choice'] == 'all'
        assert live_runs.download_files(run.chat_id, approval['id'], choice='all')['total'] == 3
        assert live_runs.download_files(run.chat_id, approval['id'], choice='default')['total'] == 1
        live_runs.decide_approval(run.chat_id, approval['id'], 'deny')
        list(live_runs.stream(run))
    finally:
        live_runs.cancel(run.id)


def test_unknown_future_file_types_are_still_not_offered_for_download(catalog):
    post, _ = catalog
    post['files'][0]['file_type'] = 'unknown_future_type'
    post['zip_url'] = None
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert not card['can_download'] and not card['files'][0]['can_download']
    with pytest.raises(ValueError, match='individual costume/stage export'):
        website.prepare_download({'post_id': 123, 'file_id': 42})


class _JsonResponse(Response):
    def __init__(self, status=200, body=None):
        super().__init__(status)
        self.body = body
    def json(self):
        if self.body is None:
            raise json.JSONDecodeError('no body', '', 0)
        return self.body


@pytest.mark.parametrize('reply,match', [
    (_JsonResponse(404, {'error': {'code': 'not_found', 'message': 'Mod not found'}}), 'no longer publicly available'),
    (_JsonResponse(400, {'error': {'code': 'invalid_parameter', 'message': 'limit must be an integer'}}),
     'refused that request: limit must be an integer'),
    (_JsonResponse(503, {'error': {'code': 'unavailable'}}), 'unavailable'),
    (_JsonResponse(302), 'unavailable'),
    (_JsonResponse(200), 'Could not reach'),
])
def test_the_public_api_transport_maps_every_answer(monkeypatch, reply, match):
    seen = []
    def get(url, **kwargs):
        seen.append((url, kwargs))
        return reply
    monkeypatch.setattr(website_posts, '_api', website_site.REAL_API)
    monkeypatch.setattr(website_posts.requests, 'get', get)
    with pytest.raises(ValueError, match=match):
        website_posts._post(123)
    url, kwargs = seen[0]
    assert url == 'https://ssbmnucleus.net/api/public/v1/mods/123'
    assert kwargs['allow_redirects'] is False
    assert kwargs['headers']['User-Agent'].startswith('SSBM-Nucleus/')
    assert kwargs['headers']['User-Agent'].endswith('(Randall; +https://ssbmnucleus.net)')


def test_the_public_api_transport_sends_the_search_as_query_parameters(monkeypatch):
    seen = []
    def get(url, **kwargs):
        seen.append((url, kwargs))
        return _JsonResponse(200, {'data': [], 'total': 0, 'next_cursor': None})
    monkeypatch.setattr(website_posts, '_api', website_site.REAL_API)
    monkeypatch.setattr(website_posts.requests, 'get', get)
    website_search.search_website_mods('widescreen', tags=['Stage Skin'], limit=2)
    url, kwargs = seen[0]
    assert url == 'https://ssbmnucleus.net/api/public/v1/mods'
    assert kwargs['params'] == {'limit': 2, 'sort': 'newest', 'order': 'desc',
                                'q': 'widescreen', 'tags': 'Stage Skin'}
