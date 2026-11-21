"""Tier 2 -- compiled move logic for cloned fighters.

`codegen`  scaffolds a donor-specific C project (move-logic table read from
           the DOL, donor callback chains, common-state wrapper, HUD text),
`build`    compiles it with MexTK and appends the `ftFunction` root to a Pl
           DAT byte-exactly (vault.echo.datroot),
`package`  (vault.echo.package) materialises an echo.json that carries a `code`
           section through the same path.
See README.md in this directory for the engine facts behind the design.
"""
