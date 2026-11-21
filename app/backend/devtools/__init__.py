"""Dev tooling that drives the app's engines from the command line (never
imported by the Flask app; `harness_mcp.py` shells out to these).

  frameshot.py        frame-exact move screenshots (docs/dev/INGAME_TESTING.md)
  effect_probe.py     spec-driven live RAM-poke probe (backend/probes/*.json)
  extras_audit.py     MAP/WIRE/EYEBALL extras audit (docs/dev/EXTRAS_AUDIT.md)
  extras_doctor.py    no-boot extras triage for a built project
  fps_batch.py        CSS health/FPS verdict per ISO (docs/dev/MEX_BUILD_LIMITS.md)
  stress_build.py     N-costume build stress
  texture_coverage.py Ef*Data texture-bank coverage sweep

research/ holds one-off investigation scripts kept because docs under
research/docs-research/ cite them. Every script adds the backend root to sys.path
itself, so `python backend/devtools/<tool>.py` works from anywhere.
"""
