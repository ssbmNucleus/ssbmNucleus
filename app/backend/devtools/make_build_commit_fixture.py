"""Build the minimal REAL MEX project that MexCLI's code compiler accepts.

``tests/backend/test_build_commit_real_project.py`` needs a project the actual
``mexcli sync-codes`` will open, because a synthetic one proves only that the
transaction works around a stand-in. A whole project is 1.4 GB; MexCLI needs a
lot less than that. Measured on 2026-09-22, ``TryOpenWorkspace`` needs exactly:

    project.mexproj                 the project file
    sys/                            boot.bin, bi2.bin, apploader.img, main.dol
    data/                           the whole mex data folder (~1.2 MB)
    files/TyDataf.dat               \\
    files/TyDatai.usd                | TrophyLoader.LoadFromFileSystem reads
    files/SdToy.usd                  | these four during LoadMiscData
    files/SdToyExp.usd              /
    files/codes.ini, files/codes.gct
    files/MnSlChr.usd               the menu file the test replaces

which is about 6 MB. That tree is retail game data, so it is NEVER committed
(``app/.gitignore`` excludes it) and is built here on demand from a project
the user already has:

    python devtools/make_build_commit_fixture.py
    python devtools/make_build_commit_fixture.py --from ../projects/My_Project

The integration test skips when the fixture is absent, and says this command.
"""
import argparse
import shutil
import sys
from pathlib import Path

# The devtools sys.path shim every script here carries, so it runs from any cwd.
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

FIXTURE = BACKEND / 'artifacts' / 'build-commit-fixture'

#: The files under ``files/`` MexCLI opens before it will touch a code list.
REQUIRED_FILES = ('TyDataf.dat', 'TyDatai.usd', 'SdToy.usd', 'SdToyExp.usd',
                  'codes.ini', 'codes.gct',
                  # not needed to OPEN the workspace, but the integration test
                  # replaces it, so the before-state has to be a real menu file
                  'MnSlChr.usd')
REQUIRED_SYS = ('boot.bin', 'bi2.bin', 'apploader.img', 'main.dol')


def pick_source():
    """The first MEX project on this machine that has everything needed."""
    from core import config
    projects = Path(config.PROJECTS_PATH)
    for marker in sorted(projects.glob('*/project.mexproj')):
        directory = marker.parent
        if all((directory / 'files' / name).is_file() for name in REQUIRED_FILES) \
                and all((directory / 'sys' / name).is_file() for name in REQUIRED_SYS) \
                and (directory / 'data' / 'mex.json').is_file():
            return directory
    return None


def build(source, destination=FIXTURE):
    """Copy the minimal tree out of a real project."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    (destination / 'files').mkdir(parents=True)
    (destination / 'sys').mkdir()
    (destination / 'assets').mkdir()
    shutil.copyfile(source / 'project.mexproj', destination / 'project.mexproj')
    shutil.copytree(source / 'data', destination / 'data')
    for name in REQUIRED_SYS:
        shutil.copyfile(source / 'sys' / name, destination / 'sys' / name)
    for name in REQUIRED_FILES:
        shutil.copyfile(source / 'files' / name, destination / 'files' / name)
    total = sum(path.stat().st_size for path in destination.rglob('*') if path.is_file())
    return destination, total


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='source', default=None,
                        help='a MEX project directory to copy from')
    parser.add_argument('--to', dest='destination', default=str(FIXTURE))
    args = parser.parse_args(argv[1:])

    source = Path(args.source) if args.source else pick_source()
    if source is None or not (source / 'project.mexproj').is_file():
        print('No usable MEX project found. Open or create one in the app first, or pass '
              '--from <project directory>.')
        return 2
    destination, total = build(source, args.destination)
    print(f'Built {destination} from {source} ({total / 1e6:.1f} MB).')
    print('This is retail game data: it is gitignored and must stay local.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
