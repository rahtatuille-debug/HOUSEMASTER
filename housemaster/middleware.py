import logging
import threading

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
