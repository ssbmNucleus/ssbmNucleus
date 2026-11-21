"""Render a costume offline so you can LOOK at what you made.

This is the app's own portrait renderer (the one that builds the character
select portrait and the stock icon when a costume is imported), pointed at a
file in the workspace.

Worked example::

    out = render.costume_preview('out/PlFxNr-blue.dat', 'Fox', 'PlFxNr')
    out['csp_path']     # 'C:/.../out/PlFxNr-blue-csp.png'  -> open it and look
    out['stock_path']   # 'C:/.../out/PlFxNr-blue-stock.png'
    out['csp_source']   # 'generated'

There is no offline renderer for menu screens or stages here - a costume is what
this draws.
"""
from pathlib import Path

from ._workspace import in_path, out_path


def costume_preview(dat_path, character, costume_code=None,
                    csp_destination=None, stock_destination=None):
    """Render a costume DAT to a character-select portrait and a stock icon.

    Args:
        dat_path: workspace path to a .dat/.usd costume.
        character: fighter the costume is for, e.g. 'Fox'. The renderer needs
            it to pick the right pose, camera and skeleton.
        costume_code: e.g. 'PlFxNr'. Defaults to the file's own stem.
        csp_destination: workspace PNG path for the portrait. Defaults to
            ``out/<name>-csp.png``.
        stock_destination: workspace PNG path for the stock icon. Defaults to
            ``out/<name>-stock.png``.

    Returns:
        dict: ``{'csp_path': str|None, 'csp_source': str, 'stock_path': str|None,
        'stock_source': str}``. ``*_source`` is provenance: 'generated',
        'vanilla', 'missing' and so on.

    Example:
        >>> from nucleus_api import render
        >>> render.costume_preview('out/PlFxNr-blue.dat', 'Fox')
        {'csp_path': 'C:/.../out/PlFxNr-blue-csp.png', 'csp_source': 'generated', ...}
    """
    from shared.rendering.costume_assets import build_csp_and_stock
    source = in_path(dat_path)
    code = costume_code or source.stem
    result = build_csp_and_stock(character, code, source.read_bytes())
    csp_path = stock_path = None
    if result.get('csp'):
        target = out_path(csp_destination, default_name=f'{source.stem}-csp.png')
        target.write_bytes(result['csp'])
        csp_path = str(target)
    if result.get('stock'):
        target = out_path(stock_destination, default_name=f'{source.stem}-stock.png')
        target.write_bytes(result['stock'])
        stock_path = str(target)
    return {'csp_path': csp_path, 'csp_source': result.get('csp_source'),
            'stock_path': stock_path, 'stock_source': result.get('stock_source')}


def costume_preview_from_zip(zip_path, character, member=None, **kwargs):
    """Same as :func:`costume_preview`, starting from a costume ZIP.

    Args:
        zip_path: workspace path to a costume .zip.
        character: fighter name.
        member: exact member to render; defaults to the archive's only DAT.
        **kwargs: passed through to :func:`costume_preview`.

    Returns:
        dict: same as :func:`costume_preview`.

    Example:
        >>> render.costume_preview_from_zip('out/goku-blue.zip', 'Fox')['csp_path']
        'C:/.../workspace/out/PlFxNr-csp.png'
    """
    import tempfile
    import zipfile
    source = in_path(zip_path)
    with zipfile.ZipFile(source) as archive:
        names = [e.filename for e in archive.infolist() if not e.is_dir()]
        if member is None:
            dats = [n for n in names if Path(n).suffix.lower() in {'.dat', '.usd'}]
            if len(dats) != 1:
                raise ValueError(f'Name the member to render; this archive holds {names}.')
            member = dats[0]
        data = archive.read(member)
    with tempfile.TemporaryDirectory(prefix='nucleus-api-render-') as scratch:
        extracted = Path(scratch) / Path(member).name
        extracted.write_bytes(data)
        from shared.rendering.costume_assets import build_csp_and_stock
        code = kwargs.pop('costume_code', None) or extracted.stem
        result = build_csp_and_stock(character, code, data)
    csp_path = stock_path = None
    if result.get('csp'):
        target = out_path(kwargs.get('csp_destination'), default_name=f'{Path(member).stem}-csp.png')
        target.write_bytes(result['csp'])
        csp_path = str(target)
    if result.get('stock'):
        target = out_path(kwargs.get('stock_destination'), default_name=f'{Path(member).stem}-stock.png')
        target.write_bytes(result['stock'])
        stock_path = str(target)
    return {'csp_path': csp_path, 'csp_source': result.get('csp_source'),
            'stock_path': stock_path, 'stock_source': result.get('stock_source')}
