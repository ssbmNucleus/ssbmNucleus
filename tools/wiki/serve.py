import argparse
import json
import os
import socketserver
import sys
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from pathlib import Path, PurePosixPath


DEFAULT_PORT = 4173
# The wiki is served from docs/ (so /wiki/ is docs/wiki/). Find it from wherever this script lives.
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "wiki").is_dir()) / "docs"
SAVE_ENDPOINT = "/__wiki_api/save"
EDITABLE_SUFFIXES = {".md", ".txt", ".json"}


class ReusableThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


class WikiRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_POST(self):
        if self.path != SAVE_ENDPOINT:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown API route.")
            return

        try:
            payload = self._read_json_body()
            raw_path = payload.get("path")
            content = payload.get("content")

            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError("A non-empty 'path' string is required.")
            if not isinstance(content, str):
                raise ValueError("A string 'content' field is required.")

            target_path = self._resolve_repo_path(raw_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with target_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)

            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "path": raw_path,
                    "bytes_written": len(content.encode("utf-8")),
                },
            )
        except ValueError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
        except OSError as error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(error)})

    def _read_json_body(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid Content-Length header.") from error

        if content_length <= 0:
            raise ValueError("Request body is required.")

        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error

        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")

        return payload

    def _resolve_repo_path(self, raw_path: str) -> Path:
        normalized_path = PurePosixPath(raw_path.strip())
        if normalized_path.is_absolute():
            raise ValueError("Absolute paths are not allowed.")

        candidate = (REPO_ROOT / Path(*normalized_path.parts)).resolve()
        try:
            candidate.relative_to(REPO_ROOT)
        except ValueError as error:
            raise ValueError("Path must stay within the docs folder.") from error

        if candidate.suffix.lower() not in EDITABLE_SUFFIXES:
            raise ValueError("Only .md, .txt, and .json files can be edited from the wiki.")

        return candidate

    def _send_json(self, status: HTTPStatus, payload):
        encoded_body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded_body)))
        self.end_headers()
        self.wfile.write(encoded_body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the local markdown wiki.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to.")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the wiki in the default browser after the server starts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.chdir(REPO_ROOT)

    handler = lambda *handler_args, **handler_kwargs: WikiRequestHandler(
        *handler_args,
        directory=str(REPO_ROOT),
        **handler_kwargs,
    )

    with ReusableThreadingTCPServer(("127.0.0.1", args.port), handler) as server:
        url = f"http://127.0.0.1:{args.port}/wiki/"
        print(f"Serving docs from: {REPO_ROOT}")
        print(f"Open the wiki at: {url}")
        print("Press Ctrl+C to stop.")

        if args.open:
            webbrowser.open(url)

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping wiki server.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
