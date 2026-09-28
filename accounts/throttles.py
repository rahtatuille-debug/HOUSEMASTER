"""
Rate limits for the public endpoints (login, password reset, invites,
sign-up links, school registration, token refresh).

Each endpoint is limited per client IP address and, where the request
names an account, per email address as well. The per-email limit ignores
the IP completely, so rotating a spoofed X-Forwarded-For header can't get
round it. The client IP comes from DRF's get_ident(), which only trusts
X-Forwarded-For as far as settings NUM_PROXIES (env DRF_NUM_PROXIES) says.

Rates live in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] and can be changed
with environment variables (housemaster/settings.py). A throttled request
gets DRF's standard 429 with a Retry-After header, which says nothing about
whether the account exists.
"""
from rest_framework.throttling import SimpleRateThrottle


def normalise_email(value):
    return value.strip().lower() if isinstance(value, str) else ""


class IPThrottle(SimpleRateThrottle):
    """Limits requests per client IP address, for the rate named by `scope`."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class EmailThrottle(SimpleRateThrottle):
    """Limits requests per email address in the request body (`email_field`)."""

    email_field = "email"

    def get_cache_key(self, request, view):
        email = normalise_email(request.data.get(self.email_field)) if hasattr(request, "data") else ""
        if not email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": email}


class FailureOnlyMixin:
    """
    Only failed attempts count: allow_request() checks the history without
    adding to it, and the view calls record_failure() when a login fails.
    Staff at one school often share an IP address, so successful logins
    must never lock their colleagues out.
    """

    def allow_request(self, request, view):
        if self.rate is None:
            return True
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True
        self.history = self.cache.get(self.key, [])
        self.now = self.timer()
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        return len(self.history) < self.num_requests

    def record_failure(self):
        if getattr(self, "key", None) is None:
            return
        self.history.insert(0, self.now)
        self.cache.set(self.key, self.history, self.duration)


class LoginIPThrottle(FailureOnlyMixin, IPThrottle):
    scope = "login_ip"


class LoginEmailThrottle(FailureOnlyMixin, EmailThrottle):
    scope = "login_email"


class PasswordResetIPThrottle(IPThrottle):
    scope = "password_reset_ip"


class PasswordResetEmailThrottle(EmailThrottle):
    scope = "password_reset_email"


class InviteIPThrottle(IPThrottle):
    """Invite previews and acceptance, parent invites and class sign-up links."""
    scope = "invite_ip"


class RegistrationEmailThrottle(EmailThrottle):
    scope = "school_registration_email"


class TokenRefreshIPThrottle(IPThrottle):
    scope = "token_refresh_ip"
