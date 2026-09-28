import logging
import threading
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework.throttling import BaseThrottle

logger = logging.getLogger("housemaster.client_ip")


class ClientIPDebugMiddleware:
    """
    Temporary diagnostic, switched on with LOG_CLIENT_IP_DEBUG=1. Logs the
    raw X-Forwarded-For header, REMOTE_ADDR and the client identity the rate
    limits would use, for the first LIMIT requests after start-up only, so
    the owner can work out how many proxies Render puts in front of the app
    and set DRF_NUM_PROXIES. See docs/ENVIRONMENT.md. Switch it off again
    once DRF_NUM_PROXIES is set: it logs IP addresses.
    """

    LIMIT = 20

    def __init__(self, get_response):
        self.get_response = get_response
        self.seen = 0
        self.lock = threading.Lock()

    def __call__(self, request):
        with self.lock:
            log_this = self.seen < self.LIMIT
            self.seen += 1
        if log_this:
            logger.info(
                "X-Forwarded-For=%r REMOTE_ADDR=%s identity=%s",
                request.META.get("HTTP_X_FORWARDED_FOR", ""),
                request.META.get("REMOTE_ADDR", ""),
                BaseThrottle().get_ident(request),
            )
        return self.get_response(request)


class AdminLoginThrottleMiddleware:
    """
    Limits failed sign-ins on the Django admin's login page per client
    address (settings.ADMIN_LOGIN_RATE per hour), since the admin is a
    single password protecting every school. Viewing the page and
    successful sign-ins don't count. The address comes from the same logic
    as the API's rate limits (DRF_NUM_PROXIES).
    """

    WINDOW = 60 * 60

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != "POST" or request.path != f"/{settings.ADMIN_PATH}login/":
            return self.get_response(request)
        key = f"admin-login-failures:{BaseThrottle().get_ident(request)}"
        now = time.time()
        recent = [t for t in cache.get(key, []) if t > now - self.WINDOW]
        if len(recent) >= settings.ADMIN_LOGIN_RATE:
            response = HttpResponse("Too many sign-in attempts. Try again later.", status=429,
                                    content_type="text/plain")
            response["Retry-After"] = str(int(self.WINDOW - (now - min(recent))) + 1)
            return response
        response = self.get_response(request)
        if response.status_code == 200:  # the form came back with an error: a failed attempt
            cache.set(key, recent + [now], self.WINDOW)
        return response
