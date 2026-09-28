"""
B-11: scripts/smoke_check.py, run against a local server set up correctly
and one set up wrongly, so each failure it reports is proven, not assumed.
"""
import importlib.util
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from django.test import SimpleTestCase

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "smoke_check.py"
spec = importlib.util.spec_from_file_location("smoke_check", SCRIPT)
smoke_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke_check)

SECURITY = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin"}


def make_handler(good):
    class Handler(BaseHTTPRequestHandler):
        logins = 0

        def log_message(self, *args):
            pass

        def reply(self, status, body=b"", content_type="application/json", headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def host_ok(self):
            return self.headers.get("Host", "").startswith("127.0.0.1")

        def do_OPTIONS(self):
            origin = self.headers.get("Origin", "")
            self.reply(200, headers={} if good else {"Access-Control-Allow-Origin": origin})

        def do_GET(self):
            base = SECURITY if good else {}
            if self.path == "/healthz":
                if good:
                    return self.reply(200, json.dumps({"status": "ok", "commit": "8e9ad30"}).encode(), headers=base)
                return self.reply(404, b"Not found", "text/html")
            if self.path == "/api/me/":
                if good and not self.host_ok():
                    return self.reply(400, b"Bad Request", "text/html")
                return self.reply(401 if good else 200, b"{}", headers=base)
            if self.path == "/api/":
                if good:
                    return self.reply(200, b"{}", headers=base)
                return self.reply(200, b"<html><form method=post></form></html>", "text/html")
            if self.path == "/admin/login/":
                if good:
                    return self.reply(404, b"Not found", "text/html")
                return self.reply(200, b"<title>Log in | Django site admin</title>", "text/html")
            if self.path == "/":
                if good:
                    return self.reply(200, b"<html></html>", "text/html",
                                      {**SECURITY, "Content-Security-Policy-Report-Only": "default-src 'self'"})
                return self.reply(302, headers={"Location": "https://elsewhere.invalid/login"})
            return self.reply(404, b"{}")

        def do_POST(self):
            if self.path == "/api/token/":
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                assert data["password"].startswith("wrong-"), "the check must never send a real password"
                type(self).logins += 1
                if good and type(self).logins > 10:
                    return self.reply(429, b'{"detail": "throttled"}', headers={"Retry-After": "3600"})
                return self.reply(401, b"{}")
            return self.reply(404, b"{}")

    return Handler


class ServerCase(SimpleTestCase):
    good = True

    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.good))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def run_checks(self, allow_http=True, throttle=False):
        out = io.StringIO()
        checker = smoke_check.Checker(self.base, self.base, allow_http=allow_http, timeout=5, out=out)
        checker.run_api()
        checker.run_frontend()
        if throttle:
            checker.verify_throttle("owner@example.org")
        code = checker.report()
        return code, {(area, check): (status, detail) for area, check, status, detail in checker.results}, out.getvalue()


class WellConfiguredTests(ServerCase):
    good = True

    def test_everything_passes(self):
        code, results, output = self.run_checks(throttle=True)
        self.assertEqual(code, 0, output)
        bad = {k: v for k, v in results.items() if v[0] == smoke_check.FAIL}
        self.assertEqual(bad, {})
        self.assertEqual(results[("API", "/healthz")], (smoke_check.PASS, "ok, commit 8e9ad30"))
        self.assertEqual(results[("API", "Login throttle")][0], smoke_check.PASS)
        self.assertEqual(results[("Frontend", "Content-Security-Policy")][0], smoke_check.WARN)  # report-only
        self.assertIn("0 failed", output)

    def test_plain_http_fails_unless_allowed_for_local_testing(self):
        code, results, _ = self.run_checks(allow_http=False)
        self.assertEqual(code, 1)
        self.assertEqual(results[("API", "HTTPS")][0], smoke_check.FAIL)
        self.assertEqual(results[("Frontend", "HTTPS")][0], smoke_check.FAIL)


class MisconfiguredTests(ServerCase):
    good = False

    def test_each_problem_is_reported(self):
        code, results, output = self.run_checks(throttle=True)
        self.assertEqual(code, 1, output)
        expected_failures = [
            ("API", "/healthz"), ("API", "/api/me/ needs a token"), ("API", "CORS"), ("API", "Unknown Host refused"),
            ("API", "Browsable API off"), ("API", "No MIME sniffing"), ("API", "Framing blocked"),
            ("API", "Login throttle"), ("Frontend", "Home page"),
        ]
        for key in expected_failures:
            self.assertEqual(results[key][0], smoke_check.FAIL, (key, results[key]))
        self.assertEqual(results[("API", "Default admin path")][0], smoke_check.WARN)
        self.assertEqual(results[("API", "Referrer policy")][0], smoke_check.WARN)

    def test_a_redirect_to_another_host_is_reported_and_not_followed(self):
        _, results, _ = self.run_checks()
        status, detail = results[("Frontend", "Home page")]
        self.assertEqual(status, smoke_check.FAIL)
        self.assertIn("ANOTHER HOST (elsewhere.invalid), not followed", detail)


class CertificateJudgementTests(SimpleTestCase):
    def test_expiry_levels(self):
        self.assertEqual(smoke_check.judge_certificate(90)[0], smoke_check.PASS)
        self.assertEqual(smoke_check.judge_certificate(5)[0], smoke_check.WARN)
        self.assertEqual(smoke_check.judge_certificate(-1)[0], smoke_check.FAIL)

    def test_unreachable_host_is_a_failure_not_a_crash(self):
        out = io.StringIO()
        checker = smoke_check.Checker("http://127.0.0.1:9", "http://127.0.0.1:9", allow_http=True, timeout=2, out=out)
        checker.run_api()
        checker.run_frontend()
        self.assertEqual(checker.report(), 1)
        self.assertIn("no answer", out.getvalue())
