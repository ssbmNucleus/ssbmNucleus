# docs-research

Point-in-time investigation write-ups (moved from the old docs tree on 2026-10-02, pruned 2026-10-03). Not maintained against current code; check dates. Code comments cite these by path.

- `effect-maps/` - per-character and per-system effect (particle, texture, colour) maps that drove the Extras wiring (Fox/Falco shine, Link, Mario, Samus, Kirby, items, EfCoData, and others).
- `color-effects-reference/` - Smashboards colour-offset reference, extras expansion notes and the reference-mods index.
- `PTCL_FORMAT.md` - decoded `Ef*Data.dat` particle-bank grammar.
- `fd-star-particles.md` - disabling Final Destination's background star sparkles for `--plain-bg`.
- `mobile-vault.md` - the original design proposal for the replay library on the phone (since built in `services/mobile`; the code is the current design).

The model-import plans and the Randall contracts are retired: the current flow and card contract are in `docs/dev/RANDALL.md`; the rest is in git history before 2026-10-03.
