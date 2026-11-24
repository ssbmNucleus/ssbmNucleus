# SSBM Nucleus 0.9.2

- **Fix**: the model import tools download (Settings > AI > Model import tools)
  no longer stops at Blender with "no longer at ... (HTTP 403)". Blender's
  download site turns some networks away (VPNs especially); Nucleus now gets
  Blender from one of its mirrors instead.
- **Fix**: the same download no longer stops with "certificate has expired" on
  Windows PCs that kept an old, expired certificate.

Full changelog: https://github.com/ssbmNucleus/ssbmNucleus/blob/main/CHANGELOG.md
