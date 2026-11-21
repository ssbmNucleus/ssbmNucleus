"""Any Climbers endpoints — build a two-fighter CSS slot.

**None of this needs a project open.** The Custom Characters vault is
project-independent, so the picker reads the bundled vanilla roster when there
is no project (and the project's own roster when there is one, so added m-ex
fighters and edited costume art show up).

A created pair is stored as a *recipe* — two fighter names plus the composited
art — not a baked fighter package. The package is materialised at install time
by `vault.climbers.pairs.materialize`, against whatever project it is being installed
into. See `vault/climbers/pairs.py` for why.
"""
import io
import json
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file

from vault.climbers import roster
from vault.climbers.pairs import (candidates, color_plan, fighter_art, load_fighters,
                            write_vault_assets)
from vault.climbers.portraits import composite
from core.state import get_current_project_path

logger = logging.getLogger(__name__)

climbers_bp = Blueprint('climbers', __name__)


def _project():
    """The open project, or None. A pair never *requires* one."""
    try:
        return get_current_project_path()
    except Exception:
        return None


@climbers_bp.route('/api/mex/climbers/candidates', methods=['GET'])
def climbers_candidates():
    """Fighters that can lead or partner a pair, with per-side blocked reasons."""
    try:
        project_path = _project()
        return jsonify({
            'success': True,
            'candidates': candidates(project_path),
            'source': 'project' if project_path else 'vanilla',
        })
    except Exception as e:
        logger.exception('climbers candidates failed')
        return jsonify({'success': False, 'error': str(e)}), 500


@climbers_bp.route('/api/mex/climbers/preview', methods=['GET'])
def climbers_preview():
    """Composite portrait for a prospective pair, so the picker can show it."""
    # Either side may be omitted: the picker previews the first fighter you
    # click rather than staying blank until both are chosen. `composite` already
    # renders a lone fighter on its own.
    leader = (request.args.get('leader') or '').strip()
    partner = (request.args.get('partner') or '').strip()
    if not leader and not partner:
        return jsonify({'success': False, 'error': 'leader or partner is required'}), 400
    try:
        color = int(request.args.get('color', 0))
    except (TypeError, ValueError):
        color = 0
    kind = 'stock' if request.args.get('kind') == 'stock' else 'csp'

    project_path = _project()
    # With both sides chosen, `color` is the PAIR's colour slot, not a costume
    # index: the two fighters' costume lists are matched by colour, so the slot
    # has to be resolved through the same plan the built pair uses. With one
    # side it is just that fighter's own costume.
    lead_color = part_color = color
    if leader and partner:
        plan = color_plan(leader, partner, project_path)
        if 0 <= color < len(plan['leaderForSlot']):
            lead_color = plan['leaderForSlot'][color]
            part_color = plan['partnerForSlot'][color]

    png = composite(fighter_art(leader, lead_color, kind, project_path) if leader else None,
                    fighter_art(partner, part_color, kind, project_path) if partner else None,
                    kind=kind)
    return send_file(io.BytesIO(png), mimetype='image/png')


@climbers_bp.route('/api/mex/climbers/fighter-icon', methods=['GET'])
def climbers_fighter_icon():
    """One fighter's CSS icon, so the picker can show faces instead of a list."""
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'name is required'}), 400
    art = fighter_art(name, 0, 'icon', _project())
    if not art:
        return jsonify({'success': False, 'error': f'no icon for {name}'}), 404
    return send_file(io.BytesIO(art), mimetype='image/png')


@climbers_bp.route('/api/mex/climbers/create', methods=['POST'])
def climbers_create():
    """Store a pair in the vault. No project needed — see the module docstring."""
    data = request.json or {}
    leader = (data.get('leader') or '').strip()
    partner = (data.get('partner') or '').strip()
    if not leader or not partner:
        return jsonify({'success': False, 'error': 'leader and partner are required'}), 400

    project_path = _project()
    eligible = {c['name'].lower(): c for c in candidates(project_path)}
    lead_info, partner_info = eligible.get(leader.lower()), eligible.get(partner.lower())
    if not lead_info or not lead_info['canLead']:
        return jsonify({'success': False, 'error':
                        (lead_info or {}).get('leaderBlockedReason')
                        or f'{leader} cannot lead a pair'}), 422
    if not partner_info or not partner_info['canPartner']:
        return jsonify({'success': False, 'error':
                        (partner_info or {}).get('partnerBlockedReason')
                        or f'{partner} cannot be a partner'}), 422

    # Same fighter twice is allowed: the leader becomes a *duplicate* with its
    # own internal id, so "Fox & Fox" is a Fox clone whose sub-fighter is the
    # original Fox -- two distinct kinds that happen to look alike.
    default_name = f'Double {leader}' if leader.lower() == partner.lower()         else f'{leader} & {partner}'
    name = (data.get('name') or '').strip() or default_name
    # One slot per leader colour. A shorter partner repeats its default rather
    # than costing the leader colours -- see vault.climbers.colors.
    colors = lead_info['costumeCount']

    leader_series = roster.series_id(leader)
    if project_path is not None:
        fighters = load_fighters(project_path)
        from vault.climbers.pairs import find_by_name
        idx = find_by_name(fighters, leader)
        if idx is not None:
            leader_series = fighters[idx].get('seriesID', leader_series)

    try:
        from vault.importing.custom_character_zip import (
            CUSTOM_CHARACTERS_PATH, _make_slug, _append_custom_character)
        from vault.catalog.custom_characters import _dedupe_slug, _read_metadata

        existing = {c['name'].lower()
                    for c in _read_metadata().get('custom_characters', [])}
        if name.lower() in existing:
            return jsonify({'success': False,
                            'error': f'A custom character called "{name}" already exists'}), 409

        # Slug from the two fighter names rather than the display name: the
        # default name is "A & B", and `_make_slug` keeps the ampersand (it only
        # strips filesystem-illegal characters), which then has to survive being
        # a URL path segment in every vault route.
        slug = _dedupe_slug(_make_slug(f'{leader} {partner}'))
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        char_dir.mkdir(parents=True, exist_ok=True)

        # css_icon.png / csp_<i>.png / stock_<i>.png / fighter.json -- the
        # files the vault card and detail page actually read.
        slots = write_vault_assets(char_dir, leader, partner, name, colors,
                                   project_path)

        entry = {
            'slug': slug,
            'name': name,
            'source': 'climbers',
            'date_added': datetime.now().isoformat(),
            'costume_count': len(slots),
            'has_css_icon': True,
            # The pair plays as the leader, so it belongs to the leader's
            # franchise. With a project open the leader's own seriesID wins.
            'series_id': leader_series,
            # The recipe. `pairs.materialize` turns this into a fighter package
            # at install time, against the project being installed into.
            'climbers': {'leader': leader, 'partner': partner},
        }
        _append_custom_character(entry)
    except Exception as e:
        logger.exception('climbers create failed')
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({
        'success': True,
        'character': entry,
        'pair': {'leader': leader, 'partner': partner, 'colors': len(slots)},
    })


