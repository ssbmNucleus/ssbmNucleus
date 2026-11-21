"""Dependency-only check: never import Nucleus or open its data directories."""
import importlib
import importlib.metadata
import sys

DEPENDENCIES = {
    "Flask": "flask", "Flask-CORS": "flask_cors",
    "Flask-SocketIO": "flask_socketio", "python-socketio": "socketio",
    "numpy": "numpy", "scipy": "scipy.spatial", "pyyaml": "yaml",
    "pillow": "PIL.Image", "requests": "requests",
    "huggingface_hub": "huggingface_hub", "tqdm": "tqdm",
    "peppi-py": "peppi_py", "py7zr": "py7zr",
    "websocket-client": "websocket", "xxhash": "xxhash",
}

def main():
    failed = sys.version_info < (3, 10)
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    if failed:
        print("[ERROR] Python 3.10+ is required.")
    for distribution, module in DEPENDENCIES.items():
        try:
            version = importlib.metadata.version(distribution)
            importlib.import_module(module)
            print(f"[OK] {distribution} {version}")
        except Exception as exc:
            failed = True
            print(f"[ERROR] {distribution}: {exc}")
    return int(failed)

if __name__ == "__main__":
    raise SystemExit(main())
