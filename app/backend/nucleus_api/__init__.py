"""nucleus_api - a small, documented library over what SSBM Nucleus already does.

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
"""
from . import builds, codes, game, menus, modfile, render, vault, website
from ._workspace import (TrustedPath, WorkspaceError, derived_output, in_path,
                         library_path, open_input, out_path, read_input,
                         reset_workspace, use_workspace, workspace)

__all__ = ['vault', 'modfile', 'menus', 'website', 'codes', 'render', 'game',
           'builds', 'workspace', 'use_workspace', 'reset_workspace', 'out_path',
           'in_path', 'open_input', 'read_input', 'derived_output',
           'library_path', 'TrustedPath', 'WorkspaceError']
