"""Extract reference data from the USER'S OWN vanilla ISO, and the first-run
flow that does it (docs/dev/VANILLA_ASSET_POLICY.md: retail data is never
shipped, always regenerated on the user's machine).

  vanilla_refs.py     reference DATs (costumes, stages, effects) ripped from the disc
  bone_refs.py        per-costume bone tables for the netplay-safety validator
  menu_refs.py        HUD / pause / series / stage-select imagery, from a project
  first_run_setup.py  first-run ISO import, builtin staging, derivation phases
"""
