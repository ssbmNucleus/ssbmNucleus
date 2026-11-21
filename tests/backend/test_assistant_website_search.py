"""An empty website search is never a dead end: the tool retries weaker searches.

The bug these cover (tester build, 2026-09-21): Randall searched tags
['css', 'background'] and the words 'sss background', got zero both times, and
told the owner there were no CSS or SSS background mods -- while the site has
them. The searching now happens inside the tool, so the reply carries cards.
"""
import pytest

from randall.website import website, website_posts, website_search


def queries(result):
    """The fallback searches actually run, after the original that failed."""
    assert result['tried'][0]['original'] and result['tried'][0]['total'] == 0
    return [attempt['filters']['query'] for attempt in result['tried'][1:]]


@pytest.fixture
def site(monkeypatch):
    """A fake public API: `totals` maps an exact search string to its result count."""
    totals, calls = {}, []

    def api(path, params=None):
        assert path == '/mods'
        calls.append(params)
        total = totals.get(params.get('q') or '', 0)
        tags = tuple(params['tags'].split(',')) if params.get('tags') else ()
        if tags or params.get('character') or params.get('creator'):
            total = totals.get(('tags', tags, params.get('character') or '',
                                params.get('creator') or ''), 0)
        mods = [{'id': 100 + i, 'title': f"{params.get('q')} #{i}",
                 'author': 'Artist', 'files': [], 'tags': []}
                for i in range(min(total, params['limit']))]
        return {'data': mods, 'total': total,
                'next_cursor': 'QDY' if total > params['limit'] else None}

    monkeypatch.setattr(website_posts, '_api', api)
    for _mod in (website, website_posts, website_search):
        monkeypatch.setattr(_mod, '_card', lambda post, details=False: {'post_id': post['id'],
                                                                          'title': post['title']})
    return totals, calls


def test_tag_filter_that_matches_nothing_falls_back_to_the_same_words_as_text(site):
    totals, calls = site
    totals['css background'] = 3
    result = website_search.search_website_mods(tags=['css', 'background'])
    assert result['website_total'] == 3 and len(result['website_mods']) == 3
    assert result['note'] == ("No mod carries both tags css and background; "
                              "3 mods match the words 'css background' as text, with the tag "
                              "filter dropped, shown below. These are broader alternatives, "
                              "not matches for what you asked for.")
    # The tagged search is tried first and named in `tried`; only when it comes
    # back empty are the tags given up, and the note says which filter went.
    assert queries(result) == ['css background', 'css background']
    assert result['tried'][1]['filters']['tags'] == ['css', 'background']
    assert result['tried'][2]['dropped'] == ['tag']
    # The relaxation is on the result and on every card, not only in the note:
    # the panel renders the note only when the result is empty, so a SUCCESSFUL
    # substitution used to hide the fact that it was one.
    assert result['relaxed']['dropped_filters'] == ['tag']
    assert result['relaxed']['requested']['tags'] == ['css', 'background']
    assert all(card['alternative_match'] for card in result['website_mods'])
    assert result['original_filters']['tags'] == ['css', 'background']
    assert result['filters']['tags'] == [] and result['filters']['query'] == 'css background'
    # 1 failed search + the tagged fallback + the tagless one that hit.
    assert len(calls) == 3
    assert calls[1]['tags'] == 'css,background' and 'tags' not in calls[2]


def test_constraints_are_given_up_one_group_at_a_time(site):
    """Tags/category first, then character and author, each step labelled.

    Clearing all of them on every fallback is how `halo sss` could become the
    generic `stage select screen` and hand the results to whoever targets
    those words.
    """
    totals, calls = site
    totals[('tags', ('rare',), 'Fox', '')] = 0   # the faithful search finds nothing
    totals[('tags', (), 'Fox', '')] = 2          # the character alone still does
    result = website_search.search_website_mods('hat', character='Fox', tags=['rare'])
    assert result['website_total'] == 2
    assert result['filters']['character'] == 'Fox' and result['filters']['tags'] == []
    assert result['relaxed']['dropped_filters'] == ['tag']
    assert 'still filed under Fox' in result['note']
    # The first fallback kept BOTH the tag and the character.
    assert calls[1]['tags'] == 'rare' and calls[1]['character'] == 'Fox'
    assert 'tags' not in calls[2] and calls[2]['character'] == 'Fox'


def test_the_character_is_only_dropped_after_the_tagless_search_fails(site):
    totals, _ = site
    totals['hat rare Fox'] = 1     # only free text, no filters at all, finds it
    result = website_search.search_website_mods('hat', character='Fox', tags=['rare'])
    assert result['website_total'] == 1
    assert result['relaxed']['dropped_filters'] == ['tag', 'character']
    assert 'with the tag and character filter dropped' in result['note']


def test_dropping_the_character_and_author_is_labelled_explicitly(site):
    totals, _ = site
    totals['hat Fox'] = 1
    result = website_search.search_website_mods('hat', character='Fox', author='Artist')
    assert result['website_total'] == 1
    assert result['relaxed']['dropped_filters'] == ['character', 'author']
    assert ('1 mod matches the words \'hat Fox\' as text, with the character and author '
            'filter dropped, shown below.') in result['note']
    assert result['tried'][1]['filters']['character'] == 'Fox'   # tried faithfully first
    assert result['tried'][1]['dropped'] == []


def test_abbreviation_is_spelled_out_for_the_phrase_then_on_its_own(site):
    totals, calls = site
    totals['stage select screen'] = 30
    result = website_search.search_website_mods('sss background')
    assert result['website_total'] == 30
    assert result['note'].startswith("No mod matches the words 'sss background'; 30 mods match "
                                     "'stage select screen' (SSS spelled out), shown below.")
    assert queries(result) == ['stage select screen background', 'stage select screen']
    assert len(calls) == 3


def test_whole_phrase_expansion_wins_when_the_site_has_it(site):
    totals, _ = site
    totals['character select screen background'] = 2
    result = website_search.search_website_mods('css background')
    assert result['website_total'] == 2
    assert result['note'].startswith("No mod matches the words 'css background'; 2 mods match "
                                     "'character select screen background', with the abbreviation "
                                     "spelled out, shown below.")


def test_a_long_phrase_is_shortened_from_the_end_before_single_words(site):
    totals, _ = site
    totals['stage select screen'] = 30
    result = website_search.search_website_mods('stage select screen background')
    assert queries(result) == ['stage select screen']
    assert result['website_total'] == 30
    assert "30 mods match the words 'stage select screen', shown below." in result['note']


def test_single_words_are_tried_last_and_stop_words_are_skipped(site):
    totals, _ = site
    totals['marth'] = 7
    result = website_search.search_website_mods('a mod for marth')
    assert queries(result) == ['marth']
    assert result['website_total'] == 7 and result['filters']['query'] == 'marth'


def test_everything_empty_reports_what_was_searched_without_pretending(site):
    _, calls = site
    result = website_search.search_website_mods('zzz qqq')
    assert result['website_total'] == 0 and result['website_mods'] == []
    assert result['note'] == ("No mod matches the words 'zzz qqq'; searching 'zzz', 'qqq' "
                              "found nothing either.")
    assert result['filters']['query'] == 'zzz qqq'  # The user's own search is what we report on.
    assert len(calls) == 3


def test_the_failed_search_is_never_repeated_as_its_own_fallback(site):
    _, calls = site
    website_search.search_website_mods('widescreen')
    assert [call['q'] for call in calls] == ['widescreen']  # Nothing weaker to try.
    calls.clear()
    website_search.search_website_mods('css')
    assert [call['q'] for call in calls] == ['css', 'character select screen']


def test_a_search_that_finds_something_never_falls_back(site):
    totals, calls = site
    totals['css background'] = 3
    result = website_search.search_website_mods('css background')
    assert result['website_total'] == 3 and 'tried' not in result
    assert result['note'].startswith('Public ssbmnucleus.net results')
    assert len(calls) == 1


def test_fallbacks_are_capped_and_never_run_for_a_later_page(site):
    totals, calls = site
    website_search.search_website_mods('one two three four five six')
    assert len(calls) == 1 + website_search.FALLBACK_LIMIT == 5
    calls.clear()
    totals[('tags', ('css', 'background'), '', '')] = 3
    website_search.search_website_mods(tags=['css', 'background'], cursor='QDY')
    assert len(calls) == 1  # Paging past the end of a real result set is not an empty search.
    assert calls[0]['cursor'] == 'QDY'


def test_a_fallback_longer_than_the_website_takes_is_not_sent(site):
    """The website's text search takes at most 200 characters; a relaxed search
    that joins the words and every tag can be longer, and would be refused."""
    _, calls = site
    tags = [f'tag{i:02}' + 'x' * 70 for i in range(3)]
    website_search.search_website_mods('hat', tags=tags)
    assert all(len(call.get('q') or '') <= website_search.QUERY_LIMIT for call in calls)


def test_a_page_carries_the_cursor_for_the_next(site):
    totals, _ = site
    totals['marth'] = 30
    result = website_search.search_website_mods('marth')
    assert result['next_cursor'] == 'QDY' and 'next_offset' not in result
