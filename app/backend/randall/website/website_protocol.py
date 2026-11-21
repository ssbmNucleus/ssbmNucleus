"""Build the same nucleus://import handoff as the website's Add to Nucleus."""
import re
from urllib.parse import urlencode


def effect_handoff(post, selected, rpc):
    files = [selected] if selected else post.get('files', [])
    candidates = [file for file in files if file.get('file_type') == 'effects_dat' or
                  (file.get('file_type') not in ('character_dat', 'stage_dat') and
                   re.match(r'^ef\w{2}data.*\.dat$', file.get('filename', '').replace('\\', '/').rsplit('/', 1)[-1], re.I))]
    if not candidates and 'Effects' not in post.get('tags', []):
        return None
    if selected and not candidates:
        return None
    types = rpc('api_get_effect_types', {}).get('effect_types', [])
    matches = [item for item in types if item.get('tag_name') in post.get('tags', [])]
    if len(matches) != 1 or len(candidates) != 1:
        raise ValueError('Choose one effect file with an unambiguous effect-type tag before downloading.')
    file, effect = candidates[0], matches[0]
    from core.extra_types import EXTRA_TYPES
    from core.extra_lookup import get_extra_types
    character = file.get('character') or next((tag for tag in post.get('tags', []) if tag in EXTRA_TYPES), None)
    character = character or next(iter(effect.get('characters') or []), None)
    normalize = lambda value: str(value).lower().replace(' ', '_').replace('-', '_')
    known = next((item for item in get_extra_types(character) if normalize(effect['tag_name']) in
                  (normalize(item['id']), normalize(item['name']))), None)
    if not known:
        raise ValueError('This effect type is not supported for the published character in this Nucleus build.')
    return {'file': file, 'character': character, 'effect_type': known['id']}


def import_link(post, selected, url, effect=None):
    character = effect['character'] if effect else (selected or {}).get('character') or 'mod'
    color = (selected or {}).get('color') or 'Default'
    fields = {'url': url, 'name': f'{character}_{color}', 'title': str(post.get('title') or 'Untitled mod')[:200]}
    if effect:
        fields.update(type='effect', effect_type=effect['effect_type'])
    if selected and selected.get('file_type') == 'stage_dat':
        fields['title'] = fields['title'][:10]
    return 'nucleus://import?' + urlencode(fields)
