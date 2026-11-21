# Nucleus native fighter-port engine

Maintained here as developer tooling, exposed through the Nucleus MCP's
`native_port` tool. Start with [the creation guide](../creation/README.md).
The direct CLI remains `python -m fighter_port.port` from this directory, with
`NUCLEUS_REPO` pointing to the Nucleus repository and the app backend on
`PYTHONPATH`. The MCP configures both automatically.

Source moved from the private fighterport repo, branch `byleth-oneshot`,
commit `ad1398a1b759cbcc8b55b2c61b31dd2811906de9` (November 14, 2026).
This includes the current shared pipeline, Ultimate/Brawl/Slap City/Rivals 2
readers, active supporting helpers and tests (now `tests/fighterport`). Historical
pilots, benchmark experiments, Shulk review output and Pokemon Trainer research
snapshots remain in that original repository; the maintained runtime has no
imports from them. The old repository was not deleted or rewritten.
Generated pixel headers and copied reference pages from the old Shulk pilot
are excluded; the shared pipeline uses its source recipes and the user's assets.

The pipeline produces playable adaptations and reports known limitations in
its package notes. Special effects and character-specific mechanics are still
development work. Gameplay calibration is optional; exact frame parity is not
a prerequisite for producing a character package.

See `fighter_port/READERS.md`, `fighter_port/SPECIALS.md` and
`fighter_port/MECHANIC_ACCEPTANCE.md` for the implementation conventions.

Python caches, compiled native helpers, source-game files and built artifacts
are local only. The `.NET` helpers build from the source under this directory.
