"""Turns authenticated webhook requests into trigger files.

POST /<hook> with "Authorization: Bearer <token>" creates
/hooks/<hook>/requested, which a systemd .path unit on the host watches. A
hook exists when WEBHOOK_<HOOK>_TOKEN is set and its directory is mounted.

The request body is never read, and nothing here runs a command: the host
decides on its own what a trigger means.
"""

import hmac
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOOKS_DIR = Path("/hooks")
HOOK_NAME = re.compile(r"[a-z0-9-]+")


def hook_token(name):
    if not HOOK_NAME.fullmatch(name):
        return ""
    return os.environ.get(f"WEBHOOK_{name.upper().replace('-', '_')}_TOKEN", "")


class Handler(BaseHTTPRequestHandler):
    # Drops clients that hold a connection open without sending a request.
    timeout = 10

    def do_POST(self):
        name = urlsplit(self.path).path.strip("/")
        token = hook_token(name)
        if not token or not (HOOKS_DIR / name).is_dir():
            self.reply(404)
            return
        given = self.headers.get("Authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
            self.reply(401)
            return
        try:
            (HOOKS_DIR / name / "requested").touch()
        except OSError as error:
            self.log_error("can't create the trigger file: %s", error)
            self.reply(500)
            return
        self.reply(202)

    def reply(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # Python's default names its version.
    def version_string(self):
        return "webhooks"

    # Requests all come through Caddy, which replaces any X-Forwarded-For a
    # client sends with the client's own address.
    def address_string(self):
        headers = getattr(self, "headers", None)
        forwarded = headers.get("X-Forwarded-For") if headers else None
        return forwarded or super().address_string()


if __name__ == "__main__":
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
