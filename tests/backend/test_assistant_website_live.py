"""Randall's website tools against the LIVE public mods API at ssbmnucleus.net.

Opt-in, read-only and uncounted: it searches, pages, inspects, and checks the
counted download link with a HEAD request (which the API redirects without
counting). Run it after a change to the API or to the website tools:

    NUCLEUS_LIVE_WEBSITE_TEST=1 pytest -o addopts= tests/backend/test_assistant_website_live.py
"""
import os

import pytest
import requests

from randall.website import website, website_posts, website_search
from tests.backend import website_site

pytestmark = pytest.mark.skipif(os.environ.get('NUCLEUS_LIVE_WEBSITE_TEST') != '1',
                                reason='set NUCLEUS_LIVE_WEBSITE_TEST=1 to call the live website')

# Final Destination Background CSS: one published `other` file (MnSlChr.dat).
KNOWN_MOD = 16824


@pytest.fixture(autouse=True)
def live_api(monkeypatch, vault):
    # `vault`: a card checks vault presence, which must read a temp vault, never the real one.
    monkeypatch.setattr(website_posts, '_api', website_site.REAL_API)


def test_search_finds_a_known_mod_and_pages_by_cursor():
    result = website_search.search_website_mods('Final Destination Background CSS')
    assert KNOWN_MOD in [card['post_id'] for card in result['website_mods']]
    first = website_search.search_website_mods('character select screen', limit=6)
    assert first['website_total'] > 6 and first['next_cursor']
    second = website_search.search_website_mods('character select screen', limit=6,
                                                cursor=first['next_cursor'])
    ids = [card['post_id'] for card in first['website_mods']]
    assert not set(ids) & {card['post_id'] for card in second['website_mods']}


def test_inspect_lists_files_and_the_archive():
    card = website_posts.inspect_website_mod(KNOWN_MOD)['website_mods'][0]
    assert card['title'] and card['author'] != 'Unknown author'
    assert card['files'][0]['file_id'] and card['archive_entries']
    assert card['images'] and all(url.startswith(website_posts.MEDIA + '/') for url in card['images'])


def test_a_mod_that_is_not_public_is_a_404():
    with pytest.raises(ValueError, match='publicly available'):
        website_posts._post(2 ** 31 - 1)


def test_the_counted_download_redirects_once_to_the_media_host():
    post = website_posts._post(KNOWN_MOD)
    url = website_posts.counted_download(post, KNOWN_MOD)
    assert url
    # HEAD: the API redirects without counting a download.
    response = requests.head(url, allow_redirects=False, timeout=30,
                             headers={'User-Agent': website_posts.user_agent()})
    assert response.status_code == 302
    assert website._redirect_target(response).startswith(website_posts.MEDIA + '/')
