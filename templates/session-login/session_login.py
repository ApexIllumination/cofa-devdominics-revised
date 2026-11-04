"""Same-origin, single-process demo login for Python WSGI applications."""
import json
import secrets
from http.cookies import CookieError, SimpleCookie
from threading import Lock
from time import monotonic


def with_login(app, verify, *, secure_cookie=True, ttl=3600):
    """verify(user_id, password) returns a canonical user ID, or None on failure."""
    sessions = {}
    lock = Lock()
    attrs = "; Path=/; HttpOnly; SameSite=Lax" + ("; Secure" if secure_cookie else "")

    def handle(env, start):
        def reply(status, payload=None, cookie=None):
            body = b"" if payload is None else json.dumps(payload).encode()
            headers = [("Cache-Control", "no-store"), ("Content-Length", str(len(body)))]
            if payload is not None:
                headers.append(("Content-Type", "application/json"))
            if cookie:
                headers.append(("Set-Cookie", cookie))
            start(status, headers)
            return [body]

        try:
            morsel = SimpleCookie(env.get("HTTP_COOKIE", "")).get("kit_sid")
        except CookieError:
            morsel = None
        token = morsel.value if morsel else None
        with lock:
            now = monotonic()
            for key in list(sessions):
                if sessions[key][1] <= now:
                    del sessions[key]
            identity = sessions.get(token, (None,))[0]
        env["kit.user_id"] = identity
        path = env.get("PATH_INFO")
        if path not in ("/api/login", "/api/logout", "/api/me"):
            return app(env, start)
        method = env["REQUEST_METHOD"]
        if path == "/api/me" and method == "GET":
            return reply("200 OK", {"id": identity}) if identity else reply("401 Unauthorized")
        if path == "/api/me" or method != "POST":
            return reply("405 Method Not Allowed")
        if env.get("CONTENT_TYPE", "").split(";")[0].strip().lower() != "application/json":
            return reply("415 Unsupported Media Type")
        if path == "/api/logout":
            with lock:
                sessions.pop(token, None)
            return reply("204 No Content", cookie="kit_sid=; Max-Age=0" + attrs)
        try:
            length = int(env.get("CONTENT_LENGTH") or 0)
            if not 0 < length <= 16384:
                return reply("400 Bad Request")
            data = json.loads(env["wsgi.input"].read(length))
            if not isinstance(data, dict) or not all(isinstance(data.get(k), str) for k in ("id", "password")):
                return reply("400 Bad Request")
        except (ValueError, UnicodeError, RecursionError):
            return reply("400 Bad Request")
        user = verify(data["id"], data["password"])
        if not user:
            return reply("401 Unauthorized")
        fresh = secrets.token_urlsafe(32)
        with lock:
            sessions.pop(token, None)
            sessions[fresh] = (user, monotonic() + ttl)
        return reply("204 No Content", cookie="kit_sid=" + fresh + attrs)

    return handle
