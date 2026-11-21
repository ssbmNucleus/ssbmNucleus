"""Inspect and edit Melee mod files (HSD DAT/USD costumes) in the workspace.

Every edit writes a NEW file; the file you pass in is never modified. These are
thin wrappers over the same headless HSDRaw operations the Nucleus app uses.

Typical texture edit:

    dat = vault.extract_member('Fox', skin_id)            # get a costume DAT
    info = modfile.inspect(dat)                           # roots + texture list
    parts = modfile.describe_parts(dat, part='hair', character='Fox')
    # ^ ASK FIRST. It names the textures a part lives on, says when another part
    # shares them, and answers `unresolved` rather than guessing. A shared or
    # unresolved scope is a decision to put to the user, not an index to edit.
    modfile.texture_sheet(dat, info['roots'][0], 'out/sheet.png')   # LOOK at it
    modfile.export_texture(dat, node, 12, 'out/hair.png')
    ... edit out/hair.png with PIL ...
    edited = modfile.replace_texture(dat, node, 12, 'out/hair.png', 'out/edited.dat')
    modfile.pack_costume(edited, 'out/goku-blue.zip')
"""
import shutil
import zipfile
from pathlib import Path

from ._workspace import in_path, out_path


def _handle(path):
    """Register a workspace/vault file with the app's file store, returning its id."""
    from shared import mod_files as files
    path = Path(path)
    return files.register(path.read_bytes(), path.name)['file_id']


def _emit(result, destination, default_name, *, suffix=None):
    from shared import mod_files as files
    wanted = [f for f in result.get('files', [])
              if suffix is None or Path(f['name']).suffix.lower() == suffix]
    if not wanted:
        raise ValueError('The operation produced no file. Log: ' + str(result.get('log', ''))[-500:])
    source, _ = files.resolve(wanted[0]['file_id'])
    target = out_path(destination, default_name=default_name)
    shutil.copyfile(source, target)
    return str(target)


def inspect(path):
    """Describe a mod file: ZIP members, or a DAT's root symbols and textures.

    Args:
        path: workspace path to a .zip, .dat/.usd, .png or model file.

    Returns:
        dict: for a ZIP, ``{'members': [{'name', 'size', ...}], ...}``; for a
        DAT, ``{'roots': ['PlyFox5K_Share_joint', ...], 'textures': [{'node',
        'texture_index', 'width', 'height', 'format'}, ...]}``. ``node`` +
        ``texture_index`` are what the texture calls below take.

    Example:
        >>> modfile.inspect('out/PlFxNr.dat')['roots']
        ['PlyFox5K_Share_joint', 'PlyFox5K_Share_matanim_joint', ...]
    """
    from shared.mod_files import inspect_mod_file
    return inspect_mod_file(_handle(in_path(path)))


def list_textures(path):
    """List every texture in a costume DAT, in the index order the tools use.

    Args:
        path: workspace path to a .dat/.usd costume.

    Returns:
        list[dict]: ``{'node': str, 'texture_index': int, 'width': int,
        'height': int, 'format': str}``. ``texture_index`` is per node.

    Example:
        >>> modfile.list_textures('out/PlFxNr.dat')[:1]
        [{'node': 'PlyFox5K_Share_joint', 'texture_index': 0, 'width': 64,
          'height': 64, 'format': 'CMP'}]
    """
    from shared.mod_files import texture_inventory
    return texture_inventory(in_path(path))


def describe_parts(path, part=None, character=None, viewer=True, previous=None):
    """Name a costume's textures ONCE: identity, parts, and what an edit escapes into.

    ``list_textures`` hands back one row per TOBJ in DAT-walk order, and the
    Skin Lab viewer hands back a de-duplicated list in its own order. Neither
    ordinal is the texture. This gives every texture a ``texture_id`` built from
    the source DAT hash and the HSD_Image descriptor it points at, records every
    ordinal as an alias of it, and separates what is DEMONSTRATED from what is
    not:

    * ``shared_texels`` / ``shared_palettes`` - descriptors reading one copy of
      the pixels or one TLUT, grouped across the whole file. An edit to any
      member is an edit to all of them.
    * ``co_owned_with`` - one descriptor two parts both name (Mario's cap emblem
      sits in a texture the cap also uses). A part with a co-owner is never
      ``exclusive``, and ``required_mask`` says what would have to narrow it.
    * ``overlapping_texels`` - whether two parts read the SAME texels of a
      shared image. NOT measured: the renderer pools UV triangles per image, so
      this is reported as unmeasured rather than assumed.

    Ask for a ``part`` before editing one. A part the vanilla map cannot place
    comes back ``scope='unresolved'`` with unconfirmed candidates and a stop -
    a guess must not authorize an edge-to-edge edit of a texture 17 meshes read.

    Args:
        path: workspace path to a .dat/.usd costume.
        part: optional part name to resolve, e.g. 'hair'.
        character: fighter name, which lets the vanilla part map name parts.
            Taken from the file's own origin when it has one.
        viewer: open a private Skin Lab session for the UV layout and
            geometry-based part matching. False (or a machine without the
            renderer) still produces the full map - it is read from the DAT.
        previous: a report from :func:`describe_parts` on the DAT this one was
            written from. Reserialization changes every id, so a new mapping is
            generated and each texture carries ``previous_texture_id`` - only
            where the correspondence is unambiguous.

    Returns:
        dict: ``{'mapping_version', 'source', 'viewer', 'textures': [{'texture_id',
        'facade': [{'node', 'texture_index'}], 'nodes', 'viewer_index', 'width',
        'height', 'format', 'descriptor', 'palettes', 'usages',
        'shares_texels_with', 'shares_palette_with', 'duplicate_content_of',
        'parts', 'uv_mask'}], 'parts': {name: {'texture_ids', 'facade_indices',
        'provenance', 'scope', 'co_owned_with', 'overlapping_texels',
        'separable_by_mask', 'required_mask', 'stop'}}, 'shared_texels',
        'shared_palettes', 'shared_descriptors', 'multi_palette_images',
        'duplicate_content', 'uv_masks', 'unresolved'}``, plus
        ``'requested_part'`` when ``part`` was given. ``scope`` is
        ``'exclusive'``, ``'shared'`` or ``'unresolved'``.

    Example:
        >>> report = modfile.describe_parts('out/PlFxNrMod.dat', part='hair',
        ...                                 character='Fox', viewer=False)
        >>> report['requested_part']['scope']          # a ported costume: unknown
        'unresolved'
        >>> widest = report['requested_part']['candidates'][0]
        >>> widest['confirmed'], widest['shared_storage'], widest['meshes']
        (False, True, 17)
        >>> sorted(f['texture_index'] for f in widest['facade_indices'])
        [0, 1, 4, 5, 6, 7, 8, 9, 10, 12, 13, 39, 72, 73, 74, 75, 76]
    """
    from shared.rendering import part_identity
    source = in_path(path)
    origin = dict(_origin(source))
    if character:
        origin['character'] = character
    mapping = part_identity.build_map(source, origin)
    if viewer:
        session = _lab_viewer(source, origin.get('character'))
        if session is not None:
            part_identity.attach_viewer(mapping, session)
    part_identity.label_parts(mapping)
    report = part_identity.describe(mapping, part=part)
    if previous:
        part_identity.rebase(previous, report)
    return report


def _origin(source):
    """The costume code the filename carries, e.g. PlFxNrMod.dat -> PlFxNr.

    Only a hint: the part map checks it against the costume's own texture
    layout and ignores it when they disagree.
    """
    code = source.stem[:6]
    return {'costume_code': code} if code[:2].lower() == 'pl' and len(code) == 6 else {}


def _lab_viewer(source, character):
    """A finished private Skin Lab session's lists, or None when unavailable."""
    from shared.rendering import lab_session, part_identity
    captured = lab_session.textures_and_masks(source, character)
    if not captured:
        return None
    textures, layout, pixels = captured
    return part_identity.DetachedViewer(textures, layout, pixels)


def list_meshes(path, node):
    """Report the meshes (DOBJs) under one node: index, vertices, bones, textures.

    Args:
        path: workspace path to a .dat/.usd costume.
        node: a root symbol from :func:`inspect`, e.g. 'PlyFox5K_Share_joint'.

    Returns:
        str: the tool's report, one block per mesh index.

    Example:
        >>> print(modfile.list_meshes('out/PlFxNr.dat', 'PlyFox5K_Share_joint'))
    """
    from randall.assistant.hsdraw import hsdraw
    return hsdraw('meshes', _handle(in_path(path)), node=node)['log']


def texture_sheet(path, node, destination=None):
    """Render ONE labelled contact sheet of every texture under a node.

    Look at this image before choosing a ``texture_index`` - the number printed
    under each tile is that texture's index.

    Args:
        path: workspace path to a .dat/.usd costume.
        node: a root symbol from :func:`inspect`.
        destination: workspace PNG path. Defaults to ``out/texture-sheet.png``.

    Returns:
        str: absolute path of the PNG.

    Example:
        >>> modfile.texture_sheet('out/PlFxNr.dat', 'PlyFox5K_Share_joint', 'out/sheet.png')
        'C:/.../workspace/out/sheet.png'
    """
    from randall.assistant.hsdraw import hsdraw
    result = hsdraw('texture_sheet', _handle(in_path(path)), node=node)
    return _emit(result, destination, 'texture-sheet.png', suffix='.png')


def export_texture(path, node, texture_index, destination=None):
    """Export one texture out of a costume DAT as a PNG.

    Args:
        path: workspace path to a .dat/.usd costume.
        node: a root symbol from :func:`inspect`.
        texture_index: integer index from :func:`list_textures` or the sheet.
        destination: workspace PNG path. Defaults to ``out/texture-<index>.png``.

    Returns:
        str: absolute path of the PNG.

    Example:
        >>> modfile.export_texture('out/PlFxNr.dat', 'PlyFox5K_Share_joint', 12, 'out/hair.png')
        'C:/.../workspace/out/hair.png'
    """
    from randall.assistant.hsdraw import hsdraw
    result = hsdraw('export_texture', _handle(in_path(path)), node=node, texture_index=texture_index)
    return _emit(result, destination, f'texture-{texture_index}.png', suffix='.png')


def replace_texture(path, node, texture_index, png_path, destination=None):
    """Write a NEW costume DAT with one texture replaced by a PNG.

    The input DAT is not modified. The PNG is re-encoded to the slot's Melee
    texture format by the same importer the app uses.

    Args:
        path: workspace path to the source .dat/.usd costume.
        node: a root symbol from :func:`inspect`.
        texture_index: integer index of the texture to overwrite.
        png_path: workspace path to the replacement PNG.
        destination: workspace .dat path for the result. Defaults to
            ``out/<name>-edited.dat``.

    Returns:
        str: absolute path of the new DAT.

    Example:
        >>> modfile.replace_texture('out/PlFxNr.dat', 'PlyFox5K_Share_joint', 12,
        ...                         'out/hair-blue.png', 'out/PlFxNr-blue.dat')
        'C:/.../workspace/out/PlFxNr-blue.dat'
    """
    from randall.assistant.hsdraw import hsdraw
    source = in_path(path)
    result = hsdraw('replace_texture', _handle(source), node=node, texture_index=texture_index,
                    replacement_file_id=_handle(in_path(png_path)))
    return _emit(result, destination, f'{source.stem}-edited.dat', suffix='.dat')


def export_model(path, node, destination=None):
    """Export the model under a node as an SMD (textures land beside it).

    Args:
        path: workspace path to a .dat/.usd costume.
        node: a root symbol from :func:`inspect`.
        destination: workspace .smd path. Defaults to ``out/<name>.smd``.

    Returns:
        str: absolute path of the SMD.

    Example:
        >>> modfile.export_model('out/PlFxNr.dat', 'PlyFox5K_Share_joint', 'out/fox.smd')
        'C:/.../workspace/out/fox.smd'
    """
    from randall.assistant.hsdraw import hsdraw
    source = in_path(path)
    result = hsdraw('export_model', _handle(source), node=node)
    return _emit(result, destination, f'{source.stem}.smd', suffix='.smd')


def pack_costume(dat_path, destination=None, member_name=None):
    """Zip a costume DAT into a Nucleus-importable costume archive.

    Args:
        dat_path: workspace path to the .dat/.usd costume.
        destination: workspace .zip path. Defaults to ``out/<name>.zip``.
        member_name: filename inside the ZIP. Defaults to the DAT's own name,
            which should be its costume code (e.g. 'PlFxNr.dat').

    Returns:
        str: absolute path of the ZIP.

    Example:
        >>> modfile.pack_costume('out/PlFxNr-blue.dat', 'out/goku-blue.zip', 'PlFxNr.dat')
        'C:/.../workspace/out/goku-blue.zip'
    """
    source = in_path(dat_path)
    target = out_path(destination, default_name=f'{source.stem}.zip')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name or source.name, source.read_bytes())
    return str(target)
