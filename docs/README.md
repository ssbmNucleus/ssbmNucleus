# docs

- `dev/` developer docs: architecture, build and release, subsystems. Start at [dev/DOCUMENTATION.md](dev/DOCUMENTATION.md)
  (index and staleness marks) and [dev/ARCHITECTURE.md](dev/ARCHITECTURE.md).
- `guide/` the end-user guide: plain-Markdown `sections/`, screenshots in `img/`, capture scripts in `scripts/`.
  Build from the repo root: `python docs/guide/scripts/build.py --strict` (writes `docs/guide/dist/`, gitignored;
  `--strict` fails on missing images or broken links). Capture output goes to `docs/guide/.capture/` (gitignored).
  Details: [guide/README.md](guide/README.md).
- `wiki/` in-app help plus reference notes; the assistant help pages ship in the installer. Serve it locally with
  `npm run wiki` from `app/` (runs `python ../tools/wiki/serve.py`).

Changelog and third-party notices stay in `app/` (`CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`).
