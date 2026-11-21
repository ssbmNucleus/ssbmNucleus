<p align="center">
  <img src="frontend/public/icon.png" alt="SSBM Nucleus" width="200">
</p>

# SSBM Nucleus

Mod manager for Super Smash Bros. Melee. Download, organize, and install character and stage skins.

This is the desktop app subtree of the private [monorepo](../README.md).
Tracker replay analysis shares the same desktop shell. For development, start
with [the app guide](CLAUDE.md), [architecture](../docs/dev/ARCHITECTURE.md), and
[setup instructions](../docs/dev/DEVELOPMENT.md). Public documentation is maintained
in [docs/public-shell/](../docs/public-shell/README.md); each release publishes the source it shipped.

**Website:** [ssbmnucleus.net](https://ssbmnucleus.net)

**Download:** [ssbmnucleus.net](https://ssbmnucleus.net) (in-app auto-updates after install)

**Discord:** [Join](https://discord.gg/EAjJnccxgF)

## Features

- One-click skin downloads from the website
- Visual vault for organizing mods, CSPs, and stock icons
- Automatic CSP generation from DAT files
- Netplay safety validation
- Batch install skins
- Skin creator with live paint, texture import/export, and 3D preview
- Extras system — edit sword trails, lasers, shine, thunder, shadow ball, and other character specific effects
- Pose manager — create and batch generate custom CSP poses
- Embedded 3D model and animation viewer
- Auto-generate Dolphin texture packs for unlimited skins per ISO
- Mod bundles (.ssbm) — one-click xdelta patches + texture packs
- XDelta patch creation for sharing modpacks
- First-run setup with auto-detection of Slippi and Melee ISO

## Credits

Built with [MexManager](https://github.com/Ploaj/MexManager), [HSDRawViewer](https://github.com/Ploaj/HSDLib), and [Costume Validator](https://ssbmtextures.com/other-mod-types/costume-validator-by-ploaj/)  by Ploaj

Built on the [MEX system](https://github.com/akaneia/m-ex) and Dynamic Alternate Stages by Unclepunch

## License

GNU General Public License v3.0 (GPL-3.0); the full text is in
[LICENSE](../LICENSE). Third-party components keep their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
