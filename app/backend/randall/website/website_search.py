"""Searching the website: validated filters, one page of cards, and the weaker searches an empty
result falls back to (abbreviations spelled out, stop words dropped, one constraint relaxed)."""

import re

from .website_posts import _card, _query


PAGE_SIZE = 6
CATEGORIES = ('Character Costume', 'Stage Skin', 'Effects', 'Assets/Other',
              'Custom Stage', 'Gameplay Mod', 'Patch')
SORT_FIELDS = ('created_at', 'download_count', 'like_count')
FALLBACK_LIMIT = 4
QUERY_LIMIT = 200   # The website's `q` takes at most 200 characters.
# The website's page cursor is opaque base64url text; it is passed back as given.
CURSOR = re.compile(r'[A-Za-z0-9_=-]{1,512}')
# Words that carry no meaning to the website's title/description/tag match.
STOP_WORDS = frozenset(('a', 'an', 'and', 'any', 'find', 'for', 'i', 'in', 'me', 'mod', 'mods',
                        'my', 'of', 'on', 'or', 'please', 'some', 'the', 'to', 'with'))
# Abbreviations players say out loud; website titles usually spell them out instead.
ABBREVIATIONS = {'css': 'character select screen', 'sss': 'stage select screen',
                 'csp': 'character select portrait', 'hud': 'heads up display',
                 'bgm': 'background music', 'sfx': 'sound effect', 'ui': 'user interface'}


def _results(posts, total, filters, next_cursor):
    return {'website_mods': [_card(p) for p in posts], 'website_total': total,
            'filters': filters, 'next_cursor': next_cursor,
            'note': 'Public ssbmnucleus.net results. Inspect a mod to see its files; downloads require approval.'}


def _expand(text):
    """The same phrase with every known abbreviation spelled out, or None."""
    words = text.split()
    swapped = [ABBREVIATIONS.get(word.strip('.,!?').casefold(), word) for word in words]
    return ' '.join(swapped) if swapped != words else None


def _fallbacks(query, tags, character, author):
    """Weaker searches to try after an empty one, most faithful first.

    Deterministic and capped: drop the strict filters but keep their words as
    free text, spell out abbreviations, then shorten the phrase from the end
    and finally try single words. Never repeats the search that just failed.
    """
    candidates, seen = [], set()
    filtered = bool(tags or character.strip() or author.strip())

    def add(text, label):
        text = ' '.join(str(text).split())
        # The website's text search takes at most QUERY_LIMIT characters.
        if text and len(text) <= QUERY_LIMIT and text.casefold() not in seen:
            seen.add(text.casefold())
            candidates.append({'query': text, 'label': label})

    words = ' '.join([query.strip(), *tags, character.strip()]).split()
    relaxed = ' '.join(words)
    if not filtered:
        seen.add(relaxed.casefold())  # Never repeat a free-text search that just came back empty.
    if filtered:
        add(relaxed, f"the words '{relaxed}' as text")
    expanded = _expand(relaxed)
    if expanded:
        add(expanded, f"'{expanded}', with the abbreviation spelled out")
    kept = [word for word in (re.sub(r"[^A-Za-z0-9'&.-]", '', w) for w in words)
            if word and word.casefold() not in STOP_WORDS]
    # An abbreviation spelled out is the most specific thing left to try.
    for word in kept:
        spelled = ABBREVIATIONS.get(word.casefold())
        if spelled:
            add(spelled, f"'{spelled}' ({word.upper()} spelled out)")
    for end in range(len(kept) - 1, 1, -1):
        add(' '.join(kept[:end]), f"the words '{' '.join(kept[:end])}'")
    for word in kept:  # Dedupe keeps this from repeating a single-word search that just failed.
        add(word, f"the single word '{word}'")
    return candidates[:FALLBACK_LIMIT]


def _empty_clause(query, tags, character, author):
    parts = []
    if len(tags) == 2:
        parts.append(f'carries both tags {tags[0]} and {tags[1]}')
    elif len(tags) > 2:
        parts.append('carries all the tags ' + ', '.join(tags))
    elif tags:
        parts.append(f'carries the tag {tags[0]}')
    if character.strip():
        parts.append(f'is filed under the character {character.strip()}')
    if author.strip():
        parts.append(f'is by {author.strip()}')
    if query.strip():
        parts.append(f"matches the words '{query.strip()}'")
    return 'No mod ' + ' and '.join(parts) if parts else 'That search found nothing'


def _held(tags, character, author):
    """A phrase naming the constraints still in force, or ''."""
    parts = []
    if tags:
        parts.append('tagged ' + ' and '.join(tags))
    if character.strip():
        parts.append(f'filed under {character.strip()}')
    if author.strip():
        parts.append(f'by {author.strip()}')
    return ' and '.join(parts)


def _relaxations(candidate, tags, character, author):
    """Each relaxation of one candidate, most faithful first.

    Every fallback used to clear the tags, the category (which IS a tag), the
    character and the author in one step, so `halo sss` could come back as the
    generic `stage select screen` and an approved publisher targeting those
    words could occupy the results without any Halo content (2026-09-22
    security review, 7). Each of those is a constraint the user typed, so they
    are given up one group at a time, each step labelled with what it gave up:
    the tags and category first, then the character and author, then nothing.
    """
    steps = []
    remaining = [(list(tags), character, author),
                 ([], character, author),
                 ([], '', '')]
    seen = set()
    for keep_tags, keep_character, keep_author in remaining:
        marker = (tuple(keep_tags), keep_character.strip(), keep_author.strip())
        if marker in seen:
            continue
        seen.add(marker)
        dropped = []
        if tags and not keep_tags:
            dropped.append('tag')
        if character.strip() and not keep_character.strip():
            dropped.append('character')
        if author.strip() and not keep_author.strip():
            dropped.append('author')
        held = _held(keep_tags, keep_character, keep_author)
        label = candidate['label']
        if held:
            label += f', still {held}'
        if dropped:
            label += ', with the ' + ' and '.join(dropped) + ' filter dropped'
        steps.append({'query': candidate['query'], 'tags': keep_tags,
                      'character': keep_character, 'author': keep_author,
                      'label': label, 'dropped': dropped})
    return steps


def _fallback_search(query, tags, character, author, filters, limit):
    """Run the weaker searches for an empty result and report what they found."""
    tried, hit = [], None
    # The search that just failed is part of the record, not a silent premise.
    tried.append({'filters': {'query': filters['query'], 'tags': list(filters['tags']),
                              'character': filters['character'], 'author': filters['author']},
                  'total': 0, 'original': True})
    for candidate in _fallbacks(query, tags, character, author):
        for attempt in _relaxations(candidate, tags, character, author):
            alternate = dict(filters, query=attempt['query'], tags=list(attempt['tags']),
                             character=attempt['character'], author=attempt['author'])
            posts, total, following = _query(alternate, None, limit)
            tried.append({'filters': {'query': attempt['query'], 'tags': list(attempt['tags']),
                                      'character': attempt['character'],
                                      'author': attempt['author']},
                          'dropped': attempt['dropped'], 'total': total})
            if total:
                hit = (attempt, alternate, posts, total, following)
                break
        if hit:
            break
    if len(tried) == 1:
        return None
    clause = _empty_clause(query, tags, character, author)
    if hit:
        attempt, alternate, posts, total, following = hit
        result = _results(posts, total, alternate, following)
        plural = 'mods match' if total != 1 else 'mod matches'
        result['note'] = f'{clause}; {total} {plural} {attempt["label"]}, shown below.'
        # These are alternatives to what was asked for, and every card says so,
        # because the note alone is only rendered on an empty result.
        result['relaxed'] = {'matched': attempt['label'], 'dropped_filters': attempt['dropped'],
                             'requested': filters}
        for card in result['website_mods']:
            card['alternative_match'] = attempt['label']
        result['note'] += (' These are broader alternatives, not matches for '
                           'what you asked for.')
    else:
        result = _results([], 0, filters, None)
        searched = ', '.join(f"'{attempt['filters']['query']}'"
                             for attempt in tried[1:])
        result['note'] = f'{clause}; searching {searched} found nothing either.'
        result['relaxed'] = {'matched': None, 'dropped_filters': [], 'requested': filters}
    result['tried'] = tried
    result['original_filters'] = filters
    return result


def search_website_mods(query='', character='', cursor=None, category='', tags=None,
                        exclude_tags=None, author='', sort_by='created_at',
                        sort_order='desc', limit=PAGE_SIZE):
    for name, value in [('query', query), ('character', character), ('author', author)]:
        if not isinstance(value, str) or len(value) > 160:
            raise ValueError(f'{name} must be text of at most 160 characters.')
    if cursor is not None and (not isinstance(cursor, str) or not CURSOR.fullmatch(cursor)):
        raise ValueError('cursor must be the next_cursor text from the previous page of the same search.')
    if type(limit) is not int or not 1 <= limit <= 24:
        raise ValueError('limit must be an integer from 1 to 24; use next_cursor for more results.')
    if category not in ('', *CATEGORIES):
        raise ValueError('Unknown website category. Use a category from the tool schema.')
    if sort_by not in SORT_FIELDS or sort_order not in ('asc', 'desc'):
        raise ValueError('Sort by created_at, download_count or like_count, in asc or desc order.')
    def tag_list(values):
        if values is None:
            return []
        if (not isinstance(values, list) or len(values) > 20
                or any(not isinstance(v, str) or not v.strip() or len(v) > 80 for v in values)):
            raise ValueError('Tags must be a list of up to 20 nonempty tag names, each at most 80 characters.')
        if any(',' in v for v in values):
            # The website takes a comma-separated tag list; a comma would split one tag in two.
            raise ValueError('Tag names cannot contain commas.')
        return list(dict.fromkeys(v.strip() for v in values))
    included, excluded = tag_list(tags), tag_list(exclude_tags)
    if category and category not in included:
        included.append(category)
    if set(t.casefold() for t in included) & set(t.casefold() for t in excluded):
        raise ValueError('A tag cannot be both included and excluded.')
    filters = {'query': query.strip(), 'character': character.strip(), 'author': author.strip(),
               'tags': included, 'exclude_tags': excluded, 'sort_by': sort_by,
               'sort_order': sort_order, 'limit': limit}
    posts, total, following = _query(filters, cursor, limit)
    if not total and not cursor:
        # An empty page is never a dead end: try the obvious weaker searches here,
        # so the reply shows mods instead of asking the user to guess again.
        fallback = _fallback_search(query, included, character, author, filters, limit)
        if fallback:
            return fallback
    return _results(posts, total, filters, following)
