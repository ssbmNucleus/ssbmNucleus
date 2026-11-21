# nucleus_api

Auto-generated from the docstrings by `python -m nucleus_api.gendocs`.
Do not edit by hand.

nucleus_api - a small, documented library over what SSBM Nucleus already does.

Import it and write Python. Every module is read-only towards the user's vault
(``app/storage``); anything this library produces is written into the
WORKSPACE, and it refuses to write anywhere else.

Modules:
    vault     Fighters, costumes and their archives in the local vault.
    modfile   Inspect and edit Melee mod files (textures, meshes) in the workspace.
    menus     Character-select / stage-select screen backdrops.
    website   Search ssbmnucleus.net and download mods into the workspace.
    codes     Gecko codes a build needs beside its files.
    render    Render a costume to a portrait PNG so you can look at it.
    game      Boot a costume in the actual game and photograph named moves.
    builds    Install a prepared menu and its codes into the build you play.

Example:
    >>> from nucleus_api import vault, modfile, render
    >>> skin = vault.find_costumes('goku fox')[0]
    >>> dat = vault.extract_member(skin['character'], skin['id'], destination='out/goku.dat')
    >>> modfile.texture_sheet(dat, modfile.inspect(dat)['roots'][0], 'out/sheet.png')
    >>> render.costume_preview(dat, 'Fox')

Conventions:
    * Paths in and out are plain strings, RELATIVE to the workspace
      (``NUCLEUS_API_WORKSPACE``, or ``use_workspace(root)``). An absolute
      path is accepted only when it is inside the workspace. There is no
      fall back to the current directory.
    * Any function that writes takes a ``destination``. It returns either the
      path it wrote (a string) or a dict whose ``path``/``*_path`` keys are the
      files it wrote; each docstring's Returns section says which. Pass the
      PATH, never the dict, to the next call.
    * Errors are ``ValueError`` with a sentence that says what to do instead.

---

## `nucleus_api.vault`

Read-only view of the local Nucleus vault (fighters, costumes, archives).

Nothing here modifies the vault. Functions that produce a file copy it into the
workspace.

Worked example - take a costume out of the vault, look at it, edit it, look
again::

    skin = vault.find_costumes('goku fox')[0]
    skin['id']                       # 'DBZ Pack _ Goku Fox-plfxnr-goku-fox'
    skin['csp_path']                 # the portrait the vault already has

    dat  = vault.extract_member(skin['character'], skin['id'],
                                destination='out/PlFxNr.dat')
    node = modfile.inspect(dat)['roots'][0]          # 'PlyFox5K_Share_joint'
    modfile.texture_sheet(dat, node, 'out/sheet.png')          # LOOK at this
    png  = modfile.export_texture(dat, node, 12, 'out/hair.png')
    # ... recolour out/hair.png with PIL ...
    new  = modfile.replace_texture(dat, node, 12, 'out/hair.png', 'out/blue.dat')
    modfile.pack_costume(new, 'out/goku-blue.zip', 'PlFxNr.dat')
    render.costume_preview(new, 'Fox', 'PlFxNr')     # LOOK at the result

### `vault.copy_costume(character, skin_id, destination=None)`

Copy a vault costume ZIP into the workspace so you can work on it.

The vault copy is never touched.

Args:
    character: fighter name.
    skin_id: the ``id`` from :func:`list_costumes`.
    destination: workspace path for the copy. Defaults to ``out/<skin_id>.zip``.

Returns:
    str: absolute path of the copy in the workspace.

Example:
    >>> vault.copy_costume('Fox', 'DBZ Pack _ Goku Fox-plfxnr-goku-fox', 'out/goku.zip')
    'C:/.../workspace/out/goku.zip'

### `vault.extract_member(character, skin_id, member=None, destination=None)`

Extract one file out of a vault costume ZIP into the workspace.

Args:
    character: fighter name.
    skin_id: the ``id`` from :func:`list_costumes`.
    member: exact member name from :func:`read_archive`. When omitted, the
        archive's single .dat/.usd costume file is used, and an archive with
        several raises.
    destination: workspace path. Defaults to ``out/<member filename>``.

Returns:
    str: absolute path of the extracted file.

Example:
    >>> vault.extract_member('Fox', 'DBZ Pack _ Goku Fox-plfxnr-goku-fox')
    'C:/.../workspace/out/PlFxNr.dat'

### `vault.find_costumes(words, character='')`

Find vault costumes whose name, colour, character or id contain all words.

Args:
    words: search text, e.g. 'goku fox'. Every whitespace-separated word
        must appear somewhere in the item.
    character: optional fighter-name filter (substring, case-insensitive).

Returns:
    list[dict]: same shape as :func:`list_costumes`, across all fighters.

Example:
    >>> vault.find_costumes('goku')[0]['character']
    'Fox'

### `vault.list_costumes(character)`

List every costume the vault holds for one fighter.

Args:
    character: exact fighter name from :func:`list_fighters`, e.g. 'Fox'.

Returns:
    list[dict]: each entry has ``id`` (the skin id you pass to other calls),
    ``name``, ``variant`` (colour slot), ``costume_code`` (e.g. 'PlFxNr'),
    ``zip_path`` (the archive in the vault, read-only), ``csp_path`` and
    ``stock_path`` (PNGs, or None), and ``slippi_safe``.

Example:
    >>> vault.list_costumes('Fox')[0]['id']
    'DBZ Pack _ Goku Fox-plfxnr-goku-fox'

### `vault.list_fighters()`

List the fighters that have costumes in the vault.

Returns:
    list[dict]: one entry per fighter, sorted by name, each
    ``{'character': str, 'costume_count': int}``.

Example:
    >>> from nucleus_api import vault
    >>> vault.list_fighters()[:1]
    [{'character': 'Bowser', 'costume_count': 12}]

### `vault.read_archive(character, skin_id)`

List what is inside a vault costume ZIP without extracting anything.

Args:
    character: fighter name.
    skin_id: the ``id`` from :func:`list_costumes`.

Returns:
    dict: ``{'zip_path': str, 'members': [{'name': str, 'size': int}, ...]}``.

Example:
    >>> vault.read_archive('Fox', 'DBZ Pack _ Goku Fox-plfxnr-goku-fox')['members']
    [{'name': 'PlFxNr.dat', 'size': 1234567}]

---

## `nucleus_api.modfile`

Inspect and edit Melee mod files (HSD DAT/USD costumes) in the workspace.

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

### `modfile.describe_parts(path, part=None, character=None, viewer=True, previous=None)`

Name a costume's textures ONCE: identity, parts, and what an edit escapes into.

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

### `modfile.export_model(path, node, destination=None)`

Export the model under a node as an SMD (textures land beside it).

Args:
    path: workspace path to a .dat/.usd costume.
    node: a root symbol from :func:`inspect`.
    destination: workspace .smd path. Defaults to ``out/<name>.smd``.

Returns:
    str: absolute path of the SMD.

Example:
    >>> modfile.export_model('out/PlFxNr.dat', 'PlyFox5K_Share_joint', 'out/fox.smd')
    'C:/.../workspace/out/fox.smd'

### `modfile.export_texture(path, node, texture_index, destination=None)`

Export one texture out of a costume DAT as a PNG.

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

### `modfile.inspect(path)`

Describe a mod file: ZIP members, or a DAT's root symbols and textures.

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

### `modfile.list_meshes(path, node)`

Report the meshes (DOBJs) under one node: index, vertices, bones, textures.

Args:
    path: workspace path to a .dat/.usd costume.
    node: a root symbol from :func:`inspect`, e.g. 'PlyFox5K_Share_joint'.

Returns:
    str: the tool's report, one block per mesh index.

Example:
    >>> print(modfile.list_meshes('out/PlFxNr.dat', 'PlyFox5K_Share_joint'))

### `modfile.list_textures(path)`

List every texture in a costume DAT, in the index order the tools use.

Args:
    path: workspace path to a .dat/.usd costume.

Returns:
    list[dict]: ``{'node': str, 'texture_index': int, 'width': int,
    'height': int, 'format': str}``. ``texture_index`` is per node.

Example:
    >>> modfile.list_textures('out/PlFxNr.dat')[:1]
    [{'node': 'PlyFox5K_Share_joint', 'texture_index': 0, 'width': 64,
      'height': 64, 'format': 'CMP'}]

### `modfile.pack_costume(dat_path, destination=None, member_name=None)`

Zip a costume DAT into a Nucleus-importable costume archive.

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

### `modfile.replace_texture(path, node, texture_index, png_path, destination=None)`

Write a NEW costume DAT with one texture replaced by a PNG.

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

### `modfile.texture_sheet(path, node, destination=None)`

Render ONE labelled contact sheet of every texture under a node.

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

---

## `nucleus_api.menus`

Melee menu screens: the CSS (character select) and SSS (stage select) backdrops.

A menu background is not a flat image - it is a 3D model bundle
(``background.dat``) that lives inside ``MnSlChr.usd`` (CSS) or ``MnSlMap.usd``
(SSS). Nucleus swaps the bundle; it cannot paste a PNG onto the screen.

The offline workflow, all inside the workspace:

    packs = menus.list_background_mods()                 # already-imported pool
    bg    = menus.export_background_mod(packs[0]['id'], 'out/background.dat')
    # or, from a mod downloaded off the website:
    bg    = menus.extract_background('out/halo-css.zip', 'out/background.dat')['path']

    src   = menus.list_menu_files()                      # MnSlChr.usd / MnSlMap.usd
    out   = menus.install_background(bg, 'out/MnSlChr.usd', menu_type='css',
                                     menu_file=src[0]['path'])['path']

### `menus.check_compatibility(path, menu_type='css', target=None, existing_codes=None, extra_codes=None, enable_disabled=False, native=True)`

Judge a menu artifact against a build, in the three dimensions that matter.

``structure`` (does the file's graph resolve, does it carry a background the
loader would follow, does the native reader agree), ``target`` (was this
package observed to work on a build like this one, by an observation that
records what it observed) and ``codes`` (does the COMPLETE final code set
merge without a name clash, without two codes writing one address different
values, and without silently flipping a disabled code on).

"It looks like a vanilla menu file" is never evidence: an unlisted package,
or a listed one whose observation does not cover this build, is ``unknown``.

Args:
    path: workspace path to the artifact that would be installed. Pass the
        SEALED copy if one exists - a mutable source can change afterwards.
    menu_type: ``'css'`` or ``'sss'``.
    target: the build's signature from
        :func:`nucleus_api.builds.target_signature`, or None to leave the
        target dimension ``unknown``.
    existing_codes: the build's current codes, so the ``codes`` dimension
        reports a real merge instead of a wish list.
    extra_codes: codes the caller is adding on top of the package's own
        requirement. They are part of the set that gets judged.
    enable_disabled: the proposal explicitly asks to enable a required code
        the build carries disabled.
    native: also reopen the file through :data:`NATIVE_MENU_READER`.

Returns:
    dict: ``{'status', 'structure', 'target', 'codes', 'package',
    'manifest_version', 'required_codes', 'limitations'}``. ``status`` is
    the worst of the three dimensions (``fail`` beats ``unknown`` beats
    ``pass``).

Example:
    >>> menus.check_compatibility('out/MnSlChr.usd', 'css')['structure']['status']
    'pass'

### `menus.compatibility_manifest()`

The versioned list of menu packages this install knows anything about.

Shipped beside the backend (``data/menus/compatibility_manifest.json``) and
seeded from the menu fixtures of the 2026-09-22 harness experiment. A
package that is not listed can still be inspected and installed - it simply
inherits nothing from a package that looks similar.

Returns:
    dict: ``{'manifest_version', 'policy', 'menu_roots', 'packages': [...]}``.
    ``{'manifest_version': 0, 'packages': []}`` when the file is missing
    from this installation, which makes every judgement ``unknown`` rather
    than optimistic.

Example:
    >>> from nucleus_api import menus
    >>> [p['package_id'] for p in menus.compatibility_manifest()['packages']][:1]
    ['halo3-matchmaking-lobby']

### `menus.dat_integrity(path)`

Walk a HAL DAT's header, relocation table and roots, and say if it holds.

Reading a root's NAME proves nothing: the app's own detection parser
discards the root's data pointer, so a file whose root points past the end
of its data section still answers "MnSelectChrDataTable". This resolves the
pointers instead:

* the header's file size is the file's real size;
* the data, relocation, root and string tables fit inside the file;
* every relocation entry points into the data section, AND the pointer
  stored at that offset points into the data section too;
* every root's data offset is inside the data section, and its name lies
  inside the string table.

Args:
    path: the .dat/.usd to inspect.

Returns:
    dict: ``{'status': 'pass'|'fail', 'reason', 'roots': [{'name',
    'offset'}], 'root_offsets': {name: offset}, 'data_size', 'relocations',
    'bad_relocations'}``.

Example:
    >>> menus.dat_integrity('out/MnSlChr.usd')['status']
    'pass'

### `menus.dat_integrity_of(data)`

The same walk, over bytes that are already in hand.

Args:
    data: the DAT's bytes.

Returns:
    dict: as :func:`dat_integrity`.

Example:
    >>> menus.dat_integrity_of(blob)['status']
    'pass'

### `menus.export_background_mod(mod_id, destination=None)`

Copy an imported background bundle out of the pool into the workspace.

Args:
    mod_id: the ``id`` from :func:`list_background_mods`.
    destination: workspace .dat path. Defaults to ``out/background.dat``.

Returns:
    str: absolute path of the copy.

Example:
    >>> menus.export_background_mod('2602dc69', 'out/background.dat')
    'C:/.../workspace/out/background.dat'

### `menus.extract_background(pack_path, destination=None, menu_type='css')`

Pull the background bundle out of a downloaded menu mod.

Accepts a ZIP containing MnSlChr/MnSlMap (.dat or .usd), or such a file on
its own. This is the same extraction the app's menu-mod import runs; here it
writes to the workspace instead of the pool.

Args:
    pack_path: workspace path to the downloaded .zip/.dat/.usd.
    destination: workspace .dat path. Defaults to ``out/background.dat``.
    menu_type: which screen to prefer when the pack contains both, 'css' or 'sss'.

Returns:
    dict: ``{'path': str, 'menu_type': 'css'|'sss', 'source_file': str}``.

Example:
    >>> menus.extract_background('out/halo-css.zip', 'out/background.dat')
    {'path': 'C:/.../out/background.dat', 'menu_type': 'css', 'source_file': 'MnSlChr.usd'}

### `menus.identify(path)`

Say what kind of Melee asset a downloaded file is.

Runs the app's own import detection, so the answer is the one the app
would act on. Useful right after :func:`nucleus_api.website.download`,
when the website only said 'other'.

Args:
    path: workspace path to a .dat/.usd/.zip you downloaded or built.

Returns:
    dict: ``{'type': str, 'confidence': str, 'detail': {...},
    'menu_type': 'css'|'sss'|None, 'roots': [str, ...]}``. A character
    select screen comes back as ``type='css_background'`` with
    ``menu_type='css'``; a costume as ``'character'``; a stage as
    ``'stage'``.

Example:
    >>> menus.identify('out/Halo3CSS.dat')
    {'type': 'css_background', 'confidence': 'high', 'menu_type': 'css',
     'roots': ['MnSelectChrDataTable', ...], ...}

### `menus.identify_package(path)`

Match a file against the compatibility manifest by its bytes.

Args:
    path: workspace path to a menu file or background bundle.

Returns:
    dict: ``{'package_id', 'name', 'matched_by', 'sha256', 'package'}``, or
    ``{'package_id': None, 'sha256': ..., 'package': None}`` when nothing in
    the manifest has those bytes. A filename never matches: only the digest.

Example:
    >>> menus.identify_package('out/background.dat')['package_id']
    'halo3-matchmaking-lobby'

### `menus.install_background(background_path, destination=None, menu_type='css', menu_file=None, include_scene=False)`

Write a NEW menu file with this background bundle swapped in.

This is the app's own CSS/SSS background install, pointed at a workspace
copy instead of a project. The source menu file is not modified.

Args:
    background_path: workspace path to a ``background.dat`` from
        :func:`export_background_mod` or :func:`extract_background`.
    destination: workspace path for the resulting menu file. Defaults to
        ``out/MnSlChr.usd`` (or ``MnSlMap.usd`` for sss).
    menu_type: 'css' for the character select screen, 'sss' for stage select.
    menu_file: the ``id`` (or the exact ``path``) of an entry from
        :func:`list_menu_files`. Required when this machine has more than
        one candidate for that screen - which build is being changed is the
        caller's decision, not a guess. An arbitrary host path is refused:
        this argument selects from the set the library located, it does not
        name a file.
    include_scene: also carry over the mod's camera/lighting scene.

Returns:
    dict: ``{'path': str, 'menu_type': str, 'source_menu_file': str,
    'gecko_code': str}``. ``gecko_code`` is the code the game also needs so
    the hardcoded CSS backdrop animation stops covering the new one.

Example:
    >>> menus.install_background('out/background.dat', 'out/MnSlChr.usd')
    {'path': 'C:/.../out/MnSlChr.usd', 'menu_type': 'css', ...}

### `menus.list_background_mods(menu_type=None)`

List the menu background bundles already imported into this Nucleus install.

Args:
    menu_type: 'css', 'sss', or None for both. A CSS backdrop and an SSS
        backdrop are different models.

Returns:
    list[dict]: ``{'id', 'name', 'description', 'source' ('css'|'sss'),
    'dat_path' (the background.dat, read-only), 'screenshot_path' (or None)}``.

Example:
    >>> from nucleus_api import menus
    >>> menus.list_background_mods('css')
    [{'id': '2602dc69', 'name': 'Halo 3 Matchmaking Lobby', 'source': 'css', ...}]

### `menus.list_menu_files()`

List the menu screen files available on this machine to edit a copy of.

These are the game's own ``MnSlChr.usd`` (character select) and
``MnSlMap.usd`` (stage select), taken from the currently loaded project when
there is one, otherwise from the extracted builds under the Nucleus storage
folder. They are read-only sources; :func:`install_background` writes its
result into the workspace.

Returns:
    list[dict]: ``{'id': str, 'menu_type': 'css'|'sss', 'name': str,
    'path': str, 'source': str}``, current project first, then storage
    builds in lexical order. ``id`` is what :func:`install_background`
    takes: the menu file is chosen from this set, never named as a free
    host path.

Example:
    >>> menus.list_menu_files()
    [{'id': 'menu_6f1c...', 'menu_type': 'css', 'name': 'MnSlChr.usd', ...}]

### `menus.menu_graph_check(path, menu_type)`

Beyond integrity: does this file's menu table actually carry a background?

The character-select table's background model sits at
``MnSelectChrDataTable+0x10``. This checks that the slot is a RELOCATED
pointer - i.e. a real reference the loader will follow - into the file's own
data section, rather than a zero or a number that merely looks like one.

Args:
    path: the menu file.
    menu_type: ``'css'`` or ``'sss'``.

Returns:
    dict: ``{'status': 'pass'|'fail'|'unknown', 'reason',
    'background_pointer', 'integrity'}``.

Example:
    >>> menus.menu_graph_check('out/MnSlChr.usd', 'css')['status']
    'pass'

### `menus.native_menu_report(path, menu_type)`

Reopen a menu file through HSDRaw and export the background it carries.

This is the strongest structural statement available: the native reader
walks the graph the game walks, and the exported bundle is what can be
compared semantically against the bundle that was meant to be installed.

Args:
    path: the menu file.
    menu_type: ``'css'`` or ``'sss'``.

Returns:
    dict: ``{'status': 'pass'|'fail'|'unknown', 'background_sha256',
    'background_bytes', 'reason'}``. ``unknown`` when HSDRaw is not part of
    this installation - a missing tool is not a passed check.

Example:
    >>> menus.native_menu_report('out/MnSlChr.usd', 'css')['status']
    'pass'

### `menus.preview(menu_file_path=None, reference_image=None, task_id='', task_revision=1, workflow='menu_background_replace', required=False, chat_id='')`

Say what a produced menu file will look like in game - which nothing can.

There is no offline renderer for a menu screen in this application:
HSDRaw cannot navigate a ``bg_model`` root as a JOBJ, and no in-game menu
capture path is verified. So this never returns an image. If one was
published with the mod it returns the author's screenshot tagged
``role='reference'``, so it can never be mistaken for a picture of this
build.

The gap is recorded ONLY when a preview was actually required. Every
prepared build calls this; filing a feature request each time would
manufacture demand out of a routine status line. The verdict comes from
``assistant.tasks.wishes.classify_blocker`` on typed evidence, not from this
module asserting a capability gap on its own.

Args:
    menu_file_path: the produced menu file. Kept in the local result; it
        never becomes wish evidence, because evidence is a typed code and a
        workspace path must not ride out with a submitted request.
    reference_image: workspace path to an author screenshot, if any.
    task_id: the task this gap was hit in, so occurrences can be counted.
    task_revision: that task's revision.
    workflow: the workflow that hit it.
    required: the user asked to SEE the result, or completion genuinely
        depends on it. Only then is anything recorded.
    chat_id: the conversation, which is the unit demand is counted in.

Returns:
    dict: ``{'status': 'unavailable', 'previewed': False, 'reason',
    'artifacts', 'wish', 'wish_recorded'}``. ``wish`` is the chat-free
    public projection or None; ``wish_recorded['stored']`` is the database
    write's own result, and nothing may claim a saved request without it.

Example:
    >>> menus.preview('out/MnSlChr.usd')['status']
    'unavailable'

### `menus.preview_background_mod(mod_id, destination=None)`

Copy a background mod's preview screenshot into the workspace, if it has one.

Background bundles have no offline renderer, so this returns the screenshot
that shipped with the mod, or None when it shipped without one.

Args:
    mod_id: the ``id`` from :func:`list_background_mods`.
    destination: workspace PNG path. Defaults to ``out/<mod_id>-preview.png``.

Returns:
    str | None: absolute path of the image, or None if the mod has no preview.

Example:
    >>> menus.preview_background_mod('2602dc69', 'out/halo-preview.png')
    None   # this one shipped without a screenshot

### `menus.walk_joint_graph(data, start, integrity)`

Walk the joint tree a menu's background hangs off, with a ceiling.

Bounds-checking the pointer says the number is inside the file. It does not
say the loader can follow it: a background whose model is a single joint
with one byte of room after it, or one whose child chain points back at
itself, passed that check and is not a model. This follows the JOBJ child
and next pointers the game follows, with a visited set (so a cycle is
reported, not recursed), a node ceiling and a depth ceiling.

Args:
    data: the whole DAT.
    start: the background model's offset inside the data section.
    integrity: the report from :func:`dat_integrity`.

Returns:
    dict: ``{'status': 'pass'|'fail', 'reason', 'nodes', 'depth',
    'cycle'}``.

Example:
    >>> menus.walk_joint_graph(blob, pointer, report)['nodes']
    41

---

## `nucleus_api.website`

Search ssbmnucleus.net and download published mods into the workspace.

Downloads land in the workspace as plain files. Nothing here imports into the
vault.

Worked example - find a character-select screen mod, look at its screenshots,
download it and find out what it actually is::

    hits = website.search('character select screen background', limit=6)
    for card in hits['website_mods']:
        card['post_id'], card['title'], card['download_count'], card['can_download']
        for url in card['images']:                     # the mod's own screenshots
            website.download_image(url, f"out/shots/{card['post_id']}.png")
    # ... LOOK at those PNGs, then pick one ...

    post = website.inspect_post(16824)['website_mods'][0]
    post['description']; post['files']      # files carry file_id + name + type

    got  = website.download(16824, destination='out/css-mod.zip')
    got['path']                             # 'C:/.../out/css-mod.zip'
    menus.identify(got['path'])             # {'type': 'css_background', 'menu_type': 'css'}

Pass a file's ``file_id`` to download that one file instead of the whole mod.
Every published file type can be downloaded, including menu files the site
labels ``other``.

### `website.download(post_id, file_id=None, destination=None)`

Download a website mod into the workspace (never into the vault).

Args:
    post_id: integer ``post_id`` from :func:`search`.
    file_id: optional integer id of ONE file from :func:`inspect_post`
        (a single costume/stage export). Omit for the whole mod archive.
        Whole mods and non-export files download through the site's
        counted link, so the creator is credited.
    destination: workspace path for the downloaded file. Defaults to
        ``out/<post title>.zip``.

Returns:
    dict: ``{'path': str, 'title': str, 'post_id': int, 'file_id': int|None,
    'size': int, 'url': str}``.

Example:
    >>> website.download(412, destination='out/halo-css.zip')
    {'path': 'C:/.../workspace/out/halo-css.zip', 'title': 'Halo 3 ...', ...}

### `website.download_image(url, destination=None)`

Download one screenshot/preview image from the mod website's media host.

Only ``https://media.ssbmnucleus.net`` URLs (the ``image``/``images`` fields
on a search card) are accepted.

Args:
    url: the image URL from a card.
    destination: workspace path. Defaults to ``out/<filename>``.

Returns:
    str: absolute path of the image.

Example:
    >>> card = website.search('halo 3 lobby')['website_mods'][0]
    >>> website.download_image(card['images'][0], 'out/shots/halo.png')
    'C:/.../workspace/out/shots/halo.png'

### `website.inspect_post(post_id)`

Full detail for one website mod: description, files, screenshots, tags.

Args:
    post_id: integer ``post_id`` from :func:`search`.

Returns:
    dict: ``{'website_mods': [card]}`` where the card also carries
    ``description``, ``files`` (each with ``file_id``, ``name``,
    ``character``, ``color``, ``can_download``) and ``archive_entries``.

Example:
    >>> website.inspect_post(412)['website_mods'][0]['description'][:40]

### `website.search(query='', character='', category='', tags=None, limit=6, cursor=None, sort_by='created_at', sort_order='desc')`

Search published mods on the Nucleus website.

An empty result automatically retries weaker searches (dropping filler
words, expanding abbreviations like 'css' to 'character select screen',
then tags alone), so you usually do not need to re-query by hand.

Args:
    query: free text, e.g. 'css background'.
    character: fighter-name filter, e.g. 'Fox'.
    category: one of CATEGORIES, or '' for all.
    tags: list of tag names to require.
    limit: results per page, 1-24.
    cursor: the ``next_cursor`` of the previous page, with the same other
        arguments; None for the first page.
    sort_by: 'created_at', 'download_count' or 'like_count'.
    sort_order: 'asc' or 'desc'.

Returns:
    dict: ``{'website_mods': [card, ...], 'website_total': int,
    'next_cursor': str|None, ...}``. Each card
    has ``post_id``, ``title``, ``author``, ``url``, ``tags``,
    ``download_count``, ``like_count``, ``file_count``, ``can_download``
    and ``default_file_id`` (a single-variant export, or None).

Example:
    >>> from nucleus_api import website
    >>> hits = website.search('character select screen background', limit=5)
    >>> [m['title'] for m in hits['website_mods']]
    ['Halo 3 Matchmaking Lobby CSS', ...]

---

## `nucleus_api.codes`

Gecko codes - the little patches a build needs beside its files.

Some menu mods only work with a code (a custom character-select backdrop needs
"Disable Hardcoded CSS Animations", or Melee's own animation draws over it).
Mod descriptions publish those codes as text; this module turns that text into
the code list a build uses, and writes it into the workspace.

    text  = '$Disable Hardcoded CSS Animations\n04263384 48000010'
    found = codes.parse(text)
    codes.write_code_list(found['codes'], 'out/codes.ini')

### `codes.address_conflicts(entries)`

Find codes that patch the same address with different values.

This is the interaction a name comparison cannot see. Two entries writing
the same address with the same value are redundant, not conflicting; two
writing it with different values are a conflict whichever order the loader
applies them in. A code the analyzer cannot decode makes the whole set
``unresolved``, because an unmodelled opcode may write anywhere.

Args:
    entries: the final code set, each with ``name``/``source``.

Returns:
    dict: ``{'conflicts': [{'address', 'writers': [...]}], 'redundant':
    [...], 'unresolved': [{'identity', 'opcodes'}], 'analyzed': int}``.

Example:
    >>> codes.address_conflicts([
    ...     {'name': 'A', 'source': '04263384 48000010'},
    ...     {'name': 'B', 'source': '04263384 60000000'}])['conflicts'][0]['address']
    '0x80263384'

### `codes.check(entry)`

Validate one code and say whether the analyzer can judge it at all.

Args:
    entry: a code dict with ``source``.

Returns:
    dict: ``{'status': 'valid'|'invalid'|'unknown', 'error': str|None,
    'content_hash': str, 'writes': [...]}``. ``'unknown'`` means the code
    uses an opcode this analyzer does not model - syntax checking is not a
    compatibility proof, so it is reported, not waved through.

Example:
    >>> codes.check({'source': '04263384 48000010'})['status']
    'valid'

### `codes.content_hash(source)`

SHA-256 of :func:`normalized_body` - a code's content identity.

Recorded for every code a change requires, so a receipt names the exact
bytes that were installed rather than a title anyone could reuse.

Args:
    source: the code's hex lines.

Returns:
    str: 64 hex characters.

Example:
    >>> codes.content_hash('04263384 48000010') == codes.content_hash('04263384 48000010 # x')
    True

### `codes.from_published_description(text, source_ref)`

Read code data out of a mod's published description.

A description may SUPPLY a code. It never authorizes installing one: the
return carries ``authorizes_install=False`` and every code is tagged with
where it came from, so a build change records a provenance instead of a
claim.

A candidate whose body had lines the parser could not read comes back
``status='invalid'`` with those lines listed. The parser drops them
silently; a two-line code that arrives as a one-line code is not the code
that was published, and installing it would patch half of something.

Args:
    text: the description text as published.
    source_ref: where the text came from, e.g.
        ``'ssbmnucleus.net post 14063'``. Required - an untraceable code is
        not a usable one.

Returns:
    dict: ``{'codes': [...], 'warnings': [...], 'source_ref': str,
    'authorizes_install': False}``. Each code gains ``origin``,
    ``content_hash``, ``status``, ``writes`` and ``dropped_lines``.

Example:
    >>> found = codes.from_published_description(text, 'ssbmnucleus.net post 14063')
    >>> found['authorizes_install']
    False

### `codes.identity(entry)`

The identifier two codes are compared BY: ``'Name [Creator]'``.

Args:
    entry: a code dict with ``name`` and optionally ``creator``.

Returns:
    str: the canonical header, exactly as a ``codes.ini`` spells it.

Example:
    >>> codes.identity({'name': 'UCF', 'creator': 'Dan'})
    'UCF [Dan]'

### `codes.list_vault_codes()`

List the Gecko codes this Nucleus install already keeps.

Read-only. These are the codes the app's Codes section offers when building
an ISO.

Returns:
    list[dict]: ``{'id', 'name', 'creator', 'category', 'description',
    'source'}``. ``source`` is the code's hex lines - :func:`write_code_list`
    needs it, so it is included here.

Example:
    >>> from nucleus_api import codes
    >>> [c['name'] for c in codes.list_vault_codes()][:3]
    ['Disable Hardcoded CSS Animations', 'UCF 0.84', ...]

### `codes.merge(existing, required, enable_disabled=False)`

Merge required codes into a build's existing list, preserving it.

The rules a build change has to follow, in one place:

* every existing code survives, and its enabled flag is NEVER changed as a
  side effect. A required code the build already carries but has DISABLED
  is reported in ``enable_required``; turning it on is an explicit
  operation the proposal has to ask for (``enable_disabled=True``), because
  enabling a code changes what the game does;
* a required code whose normalized body already appears is a duplicate - it
  is not added twice;
* the same identifier carrying different bytes is a CONFLICT, never an
  overwrite;
* two codes writing the same address with different values are a conflict
  too, however they are named (:func:`address_conflicts`);
* a code the analyzer cannot judge is merged but reported as ``unknown``;
* invalid hex is a conflict.

Args:
    existing: the build's current codes (from :func:`read_code_list` or the
        app's project code list).
    required: the codes the change needs, each with ``name``/``source`` and
        ideally ``origin``.
    enable_disabled: the proposal explicitly asks to enable a required code
        the build carries disabled. Without it, that situation blocks.

Returns:
    dict: ``{'merged', 'added', 'preserved', 'duplicates', 'conflicts',
    'unknown', 'enable_required', 'enabled', 'interactions', 'ok'}``.
    ``preserved`` reports each existing code's RESULTING enabled flag.
    ``ok`` is False when there is any conflict or an unrequested enable.

Example:
    >>> codes.merge([{'name': 'UCF', 'source': '04001234 60000000', 'enabled': True}],
    ...             [{'name': 'Disable Hardcoded CSS Animations',
    ...               'source': '04263384 48000010'}])['added'][0]['identity']
    'Disable Hardcoded CSS Animations'

### `codes.normalized_body(source)`

The comparable form of a code's hex: comments gone, upper case, one
8-byte word per pair.

Two codes with the same normalized body ARE the same patch however they
were pasted, which is what deduplication may rely on. Anything that is not
a valid hex line is kept verbatim (upper-cased) so a malformed code never
silently normalizes into a valid-looking one.

Args:
    source: the code's hex lines.

Returns:
    str: the normalized body.

Example:
    >>> codes.normalized_body('04263384 48000010  # label')
    '04263384 48000010'

### `codes.parse(text)`

Turn pasted code text into normalized Gecko codes.

Handles a full INI block (``$Name [Creator]`` plus hex lines), bare hex
lines, and the loose "title, blurb, hex" shape mod descriptions use. It
validates the hex; nothing is saved anywhere.

Args:
    text: the pasted text, e.g. a mod description's code section.

Returns:
    dict: ``{'codes': [{'name', 'creator', 'description', 'source',
    'enabled', 'valid', 'error'?}], 'warnings': [str, ...]}``. Check
    ``valid`` before using a code.

Example:
    >>> codes.parse('$Disable Hardcoded CSS Animations\n04263384 48000010')
    {'codes': [{'name': 'Disable Hardcoded CSS Animations', 'valid': True, ...}], 'warnings': []}

### `codes.read_code_list(path)`

Read a ``codes.ini`` back into code dicts.

Args:
    path: workspace path to a codes.ini.

Returns:
    list[dict]: same shape as :func:`parse`'s ``codes``.

Example:
    >>> codes.read_code_list('out/codes.ini')[0]['name']
    'Disable Hardcoded CSS Animations'

### `codes.write_code_list(entries, destination=None)`

Write codes to a ``codes.ini`` in the workspace, the format a build reads.

Args:
    entries: list of code dicts from :func:`parse` or :func:`list_vault_codes`
        (each needs at least ``name`` and ``source``).
    destination: workspace path. Defaults to ``out/codes.ini``.

Returns:
    str: absolute path of the file written.

Example:
    >>> codes.write_code_list(codes.parse(text)['codes'], 'out/codes.ini')
    'C:/.../workspace/out/codes.ini'

### `codes.write_targets(source)`

What a code actually writes, so two codes can be compared by EFFECT.

Comparing names catches a code being added twice under one title. It does
not catch the real collision: two differently named codes patching the same
instruction with different values, where whichever the loader applies last
silently wins. This decodes the opcodes the m-ex loader supports and returns
the address each one touches.

Supported: ``00``/``02``/``04`` writes (8, 16 and 32 bit) and ``C2``
branch injections. Anything else is reported as unsupported - it may write
anywhere, and saying otherwise would be a guess.

Args:
    source: the code's hex lines.

Returns:
    dict: ``{'writes': [{'address', 'opcode', 'value', 'width', 'line'}],
    'unsupported': [{'opcode', 'line'}], 'analyzable': bool}``. Addresses
    are the full ``0x8...`` form the Gecko base implies.

Example:
    >>> codes.write_targets('04263384 48000010')['writes'][0]['address']
    '0x80263384'

---

## `nucleus_api.render`

Render a costume offline so you can LOOK at what you made.

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

### `render.costume_preview(dat_path, character, costume_code=None, csp_destination=None, stock_destination=None)`

Render a costume DAT to a character-select portrait and a stock icon.

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

### `render.costume_preview_from_zip(zip_path, character, member=None, **kwargs)`

Same as :func:`costume_preview`, starting from a costume ZIP.

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

---

## `nucleus_api.game`

Run a costume in the actual game and photograph it.

Offline renders show what a costume looks like posed by a Blender rig. Only the
game shows what the game does with it. This module builds a throwaway test ISO
with one costume in it, boots it in an isolated Slippi Dolphin, performs named
moves by single-frame stepping, and captures the exact frames - the same engine
the app's "Test in game" button uses.

One Dolphin runs on this machine at a time. :func:`status` says whether the slot
is free; every call here takes the same machine-wide lock and only ever stops
the process it started.

Worked example - verify a costume you just exported::

    iso = game.build_costume_iso('out/dragon-costume.zip', 'Mewtwo')
    iso['iso_path']; iso['color_index']    # the slot the costume landed in

    shots = game.capture_moves(iso['iso_path'], 'Mewtwo',
                               ['jab:1-3', 'fsmash:10', 'upb:5', 'dashattack:6', 'grab:3'],
                               color=iso['color_index'], destination='out/ingame')
    shots['images']        # one PNG per captured frame
    shots['sheet']         # all of them tiled and labelled - LOOK at this

Building the ISO takes a few minutes and booting takes about 90 seconds, so a
capture run is slow; ask for every move you need in ONE call.

### `game.build_costume_iso(costume_zip, character, destination=None, nana_zip=None)`

Build a throwaway ISO containing exactly one extra costume.

A fresh m-ex project is made from the clean ISO, the costume is imported as
a new colour slot, and the project is exported. Nothing in the vault or in
any existing build is touched.

Args:
    costume_zip: workspace path to a costume .zip.
    character: the fighter the costume belongs to, e.g. 'Mewtwo'.
    destination: workspace .iso path. Defaults to ``out/test.iso``.
    nana_zip: the paired Nana archive, for an Ice Climbers costume.

Returns:
    dict: ``{'iso_path': str, 'color_index': int, 'character': str,
    'next': str}``. ``color_index`` is the costume slot to pass to
    :func:`capture_moves`.

Example:
    >>> game.build_costume_iso('out/dragon-costume.zip', 'Mewtwo')
    {'iso_path': 'C:/.../out/test.iso', 'color_index': 4, ...}

### `game.capture_moves(iso_path, character, moves, color=0, destination='out/ingame', stage='finaldestination', closeup=True, timeout=1800)`

Boot an ISO, perform moves frame by frame and photograph exact frames.

The match is solo (no CPU, no menu cursor): the player block is written
straight to game RAM. Each move is executed by single-frame stepping, so
frame 1 really is the move's first frame.

Args:
    iso_path: workspace path to the ISO, from :func:`build_costume_iso`.
    character: fighter name, e.g. 'Mewtwo'.
    moves: list of ``'move'`` or ``'move:frames'`` strings, e.g.
        ``['jab:1-3', 'fsmash:10', 'upb:5', 'dashattack:6', 'grab:3']``.
        :data:`MOVES` is the exact set the engine accepts - note that
        running is ``'run'`` and the dash attack is ``'dashattack'``; there
        is no ``'dash'``.
    color: costume slot to wear - the ``color_index`` from the build.
    destination: workspace folder for the PNGs.
    stage: stage name, default 'finaldestination'.
    closeup: park the camera on the fighter before every capture.
    timeout: seconds to allow the whole run (a boot alone costs ~90 s).

Returns:
    dict: ``{'images': [png path, ...], 'sheet': png path, 'log': str,
    'next': str}``. ``sheet`` tiles every capture with its move and frame
    written on - open that first.

Example:
    >>> game.capture_moves('out/test.iso', 'Mewtwo', ['jab:1-3'], color=4)
    {'images': ['C:/.../out/ingame/mewtwo-jab-f01.png', ...], 'sheet': '...'}

### `game.read_captures(destination='out/ingame')`

The per-capture sidecars a run wrote: action state, animation frame, position.

Args:
    destination: the workspace folder a :func:`capture_moves` run wrote to.

Returns:
    list[dict]: one entry per move, as the capture engine recorded it.

Example:
    >>> game.read_captures('out/ingame')[0]['file']
    'C:/.../workspace/out/ingame/mewtwo-jab.json'

### `game.status()`

Whether the machine's single Dolphin slot is free.

Returns:
    dict: ``{'busy': bool, 'owner': str|None, 'pid': int|None}``. When it is
    busy, something else on this machine is driving Dolphin - wait rather
    than killing it.

Example:
    >>> from nucleus_api import game
    >>> game.status()
    {'busy': False, 'owner': None, 'pid': None}

### `game.vanilla_iso()`

The clean Melee ISO this install builds test ISOs from.

Returns:
    str | None: its path, or None when no ISO has been configured.

Example:
    >>> game.vanilla_iso()
    'C:/Users/.../Super Smash Bros. Melee (USA) (En,Ja) (v1.02).iso'

### `game.verification_profile(profile='costume_verification_v1')`

What a capture profile asks for, resolved against the engine's move catalog.

Args:
    profile: the profile version.

Returns:
    dict: entries with ``status`` 'supported' or 'unsupported', the expected
    captures, and ``complete``. An unsupported entry is never dropped.

Example:
    >>> game.verification_profile()['complete']
    True

### `game.verification_self_consistency(manifest, character=None)`

Reasons this manifest is not usable as evidence about anything. -> list.

Args:
    manifest: a verification manifest.
    character: the fighter the costume targets, when known.

Returns:
    list[str]: empty when the manifest is internally consistent.

Example:
    >>> game.verification_self_consistency(result)
    []

### `game.verify_costume(candidate_file, character, destination='out/verification', profile='costume_verification_v1', lock_wait=0, timeout=None, use_cache=True, keep_iso=False)`

Run a costume in the game under a fixed capture profile and MEASURE it.

This is the metered verification path, not the free-form one above. It
builds a private verification package from the candidate's exact bytes,
boots the isolated emulator, reads back from RAM which fighter and which
costume slot the match actually loaded, captures the profile's frames with a
camera fixed in advance, and measures every frame.

It never turns a completed capture run into a pass. A measurement that could
not be taken is ``unknown``; a profile entry the engine does not support
makes the profile incomplete and is recorded.

Args:
    candidate_file: workspace path to the costume .zip to verify.
    character: the fighter it belongs to, e.g. 'Mewtwo'.
    destination: workspace folder for the captures, sheet and manifest.
    profile: capture-profile version. 'costume_verification_v1' captures
        idle, run frames 5 and 15, jab 1-3, forward smash 10, up-B 5, dash
        attack 6 and grab 3.
    lock_wait: seconds to queue for the machine's single Dolphin slot. 0
        means report a busy Dolphin and leave it alone.
    timeout: watchdog, in seconds, over the whole boot-and-capture phase.
        The default is :data:`shared.ingame.verify_costume.WATCHDOG_SECONDS`; when
        it expires the emulator this run started is stopped and the outcome
        is 'failed' with reason 'timeout'.
    use_cache: skip the run when the same bytes were verified under the same
        profile, engine and toolchain, and the stored evidence still hashes.

Returns:
    dict: ``{'outcome': 'verified'|'incomplete'|'unknown'|'failed',
    'reasons': [...], 'manifest': str, 'sheet': str|None, 'timing': {...},
    'game_verification': {...}}``. ``game_verification`` is the review
    record's field; ``manifest`` is the JSON written beside the captures.

Example:
    >>> game.verify_costume('out/dragon-costume.zip', 'Mewtwo')
    {'outcome': 'failed', 'reasons': ['...run-f05.png: the actor is clipped...']}

---

## `nucleus_api.builds`

Change the build you play - as one sealed, authorized, revocable step.

Every other module here writes a workspace copy. This one is the exception, and
the only one: it installs a prepared menu file and the codes it needs INTO a
managed build, through the single build-access service every app writer uses
(:mod:`core.build_access`), journaled so an interrupted change is repaired
before anything reads the build again.

It never takes a destination path. It takes a registered build id and registered
artifact ids; where an artifact lands is decided by its KIND
(:data:`ARTIFACT_KINDS`) at the moment of use, never by a stored field a caller
could edit.

The shape of a change:

    build  = builds.list_builds()[0]                      # an explicit choice
    art    = builds.register_artifact('out/MnSlChr.usd', 'css_menu_file')
    change = builds.prepare_change(build['id'], build['revision'], [art['id']])
    ask    = builds.authorization_request(change['prepared_change_id'])
    #   -> exactly what the user has to be shown and agree to. This library
    #      cannot answer it: `core.build_authorization.grant` is backend code
    #      the approval endpoint calls once the user has clicked.
    got    = builds.commit_change(change['prepared_change_id'], authorization_id)
    got['achieved']['installed']
    # False - the project's inputs changed; the ISO you boot is a separate build.

What this module will not do: decide which build you meant, authorize itself,
treat "it parses" as compatibility, treat an author's screenshot as a preview,
or call a changed project an installed game.

### `builds.artifact(artifact_id)`

The registration record for an artifact id.

Args:
    artifact_id: an ``id`` from :func:`register_artifact`.

Returns:
    dict: the record, with ``role``/``menu_type``/``destination``
    recomputed from its kind rather than read from the file.

Example:
    >>> builds.artifact(art_id)['kind']
    'css_menu_file'

### `builds.authorization_request(prepared_change_id)`

Exactly what the user has to be shown, and agree to, before a commit.

This library cannot answer it. Granting an authorization is backend code
(:func:`core.build_authorization.grant`, reached from the approval endpoint
``POST /api/mex/builds/changes/<id>/approve``), so a model can ask for a
change to be approved and cannot approve one.

Args:
    prepared_change_id: from :func:`prepare_change`.

Returns:
    dict: ``{'prepared_change_id', 'build', 'destinations', 'codes',
    'compatibility', 'unknown_dimensions', 'limitations', 'preview',
    'granted_by', 'endpoint'}`` - the card's contents, and where a decision
    about it comes from.

Example:
    >>> builds.authorization_request(change_id)['granted_by']
    'the user, through the approval endpoint'

### `builds.commit_change(prepared_change_id, authorization_id)`

Apply a sealed, authorized change to the build - the only write here.

Takes the build's exclusive mutation lock through the one build-access
service, recovers any interrupted change first, then revalidates everything
from scratch: the authorization's binding is RECOMPUTED from the proposal on
disk (so editing the proposal after approval invalidates it), the build is
still at the revision that was authorized, the target and the code compiler
are still the ones the proposal named, and every file - sealed copy,
workspace original, and the bytes currently in the build - still hashes to
what was agreed. Only then does it write, as one journaled transaction.

The receipt and the authorization's consumption are recorded in the journal
BEFORE they are written out, and written under the same lock, so a crash
cannot lose the outcome or let the authorization be spent twice. Calling it
again with a spent authorization returns the receipt that already exists.

Args:
    prepared_change_id: from :func:`prepare_change`.
    authorization_id: granted by the app's approval endpoint.

Returns:
    dict: the receipt - ``{'receipt_id', 'outcome', 'stage', 'achieved',
    'build_id', 'before_revision', 'after_revision', 'installed', 'codes',
    'verification', 'playable', 'preview', 'journal_id', 'next'}``.
    ``achieved['build_inputs_updated']`` is True and
    ``achieved['installed']`` is False: the project changed, the disc you
    boot has not been rebuilt. ``outcome`` is ``'partial'``.

    When ``NUCLEUS_BUILD_COMMIT=0`` this installation does not let the app
    write builds at all: the call returns
    ``outcome='build_commit_disabled'`` before taking a lock or writing a
    byte, rather than applying part of the change.

Raises:
    BuildChangeRejected: stale or mismatched authorization, changed bytes,
        unaccepted unknown compatibility, or a verification failure. In
        every case the build is left exactly as it was.

Example:
    >>> receipt = builds.commit_change(change_id, auth_id)
    >>> receipt['achieved']['installed'], receipt['preview']['status']
    (False, 'unavailable')

### `builds.describe(build_id)`

Everything a change needs to know about one build before proposing one.

Args:
    build_id: an ``id`` from :func:`list_builds`.

Returns:
    dict: the :func:`list_builds` row plus ``'target'`` (its game code, disc
    revision, menu variant and the digest of the menu file it currently
    carries), ``'managed_digests'``, ``'codes'`` (its current Gecko list)
    and ``'playable'`` (whether the game you boot reflects any of it).

Example:
    >>> builds.describe(build_id)['target']['game_code']
    'GALE01'

### `builds.list_builds()`

List the builds on this machine that a change can name.

A build is a MEX project (``project.mexproj`` beside ``files/``) - those are
committable. Extracted build folders under the storage root are listed too,
marked ``committable=False``, so "which build?" is answered with the real
set rather than the convenient subset.

Returns:
    list[dict]: ``{'id', 'name', 'path', 'format', 'committable',
    'revision', 'menu_files', 'codes_path'}``. ``revision`` is a content
    revision of the build's managed AND identity files (its menu, its code
    list, its disc header, its m-ex marker), so anything that changes what
    the build IS also invalidates a pending authorization.

Example:
    >>> from nucleus_api import builds
    >>> [b['name'] for b in builds.list_builds()][:2]
    ['My_Project', 'test-base']

### `builds.playable_status(build_id)`

Whether the game you actually boot reflects this build's current files.

Changing a project's files is not installing a game. The disc the user
plays is produced by the app's separate ISO export, and this library does
not run it, so it never reports one as verified.

Args:
    build_id: an ``id`` from :func:`list_builds`.

Returns:
    dict: ``{'status': 'not_verified', 'reason', 'required_operation',
    'artifacts_dir'}``.

Example:
    >>> builds.playable_status(build_id)['status']
    'not_verified'

### `builds.prepare_change(build_id, expected_revision, artifacts, code_changes=None, preview_requested=False, task_id='', task_revision=1, chat_id='')`

Seal a proposed change to a build: what would be written, and what is known.

Nothing is written to the build. Everything the proposal depends on is read
and sealed under the build's own lock, in one pass, so the facts it states
were all true at one instant: the revision, the target signature, the
current code list, the artifacts' bytes (copied into the journal), the
compiler that will build the code list, and the compatibility verdict -
which is computed against the SEALED copy, not the workspace file a later
call could replace.

Args:
    build_id: an ``id`` from :func:`list_builds`.
    expected_revision: the build's ``revision`` as the caller last saw it.
    artifacts: artifact ids from :func:`register_artifact`. Artifacts whose
        kind has no destination (a reference screenshot) are recorded and
        never installed.
    code_changes: optional ``{'add': [code dicts], 'enable_disabled': bool,
        'reason': str}``. The package's own required codes are added
        automatically; ``add`` is for codes on top of those, and they are
        judged with the rest. ``enable_disabled`` makes turning on a
        required code the build carries switched OFF an explicit part of
        the proposal instead of a side effect.
    preview_requested: the user asked to see the result. No renderer
        exists, so this makes the outcome ``partial`` rather than letting a
        missing preview pass unnoticed.
    task_id: the task this proposal belongs to, carried into the
        authorization and the wish.
    task_revision: that task's revision.
    chat_id: the conversation, which is the unit capability demand is
        counted in.

Returns:
    dict: the sealed manifest -
    ``{'status', 'prepared_change_id', 'build_id', 'build_path',
    'before_revision', 'target', 'compiler', 'writes', 'references',
    'codes', 'codes_ini_sha256', 'codes_required', 'compatibility',
    'unknown_dimensions', 'preview', 'preview_status', 'rollback',
    'subject_digest', 'limitations'}``. ``status`` is ``'prepared'`` or
    ``'blocked'`` (with an ``error``, and a typed ``wish`` for a build
    format that cannot be committed to).

Raises:
    BuildChangeRejected: unknown build or artifact, a stale
        ``expected_revision``, or an artifact whose bytes moved.

Example:
    >>> change = builds.prepare_change(build_id, revision, [artifact_id])
    >>> change['status'], change['preview']['status']
    ('prepared', 'unavailable')

### `builds.prepared_change(prepared_change_id)`

Read back a sealed proposal by its id.

Args:
    prepared_change_id: from :func:`prepare_change`.

Returns:
    dict: the sealed manifest, exactly as it was written.

Example:
    >>> builds.prepared_change(change_id)['status']
    'prepared'

### `builds.receipt(receipt_id)`

Read a commit receipt back by its id.

Args:
    receipt_id: from :func:`commit_change`.

Returns:
    dict: the receipt as it was recorded.

Example:
    >>> builds.receipt(receipt_id)['achieved']['build_inputs_updated']
    True

### `builds.record_build_commit_gap(row, task_id='', task_revision=1, chat_id='', workflow='install_menu')`

Record the unsupported-build gap - for a REQUESTED INSTALLATION only.

:func:`prepare_change` meeting an uncommittable build is a validation
result, not a request to install one, so it returns the typed error and
records nothing. This is called from the install path, where the capability
really was required for the user's outcome. The build FORMAT is the variant,
because it is the missing implementation; an unknown build or a stale
revision stays an ordinary validation failure and never reaches here.

Args:
    row: a :func:`list_builds` entry for the build that cannot be committed.
    task_id: the task the install was requested in.
    task_revision: that task's revision.
    chat_id: the conversation, which is the unit demand is counted in.
    workflow: the workflow that needed the install.

Returns:
    The ``wishes.WishRecord``, or None when the build's format has no
    declared variant (:data:`BUILD_FORMAT_VARIANTS`) or the classifier does
    not call it a gap.

Example:
    >>> builds.record_build_commit_gap(row, task_id='task_1').persisted
    True

### `builds.recover(build_id)`

Finish or undo a change that was interrupted, before anything reads the build.

Every entry point here does this already, and so does the app when it opens
a project; call it directly only when you want the report.

Args:
    build_id: an ``id`` from :func:`list_builds`.

Returns:
    list[dict]: one entry per journal that needed attention, each
    ``{'txn_id', 'action', 'restored', 'finalized'}``. ``action`` is
    ``'rolled_back'`` for a change that never finished, or ``'finalized'``
    for one whose files were already written and verified - that one is
    completed, not undone, and its receipt appears.

Example:
    >>> builds.recover(build_id)
    [{'txn_id': 'txn_ab12cd34ef56', 'action': 'rolled_back',
      'restored': ['files/MnSlChr.usd'], 'finalized': []}]

### `builds.register_artifact(path, kind, name=None)`

Register a workspace file as an artifact a change may install.

Registration turns "a file somewhere" into a resource with an id, a hash and
a KIND. The record is written under the app's trusted store, not the
workspace: a registration a caller can rewrite is not a record of anything.
Its destination and role are never read back from the record - they are
re-derived from :data:`ARTIFACT_KINDS` wherever they are used.

Args:
    path: workspace path to the file, e.g. the ``MnSlChr.usd`` that
        :func:`nucleus_api.menus.install_background` produced.
    kind: one of :data:`ARTIFACT_KINDS`. ``'reference_screenshot'`` has no
        destination and can never be installed.
    name: a label for receipts. Defaults to the file's name.

Returns:
    dict: ``{'id', 'kind', 'role', 'path', 'sha256', 'bytes',
    'destination', 'registered_utc'}``. Registering the same bytes at the
    same path twice returns the same id.

Example:
    >>> builds.register_artifact('out/MnSlChr.usd', 'css_menu_file')['role']
    'install'

### `builds.rollback(receipt_id)`

Undo a committed change, putting every original file back.

Refuses when the build no longer holds what that change wrote: undoing it
then would silently delete a later change nobody asked to lose.

Args:
    receipt_id: from :func:`commit_change`.

Returns:
    dict: ``{'receipt_id', 'restored', 'before_revision', 'after_revision'}``
    where ``after_revision`` is the build's revision once the originals are
    back - normally the receipt's ``before_revision`` again.

Raises:
    BuildChangeRejected: ``stale_rollback`` or ``backup_not_intact``.

Example:
    >>> builds.rollback(receipt_id)['after_revision'] == change['before_revision']
    True

### `builds.target_signature(build_id, menu_type='css')`

The game this build IS, read from its own boot header.

Compatibility is judged against this, never against a build's name.

Args:
    build_id: an ``id`` from :func:`list_builds`.
    menu_type: which screen's current file to report the digest of.

Returns:
    dict: ``{'game_code', 'disc_revision', 'menu_variant',
    'current_menu_sha256'}``. Any field the build cannot answer for is
    None, which makes the target dimension ``unknown`` rather than assuming
    NTSC 1.02 - a recorded observation only covers the signature fields it
    recorded.

Example:
    >>> builds.target_signature(build_id)['disc_revision']
    2

---

## Workspace rules

Where this library may read and write, and how that is actually enforced.

Every public function that names a file routes it through :func:`in_path` or
:func:`out_path`. Four rules, and the reasons each one exists:

1. **The root is explicit.** It comes from ``NUCLEUS_API_WORKSPACE`` or an
   installed root (:func:`use_workspace`), never from the current directory.
   A root that changes when the process happens to ``chdir`` is not a boundary,
   and a relative path that resolves against the CWD is not inside it.

2. **The root is fixed for the task.** It is resolved once per configured
   value and cached, so two calls in one operation cannot disagree about where
   the workspace is. Changing the configured value starts a new task.

3. **Absolute is not a licence.** An absolute path is accepted only when it is
   inside the workspace, and it is checked exactly as a relative one is. There
   is no "the caller gave an absolute path, so the library must have located
   it" exemption: a path this library located itself is carried as a
   :class:`TrustedPath`, an object a caller cannot produce by passing a string.

4. **Containment is verified against the open file, not the name.** The file is
   opened first, then ``fstat`` identity is compared with an independent stat
   of the resolved path, and every component between the root and the file is
   rejected if it is a symlink, junction or other reparse point - while the
   handle is held. Resolving a name and opening it afterwards are two
   operations, and a junction swapped in between would turn the second one into
   a write outside the workspace. :func:`open_input` and :func:`read_input`
   hand back the verified handle so there is no second open at all.

The vault (``app/storage``) is read-only from here as a consequence: a
caller cannot name a vault path as an input or an output even by accident.

### `workspace()`

The folder this library reads from and writes into, and nowhere else.

Read once from ``NUCLEUS_API_WORKSPACE`` (or :func:`use_workspace`) and
cached until that value changes. There is deliberately no fall back to the
current working directory: a boundary that moves with ``chdir`` is not one,
and relative paths that resolve against the CWD are outside it by
construction.

Returns:
    pathlib.Path: absolute path to the workspace root.

Raises:
    WorkspaceError: no workspace is configured.

Example:
    >>> from nucleus_api import workspace
    >>> print(workspace())
    C:\...\workspace

### `use_workspace(root, *, create=True)`

Install the workspace root explicitly, for this process.

The host calls this when it starts a task. It replaces whatever was
installed, so it is the one supported way to move the boundary.

Args:
    root: an absolute directory.
    create: create it when it does not exist.

Returns:
    pathlib.Path: the resolved root.

Raises:
    WorkspaceError: the path is not absolute, or is not a directory.

Example:
    >>> use_workspace('C:/work/task-1')
    WindowsPath('C:/work/task-1')

### `in_path(path)`

Resolve an input path the caller names, which must be in the workspace.

A relative path resolves against the WORKSPACE, never the current
directory. An absolute path is accepted only when it is inside the
workspace, and is checked the same way. There is no exemption for paths
that merely happen to be absolute and to exist - a path this library
located is passed as a :class:`TrustedPath` instead.

The file is opened and verified through its handle before this returns, so
the answer is true at that instant; a caller that must be immune to a
substitution afterwards should read through :func:`open_input` rather than
opening the returned path a second time.

Args:
    path: a workspace-relative path, an absolute path inside the workspace,
        or a :class:`TrustedPath`.

Returns:
    pathlib.Path: the absolute existing path.

Raises:
    WorkspaceError: missing, outside the workspace, or reached through a
        link or junction.

Example:
    >>> in_path('out/fox.png')
    WindowsPath('C:/.../workspace/out/fox.png')

### `open_input(path)`

Open a caller-named input, verified through the handle.

Prefer this over :func:`in_path` wherever the bytes are what matter: the
file is opened once and read through that handle, so there is no window in
which the name could come to mean a different file.

Args:
    path: a workspace-relative path, an absolute path inside the workspace,
        or a :class:`TrustedPath` this library located.

Returns:
    A context manager with ``.handle`` (an open binary file) and ``.path``.

Raises:
    WorkspaceError: outside the workspace, missing, or reached through a
        link.

Example:
    >>> with open_input('out/MnSlChr.usd') as source:
    ...     header = source.handle.read(32)

### `read_input(path)`

The bytes of a caller-named input, read through the verified handle.

Args:
    path: as :func:`open_input`.

Returns:
    bytes: the file's contents.

Example:
    >>> read_input('out/MnSlChr.usd')[:4]
    b'\x00?\x1f\xc5'

### `out_path(path, *, default_name=None, make_parents=True)`

Resolve a caller-supplied output path inside the workspace.

A relative path resolves against the workspace. Every component that
already exists is checked for a link or junction, so a planted reparse
point cannot redirect the write out of the workspace.

Args:
    path: a workspace-relative path, or an absolute path inside the
        workspace. ``None`` uses ``default_name`` under ``out/``.
    default_name: filename used when ``path`` is None.
    make_parents: create the parent folder.

Returns:
    pathlib.Path: the absolute, validated destination.

Raises:
    WorkspaceError: the destination is outside the workspace, or is reached
        through a link.

Example:
    >>> out_path('out/fox.png')
    WindowsPath('C:/.../workspace/out/fox.png')

### `derived_output(path, suffix, *, make_parents=True)`

A second output derived from a checked one - checked in its own right.

An operation that validates ``out/model.zip`` and then writes
``out/model.dat`` beside it has written a path nothing checked. Deriving it
here runs the same containment rules over the real destination.

Args:
    path: the output already resolved by :func:`out_path`, or a path that
        will be.
    suffix: the new suffix, e.g. ``'.dat'``, or a full replacement name
        when it contains no leading dot.
    make_parents: create the parent folder.

Returns:
    pathlib.Path: the absolute, validated derived destination.

Raises:
    WorkspaceError: the derived destination escapes the workspace.

Example:
    >>> derived_output(out_path('out/model.zip'), '.dat')
    WindowsPath('C:/.../workspace/out/model.dat')

### `library_path(path, *, why)`

Mark a path this library located as usable where a caller path is not.

Args:
    path: the absolute path.
    why: where it came from, e.g. ``'sealed copy in the build journal'``.

Returns:
    TrustedPath: pass it where a public function takes a path.

Example:
    >>> library_path(sealed, why='sealed copy in the build journal')
    TrustedPath('C:/.../MnSlChr.usd', why='sealed copy in the build journal')
