"""One approval for a bounded set of website downloads and its safety policy."""
import logging
from . import website, website_exports, website_posts

MAX_BATCH = 24


def validate_items(items):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH:
        raise ValueError(f'Choose between 1 and {MAX_BATCH} website mods per batch.')
    normalized, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {'post_id', 'file_id', 'variants'} or 'post_id' not in item:
            raise ValueError('Each download needs a post_id and optional file_id or variants.')
        post_id = website_posts._id(item['post_id'], 'post_id')
        if post_id in seen:
            raise ValueError('Choose each website mod once per batch.')
        seen.add(post_id)
        row = {'post_id': post_id, 'variants': item.get('variants', 'default')}
        if row['variants'] not in ('default', 'all'):
            raise ValueError('variants must be default or all.')
        if 'file_id' in item:
            if 'variants' in item:
                raise ValueError('Choose a file_id or a variant scope, not both.')
            row['file_id'] = website_posts._id(item['file_id'], 'file_id')
        normalized.append(row)
    return normalized


MAX_PLANS = 60


def _expand(items):
    """Turn "download this mod" rows into the published exports they mean.

    "Download all" submits post ids alone. With whole-archive fetching closed
    that read as a forbidden whole archive and every item failed, so a batch of
    ordinary costumes could not be downloaded at all (2026-09-22 review MM, 1).
    Each row becomes explicit export file_ids here, before any preparation runs.
    """
    if website_exports.any_mod_download_enabled():
        return items
    expanded = []
    for item in items:
        if 'file_id' in item:
            expanded.append(item)
            continue
        post = website_posts._post(item['post_id'])
        exports = website_exports.published_exports(post)
        if item.get('variants') == 'all' and len(exports) > 1:
            chosen = exports
        else:
            resolved = website.resolve_export(post)   # raises when ambiguous
            chosen = [resolved] if resolved else []
        if not chosen:
            # Nothing downloadable: let preparation give the real refusal, in
            # its own words, for this one item.
            expanded.append(item)
            continue
        for file in chosen:
            expanded.append({'post_id': item['post_id'],
                             'file_id': website_posts._id(file['id'], 'file_id')})
    if len(expanded) > MAX_PLANS:
        raise ValueError(f'That is {len(expanded)} files, more than the {MAX_PLANS} this '
                         'app downloads in one batch. Choose fewer mods, or download '
                         'individual files.')
    return expanded


def prepare_batch(args):
    plans, mods, files, cards = [], [], [], []
    for item in _expand(validate_items(args['items'])):
        request = {k: item[k] for k in ('post_id', 'file_id') if k in item}
        # No quarantine pre-fetch for a batch: 24 downloads before the one
        # approval would be worse than the problem. Each item is still
        # identified and bound before it is imported.
        plan, _ = website.prepare_download(request, quarantine=False)
        if item.get('variants') == 'default' and plan.get('default_variant'):
            plan = plan['default_variant']
        plans.append(plan)
        summary = plan['contents']['summary']
        cards.append({**plan['mod'], 'download_file_count': summary['file_count'],
                      'download_mod_count': summary['mod_count']})
        mods.extend(plan['contents']['mods'])
        files.extend({**file, 'name': f"{plan['mod']['title']} / {file['name']}"}
                     for file in plan['contents']['files'])
    summary = {'mod_count': len(mods), 'file_count': len(files), 'groups': []}
    return {'plans': plans, 'contents': {'mods': mods, 'files': files, 'summary': summary}}, {
        'title': f'Download {len(plans)} mods?', 'bulk_download': True,
        'website_mods': cards, 'contents_summary': summary,
        'choices': [{'id': 'fix', 'label': 'Fix unsafe skins'},
                    {'id': 'import_as_is', 'label': 'Keep original files'}],
        'default_choice': 'fix', 'confirm_label': f'Download {len(plans)} mods'}


def apply_batch(args, plan, *, choice, progress=None, cancelled=lambda: False):
    if choice not in ('fix', 'import_as_is'):
        raise ValueError('Approve a safety option for these downloads.')
    # The approved plan is server-owned; no new items or expanded scope are
    # accepted at execution time. Each executor rechecks its post revision.
    rows = [{'post_id': p['post_id'], 'title': p['mod']['title'], 'status': 'queued'} for p in plan['plans']]

    def snapshot():
        results = [row['result'] for row in rows if row.get('result')]
        failed = [{'name': row['title'], 'error': row['result']['error']}
                  for row in rows if row.get('result', {}).get('error')]
        for result in results:
            failed.extend(result.get('failed', []))
        stopped = cancelled() or any(row['status'] == 'cancelled' for row in rows)
        value = {'bulk_download': True, 'website_mods': [p['mod'] for p in plan['plans']],
                 'downloads': [dict(row) for row in rows], 'total_count': len(rows),
                 'completed_count': sum(row['status'] in ('done', 'error') for row in rows),
                 'cancelled': stopped, 'slippi_action': choice,
                 'imported_items': [item for result in results for item in result.get('imported_items', [])],
                 'imported_stages': [item for result in results for item in result.get('imported_stages', [])],
                 'warnings': [warning for result in results for warning in result.get('warnings', [])],
                 'failed': failed}
        for field in ('imported_count', 'skipped_count', 'fixed_count', 'unsafe_count'):
            value[field] = sum(result.get(field, 0) for result in results)
        value['vault_changed'] = value['imported_count'] > 0
        if stopped:
            value['approval_status'] = 'cancelled'
        if failed:
            value['error'] = 'Some downloads failed. Completed imports are kept.'
        return value

    for index, approved in enumerate(plan['plans']):
        if cancelled():
            for row in rows[index:]:
                row['status'] = 'cancelled'
            break
        rows[index]['status'] = 'running'
        if progress:
            progress(snapshot())
        try:
            request = {'post_id': approved['post_id'], **({'file_id': approved['file_id']} if approved['file_id'] is not None else {})}
            result = website.apply_download(request, approved,
                safety_review=lambda safety, mod: {'action': choice, 'status': 'approved'}, cancelled=cancelled)
        except ValueError as exc:
            result = {'error': str(exc)}
        except Exception:
            logging.getLogger(__name__).exception('Batch download failed for post %s', approved['post_id'])
            result = {'error': 'This mod could not be downloaded. Check the backend log.'}
        rows[index].update(status='error' if result.get('error') else 'done', result=result)
        if progress:
            progress(snapshot())
    return snapshot()
