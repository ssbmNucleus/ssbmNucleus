"""Search ssbmnucleus.net and download published mods into the workspace.

Downloads land in the workspace as plain files. Nothing here imports into the
vault.

Worked example - find a character-select screen mod, look at its screenshots,
download it and find out what it actually is::

    hits = website.search('character select screen background', limit=6)
    for card in hits['website_mods']:
        card['post_id'], card['title'], card['download_count'], card['can_download']
        for url in card['images']:                     # the mod's own screenshots
            website.download_image(url, f"out/shots/{card['post_id']}.png")
    # ... LOOK at those PNGs, then pick one ...

    post = website.inspect_post(16824)['website_mods'][0]
    post['description']; post['files']      # files carry file_id + name + type

    got  = website.download(16824, destination='out/css-mod.zip')
    got['path']                             # 'C:/.../out/css-mod.zip'
    menus.identify(got['path'])             # {'type': 'css_background', 'menu_type': 'css'}

Pass a file's ``file_id`` to download that one file instead of the whole mod.
Every published file type can be downloaded, including menu files the site
labels ``other``.
"""
import shutil
from pathlib import Path

from ._workspace import out_path

CATEGORIES = ('Character Costume', 'Stage Skin', 'Effects', 'Assets/Other',
              'Custom Stage', 'Gameplay Mod', 'Patch')


def search(query='', character='', category='', tags=None, limit=6, cursor=None,
           sort_by='created_at', sort_order='desc'):
    """Search published mods on the Nucleus website.

    An empty result automatically retries weaker searches (dropping filler
    words, expanding abbreviations like 'css' to 'character select screen',
    then tags alone), so you usually do not need to re-query by hand.

    Args:
        query: free text, e.g. 'css background'.
        character: fighter-name filter, e.g. 'Fox'.
        category: one of CATEGORIES, or '' for all.
        tags: list of tag names to require.
        limit: results per page, 1-24.
        cursor: the ``next_cursor`` of the previous page, with the same other
            arguments; None for the first page.
        sort_by: 'created_at', 'download_count' or 'like_count'.
        sort_order: 'asc' or 'desc'.

    Returns:
        dict: ``{'website_mods': [card, ...], 'website_total': int,
        'next_cursor': str|None, ...}``. Each card
        has ``post_id``, ``title``, ``author``, ``url``, ``tags``,
        ``download_count``, ``like_count``, ``file_count``, ``can_download``
        and ``default_file_id`` (a single-variant export, or None).

    Example:
        >>> from nucleus_api import website
        >>> hits = website.search('character select screen background', limit=5)
        >>> [m['title'] for m in hits['website_mods']]
        ['Halo 3 Matchmaking Lobby CSS', ...]
    """
    from randall.website.website_search import search_website_mods
    return search_website_mods(query=query, character=character, cursor=cursor, category=category,
                               tags=tags, sort_by=sort_by, sort_order=sort_order, limit=limit)


def inspect_post(post_id):
    """Full detail for one website mod: description, files, screenshots, tags.

    Args:
        post_id: integer ``post_id`` from :func:`search`.

    Returns:
        dict: ``{'website_mods': [card]}`` where the card also carries
        ``description``, ``files`` (each with ``file_id``, ``name``,
        ``character``, ``color``, ``can_download``) and ``archive_entries``.

    Example:
        >>> website.inspect_post(412)['website_mods'][0]['description'][:40]
    """
    from randall.website.website_posts import inspect_website_mod
    return inspect_website_mod(post_id)


def download(post_id, file_id=None, destination=None):
    """Download a website mod into the workspace (never into the vault).

    Args:
        post_id: integer ``post_id`` from :func:`search`.
        file_id: optional integer id of ONE file from :func:`inspect_post`
            (a single costume/stage export). Omit for the whole mod archive.
            Whole mods and non-export files download through the site's
            counted link, so the creator is credited.
        destination: workspace path for the downloaded file. Defaults to
            ``out/<post title>.zip``.

    Returns:
        dict: ``{'path': str, 'title': str, 'post_id': int, 'file_id': int|None,
        'size': int, 'url': str}``.

    Example:
        >>> website.download(412, destination='out/halo-css.zip')
        {'path': 'C:/.../workspace/out/halo-css.zip', 'title': 'Halo 3 ...', ...}
    """
    from randall.website.website import _plan, _download
    plan = _plan(post_id, file_id)
    title = plan['mod']['title']
    safe = ''.join(c if c.isalnum() or c in ' -_.' else '_' for c in title).strip() or f'mod-{post_id}'
    suffix = '.zip'
    if file_id is not None:
        name = (plan['mod'].get('selected_file') or {}).get('name') or ''
        suffix = Path(name).suffix or '.dat'
        safe = Path(name).stem or safe
    target = out_path(destination, default_name=f'{safe}{suffix}')
    _download(plan['url'], target)
    return {'path': str(target), 'title': title, 'post_id': post_id, 'file_id': file_id,
            'size': target.stat().st_size, 'url': plan['mod']['url']}


def download_image(url, destination=None):
    """Download one screenshot/preview image from the mod website's media host.

    Only ``https://media.ssbmnucleus.net`` URLs (the ``image``/``images`` fields
    on a search card) are accepted.

    Args:
        url: the image URL from a card.
        destination: workspace path. Defaults to ``out/<filename>``.

    Returns:
        str: absolute path of the image.

    Example:
        >>> card = website.search('halo 3 lobby')['website_mods'][0]
        >>> website.download_image(card['images'][0], 'out/shots/halo.png')
        'C:/.../workspace/out/shots/halo.png'
    """
    from urllib.parse import urlsplit
    from randall.website.website import _download
    from randall.website.website_posts import _media
    checked = _media(url)
    if not checked:
        raise ValueError('Only media.ssbmnucleus.net image URLs from a search card can be downloaded.')
    name = Path(urlsplit(checked).path).name or 'image.png'
    target = out_path(destination, default_name=name)
    _download(checked, target)
    return str(target)
