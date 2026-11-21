"""The select-screen grid re-fit the Install page runs after it adds or removes fighters and stages, for MCP.

In the app this math runs in the window, not the backend: after ``/custom-characters/install-batch`` the Install
page re-fits the character select grid (``frontend/src/projects/menus/cssGridLayout.js`` ``computeAutoCssLayout``,
called from ``projects/characters/useCustomCharacters.js``), and after ``/custom-stages/install-batch`` it re-fits
the stage select pages (``autoApplySssGrid`` in ``projects/stages/useCustomStages.js``). That re-fit is what puts
the new icons on the grid. Over MCP there is no window, so build_tools.py runs this port of it and saves the result
through the same ``/menus/css/layout`` and ``/menus/sss/layout`` handlers. It must stay identical to the JS:
``tests/backend/test_app_mcp_build_tools.py`` compares it with the JS module (slow test, through node) and reads the
stage grid's constants out of the hook.
"""
import math

# Vanilla 9x3 grid boundaries (game units): cssGridLayout.js
CSS_VANILLA_WIDTH = 63.45
CSS_VANILLA_HEIGHT = 21.6
CSS_ICON_BASE_WIDTH = 7.05
CSS_ICON_BASE_HEIGHT = 7.2
CSS_GRID_CENTER_X = 0.05
CSS_GRID_CENTER_Y = 9.5

# The stage select grid of useCustomStages.js autoApplySssGrid (page 0, the vanilla page, is left alone).
SSS_COLUMNS = 6
SSS_BASE_W = 5.95
SSS_BASE_H = 5.21
SSS_SPACING_X = 0.8
SSS_SPACING_Y = 0.6
SSS_CENTER_X = 0
SSS_CENTER_Y = 5.5


def grid_icons(icons, alt_external_ids=()):
    """The icons that take a grid slot: everything but tucked L-load alternates."""
    if not alt_external_ids:
        return list(icons)
    tucked = set(alt_external_ids)
    return [icon for icon in icons if icon.get('fighter') not in tucked]


def apply_css_template(icons, template, alt_external_ids=()):
    """applyCssTemplate: lay the icons out on the template grid, rows centred, edge columns dropped."""
    per_row = template['iconsPerRow']
    scale_x, scale_y = template['scaleX'], template['scaleY']
    center_x, center_y = template['centerX'], template['centerY']
    icon_w, icon_h = template['iconWidth'], template['iconHeight']
    drop_x = template.get('iconSideDropX', 0)
    drop_y = template.get('iconSideDropY', 0)
    drop_z = template.get('iconSideDropZ', 0)
    tucked = set(alt_external_ids)
    count = len(grid_icons(icons, alt_external_ids))
    if count == 0 or per_row <= 0:
        return icons
    rows = math.ceil(count / per_row)
    iw = icon_w * scale_x
    ih = icon_h * scale_y
    total_w = min(count, per_row) * iw
    total_h = rows * ih
    out, slot = [], 0
    for icon in icons:
        if icon.get('fighter') in tucked:
            out.append(icon)
            continue
        i = slot
        slot += 1
        col = i % per_row
        row = i // per_row
        in_row = count - row * per_row if row == rows - 1 else per_row
        edge = col == 0 or col == in_row - 1
        row_offset_x = (per_row - in_row) * iw / 2
        x = center_x - total_w / 2 + iw * col + iw / 2 + row_offset_x
        y = center_y + total_h / 2 - ih * row - ih / 2
        z, off_x, off_y = 0, 0, 0
        if edge:
            off_x, off_y, z = -drop_x, -drop_y, drop_z
        out.append({**icon, 'x': x, 'y': y, 'z': z, 'scaleX': scale_x, 'scaleY': scale_y,
                    'collisionSizeX': icon_w, 'collisionSizeY': icon_h,
                    'collisionOffsetX': off_x, 'collisionOffsetY': off_y})
    return out


def build_css_grid_template(template, count, cols):
    """buildCssGridTemplate: a cols-wide grid of count icons, scaled per axis to fill the vanilla box."""
    rows = max(1, math.ceil(count / cols))
    return {**template, 'iconsPerRow': cols,
            'scaleX': CSS_VANILLA_WIDTH / (cols * CSS_ICON_BASE_WIDTH),
            'scaleY': CSS_VANILLA_HEIGHT / (rows * CSS_ICON_BASE_HEIGHT),
            'iconWidth': CSS_ICON_BASE_WIDTH, 'iconHeight': CSS_ICON_BASE_HEIGHT,
            'centerX': CSS_GRID_CENTER_X, 'centerY': CSS_GRID_CENTER_Y}


def pick_auto_columns(count):
    """pickAutoColumns: the column count that keeps the icons closest to their vanilla aspect."""
    if count <= 0:
        return 9
    best_cols, best_score = min(count, 9), float('-inf')
    for rows in range(1, min(8, count) + 1):
        cols = math.ceil(count / rows)
        score = min(CSS_VANILLA_WIDTH / (cols * CSS_ICON_BASE_WIDTH),
                    CSS_VANILLA_HEIGHT / (rows * CSS_ICON_BASE_HEIGHT))
        if score > best_score + 1e-9:
            best_score, best_cols = score, cols
    return best_cols


def auto_css_layout(icons, template, alt_external_ids=()):
    """computeAutoCssLayout: {icons, template} ready for POST /menus/css/layout."""
    count = len(grid_icons(icons, alt_external_ids))
    new_template = build_css_grid_template(template, count, pick_auto_columns(count))
    return {'icons': apply_css_template(icons, new_template, alt_external_ids), 'template': new_template}


def auto_sss_pages(pages):
    """autoApplySssGrid: every page but the first (vanilla) laid out six wide. -> pages for POST /menus/sss/layout."""
    out = []
    for index, page in enumerate(pages):
        icons = page.get('icons') or []
        if index == 0 or not icons:
            out.append(page)
            continue
        rows = math.ceil(len(icons) / SSS_COLUMNS)
        iw, ih = SSS_BASE_W + SSS_SPACING_X, SSS_BASE_H + SSS_SPACING_Y
        total_w = min(len(icons), SSS_COLUMNS) * iw - SSS_SPACING_X
        total_h = rows * ih - SSS_SPACING_Y
        placed = []
        for i, icon in enumerate(icons):
            col, row = i % SSS_COLUMNS, i // SSS_COLUMNS
            placed.append({**icon, 'x': SSS_CENTER_X - total_w / 2 + iw * col + SSS_BASE_W / 2,
                           'y': SSS_CENTER_Y + total_h / 2 - ih * row - SSS_BASE_H / 2,
                           'z': 0, 'scaleX': 1.0, 'scaleY': 1.0})
        out.append({**page, 'icons': placed})
    return out
