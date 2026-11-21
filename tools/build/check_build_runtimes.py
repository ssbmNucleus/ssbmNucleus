"""Check the actual Electron binary and Windows Python used by this build."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app/backend"))
from core.runtime_versions import check_electron, check_windows_python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--electron-exe", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    check_windows_python()
    package = json.loads((ROOT / "app/package.json").read_text(encoding="utf-8"))
    expected = package["devDependencies"]["electron"]
    check_electron(expected)
    executable = args.electron_exe or ROOT / "app/node_modules/electron/dist/electron.exe"
    if not executable.is_file():
        raise RuntimeError(f"Electron executable is missing: {executable}. Run node node_modules/electron/install.js from app/ first.")
    env = os.environ.copy()
    env["ELECTRON_RUN_AS_NODE"] = "1"
    result = subprocess.run(
        [str(executable), "-e", "console.log(JSON.stringify(process.versions))"],
        env=env, capture_output=True, text=True, timeout=30, check=True,
    )
    versions = json.loads(result.stdout.strip())
    check_electron(versions["electron"])
    if versions["electron"] != expected:
        raise RuntimeError(f"Actual Electron {versions['electron']} differs from pin {expected}")
    report = {"python": sys.version.split()[0], "electron": versions,
              "electron_executable": str(executable.resolve())}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
