"""A fake of the website's public mods API (`/api/public/v1`) for Randall's website tests.

Mods are written in the API's own shape (`author`, `screenshots` as URLs,
`zip_url`, `archive_files`, ...). The fake fills each mod's and each listed
file's counted `download_url` the way the real API does, unless a test set one
itself (None included), and answers 404 -- `NOT_PUBLIC` -- for a mod that is
not in the catalog or is marked `hidden`. Like the real API it fills the credit
(`creator` = `author`, `original_source` = None) unless a test set it; with
`Site.legacy` it plays a site from before that change, refusing `?creator=`.
"""
import copy
import re

from randall.website import website_posts

API = website_posts.API
# The real transport, kept before conftest's autouse fixture replaces it in each test.
REAL_API = website_posts._api
MEDIA = website_posts.MEDIA


def media(path):
    """An absolute media-host URL, as every API URL field is."""
    return f'{MEDIA}/{path.lstrip("/")}'


def counted(post_id, file_id=None):
    return f'{API}/mods/{post_id}/download' + (f'?file={file_id}' if file_id is not None else '')


def published(post, legacy=False):
    """The mod as the API would serve it right now."""
    mod = copy.deepcopy(post)
    mod.pop('hidden', None)
    if legacy:
        # Before the site's creator migration: no credit fields at all.
        mod.pop('creator', None)
        mod.pop('original_source', None)
    else:
        # The credit, as the real API fills it: creator = author unless a
        # re-upload names its original creator.
        mod.setdefault('creator', mod.get('author'))
        mod.setdefault('original_source', None)
    mod.setdefault('download_url', counted(mod['id']) if mod.get('zip_url') else None)
    for file in mod.get('files') or []:
        file.setdefault('download_url', counted(mod['id'], file['id'])
                        if file.get('file_url') else None)
    return mod


class Site:
    """The catalog the fake serves, and every request it was sent."""

    def __init__(self, posts=(), total=None):
        self.posts = {post['id']: post for post in posts}
        self.total = total
        self.calls = []          # (path, params) of every request
        self.search = None       # optional callable(params) -> (mods, total, next_cursor)
        self.legacy = False      # True: a site from before ?creator= and the credit fields

    def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path == '/mods':
            if self.legacy and 'creator' in (params or {}):
                # What website_posts._api raises for the API's 400.
                raise ValueError('The mod website refused that request: Unknown parameter "creator". '
                                 'Allowed: cursor, limit, type, character, stage, updated_since, q, '
                                 'tags, exclude_tags, author, sort, order.')
            if self.search is not None:
                mods, total, following = self.search(dict(params or {}))
            else:
                mods = [post for post in self.posts.values() if not post.get('hidden')]
                total, following = self.total if self.total is not None else len(mods), None
            return {'data': [published(mod, self.legacy) for mod in mods][:params['limit']],
                    'total': total, 'next_cursor': following}
        match = re.fullmatch(r'/mods/(\d+)', path)
        assert match, f'unexpected API route {path}'
        post = self.posts.get(int(match.group(1)))
        if post is None or post.get('hidden'):
            raise ValueError(website_posts.NOT_PUBLIC)
        return {'data': published(post, self.legacy)}

    def searches(self):
        return [params for path, params in self.calls if path == '/mods']

    def fetched(self):
        return [path for path, _ in self.calls if path != '/mods']


def install(monkeypatch, *posts, total=None):
    """Serve `posts` through the public API for the rest of the test."""
    site = Site(posts, total)
    monkeypatch.setattr(website_posts, '_api', site)
    return site
