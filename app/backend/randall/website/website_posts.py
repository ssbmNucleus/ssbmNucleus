"""The site's posts: the public mods API and the account RPCs, the rules for untrusted publisher
text, ids and media URLs, fetching one public mod and shaping its card, inspecting a mod, and
account likes."""

import json
import re
import threading
from urllib.parse import urlsplit

import requests

from .website_exports import any_mod_download_enabled, _default_variant, _downloadable


SITE = 'https://ssbmnucleus.net'
MEDIA = 'https://media.ssbmnucleus.net'
# The site's public, read-only mods API (meleeWebsite docs/public-api.md).
# Search, a mod's detail and its counted downloads come from here; only the
# signed-in like routes and the effect-type list still use `_rpc`.
API = f'{SITE}/api/public/v1'
NOT_PUBLIC = 'This mod is no longer publicly available on the website.'


# Publisher-controlled text (titles, descriptions, filenames, tag names,
# manifest entries) reaches the model through tool results. It is labelled
# untrusted in the prompt, but it must also be inert: invisible control
# characters, bidi overrides and zero-width joiners are how a description
# smuggles a line that reads like an instruction past a human reader.
_INERT = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]')


def _text(value, limit):
    """One field of untrusted publisher text: stripped, inert, length-capped."""
    return _INERT.sub('', str(value or '')).strip()[:limit]


def user_agent():
    """Who is asking, as the public API's etiquette requests."""
    try:
        from randall.reports.wish_keys import safe_app_version
        version = safe_app_version()
    except Exception:  # noqa: BLE001 - a header must never fail a request
        version = 'unknown'
    return f'SSBM-Nucleus/{version} (Randall; +{SITE})'


def _api(path, params=None):
    """GET one public mods API route and return its JSON. A 404 means not public."""
    try:
        with requests.get(f'{API}{path}', params=params or None,
                          headers={'User-Agent': user_agent(), 'Accept': 'application/json'},
                          timeout=(10, 30), allow_redirects=False) as response:
            if response.status_code == 404:
                raise ValueError(NOT_PUBLIC)
            if response.status_code == 400:
                try:
                    detail = _text((response.json().get('error') or {}).get('message'), 200)
                except (ValueError, AttributeError):
                    detail = ''
                raise ValueError('The mod website refused that request'
                                 + (f': {detail}.' if detail else '.'))
            if response.status_code != 200:
                raise ValueError('The mod website is unavailable. Please try again later.')
            return response.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        raise ValueError('Could not reach the mod website. Please try again.') from exc


def _rpc(name, args, account_token=None):
    """The site's Supabase RPCs: account likes and the effect-type list only."""
    # Reuse the desktop publisher's public project configuration, never a user key.
    from core.config import SUPABASE_URL, SUPABASE_ANON_KEY
    try:
        with requests.post(f'{SUPABASE_URL}/rest/v1/rpc/{name}', json=args,
                           headers={'apikey': SUPABASE_ANON_KEY,
                                    'Authorization': f'Bearer {account_token or SUPABASE_ANON_KEY}'},
                           timeout=(10, 30), allow_redirects=False) as response:
            if response.status_code in (401, 403) and account_token:
                raise ValueError('Your Nucleus account session expired. Sign in again to like mods.')
            if response.status_code != 200:
                raise ValueError('The mod website is unavailable. Please try again later.')
            return response.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        raise ValueError('Could not reach the mod website. Please try again.') from exc


def _id(value, name):
    if type(value) is not int or not 0 < value < 2 ** 31:
        raise ValueError(f'{name} must be an exact positive website ID.')
    return value


def _media(value):
    """A URL on the media host, exactly as the API published it, or None."""
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != 'media.ssbmnucleus.net'
            or '\\' in value or any(ord(c) < 32 for c in value)):
        return None
    return value


def counted_download(record, post_id, file_id=None):
    """The API's counted download link for a mod (or one of its files), or None.

    Fetching it credits the creator, and it answers with one redirect to the
    media host. Only the exact link the API documents for THIS mod and file is
    accepted, never another route or host a record might name.
    """
    value = (record or {}).get('download_url')
    expected = f'{API}/mods/{post_id}/download' + (f'?file={file_id}' if file_id is not None else '')
    return value if isinstance(value, str) and value == expected else None


def _post(post_id):
    """One public mod from the API; a mod that is not public answers 404."""
    body = _api(f"/mods/{_id(post_id, 'post_id')}")
    post = body.get('data') if isinstance(body, dict) else None
    if not isinstance(post, dict) or post.get('id') != post_id:
        raise ValueError(NOT_PUBLIC)
    return post


def archive_files(post):
    """Every file in the mod's zip, as the API's detail lists them."""
    rows = post.get('archive_files')
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get('filename')]


def credit(post):
    """Who made a mod and how it reached the site: (creator, author, credit line).

    `author` is the account that uploaded it. Most older mods were re-uploaded
    in bulk from SSBM Textures by the "SSBM Textures" account; for those the
    API's `creator` names the original creator (meleeWebsite docs/public-api.md,
    "Credit"), so the line reads "mcromich (via SSBM Textures)". A site that
    predates the field sends no `creator`, which reads as the uploader.
    """
    author = _text(post.get('author'), 100) or 'Unknown author'
    creator = _text(post.get('creator'), 100) or author
    line = creator if creator.casefold() == author.casefold() else f'{creator} (via {author})'
    return creator, author, line


def _card(post, details=False):
    files = post.get('files') or []
    screenshots = [url for url in post.get('screenshots') or [] if isinstance(url, str)]
    candidates = [post.get('thumbnail_url'), *screenshots,
                  *(f.get('csp_url') for f in files)]
    creator, author, credit_line = credit(post)
    card = {'post_id': post['id'], 'title': _text(post.get('title') or 'Untitled mod', 200),
            # Credit the creator; `author` is only the uploading account.
            'creator': creator, 'author': author, 'credit': credit_line,
            'url': f"{SITE}/post/{post['id']}",
            'image': next((url for p in candidates if (url := _media(p))), None),
            'tags': [_text(t, 80) for t in (post.get('tags') or [])[:12]],
            'file_count': len(files),
            'can_download': bool(any_mod_download_enabled() and counted_download(post, post['id']))
                or any(_downloadable(file) for file in files)}
    for field in ('download_count', 'like_count', 'created_at'):
        if post.get(field) is not None:
            card[field] = post[field]
    if isinstance(post.get('original_source'), str) and post['original_source'].strip():
        # Where it was first posted, e.g. "SSBM Textures".
        card['original_source'] = _text(post['original_source'], 60)
    gallery = [_media(url) for url in screenshots]
    card['images'] = list(dict.fromkeys(url for url in gallery if url))[:12]
    if not card['images'] and card['image']:
        card['images'] = [card['image']]
    variants = [{'file_id': f.get('id'), 'name': f.get('filename') or '',
                 'type': f.get('file_type')} for f in files]
    default = _default_variant(variants) if len(variants) <= 60 else None
    card['default_file_id'] = default['file_id'] if default else None
    card['variant_count'] = len(variants) if default else 0
    if details:
        card['description'] = _text(post.get('description'), 1600)
        # Everything in this card came from a public post. It is material to
        # show the user and to reason about -- never an instruction to follow.
        card['content_is_untrusted'] = True
        card['files'] = [{'file_id': f['id'], 'name': _text(f.get('filename') or 'File', 160),
                          'character': f.get('character'), 'color': f.get('color'),
                          'type': f.get('file_type'), 'image': _media(f.get('csp_url') or f.get('preview_url')),
                          'can_download': _downloadable(f)}
                         for f in files[:60]]
        card['files_truncated'] = len(files) > 60
        card['archive_entries'] = [_text(row['filename'], 200) for row in archive_files(post)[:60]]
    from .vault_presence import recover_history, vault_status
    recover_history()
    card['in_vault'] = vault_status([post['id']])[str(post['id'])]
    return card


# The tool's sort names, as the public API spells them.
API_SORTS = {'created_at': 'newest', 'download_count': 'downloads', 'like_count': 'likes'}


def query_params(filters, cursor, limit):
    """The `/mods` query for one page of a search. Empty filters are left out:
    the API refuses unknown or repeated parameters, and an empty one is noise.
    The tool's author filter means who made the mod, so it is the API's
    `creator` (the uploading account for everything but SSBM Textures
    re-uploads, where it is the original creator)."""
    params = {'limit': limit, 'sort': API_SORTS[filters['sort_by']], 'order': filters['sort_order']}
    for key, name in (('query', 'q'), ('character', 'character'), ('author', 'creator')):
        if filters[key]:
            params[name] = filters[key]
    for key in ('tags', 'exclude_tags'):
        if filters[key]:
            params[key] = ','.join(filters[key])
    if cursor:
        params['cursor'] = cursor
    return params


def _query(filters, cursor, limit):
    """One page of public mods: (mods, total, next_cursor)."""
    params = query_params(filters, cursor, limit)
    try:
        data = _api('/mods', params)
    except ValueError as exc:
        # A site from before ?creator= refuses it as an unknown parameter; its
        # closest filter is the uploading account.
        if 'creator' not in params or 'Unknown parameter "creator"' not in str(exc):
            raise
        params['author'] = params.pop('creator')
        data = _api('/mods', params)
    if not isinstance(data, dict):
        raise ValueError('The mod website is unavailable. Please try again later.')
    mods = [mod for mod in data.get('data') or [] if isinstance(mod, dict) and type(mod.get('id')) is int]
    following = data.get('next_cursor')
    total = data.get('total')
    return (mods[:limit], total if type(total) is int else len(mods),
            following if isinstance(following, str) and following else None)


def inspect_website_mod(post_id):
    return {'website_mods': [_card(_post(post_id), details=True)]}


def _account_token(token):
    if not isinstance(token, str) or not token.strip() or len(token) > 8192 or '\n' in token or '\r' in token:
        raise ValueError('Sign in to your Nucleus account to like mods.')
    return token


def website_like_status(post_id, account_token):
    return _rpc('api_like_status', {'p_post_id': _id(post_id, 'post_id')}, _account_token(account_token))


_like_lock = threading.Lock()


def set_website_mod_like(post_id, liked, account_token=None):
    token = _account_token(account_token)
    _id(post_id, 'post_id')
    if type(liked) is not bool:
        raise ValueError('liked must be true or false.')
    post = _post(post_id)   # Only a public mod can be liked from here.
    # Desired state makes retries safe; serialize app clicks and agent requests.
    # Never retry a failed toggle: its response may have been lost after commit.
    with _like_lock:
        state = website_like_status(post_id, token)
        if not isinstance(state, dict) or type(state.get('liked')) is not bool:
            raise ValueError('Could not check your like. Please try again.')
        if state['liked'] != liked:
            state = _rpc('api_toggle_like', {'p_post_id': post_id}, token)
    if not isinstance(state, dict) or state.get('liked') is not liked:
        raise ValueError('Could not confirm your like. Check the website before retrying.')
    post['like_count'] = state.get('like_count')
    return {'website_mods': [_card(post)], 'liked': liked, 'like_count': state.get('like_count')}
