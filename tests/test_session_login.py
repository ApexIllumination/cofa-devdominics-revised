import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "templates/session-login"))
from session_login import with_login


class LoginContract(unittest.TestCase):
    def setUp(self):
        def private_page(env, start):
            user = env["kit.user_id"]
            start("200 OK" if user else "401 Unauthorized", [])
            return [(user or "").encode()]

        accounts = {"a": "a-pass", "b": "b-pass"}
        self.app = with_login(private_page, lambda u, p: u if accounts.get(u) == p else None)

    def request(self, path, cookie="", data=None, query=""):
        env = {}
        setup_testing_defaults(env)
        body = json.dumps(data).encode()
        env.update(PATH_INFO=path, QUERY_STRING=query, HTTP_COOKIE=cookie,
                   REQUEST_METHOD="GET" if data is None else "POST",
                   CONTENT_LENGTH=str(len(body)), CONTENT_TYPE="application/json")
        env["wsgi.input"] = io.BytesIO(body)
        response = []
        payload = b"".join(self.app(env, lambda s, h: response.extend((int(s[:3]), dict(h)))))
        return response[0], response[1], payload

    def login(self, user, old=""):
        status, headers, body = self.request("/api/login", old, {"id": user, "password": user+"-pass"})
        self.assertEqual((status, body), (204, b""))
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("; Secure", headers["Set-Cookie"])
        return headers["Set-Cookie"].split(";")[0]

    def test_switch_refresh_and_replay(self):
        self.assertEqual(self.request("/api/me")[0], 401)
        self.assertEqual(self.request("/api/login", data={"id":"a","password":"bad"})[0], 401)
        first = self.login("a")
        self.assertEqual(json.loads(self.request("/api/me", first)[2]), {"id":"a"})
        self.assertEqual(self.request("/private", first, query="id=b")[2], b"a")
        second = self.login("b", first)
        self.assertEqual(self.request("/private", first)[0], 401)
        self.assertEqual(self.request("/private", second)[2], b"b")
        self.assertEqual(self.request("/api/logout", second, {})[0], 204)
        self.assertEqual(self.request("/private", second)[0], 401)

    def test_expiry(self):
        with patch("session_login.monotonic", return_value=100):
            token = self.login("a")
        with patch("session_login.monotonic", return_value=3700):
            self.assertEqual(self.request("/api/me", token)[0], 401)
