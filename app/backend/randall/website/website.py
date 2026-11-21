"""Public website discovery and approval-bound imports into the local vault."""

import hashlib
import json
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests

from .website_exports import (ANY_MOD_REFUSAL, DOWNLOADABLE_TYPES, EXPORT_TYPES,
                              any_mod_download_enabled, assert_download_allowed, _default_variant,
                              _downloadable, downloadable_types, published_exports)
from .website_posts import (SITE, _card, _id, _media, _post, _rpc, _text, archive_files,
                            counted_download, user_agent)
from .website_receipts import NO_DUPLICATE_DETECTION, _completed_operation, _record_operation
from .website_scope import _choice_destination, _declared_destinations, _pending_choice, _scope_refusal


MAX_DOWNLOAD = 256 * 1024 * 1024
_IMPORT_LOCK = threading.Lock()


def resolve_export(post):
    """Which single published export a "download this mod" request means.

    The mod cards advertise `can_download` for a post whose only downloadable
    thing is its per-file exports, and their button submits the post id alone.
    With whole-archive fetching closed that read as "the whole archive", which
    is refused -- so ordinary costume and stage downloads failed outright
    (2026-09-22 review MM, 1). One export is unambiguous; a recognisable family
    of colour variants means the default colour, which is what the card offers
    anyway; anything else has to be asked about by file_id rather than guessed.
    """
    exports = published_exports(post)
    if not exports:
        return None
    if len(exports) == 1:
        return exports[0]
    variants = [{'file_id': f.get('id'), 'name': f.get('filename') or '',
                 'type': f.get('file_type')} for f in exports]
    default = _default_variant(variants) if len(variants) <= 60 else None
    if default:
        return next(f for f in exports if f.get('id') == default['file_id'])
    listed = '; '.join(f"{_text(f.get('filename') or 'File', 80)} (file_id {f.get('id')})"
                       for f in exports[:12])
    raise ValueError(
        f'This mod publishes {len(exports)} separate files, so there is no single '
        f'"download this mod". Ask for one of them by file_id: {listed}'
        + ('; ...' if len(exports) > 12 else '') + '.')


def _contents(post, selected=None):
    records = [selected] if selected else post.get('files') or []
    fallback_image = _card(post)['image']
    mods = [{'name': str(f.get('filename') or 'File')[:300], 'character': f.get('character'),
             'color': f.get('color'), 'type': f.get('file_type') or 'File',
             'image': _media(f.get('csp_url')) or _media(f.get('preview_url')) or fallback_image,
             'image_is_post': not (_media(f.get('csp_url')) or _media(f.get('preview_url'))),
             'stock_image': _media(f.get('stock_url'))} for f in records]
    files = list(mods)
    for record in records:
        for field, label in [('csp_url', 'CSP'), ('stock_url', 'Stock icon')]:
            if record.get(field):
                files.append({'name': str(record[field]).rsplit('/', 1)[-1][:300], 'type': label,
                              'character': record.get('character'), 'color': record.get('color')})
    # Whole archives also hold files that have no individual export (and the
    # files the site hides from the mod's page); the API lists them all.
    if selected is None:
        published = []
        known = set()
        for row in archive_files(post):
            if row['filename'] not in known:
                published.append({'name': str(row['filename'])[:300], 'type': 'Published file', 'size': row.get('size')})
                known.add(row['filename'])
        if published:
            files = published
    groups = {}
    for mod in mods:
        label = mod.get('character') or mod['type'].replace('_', ' ')
        groups[label] = groups.get(label, 0) + 1
    return {'mods': mods, 'files': files, 'summary': {'mod_count': len(mods), 'file_count': len(files),
            'groups': [{'name': name, 'count': count} for name, count in sorted(groups.items())]}}


def _plan(post_id, file_id=None):
    from .website_protocol import effect_handoff, import_link
    post = _post(post_id)
    card = _card(post, details=True)
    selected = None
    if file_id is None and not any_mod_download_enabled():
        # Resolve what the button actually means BEFORE the gate is asked, so
        # an ordinary costume download is a costume download and not a refused
        # whole archive. Whole-archive fetching itself stays closed.
        resolved = resolve_export(post)
        if resolved is not None:
            file_id = resolved.get('id')
            _id(file_id, 'file_id')
    if file_id is not None:
        _id(file_id, 'file_id')
        selected = next((f for f in post.get('files') or [] if f.get('id') == file_id), None)
        if not selected:
            # The public API leaves out files the site hides (duplicates, for
            # one), so an id seen elsewhere can be missing here.
            raise ValueError("That file is not listed on this mod's public page; it may be hidden "
                             'or removed. Inspect the mod and choose one of its listed file_ids, '
                             'or download the whole mod.')
        if selected.get('file_type') not in DOWNLOADABLE_TYPES:
            raise ValueError('This file has no individual costume/stage export. Inspect the mod or download the whole mod.')
        if selected.get('file_type') not in downloadable_types():
            raise ValueError(ANY_MOD_REFUSAL)
        if not _downloadable(selected):
            from vault.importing.unified.normalize import GECKO_REFUSAL
            raise ValueError(GECKO_REFUSAL)
    effect = effect_handoff(post, selected, _rpc)
    if effect:
        selected = effect['file']
        file_id = selected['id']
    # The selection is final here: `effect_handoff` above may have chosen a
    # file the caller never named. The gate answers about THAT file.
    assert_download_allowed(selected, whole_archive=file_id is None)
    if file_id is not None:
        _id(file_id, 'file_id')
        if selected.get('file_type') in EXPORT_TYPES:
            url = f'{SITE}/api/posts/{post_id}/export-nucleus/{file_id}'
        else:
            # The counted link credits the creator and redirects to the file.
            url = counted_download(selected, post_id, file_id)
            if not url:
                raise ValueError('This file has no published download. Download the whole mod instead.')
        card['selected_file'] = {'name': str(selected.get('filename') or 'File')[:160],
                                 'character': selected.get('character'), 'color': selected.get('color')}
    else:
        # The counted link credits the creator and redirects to the zip.
        url = counted_download(post, post_id)
        if not url:
            raise ValueError('This mod has no supported website archive. Choose an individual costume/stage file.')
    # Exclude counters/likes, which change during ordinary browsing. Bind the
    # approval to the published content and recheck it before fetching bytes.
    protocol_url = import_link(post, selected, url, effect)
    revision = {k: post.get(k) for k in ('id', 'title', 'description', 'author', 'updated_at',
                'zip_url', 'download_url', 'files', 'archive_files', 'tags', 'screenshots')}
    revision['effect_handoff'] = {key: effect[key] for key in ('character', 'effect_type')} if effect else None
    fingerprint = hashlib.sha256(json.dumps(revision, sort_keys=True).encode()).hexdigest()
    return {'post_id': post_id, 'file_id': file_id, 'url': url, 'protocol_url': protocol_url,
            'revision': fingerprint, 'mod': card,
            # The publisher's own filename, so a raw download is wrapped under
            # its real name and detection sees the real extension.
            'source_filename': _text((selected or {}).get('filename')
                                     or (_media(post.get('zip_url')) or '').rsplit('/', 1)[-1]
                                     or 'mod.zip', 160),
            # A selected file's published type is a promise; a whole-mod
            # archive is unpromised however its individual files are typed.
            'declared_types': (sorted({str(selected.get('file_type') or 'other')})
                               if selected else ['other']),
            # The resolved selection the gate answered about, so the answer can
            # be re-derived at fetch time without re-resolving the handoff.
            'gate_subject': ({'file_type': selected.get('file_type'),
                              'filename': _text(selected.get('filename'), 160)}
                             if selected else None),
            'contents': _contents(post, selected),
            'artwork': [{k: f.get(k) for k in ('id', 'filename', 'file_type', 'csp_url', 'stock_url')}
                        for f in post.get('files', [])] if file_id is None else []}


def _identify_in_quarantine(plan, budget=None):
    """Fetch this plan's object, hold it, and identify it. Returns the report.

    This runs while the PREVIEW is being built, so the approval can state what
    the file actually is and where it lands rather than repeating publisher
    metadata, and the grant binds to this object's hash.
    """
    from vault.importing.unified.normalize import describe_import_target, normalized_upload
    from vault.importing.unified.protocol import parse_import_link
    from . import website_quarantine
    from .website_artwork import hydrate_archive
    from .website_safety import download_budget

    budget = budget or download_budget()
    source_name = plan.get('source_filename') or 'mod.zip'
    hint = parse_import_link(plan['protocol_url'])['mod_type']
    with tempfile.TemporaryDirectory(prefix='nucleus-quarantine-') as temporary:
        raw = Path(temporary) / 'download'
        _download(plan['url'], raw, allowed=_gate_subject(plan))
        with normalized_upload(raw, source_name, source_filename=source_name,
                               budget=budget) as upload:
            # Artwork hydration REWRITES the archive, so it has to finish
            # before the object is identified and held; identifying first and
            # hydrating afterwards meant the approval described bytes that no
            # longer existed (2026-09-22 review JJ, 2).
            warnings = hydrate_archive(Path(upload.path), plan.get('artwork', []), _download)
            content = describe_import_target(upload.path, upload.filename,
                                             budget=budget, mod_type=hint)
            token, digest = website_quarantine.hold(upload.path,
                                                    owner=_holding_owner(plan))
            plan['quarantine'] = {'token': token, 'sha256': digest,
                                  'filename': upload.filename}
    content['sha256'] = digest
    plan['detected'] = content
    plan['hydration_warnings'] = warnings
    return content


def _holding_owner(plan):
    """Who a held object belongs to: this post, at this revision, this scope."""
    return f"{plan['post_id']}:{plan.get('file_id')}:{plan['revision']}"


def prepare_download(args, quarantine=True):
    plan = _plan(**args)
    mod = plan['mod']
    scope = mod.get('selected_file', {}).get('name') or 'All supported files in this mod archive'
    destinations = _declared_destinations(plan)
    content = _identify_in_quarantine(plan) if quarantine else None
    if content is not None:
        refusal = _scope_refusal(plan, content)
        if refusal:
            # Never show an approval for something we already know we will
            # refuse: the user would be approving a download that cannot land.
            from . import website_quarantine
            website_quarantine.release(plan['quarantine']['token'])
            raise ValueError(refusal)
        if content.get('destination'):
            destinations = [content['destination']]
        plan['pending_choice'] = _pending_choice(content)
    preview = {'title': f"Download {mod['title']} to your vault?",
               'contents_summary': plan['contents']['summary'],
               'description': scope, 'website_mods': [mod], 'confirm_label': 'Download to vault',
               # What the PUBLISHER says this is, what it TURNED OUT to be, and
               # where it will land. The detected report is of the object now
               # held in quarantine; the import is bound to its hash.
               'declared_types': plan['declared_types'],
               'destinations': destinations,
               'detected': content,
               # Every word of the card that came from the post is material to
               # read, never an instruction to follow.
               'content_is_untrusted': True,
               'consequence': ('Adds to ' + (', '.join(destinations) if destinations else 'your vault')
                               + ' and skips duplicates. '
                               + ('These exact files have been identified and are held until you '
                                  'decide; nothing else can be substituted for them. '
                                  if content is not None else
                                  'The downloaded files are identified before anything is written; '
                                  'if they are not what the post says they are, nothing is imported. ')
                               + 'Unsafe costumes ask before fixing or importing.')}
    if plan.get('pending_choice'):
        preview['choices'] = [{'id': option['key'],
                               'label': option['label'],
                               'description': option['description'],
                               'destination': option['destination']}
                              for option in plan['pending_choice']['options']]
        preview['default_choice'] = plan['pending_choice']['default']
        preview['question'] = plan['pending_choice']['question']
        return plan, preview
    default = _default_variant(mod['files']) if args.get('file_id') is None and not mod['files_truncated'] else None
    if default:
        # Both scopes are prepared by the server and bound to the same approval.
        single = _plan(args['post_id'], default['file_id'])
        if single['revision'] != plan['revision']:
            raise ValueError('This mod changed while preparing its variants. Please try again.')
        if quarantine:
            _identify_in_quarantine(single)
        plan['default_variant'] = single
        preview['choices'] = [{'id': 'default', 'label': 'Default variant only'},
                              {'id': 'all', 'label': f"All {len(mod['files'])} variants"}]
        preview['default_choice'] = 'default'
    return plan, preview


ALLOWED_DOWNLOAD_HOSTS = ('media.ssbmnucleus.net', 'ssbmnucleus.net')
REDIRECTS = (301, 302, 303, 307, 308)
# The public API's counted download: it records the download for the creator,
# then redirects once to the zip (or, with ?file=, one file) on the media host.
_COUNTED_PATH = re.compile(r'/api/public/v1/mods/[1-9][0-9]{0,9}/download')
_COUNTED_QUERY = re.compile(r'(?:file=[1-9][0-9]{0,9})?')


def _check_download_url(url):
    """HTTPS, one of our two hosts, no credentials, no port, no control bytes.

    `_media` validates the URLs that come out of a post, but `_download` is
    also handed the fixed `/export-nucleus` route and the artwork URLs, so the
    check belongs at the fetch itself: this is the last point before bytes
    arrive.
    """
    if not isinstance(url, str) or not url or any(ord(c) < 32 for c in url):
        raise ValueError('That download link is not a Nucleus website address.')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.port is not None or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS):
        raise ValueError('That download link is not a Nucleus website address.')
    return url


def _counted(url):
    """True for the public API's counted download link, the one URL that may redirect."""
    parsed = urlsplit(url)
    return (parsed.hostname == 'ssbmnucleus.net' and not parsed.fragment
            and bool(_COUNTED_PATH.fullmatch(parsed.path))
            and bool(_COUNTED_QUERY.fullmatch(parsed.query)))


def _redirect_target(response):
    """Where a counted download sends us: the media host and nowhere else."""
    location = response.headers.get('Location') or ''
    try:
        _check_download_url(location)
    except ValueError:
        location = ''
    if urlsplit(location).hostname != 'media.ssbmnucleus.net':
        raise ValueError('The website download was redirected elsewhere. Nothing was downloaded.')
    return location


def _download(url, destination, *, allowed=None):
    # URLs come exclusively from a public post or a fixed export route, never
    # from the model. Only the counted download link may redirect, exactly
    # once, and only to the media host; every other redirect is refused.
    _check_download_url(url)
    if allowed is not None:
        assert_download_allowed(allowed.get('selected'),
                                whole_archive=allowed.get('whole_archive', False))
    started = time.monotonic()
    headers = {'User-Agent': user_agent()}
    try:
        response = requests.get(url, stream=True, timeout=(10, 30), allow_redirects=False,
                                headers=headers)
        if response.status_code in REDIRECTS and _counted(url):
            with response:
                target = _redirect_target(response)
            response = requests.get(target, stream=True, timeout=(10, 30),
                                    allow_redirects=False, headers=headers)
        with response:
            if response.status_code in REDIRECTS:
                # A redirect off the media host (or a second hop) is exactly how
                # an approved link would become a different object after the
                # user said yes.
                raise ValueError('The website download was redirected elsewhere. '
                                 'Nothing was downloaded.')
            if response.status_code != 200:
                raise ValueError(f'The website download failed (HTTP {response.status_code}).')
            if int(response.headers.get('Content-Length', 0)) > MAX_DOWNLOAD:
                raise ValueError('This mod exceeds the 256 MB chat download limit. Download it from the website.')
            size = 0
            with open(destination, 'wb') as output:
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD or time.monotonic() - started > 180:
                        raise ValueError('This download exceeded the chat size or time limit. Use the website for this mod.')
                    output.write(chunk)
    except requests.RequestException as exc:
        raise ValueError('The mod download was interrupted. Nothing was imported.') from exc


def _import_archive(path, title, slippi_action='import_as_is', protocol_url=None,
                    expected_url=None, budget=None, source_filename=None,
                    mod_type_override=None):
    from vault.importing.unified.protocol import import_handoff
    return import_handoff(str(path), 'website-mod.zip', slippi_action=slippi_action,
                          duplicate_action='skip', custom_title=title,
                          protocol_url=protocol_url, expected_url=expected_url,
                          budget=budget, source_filename=source_filename,
                          mod_type_override=mod_type_override)


def _gate_subject(plan):
    """What the gate should be asked about for this plan's fetch."""
    return {'selected': plan.get('gate_subject'),
            'whole_archive': plan.get('file_id') is None}


def _operation_key(plan):
    """Identity of one download+import, stable across retries of the same request."""
    return hashlib.sha256(json.dumps(
        [plan['post_id'], plan['file_id'], plan['url'], plan['revision']],
        sort_keys=True).encode()).hexdigest()


def apply_download(args, plan, safety_review=None, cancelled=lambda: False,
                   allow_scope_change=False, menu_choice=None):
    """Download into quarantine, identify the bytes, then import what was approved.

    The approval the user gave describes a publisher's post. What arrives is an
    object nobody has looked at yet, so between the two there is a quarantine
    step: the download is normalized (raw files wrapped, archives converted),
    its real type and destination are identified from the bytes, and the import
    is authorized against THAT -- its sha256, its detected type and the exact
    vault section it lands in (2026-09-22 security review, findings 3 and 4).

    An object that turns out to be a patch, to carry executable members, or to
    disagree with the published type is refused rather than imported: that is a
    change of scope, and the approval the user gave did not cover it.
    """
    from vault.importing.unified.normalize import describe_import_target, normalized_upload
    from .website_artwork import hydrate_archive
    from .website_safety import download_budget, inspect_archive
    current = _plan(**args)
    if current['revision'] != plan['revision'] or current['url'] != plan['url']:
        raise ValueError('This mod changed while approval was pending. Nothing was downloaded. Request a fresh preview.')
    receipt_key = _operation_key(plan)
    done = _completed_operation(receipt_key)
    if done is not None:
        # A retry after a lost response, a partial batch or a restart must not
        # download and import the same object a second time.
        return done
    from . import website_quarantine
    budget = download_budget()
    holding = plan.get('quarantine') or {}
    retained = None
    if holding:
        # This approval was shown a specific object. If those exact bytes are
        # not still here, the approval no longer refers to anything: replacing
        # the held file and letting the fetch run again imported DIFFERENT
        # bytes under the old grant (2026-09-22 review JJ, 2).
        retained = website_quarantine.held(holding.get('token'), holding.get('sha256'),
                                           owner=_holding_owner(plan))
        if retained is None:
            raise ValueError('The files this approval was given for are no longer held, so '
                             'they cannot be imported. Request a fresh preview.')
    with tempfile.TemporaryDirectory(prefix='nucleus-mod-') as temporary:
        quarantine = Path(temporary) / 'quarantine'
        quarantine.mkdir()
        # The held object is already normalized, and the cascade dispatches
        # packages and containers on a `.zip` suffix -- an extensionless copy
        # was silently demoted to "loose files" (review JJ, 3/5).
        path = quarantine / (holding.get('filename') and 'approved.zip' or 'download')
        if retained is not None:
            shutil.copyfile(retained, path)
        else:
            _download(plan['url'], path, allowed=_gate_subject(plan))
        # No separate count: the transfer itself went through the API's
        # counted download link (or the export route), which credits the creator.
        from vault.importing.unified.protocol import parse_import_link
        hint = parse_import_link(plan['protocol_url'])['mod_type']
        source_name = plan.get('source_filename') or 'mod.zip'
        # ONE normalization for the safety preflight, the identification and
        # the import, so all three see exactly the same bytes.
        with normalized_upload(path, source_name, source_filename=source_name,
                               budget=budget) as upload:
            staged = Path(upload.path)
            # Hydration already ran before the object was identified and held.
            warnings = list(plan.get('hydration_warnings') or [])
            if retained is None:
                warnings = hydrate_archive(staged, plan.get('artwork', []), _download)
            # Detect removal/edits during the download too, before touching the vault.
            verified = _plan(**args)
            if verified['revision'] != plan['revision']:
                raise ValueError('This mod changed during download. Nothing was imported. Request a fresh preview.')
            if verified['mod'].get('download_count') is not None:
                plan['mod']['download_count'] = verified['mod']['download_count']
            safety = inspect_archive(staged, cancelled, hint, budget=budget)
            # No rewind: the budget is keyed to each archive occurrence, so
            # this second walk of the SAME archive costs nothing and a
            # different one is still charged.
            content = describe_import_target(staged, upload.filename,
                                             budget=budget, mod_type=hint)
            if holding:
                # Bound to what was APPROVED, not to a report generated from
                # whatever arrived: the hash, the detected type and the
                # destination all have to be the ones on the card.
                approved = plan.get('detected') or {}
                if (content['sha256'] != holding.get('sha256')
                        or content['type'] != approved.get('type')
                        or content.get('destination') != approved.get('destination')):
                    website_quarantine.release(holding.get('token'))
                    raise ValueError('These are not the files this approval was given for. '
                                     'Nothing was imported. Request a fresh preview.')
            safety['content'] = content
            refusal = _scope_refusal(plan, content)
            if refusal and not allow_scope_change:
                website_quarantine.release(holding.get('token'))
                return {'website_mods': [plan['mod']], 'imported_count': 0, 'vault_changed': False,
                        'detected': content, 'declared_types': plan.get('declared_types') or [],
                        'approval_status': 'denied',
                        'error': refusal,
                        'note': 'Nothing was imported. The downloaded files are not what this post '
                                'said they are, so the approval you gave does not cover them.'}
            action = 'import_as_is'
            if safety['unsafe_costumes']:
                if safety_review is None:
                    raise ValueError('Slippi safety approval is required. Nothing was imported.')
                decision = safety_review(safety, plan['mod'])
                action = decision.get('action')
                if action not in ('fix', 'import_as_is'):
                    website_quarantine.release(holding.get('token'))
                    return {'website_mods': [plan['mod']], 'imported_count': 0, 'vault_changed': False,
                            'detected': content,
                            'declared_types': plan.get('declared_types') or [],
                            'approval_status': decision.get('status', 'denied'),
                            'note': 'Download discarded. Nothing was added to the vault.'}
                if hashlib.sha256(staged.read_bytes()).hexdigest() != safety['archive_hash']:
                    raise ValueError('Downloaded files changed during safety review. Nothing was imported.')
                if _plan(**args)['revision'] != plan['revision']:
                    raise ValueError('This mod changed during safety review. Nothing was imported. Request a fresh preview.')
            if cancelled():
                raise ValueError('Download cancelled. Nothing was imported.')
            with _IMPORT_LOCK:
                if cancelled():
                    raise ValueError('Download cancelled. Nothing was imported.')
                # Look again under the lock: two requests that both missed the
                # first check would otherwise both import.
                done = _completed_operation(receipt_key)
                if done is not None:
                    return done
                # The authorization is bound to the object that was identified,
                # not to the post's metadata: if these bytes are not the ones
                # the report describes, nothing is imported.
                expected = holding.get('sha256') or content['sha256']
                if hashlib.sha256(staged.read_bytes()).hexdigest() != expected:
                    raise ValueError('The downloaded files changed after they were checked. '
                                     'Nothing was imported.')
                payload, status = _import_archive(staged, plan['mod']['title'], slippi_action=action,
                                                 protocol_url=plan['protocol_url'],
                                                 expected_url=plan['url'],
                                                 source_filename=source_name,
                                                 budget=budget,
                                                 mod_type_override=menu_choice)
                # Recorded HERE, still holding the lock, so a crash between the
                # import and the receipt cannot leave a completed import with
                # nothing remembering it. The richer result refreshes this
                # entry below; the minimal one already protects a retry.
                recorded = (payload.get('success')
                            and payload.get('imported_count', 1)
                            and payload.get('type') in NO_DUPLICATE_DETECTION)
                if recorded:
                    _record_operation(receipt_key, {
                        'imported_count': payload.get('imported_count', 1),
                        'note': str(payload.get('message') or 'Imported.')[:2000],
                        'detected': content}, payload, content)
    from core.metadata import load_metadata
    from randall.assistant.vault_items import _item
    metadata = load_metadata(default={}) or {}
    imported_items = []
    for costume in payload.get('costumes', []):
        character = costume.get('character')
        skin = next((s for s in metadata.get('characters', {}).get(character, {}).get('skins', [])
                     if costume.get('id') and s.get('id') == costume['id']), None)
        if skin:
            imported_items.append(_item(character, skin))
    count = payload.get('imported_count', 1 if payload.get('success') else 0)
    from core.stages import ALL_STAGES
    stage_folders = {info['name']: info['folder'] for info in ALL_STAGES.values()}
    imported_stages = []
    for stage in payload.get('stages', []):
        folder = stage.get('folder') or stage_folders.get(stage.get('stage'))
        variant = next((v for v in metadata.get('stages', {}).get(folder, {}).get('variants', [])
                        if v.get('id') == stage.get('variant')), None)
        if variant:
            screenshot = variant.get('screenshot_filename')
            imported_stages.append({'id': variant['id'], 'kind': 'stage', 'folder': folder,
                'name': plan['mod']['title'], 'stage': stage.get('stage'),
                'image': f'/storage/das/{quote(folder, safe="")}/{quote(screenshot, safe="")}' if screenshot else plan['mod']['image'],
                'fallback_image': plan['mod']['image']})
    skipped = payload.get('skipped_count', 0)
    failed = payload.get('failed') or []
    result = {'website_mods': [plan['mod']], 'vault_changed': count > 0,
              'imported_count': count, 'skipped_count': skipped,
              'fixed_count': payload.get('fixed_count', 0),
              'unsafe_count': sum(item.get('slippi_safe') is False for item in imported_items),
              'slippi_action': action,
              'warnings': warnings,
              'imported_items': imported_items,
              'imported_stages': imported_stages,
              'note': str(payload.get('message') or 'Import finished.')[:2000],
              'failed': [{'name': str(f.get('name', 'File'))[:160],
                          'error': str(f.get('error', 'Not imported'))[:500]} for f in failed[:20]]}
    if payload.get('type') == 'choice_dialog':
        # A whole character-select DAT genuinely carries both the icons and the
        # backdrop, so the importer asks. Randall used to drop the question and
        # report a generic import failure (2026-09-22 review, finding 5); the
        # question, its options and its default are the answer to give the user.
        result['choice_required'] = True
        result['choice'] = {'question': str(payload.get('question') or '')[:500],
                            'options': [{'key': str(o.get('key'))[:60],
                                         'label': str(o.get('label') or '')[:120],
                                         'description': str(o.get('description') or '')[:300],
                                         'destination': _choice_destination(o)}
                                        for o in (payload.get('options') or [])[:8]],
                            'default': str(payload.get('default') or '')[:60]}
        result['note'] = ('Nothing was imported yet: this file can be imported in more than one '
                          'way and needs your answer. Choose an option and download it again.')
    elif status >= 400 or not payload.get('success') or (count == 0 and skipped == 0):
        result['error'] = str(payload.get('error') or 'No files were added. This archive could not be imported.')[:1000]
    if failed and count:
        result['note'] = 'Partially imported. ' + result['note']
    from .vault_presence import record_import, vault_status
    if payload.get('type') == 'effect' and payload.get('id'):
        result['imported_effects'] = [{key: payload[key] for key in ('id', 'character', 'effect_type')}]
    existing = []
    for duplicate in payload.get('skipped_duplicates', []):
        owner, item_id = duplicate.get('character'), (duplicate.get('existing_skin') or {}).get('id')
        if item_id and any(s.get('id') == item_id for s in metadata.get('characters', {}).get(owner, {}).get('skins', [])):
            existing.append({'kind': 'costume', 'owner': owner, 'id': item_id})
        folder = stage_folders.get(owner)
        if item_id and folder and any(v.get('id') == item_id for v in metadata.get('stages', {}).get(folder, {}).get('variants', [])):
            existing.append({'kind': 'stage', 'owner': folder, 'id': item_id})
        for effect_type, effects in metadata.get('characters', {}).get(owner, {}).get('extras', {}).items():
            if item_id and isinstance(effects, list) and any(effect.get('id') == item_id for effect in effects):
                existing.append({'kind': 'effect', 'owner': owner, 'effect_type': effect_type, 'id': item_id})
    record_import(plan['post_id'], result, existing)
    result['website_mods'][0]['in_vault'] = vault_status([plan['post_id']])[str(plan['post_id'])]
    result['detected'] = content
    result['declared_types'] = plan.get('declared_types') or []
    if recorded:
        _record_operation(receipt_key, result, payload, content)
    if not result.get('choice_required'):
        # The held bytes did their job. A pending question keeps them, so the
        # answer can be applied without fetching anything again.
        website_quarantine.release(holding.get('token'))
    return result
