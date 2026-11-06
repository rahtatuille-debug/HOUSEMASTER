"""
The refresh token in an httpOnly cookie instead of the browser's localStorage (docs/DESIGN_httpOnly_refresh.md).

Off unless AUTH_REFRESH_COOKIE is set, because it needs the app and the API on one site (e.g. app.example.com and
api.example.com): from *.vercel.app to *.onrender.com the cookie would be a third-party cookie, which Safari blocks.

When on, every answer that signs someone in ({"access", "refresh"}) keeps the refresh token in a cookie only page
scripts can't read, scoped to /api/token/, and says so with "refresh_cookie": true; the frontend then keeps the
access token in memory. /api/token/refresh/ and /api/token/logout/ take the token from the cookie when the body has
none. Those two accept a cookie, so they also need the X-Requested-With: HouseMaster header (a form on another site
can't add it) and an Origin from CORS_ALLOWED_ORIGINS.
"""
import json
import re
from io import BytesIO

from django.conf import settings
from django.http import JsonResponse

COOKIE = "hm_refresh"
PATH = "/api/token/"
COOKIE_ENDPOINTS = ("/api/token/refresh/", "/api/token/logout/")
HEADER = "HouseMaster"


def enabled():
    return bool(getattr(settings, "AUTH_REFRESH_COOKIE", False))


def _origin_allowed(request):
    origin = request.headers.get("Origin", "")
    if not origin:
        return False
    if origin in settings.CORS_ALLOWED_ORIGINS:
        return True
    return any(re.match(p, origin) for p in getattr(settings, "CORS_ALLOWED_ORIGIN_REGEXES", []))


def _clear(response):
    response.delete_cookie(COOKIE, path=PATH, domain=settings.AUTH_REFRESH_COOKIE_DOMAIN or None, samesite="Strict")


class RefreshCookieMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not enabled() or request.method != "POST" or not request.path.startswith("/api/"):
            return self.get_response(request)
        from_cookie = False
        if request.path in COOKIE_ENDPOINTS:
            refused, from_cookie = self._take_cookie(request)
            if refused is not None:
                return refused
        response = self.get_response(request)
        if from_cookie and (request.path == "/api/token/logout/" or response.status_code == 401):
            _clear(response)
            return response
        return self._keep_in_cookie(response)

    def _take_cookie(self, request):
        """(refusal or None, whether the token came from the cookie)."""
        try:
            body = json.loads(request.body or b"{}")
        except ValueError:
            return None, False
        if not isinstance(body, dict) or body.get("refresh"):
            return None, False  # the old way (a token in the body) still works during the change-over
        token = request.COOKIES.get(COOKIE)
        if not token:
            return None, False
        if request.headers.get("X-Requested-With") != HEADER or not _origin_allowed(request):
            return JsonResponse({"detail": "This request must come from the HouseMaster app."}, status=403), False
        data = json.dumps({**body, "refresh": token}).encode()
        request._body = data
        request._stream = BytesIO(data)
        request.META["CONTENT_LENGTH"] = str(len(data))
        request.META["CONTENT_TYPE"] = "application/json"
        return None, True

    @staticmethod
    def _keep_in_cookie(response):
        if response.status_code not in (200, 201) or "json" not in response.get("Content-Type", ""):
            return response
        try:
            data = json.loads(response.content)
        except ValueError:
            return response
        if not (isinstance(data, dict) and data.get("refresh") and data.get("access")):
            return response
        token = data.pop("refresh")
        data["refresh_cookie"] = True
        response.content = json.dumps(data).encode()
        response["Content-Length"] = str(len(response.content))
        response.set_cookie(
            COOKIE, token, max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()), path=PATH,
            domain=settings.AUTH_REFRESH_COOKIE_DOMAIN or None, secure=not settings.DEBUG, httponly=True,
            samesite="Strict",
        )
        return response
