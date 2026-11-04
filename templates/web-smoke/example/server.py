"""Local smoke fixture. Pass the compiled example bundle path as argv[1]."""
import json
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "session-login"))
from session_login import with_login

items = {"alice": "ALPHA-17", "bob": "BRAVO-42"}


def fixture(env, start):
    path = env["PATH_INFO"]
    status = "200 OK"
    if path == "/":
        content, body = "text/html; charset=utf-8", b'<meta charset=utf-8><div id=root></div><script src="/app.js"></script>'
    elif path == "/app.js":
        content, body = "text/javascript", Path(sys.argv[1]).read_bytes()
    elif path == "/api/item" and env["kit.user_id"]:
        content, body = "application/json", json.dumps({"item": items[env["kit.user_id"]]}).encode()
    else:
        status = "401 Unauthorized" if path == "/api/item" else "404 Not Found"
        content, body = "text/plain", b""
    start(status, [("Content-Type", content), ("Cache-Control", "no-store")])
    return [body]


if __name__ == "__main__":
    verify = lambda user, password: user if user in items and password == "demo" else None
    with make_server("127.0.0.1", int(sys.argv[2]) if len(sys.argv) > 2 else 0,
                     with_login(fixture, verify, secure_cookie=False)) as server:
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
