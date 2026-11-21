"""
The choice dialogs the import endpoint returns when an upload could be more
than one kind of mod (the user picks; the next request carries the choice).
"""




# ── choice dialog: the honest answer to a genuinely ambiguous upload ────────

def _choice_dialog(filename, question, options, default):
    """A {type: 'choice_dialog'} envelope. The frontend shows the options and
    re-posts the same file with the chosen option's `hints` as form fields
    (mod_type / effect_type / character); batch imports take `default`."""
    return {
        'success': False,
        'type': 'choice_dialog',
        'filename': filename,
        'question': question,
        'options': options,
        'default': default,
    }, 200


_IMAGE_OPTION_TEXT = {
    'css_doors': ('CSS door texture',
                  'Stretched onto the 128×200 character-select port door.'),
    'pause_picture': ('Pause screen picture',
                      'Replaces the central graphic of the pause screen.'),
}


def _image_choice_dialog(filename, verdict):
    """Every picture kind as an option, the detector's pick first/default."""
    options = []
    ordered = list(verdict['candidates'])
    for extra in ('css_doors', 'pause_picture'):
        if extra not in ordered:
            ordered.append(extra)
    for cand in ordered:
        if cand == 'effect_image':
            d = verdict['all_details'].get('effect_image', {})
            options.append({
                'key': f"effect_image:{d.get('character')}:{d.get('extra_type')}",
                'label': f"{d.get('name', 'Effect picture')} for {d.get('character', '?')}",
                'description': 'Installed as an effect picture in that character\'s Extras.',
                'hints': {'mod_type': 'effect_image', 'character': d.get('character'),
                          'effect_type': d.get('extra_type')},
            })
        elif cand in _IMAGE_OPTION_TEXT:
            label, description = _IMAGE_OPTION_TEXT[cand]
            options.append({'key': cand, 'label': label, 'description': description,
                            'hints': {'mod_type': cand}})
    d = verdict['detail']
    n = len(d.get('images', [])) if isinstance(d.get('images'), list) else 1
    size = f" ({d['width']}×{d['height']})" if d.get('width') and n == 1 else ''
    question = (f'What is this picture{size}?' if n == 1
                else f'What are these {n} pictures?')
    return _choice_dialog(filename, question, options, default=options[0]['key'])
