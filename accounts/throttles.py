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
from collections import Counter

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


class InviteSendUserThrottle(SimpleRateThrottle):
    """Invite emails (new or renewed) one admin can send. Reading and cancelling aren't limited."""

    scope = "invite_send_user"

    @classmethod
    def key_for(cls, user):
        return cls.cache_format % {"scope": cls.scope, "ident": user.pk}

    def get_cache_key(self, request, view):
        if request.method != "POST" or not request.user.is_authenticated:
            return None
        return self.key_for(request.user)


class InviteSendRecipientThrottle(SimpleRateThrottle):
    """
    Invite emails one address can receive, from any school, so invites can't
    be used to flood someone's inbox. A renewal counts against the invite
    being renewed.
    """

    scope = "invite_send_recipient"

    @classmethod
    def key_for(cls, ident):
        return cls.cache_format % {"scope": cls.scope, "ident": ident}

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None
        email = normalise_email(request.data.get("email"))
        ident = email or (f"{view.basename}-{view.kwargs['pk']}" if view.kwargs.get("pk") else "")
        if not ident:
            return None
        return self.key_for(ident)


def _per(seconds):
    return {1: "per second", 60: "per minute", 3600: "per hour", 86400: "per day"}.get(seconds, f"per {seconds} seconds")


def reserve_invite_email(user, email, *, record=True, pending=None):
    """
    Counts one invite from `user` to `email` against the same two limits as
    single invites (the two throttles above, same counters and rates), for
    code that creates invites outside those requests: the bulk staff import.

    Returns None when the invite may go ahead, otherwise a sentence saying
    which limit is full. Nothing is counted when it's refused. With
    record=False (a preview) the counts are kept in `pending`, a Counter the
    caller passes for the whole run, instead of the shared counters.
    """
    pending = Counter() if pending is None else pending
    checks = [
        (InviteSendUserThrottle(), InviteSendUserThrottle.key_for(user),
         "You have reached the limit of {n} staff and parent invites {per}. Run the import again later "
         "to invite this person."),
        (InviteSendRecipientThrottle(), InviteSendRecipientThrottle.key_for(normalise_email(email)),
         "This address has reached the limit of {n} invites {per}. Try again later."),
    ]
    for throttle, key, message in checks:
        if throttle.rate is None:
            continue
        throttle.key, throttle.now = key, throttle.timer()
        throttle.history = [t for t in throttle.cache.get(key, []) if t > throttle.now - throttle.duration]
        if len(throttle.history) + pending[key] >= throttle.num_requests:
            return message.format(n=throttle.num_requests, per=_per(throttle.duration))
    for throttle, key, _ in checks:
        if throttle.rate is None:
            continue
        if record:
            throttle.throttle_success()  # DRF's own bookkeeping, as for a single invite
        else:
            pending[key] += 1
    return None
