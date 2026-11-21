"""What the local backend serves to whom, beyond the /api token gate in app.py.

Two holes this closes:

* The file routes outside /api (/storage, /vanilla, /utility, /assets and the
  pose thumbnails under /storage/poses) carried no token at all, so any local
  process -- and any web page, through a sandboxed iframe (Origin "null" is a
  CORS-allowed origin, because the packaged app loads from file://) or through
  DNS rebinding -- could read storage/nucleome.db (whose kv table holds the
  Patreon vault token), vault.db and metadata.json.
  Now only media files stay public, because <img src>, new Audio() and CSS
  backgrounds cannot send the X-Nucleus-Token header and the backend hands the
  frontend bare /storage URLs. Every other file needs the token (header, or
  ?_nucleus_token= on GET), and databases, their -wal/-shm/-journal sidecars
  and key material are never served at all.
* No Host check, so a DNS-rebinding page (attacker.example resolving to
  127.0.0.1) was same-origin with the backend. Every request, Socket.IO
  included, must now name a loopback host: 127.0.0.1, localhost or [::1], with
  any port.
"""

import json
from pathlib import PurePosixPath

from flask import jsonify, request

LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})

# Route prefixes that serve files from disk without going through /api.
STATIC_FILE_PREFIXES = ("/storage/", "/vanilla/", "/utility/", "/assets/", "/static/")

# What the UI loads with a plain tag: images, menu sounds, previews.
MEDIA_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico",
    ".wav", ".mp3", ".ogg", ".m4a", ".flac",
    ".mp4", ".webm",
})

# Never served, token or not: databases with their sidecars, and key material.
SENSITIVE_SUFFIXES = (
    ".db", ".sqlite", ".sqlite3", ".db3",
    "-wal", "-shm", "-journal",
    ".pem", ".key", ".env", "token",
)


def host_is_local(host_header):
    """True when a Host header names the loopback interface (any port or none)."""
    if not isinstance(host_header, str) or not host_header.strip():
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        if end < 0:
            return False
        name, rest = host[1:end], host[end + 1:]
    else:
        name, sep, port = host.partition(":")
        rest = sep + port
    if rest and not (rest.startswith(":") and rest[1:].isdigit()):
        return False
    return name in LOCAL_HOSTNAMES


class LocalHostOnly:
    """WSGI middleware: refuse any request whose Host is not loopback.

    Wraps the whole app (Flask routes and the Socket.IO endpoint), so a page
    reached through DNS rebinding gets a 403 before any route runs."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        if host_is_local(environ.get("HTTP_HOST")):
            return self.wsgi_app(environ, start_response)
        body = json.dumps({"success": False, "error": "Forbidden host"}).encode()
        start_response("403 FORBIDDEN", [("Content-Type", "application/json"),
                                         ("Content-Length", str(len(body)))])
        return [body]


def static_file_access(path):
    """How a request path may be served: None (not a file route), 'public',
    'token' (needs the backend token) or 'deny' (never served)."""
    if not path.startswith(STATIC_FILE_PREFIXES):
        return None
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    # Windows opens "x.db." and "x.db " as x.db: judge the name it will open.
    name = name.rstrip(" .")
    if name.endswith(SENSITIVE_SUFFIXES):
        return "deny"
    if ":" in name or "\x00" in name:
        return "deny"  # NTFS streams (x.db::$DATA) and other tricks
    return "public" if PurePosixPath(name).suffix in MEDIA_EXTENSIONS else "token"


def install(app, is_valid_token):
    """Gate the file routes and wrap the WSGI app in the Host check.

    Call after SocketIO(app) so the Host check also covers /socket.io."""

    @app.before_request
    def guard_static_files():
        if request.method == "OPTIONS":
            return None
        access = static_file_access(request.path)
        if access in (None, "public"):
            return None
        if access == "deny":
            return jsonify({"success": False, "error": "Not found"}), 404
        if app.testing:
            return None
        candidate = request.headers.get("X-Nucleus-Token")
        if request.method in ("GET", "HEAD") and not candidate:
            candidate = request.args.get("_nucleus_token")
        if not is_valid_token(candidate):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return None

    app.wsgi_app = LocalHostOnly(app.wsgi_app)
    return guard_static_files
