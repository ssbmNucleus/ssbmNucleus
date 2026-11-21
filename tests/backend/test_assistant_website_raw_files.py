"""Finding 3: a raw published file reaches a working importer, for real.

The test this replaces mocked the safety inspection AND the importer and fed
them `b'menu'`, so it asserted a fabricated `type='menu_mod'` / `type='codes'`
response and proved nothing. Nothing is mocked here except the website RPC and
the network fetch: the real `normalized_upload` wraps the bytes, the real
`website_safety.inspect_archive` preflights them, and the real
`_import_single_archive` cascade classifies and dispatches them.

The character-select fixture is a genuine HAL DAT header carrying the
`MnSelectChrDataTable` root symbol -- the same thing that makes the real
4 MB `MnSlChr.usd` a character-select screen, which is how a file published as
`Halo3CSS.dat` is recognised whatever it is called. It is built here rather
than committed so no vanilla-derived bytes enter the repo.
"""
import json
import struct

import pytest

from randall.assistant import approvals, tools
from randall.website import website, website_posts
from tests.backend import website_site
from tests.backend.website_site import media
from vault.importing.unified.detection import dat_root_symbols, detect_content_type
from vault.importing.unified.normalize import (
    GECKO_REFUSAL, describe_import_target, normalized_upload, safe_member_name, sniff_format)


def menu_dat(symbol=b'MnSelectChrDataTable', payload_size=0x40):
    """A header-valid HAL DAT whose single root symbol is `symbol`.

    Layout: 0x20 header, data block, relocation table (empty), root table,
    then the symbol string pool -- exactly what `dat_root_symbols` walks.
    """
    data_size = payload_size
    root_count, ref_count, reloc_count = 1, 0, 0
    root_off = 0x20 + data_size
    str_off = root_off + (root_count + ref_count) * 8
    strings = symbol + b'\x00'
    file_size = str_off + len(strings)
    header = struct.pack('>5I', file_size, data_size, reloc_count, root_count, ref_count)
    header += b'\x00' * (0x20 - len(header))
    return header + b'\x00' * data_size + struct.pack('>II', 0, 0) + strings


CODES_INI = (b'[Gecko]\r\n'
             b'$Disable Hardcoded CSS Animations [Author]\r\n'
             b'04043D6C 60000000\r\n')


def test_the_menu_dat_fixture_is_really_a_character_select_screen():
    assert dat_root_symbols(menu_dat()) == ['MnSelectChrDataTable']


def _default_download(url, path, **kwargs):
    from pathlib import Path
    Path(path).write_bytes(menu_dat())


@pytest.fixture
def post(monkeypatch, vault):
    record = {'id': 123, 'title': 'Halo 3 Matchmaking Lobby',
              'author': 'Artist', 'description': 'A CSS', 'tags': [],
              'updated_at': 'v1', 'zip_url': None, 'screenshots': [],
              'files': [{'id': 42, 'filename': 'Halo3CSS.dat', 'file_type': 'other',
                         'character': None, 'color': None,
                         'file_url': media('posts/123/Halo3CSS.dat')}]}
    website_site.install(monkeypatch, record)
    # An approval is prepared by fetching into quarantine, so a download
    # that produces a real archive is the baseline for every case here.
    monkeypatch.setattr(website, '_download', _default_download)
    return record


# ── the normalizer itself ──────────────────────────────────────────────────

def test_format_is_decided_by_magic_bytes_not_the_extension(tmp_path):
    lying = tmp_path / 'costume.zip'
    lying.write_bytes(menu_dat())
    assert sniff_format(lying) == 'raw'
    honest = tmp_path / 'thing.dat'
    honest.write_bytes(b'PK\x03\x04rest')
    assert sniff_format(honest) == 'zip'


@pytest.mark.parametrize('given,expected', [
    ('Halo3CSS.dat', 'Halo3CSS.dat'),
    ('folder/Halo3CSS.dat', 'Halo3CSS.dat'),
    ('../../Halo3CSS.dat', 'Halo3CSS.dat'),
    ('C:\\Windows\\evil.dat', 'evil.dat'),
    ('CON.dat', 'mod.dat'),
    ('', 'mod.dat'),
])
def test_the_published_filename_is_preserved_but_sanitized(given, expected):
    assert safe_member_name(given) == expected


def test_a_raw_dat_is_wrapped_under_its_published_name(tmp_path):
    import zipfile
    raw = tmp_path / 'download'
    raw.write_bytes(menu_dat())
    with normalized_upload(raw, 'mod.zip', source_filename='Halo3CSS.dat') as upload:
        assert upload.wrapped and upload.filename == 'Halo3CSS.dat'
        with zipfile.ZipFile(upload.path) as zf:
            assert zf.namelist() == ['Halo3CSS.dat']
        # ... and that is enough for the real classifier to recognise it.
        verdict = detect_content_type(upload.path, upload.filename)
        assert verdict['type'] in ('css_icon_grid', 'css_background')


def test_the_approval_report_names_the_detected_type_and_destination(tmp_path):
    raw = tmp_path / 'download'
    raw.write_bytes(menu_dat())
    with normalized_upload(raw, 'mod.zip', source_filename='Halo3CSS.dat') as upload:
        report = describe_import_target(upload.path, upload.filename)
    assert report['type'] in ('css_icon_grid', 'css_background')
    assert 'Character Select' in report['destination']
    assert len(report['sha256']) == 64 and not report['executable_members']


def test_an_explicit_menu_hint_is_reported_as_the_hint_not_a_guess(tmp_path):
    raw = tmp_path / 'download'
    raw.write_bytes(menu_dat())
    with normalized_upload(raw, 'mod.zip', source_filename='Halo3CSS.dat') as upload:
        report = describe_import_target(upload.path, upload.filename,
                                        mod_type='css_background')
    assert report['type'] == 'css_background'
    assert report['destination'] == 'Menus › Character Select › Backgrounds'


def test_a_code_list_is_refused_by_the_normalizer(tmp_path):
    raw = tmp_path / 'download'
    raw.write_bytes(CODES_INI)
    with pytest.raises(ValueError, match='Gecko codes are not imported'):
        with normalized_upload(raw, 'mod.zip',
                               source_filename='Disable Hardcoded CSS Animations.ini'):
            pass


# ── end to end through the real preflight and the real cascade ─────────────

def test_a_real_menu_dat_is_identified_on_the_approval_card(post, monkeypatch):
    """The motivating task: a character-select DAT published as `other`.

    It used to be saved as `mod.zip` and handed to `inspect_archive`, which
    unconditionally opens a ZIP, so it failed before any importer saw it. Now
    the bytes are fetched into quarantine and classified BEFORE the approval,
    so the card states what the file is, where it lands, and the one genuine
    question a whole character-select screen raises.
    """
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert card['can_download'] and card['files'][0]['can_download']
    plan, preview = website.prepare_download({'post_id': 123, 'file_id': 42})

    assert preview['detected']['type'] in ('css_icon_grid', 'css_background')
    assert 'Character Select' in preview['detected']['destination']
    assert len(preview['detected']['sha256']) == 64
    assert preview['content_is_untrusted'] is True
    # The importer's own question is a radio button on the card, offered with
    # the destination each answer means.
    assert preview['question'].startswith('This file is a whole character select screen')
    assert {option['id'] for option in preview['choices']} == {'css_icon_grid', 'css_background'}
    assert all(option['destination'] for option in preview['choices'])
    assert preview['default_choice'] in ('css_icon_grid', 'css_background')
    # The object itself is held, bound to the hash on the card.
    from randall.website import website_quarantine
    held = website_quarantine.held(plan['quarantine']['token'], plan['quarantine']['sha256'])
    assert held is not None and held.is_file()
    website_quarantine.release(plan['quarantine']['token'])


def test_the_menu_answer_reaches_the_real_importer_without_downloading_again(post, monkeypatch):
    """The answer round-trips through the approval into the REAL cascade."""
    downloads = []
    monkeypatch.setattr(website, '_download', lambda url, path, **kw: (
        downloads.append(url), path.write_bytes(menu_dat())))
    seen = []
    real_import = website._import_archive

    def record(path, title, **kwargs):
        seen.append(kwargs.get('mod_type_override'))
        return real_import(path, title, **kwargs)
    monkeypatch.setattr(website, '_import_archive', record)

    call = tools.prepare('download_website_mod', {'post_id': 123, 'file_id': 42})
    assert len(downloads) == 1                       # fetched once, at preview
    result = tools.execute(call, approvals.Grant(call.fingerprint, 'css_background'))

    assert seen == ['css_background']                # the answer was carried
    assert len(downloads) == 1                       # and nothing was refetched
    # The cascade dispatched on the hint instead of asking the question again.
    assert not result.get('choice_required')


def test_an_unanswered_menu_choice_is_refused_rather_than_guessed(post):
    call = tools.prepare('download_website_mod', {'post_id': 123, 'file_id': 42})
    assert 'offered import options' in tools.execute(
        call, approvals.Grant(call.fingerprint))['error']
    assert 'offered import options' in tools.execute(
        call, approvals.Grant(call.fingerprint, 'something_else'))['error']
    # approvals.decide refuses an unlisted id before it ever reaches here.
    approval = approvals.request(json.loads(call.preview))
    with pytest.raises(ValueError, match='offered download options'):
        approvals.decide(approval, 'approve', 'something_else')
    assert approvals.decide(approval, 'approve', 'css_background')
    assert approval['choice'] == 'css_background'


def test_the_explicit_hint_dispatches_past_the_choice_dialog(tmp_path):
    """Proof the hint is what the real cascade acts on, not a guess."""
    import zipfile
    from vault.importing.unified.archive import _import_single_archive
    archive = tmp_path / 'wrapped.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('Halo3CSS.dat', menu_dat())
    asked, _ = _import_single_archive(str(archive), 'Halo3CSS.dat')
    assert asked['type'] == 'choice_dialog'
    answered, _ = _import_single_archive(str(archive), 'Halo3CSS.dat',
                                         mod_type='css_background')
    assert answered.get('type') != 'choice_dialog'


def test_a_code_list_is_never_offered_for_download(post):
    post['files'][0].update(filename='Disable Hardcoded CSS Animations.ini')
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert not card['files'][0]['can_download'] and not card['can_download']
    with pytest.raises(ValueError, match='Gecko codes are not imported'):
        website.prepare_download({'post_id': 123, 'file_id': 42})
    assert GECKO_REFUSAL.startswith('Gecko codes are not imported')


# ── the any_mod_download release gate ──────────────────────────────────────

def test_with_the_gate_closed_only_the_three_export_types_download(post, monkeypatch):
    """The preview can ship without the any-mod path: it falls back, honestly.

    Browsing, searching and inspecting every post keep working; what closes is
    fetching a published file that is not one of the three export types.
    """
    from core import gates
    monkeypatch.setenv(gates.GATES['any_mod_download'].env, '0')
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert not card['can_download'] and not card['files'][0]['can_download']
    assert card['title'] == 'Halo 3 Matchmaking Lobby'      # still inspectable
    with pytest.raises(ValueError, match='ssbmnucleus.net'):
        website.prepare_download({'post_id': 123, 'file_id': 42})


def test_with_the_gate_closed_a_whole_mod_archive_is_refused_too(post, monkeypatch):
    from core import gates
    monkeypatch.setenv(gates.GATES['any_mod_download'].env, '0')
    post['zip_url'] = media('posts/123/files.zip')
    assert not website_posts.inspect_website_mod(123)['website_mods'][0]['can_download']
    with pytest.raises(ValueError, match='Download button'):
        website.prepare_download({'post_id': 123})


def test_with_the_gate_closed_a_published_costume_still_downloads(post, monkeypatch):
    import io
    import zipfile
    from core import gates
    monkeypatch.setenv(gates.GATES['any_mod_download'].env, '0')
    post['files'][0].update(file_type='character_dat', filename='PlMsBu.dat',
                            character='Marth', color='Blue')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr('PlMsBu.dat', bytes(64))
    monkeypatch.setattr(website, '_download',
                        lambda url, path, **kw: path.write_bytes(buffer.getvalue()))
    card = website_posts.inspect_website_mod(123)['website_mods'][0]
    assert card['can_download'] and card['files'][0]['can_download']
    plan, preview = website.prepare_download({'post_id': 123, 'file_id': 42})
    assert plan['declared_types'] == ['character_dat']


def test_the_gate_is_open_by_default(post):
    from core import gates
    assert gates.enabled('any_mod_download')
    assert website_posts.inspect_website_mod(123)['website_mods'][0]['can_download']


# ── the menu approval, through the endpoints the app actually calls ────────

def test_the_menu_choice_completes_through_the_real_http_endpoints(post, monkeypatch, vault):
    """Both shipped endpoints returned 400 for the legal menu ids.

    Listing failure disables the dialog's confirm button, so an ambiguous menu
    file could not be approved at all. This drives the same two routes the
    viewer does, with a real engine run.
    """
    from flask import Flask
    from randall.assistant import engine, live_runs
    from randall.routes.assistant_bp import assistant_bp

    monkeypatch.setattr(engine, '_provider',
                        lambda *a, **k: pytest.fail('a download button must not call the LLM'))
    post['zip_url'] = media('posts/123/files.zip')   # the card's own button
    seen = []
    monkeypatch.setattr(website, '_import_archive', lambda path, title, **kwargs: (
        seen.append(kwargs.get('mod_type_override'))
        or ({'success': True, 'type': 'menu_mod', 'menu_mod_type': 'css_background',
             'imported_count': 1, 'mods': [{'id': 'bg-1'}],
             'message': 'Imported CSS background'}, 200)))

    app = Flask(__name__)
    app.register_blueprint(assistant_bp)
    client = app.test_client()
    run = engine.start_download(None, 123)
    try:
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested':
                break
        approval = event['tool']['approval']
        offered = [option['id'] for option in approval['choices']]
        assert set(offered) == {'css_icon_grid', 'css_background'}
        assert approval['default_choice'] in offered      # never the unoffered 'all'

        # 1. the inventory listing the dialog calls before it enables confirm
        listing = client.get(
            f'/api/assistant/chats/{run.chat_id}/approvals/{approval["id"]}/files'
            '?choice=css_background&kind=files')
        assert listing.status_code == 200, listing.get_json()

        # 2. an id nobody offered is a bad request, not a missing approval
        route = f'/api/assistant/chats/{run.chat_id}/approvals/{approval["id"]}'
        refused = client.post(route, json={'decision': 'approve', 'choice': 'all'})
        assert refused.status_code == 400

        # 3. the offered id goes through, and reaches the importer as the hint
        accepted = client.post(route, json={'decision': 'approve', 'choice': 'css_background'})
        assert accepted.status_code == 200, accepted.get_json()
        list(live_runs.stream(run))
        assert seen == ['css_background']
    finally:
        live_runs.cancel(run.id)
        if live_runs.active_run():
            list(live_runs.stream(run))


# ── the gate, on every path that could fetch ───────────────────────────────

def _refuse_network(monkeypatch):
    """Any fetch at all is a failure while the gate is closed."""
    fetched = []

    def download(url, path, **kwargs):
        fetched.append(url)
        raise AssertionError(f'the gate is closed; nothing may be fetched ({url})')
    monkeypatch.setattr(website, '_download', download)
    monkeypatch.setattr(website.requests, 'get',
                        lambda *a, **k: pytest.fail('no HTTP request may be made'))
    return fetched


def test_gate_off_fetches_nothing_for_a_single_other_file(post, monkeypatch):
    from core import gates
    monkeypatch.setenv(gates.GATES['any_mod_download'].env, '0')
    fetched = _refuse_network(monkeypatch)
    with pytest.raises(ValueError, match='ssbmnucleus.net'):
        website.prepare_download({'post_id': 123, 'file_id': 42})
    assert fetched == []


def test_gate_off_fetches_nothing_for_a_whole_archive(post, monkeypatch):
    from core import gates
    monkeypatch.setenv(gates.GATES['any_mod_download'].env, '0')
    post['zip_url'] = media('posts/123/files.zip')
    fetched = _refuse_network(monkeypatch)
    with pytest.raises(ValueError, match='Download button'):
        website.prepare_download({'post_id': 123})
    assert fetched == []


def test_gate_off_fetches_nothing_through_the_effect_handoff(post, monkeypatch):
    """The reproduced bypass: an `other` file auto-selected as an effect.

    A whole-post request whose only file was `EfFxData.dat` with a supported
    Laser tag was converted into an effect SELECTION after the gate check and
    fetched the media URL anyway (2026-09-22 review JJ, 3).
    """
    from core import gates
    monkeypatch.setenv(gates.GATES['any_mod_download'].env, '0')
    post['tags'] = ['Effects', 'Fox', 'Laser']
    post['zip_url'] = None
    post['files'][0].update(filename='EfFxData.dat', file_type='other', character='Fox')
    for _mod in (website, website_posts):
        monkeypatch.setattr(_mod, '_rpc', lambda name, args, *rest: (
            {'effect_types': [{'tag_name': 'Laser', 'characters': ['Fox']}]}
            if name == 'api_get_effect_types' else pytest.fail(name)))
    fetched = _refuse_network(monkeypatch)
    assert not website_posts.inspect_website_mod(123)['website_mods'][0]['can_download']
    with pytest.raises(ValueError, match='ssbmnucleus.net'):
        website.prepare_download({'post_id': 123})
    assert fetched == []


def test_gate_off_fetches_nothing_for_a_batch(post, monkeypatch):
    from randall.website import website_bulk
    from core import gates
    monkeypatch.setenv(gates.GATES['any_mod_download'].env, '0')
    fetched = _refuse_network(monkeypatch)
    with pytest.raises(ValueError, match='ssbmnucleus.net'):
        website_bulk.prepare_batch({'items': [{'post_id': 123, 'file_id': 42}]})
    assert fetched == []


def test_gate_off_still_fetches_a_published_export_type(post, monkeypatch):
    import io
    import zipfile
    from core import gates
    monkeypatch.setenv(gates.GATES['any_mod_download'].env, '0')
    post['files'][0].update(file_type='character_dat', filename='PlMsBu.dat',
                            character='Marth', color='Blue')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr('PlMsBu.dat', bytes(64))
    fetched = []
    monkeypatch.setattr(website, '_download', lambda url, path, **kw: (
        fetched.append(url), path.write_bytes(buffer.getvalue())))
    plan, _ = website.prepare_download({'post_id': 123, 'file_id': 42})
    assert len(fetched) == 1
    from randall.website import website_quarantine
    website_quarantine.release(plan['quarantine']['token'])
