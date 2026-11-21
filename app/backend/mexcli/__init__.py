"""MexCLI access: everything the backend runs the MexCLI executable through.

``mexcli.project``  -- ``MexManager``: one open ``.mexproj`` workspace (open,
                      list fighters, import/remove/reorder costumes, layouts,
                      export an ISO). Imports no ``core``: ``core.state`` imports
                      it while ``core`` initialises, and standalone workers use it
                      without loading the app's configuration.
``mexcli.commands`` -- ``run`` / ``run_json`` / ``parse_json``: one-shot MexCLI
                      commands at the configured ``MEXCLI_PATH``, with the build
                      lock for the commands that save a workspace. Reads
                      ``core.config``.

This file stays empty of imports so that importing ``mexcli.project`` never
pulls in ``core``.
"""
