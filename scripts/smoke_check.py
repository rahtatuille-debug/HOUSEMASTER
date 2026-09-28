#!/usr/bin/env python3
"""
Read-only checks of a deployed HouseMaster (B-11). Standard library only.

    python scripts/smoke_check.py --api https://housemaster-api.onrender.com \\
                                  --frontend https://housemaster.vercel.app

It only reads: it never signs in, never sends a real password, never
changes data and never follows a redirect (a redirect is reported, with
where it points). It prints a pass/fail table in plain language and exits
with status 1 if anything failed (warnings don't fail it).

Checks: HTTPS and the certificate (days left), HSTS, security headers
(nosniff, frame options, referrer policy) on both sites, the frontend's
Content-Security-Policy (report-only or enforcing), that the API doesn't
hand its CORS permission to a foreign Origin, that an unknown Host is
refused, that /api/me/ needs a token (401), that DRF's HTML browsable API
is off, whether the default /admin/ path answers (a warning), /healthz and
the commit it reports, and how long the first request took (a sleeping
free-tier instance takes about a minute).

--verify-throttle EMAIL (off by default) also sends 12 wrong-password
logins for EMAIL, with a random password, and expects 429 by the 11th.
That locks EMAIL out of signing in for up to an hour, so use an address
you control. --allow-http lets the checks run against a local http://
server (HTTPS-only checks are then skipped); never use it for production.
"""
import argparse
import json
import secrets
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
FOREIGN_ORIGIN = "https://smoke-check.invalid"
UNKNOWN_HOST = "unknown-host.smoke-check.invalid"
USER_AGENT = "HouseMaster-smoke-check/1 (read-only)"
CERT_WARN_DAYS = 14
COLD_START_WARN_SECONDS = 10


class Response:
    def __init__(self, status, headers, body, seconds):
        self.status, self.headers, self.body, self.seconds = status, headers, body, seconds

    def header(self, name):
        return self.headers.get(name.lower(), "")

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8", "replace"))
        except ValueError:
            return None


def fetch(base, path, *, method="GET", headers=None, body=None, host=None, timeout=20):
    """One request, never following redirects. `host` overrides the Host header."""
    parts = urlsplit(base)
    connection_class = HTTPSConnection if parts.scheme == "https" else HTTPConnection
    kwargs = {"timeout": timeout}
    if parts.scheme == "https":
        kwargs["context"] = ssl.create_default_context()
    connection = connection_class(parts.hostname, parts.port, **kwargs)
    sent = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    if host:
        sent["Host"] = host
    started = time.monotonic()
    try:
        connection.request(method, (parts.path.rstrip("/") + path) or "/", body=body, headers=sent)
        raw = connection.getresponse()
        content = raw.read(256 * 1024)
        return Response(raw.status, {k.lower(): v for k, v in raw.getheaders()}, content, time.monotonic() - started)
    finally:
        connection.close()


def certificate_days_left(hostname, port=443, timeout=20):
    context = ssl.create_default_context()
    with socket.create_connection((hostname, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=hostname) as tls:
            not_after = tls.getpeercert()["notAfter"]
    expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    return (expires - datetime.now(timezone.utc)).days


def judge_certificate(days_left):
    if days_left < 0:
        return FAIL, f"the certificate expired {-days_left} days ago"
    if days_left < CERT_WARN_DAYS:
        return WARN, f"the certificate expires in {days_left} days"
    return PASS, f"valid for {days_left} more days"


def redirect_note(response, base):
    """A redirect we did not follow, described. A different host is called out."""
    location = response.header("location")
    if not location:
        return "redirected with no Location"
    target = urlsplit(location)
    if target.hostname and target.hostname != urlsplit(base).hostname:
        return f"redirects to ANOTHER HOST ({target.hostname}), not followed"
    return f"redirects to {location}, not followed"


class Checker:
    def __init__(self, api, frontend, allow_http=False, timeout=20, out=sys.stdout):
        self.api, self.frontend = api.rstrip("/"), frontend.rstrip("/")
        self.allow_http, self.timeout, self.out = allow_http, timeout, out
        self.results = []

    def add(self, area, check, status, detail):
        self.results.append((area, check, status, detail))

    def get(self, base, path, **kwargs):
        return fetch(base, path, timeout=self.timeout, **kwargs)

    # --- both sites ---------------------------------------------------------

    def transport(self, area, base):
        parts = urlsplit(base)
        if parts.scheme != "https":
            status = SKIP if self.allow_http else FAIL
            self.add(area, "HTTPS", status, "not https (local test)" if self.allow_http else "the address isn't https://")
            self.add(area, "Certificate", SKIP, "not https")
            self.add(area, "HSTS", SKIP, "not https")
            return
        self.add(area, "HTTPS", PASS, "https://")
        try:
            self.add(area, "Certificate", *judge_certificate(certificate_days_left(parts.hostname, parts.port or 443,
                                                                                   self.timeout)))
        except (ssl.SSLError, ssl.CertificateError) as exc:
            self.add(area, "Certificate", FAIL, f"not trusted: {exc.__class__.__name__}")
        except OSError as exc:
            self.add(area, "Certificate", FAIL, f"couldn't connect: {exc.__class__.__name__}")

    def hsts(self, area, response):
        if urlsplit(self.api if area == "API" else self.frontend).scheme != "https":
            return
        value = response.header("strict-transport-security")
        max_age = 0
        for part in value.split(";"):
            if part.strip().lower().startswith("max-age="):
                try:
                    max_age = int(part.split("=", 1)[1])
                except ValueError:
                    max_age = 0
        if max_age > 0:
            self.add(area, "HSTS", PASS, f"max-age={max_age}")
        else:
            self.add(area, "HSTS", FAIL, "no Strict-Transport-Security header")

    def security_headers(self, area, response):
        nosniff = response.header("x-content-type-options").lower() == "nosniff"
        self.add(area, "No MIME sniffing", PASS if nosniff else FAIL,
                 "X-Content-Type-Options: nosniff" if nosniff else "X-Content-Type-Options: nosniff is missing")
        frames = response.header("x-frame-options").upper()
        csp = response.header("content-security-policy") + response.header("content-security-policy-report-only")
        framing_ok = frames in ("DENY", "SAMEORIGIN") or "frame-ancestors" in csp
        self.add(area, "Framing blocked", PASS if framing_ok else FAIL,
                 f"X-Frame-Options: {frames}" if frames else ("CSP frame-ancestors" if framing_ok
                                                              else "no X-Frame-Options or frame-ancestors"))
        referrer = response.header("referrer-policy")
        self.add(area, "Referrer policy", PASS if referrer else WARN,
                 referrer or "no Referrer-Policy (browsers default to strict-origin-when-cross-origin)")

    # --- API ------------------------------------------------------------------

    def run_api(self):
        self.transport("API", self.api)
        try:
            first = self.get(self.api, "/healthz")
        except OSError as exc:
            self.add("API", "Reachable", FAIL, f"no answer from {self.api}: {exc.__class__.__name__}")
            return
        seconds = round(first.seconds, 1)
        self.add("API", "First request", WARN if seconds > COLD_START_WARN_SECONDS else PASS,
                 f"{seconds} s" + (" (asleep? the free tier sleeps when idle)" if seconds > COLD_START_WARN_SECONDS
                                    else ""))
        self.healthz(first)
        me = self.get(self.api, "/api/me/")
        self.hsts("API", me)
        self.security_headers("API", me)
        if 300 <= me.status < 400:
            self.add("API", "/api/me/ needs a token", FAIL, redirect_note(me, self.api))
        else:
            self.add("API", "/api/me/ needs a token", PASS if me.status == 401 else FAIL,
                     f"{me.status} without a token" + ("" if me.status == 401 else " (expected 401)"))
        self.cors()
        self.unknown_host()
        self.browsable_api()
        self.admin_path()

    def healthz(self, response):
        data = response.json() if response.status in (200, 503) else None
        if response.status == 200 and isinstance(data, dict) and data.get("status") == "ok":
            commit = data.get("commit") or "unknown"
            self.add("API", "/healthz", PASS if commit != "unknown" else WARN,
                     f"ok, commit {commit}" + ("" if commit != "unknown" else " (RENDER_GIT_COMMIT not set)"))
        elif response.status == 503:
            self.add("API", "/healthz", FAIL, "degraded: the app runs but the database isn't answering")
        elif 300 <= response.status < 400:
            self.add("API", "/healthz", FAIL, redirect_note(response, self.api))
        else:
            self.add("API", "/healthz", FAIL, f"{response.status}: not the HouseMaster health check (deployed?)")

    def cors(self):
        response = self.get(self.api, "/api/me/", method="OPTIONS", headers={
            "Origin": FOREIGN_ORIGIN, "Access-Control-Request-Method": "GET"})
        allowed = response.header("access-control-allow-origin")
        if allowed in (FOREIGN_ORIGIN, "*"):
            self.add("API", "CORS", FAIL, f"a foreign website is allowed to call the API ({allowed})")
        else:
            self.add("API", "CORS", PASS, "a foreign Origin isn't allowed")

    def unknown_host(self):
        try:
            response = self.get(self.api, "/api/me/", host=UNKNOWN_HOST)
        except OSError as exc:
            self.add("API", "Unknown Host refused", PASS, f"connection refused ({exc.__class__.__name__})")
            return
        if response.status in (401, 200) or 300 <= response.status < 400:
            self.add("API", "Unknown Host refused", FAIL,
                     f"answered {response.status} for Host {UNKNOWN_HOST} (DJANGO_ALLOWED_HOSTS too open?)")
        else:
            self.add("API", "Unknown Host refused", PASS, f"{response.status}")

    def browsable_api(self):
        response = self.get(self.api, "/api/", headers={"Accept": "text/html"})
        html = "text/html" in response.header("content-type") and b"<form" in response.body.lower()
        self.add("API", "Browsable API off", FAIL if html else PASS,
                 "DRF's HTML pages are switched on" if html else "JSON only")

    def admin_path(self):
        response = self.get(self.api, "/admin/login/", headers={"Accept": "text/html"})
        exposed = response.status == 200 and b"django" in response.body.lower() or (
            300 <= response.status < 400 and "/admin/" in response.header("location"))
        self.add("API", "Default admin path", WARN if exposed else PASS,
                 "the Django admin is at /admin/ (set DJANGO_ADMIN_PATH)" if exposed else f"{response.status}")

    # --- frontend -----------------------------------------------------------

    def run_frontend(self):
        self.transport("Frontend", self.frontend)
        try:
            page = self.get(self.frontend, "/", headers={"Accept": "text/html"})
        except OSError as exc:
            self.add("Frontend", "Reachable", FAIL, f"no answer from {self.frontend}: {exc.__class__.__name__}")
            return
        if 300 <= page.status < 400:
            self.add("Frontend", "Home page", FAIL, redirect_note(page, self.frontend))
            return
        self.add("Frontend", "Home page", PASS if page.status == 200 else FAIL, f"{page.status}")
        self.hsts("Frontend", page)
        self.security_headers("Frontend", page)
        if page.header("content-security-policy"):
            self.add("Frontend", "Content-Security-Policy", PASS, "enforcing")
        elif page.header("content-security-policy-report-only"):
            self.add("Frontend", "Content-Security-Policy", WARN, "report-only (switch to enforcing after clean days, H-12)")
        else:
            self.add("Frontend", "Content-Security-Policy", FAIL, "no CSP header")

    # --- opt-in throttle check ----------------------------------------------

    def verify_throttle(self, email, attempts=12, expect_by=11):
        password = "wrong-" + secrets.token_urlsafe(16)  # never a real password
        codes = []
        for _ in range(attempts):
            response = self.get(self.api, "/api/token/", method="POST",
                                headers={"Content-Type": "application/json"},
                                body=json.dumps({"email": email, "password": password}))
            codes.append(response.status)
            if response.status == 429:
                break
        limited_at = codes.index(429) + 1 if 429 in codes else None
        ok = limited_at is not None and limited_at <= expect_by
        self.add("API", "Login throttle", PASS if ok else FAIL,
                 f"429 on attempt {limited_at}" if limited_at else f"no 429 after {len(codes)} wrong passwords")

    # --- output ---------------------------------------------------------------

    def report(self):
        widths = [max(len(str(row[i])) for row in self.results + [("Area", "Check", "Result", "")]) for i in range(3)]
        print(f"{'Area':<{widths[0]}}  {'Check':<{widths[1]}}  {'Result':<{widths[2]}}  Detail", file=self.out)
        for area, check, status, detail in self.results:
            print(f"{area:<{widths[0]}}  {check:<{widths[1]}}  {status:<{widths[2]}}  {detail}", file=self.out)
        failed = [r for r in self.results if r[2] == FAIL]
        warned = [r for r in self.results if r[2] == WARN]
        print(f"\n{len(self.results)} checks: {len(failed)} failed, {len(warned)} warnings.", file=self.out)
        return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", required=True, help="the backend's base URL, e.g. https://housemaster-api.onrender.com")
    parser.add_argument("--frontend", required=True, help="the frontend's base URL, e.g. https://housemaster.vercel.app")
    parser.add_argument("--verify-throttle", metavar="EMAIL",
                        help="also send 12 wrong-password logins for EMAIL (locks it out for up to an hour)")
    parser.add_argument("--yes", action="store_true", help="don't pause before --verify-throttle")
    parser.add_argument("--allow-http", action="store_true", help="local testing only: allow http:// addresses")
    parser.add_argument("--timeout", type=float, default=90, help="seconds to wait for each answer (default 90)")
    args = parser.parse_args(argv)
    checker = Checker(args.api, args.frontend, allow_http=args.allow_http, timeout=args.timeout)
    checker.run_api()
    checker.run_frontend()
    if args.verify_throttle:
        print(f"WARNING: sending 12 wrong-password logins for {args.verify_throttle}. That address won't be able to "
              "sign in for up to an hour. Press Ctrl+C now to stop.", file=sys.stderr)
        if not args.yes:
            time.sleep(5)
        checker.verify_throttle(args.verify_throttle)
    return checker.report()


if __name__ == "__main__":
    sys.exit(main())
