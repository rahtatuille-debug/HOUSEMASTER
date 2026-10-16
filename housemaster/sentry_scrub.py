"""
Removes secrets from Sentry events before they leave the server.

send_default_pii=False keeps cookies, auth headers and request bodies out, but not URLs or the
local variables Sentry attaches to each stack frame. Several addresses carry their secret in the
path (the M-Pesa callbacks, the calendar feed, sign-up, invite and admissions links), so an error
in one of those views would send the secret itself to Sentry: for the M-Pesa callbacks, enough to
mark fees as paid. Every string in the event is scrubbed, and values under sensitive names are
dropped.
"""
import re

from django.conf import settings

FILTERED = "[Filtered]"

# The segment after these is a secret. Longer alternatives come first ("apply/confirm" before "apply").
TOKEN_PATH = re.compile(
    r"(/(?:payments/hooks|mpesa/hooks|calendar/ical|staff-join|join|guardian-invites/preview|invites/preview"
    r"|guardian-invite|invite|admissions/apply|admissions/confirm|apply/confirm|apply|reset-password)/)"
    r"[^/?#\s'\"<>]+",
    re.IGNORECASE)
TOKEN_QUERY = re.compile(r"([?&](?:token|key|code|uid|secret|password|signature)=)[^&#\s'\"<>]+", re.IGNORECASE)
# The schools' M-Pesa callback tokens are 40 hex characters (secrets.token_hex(20)).
HEX_40 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{40}(?![0-9a-fA-F])")
SENSITIVE_NAMES = {
    "token", "callback_token", "passkey", "consumer_key", "consumer_secret", "secret", "password", "passphrase",
    "access", "refresh", "authorization", "cookie", "api_key", "key", "creds", "credentials",
}
# Event fields that are identifiers, not content, and may legitimately be 40 hex characters.
KEEP = {"release", "event_id", "trace_id", "span_id", "parent_span_id", "dist"}


def _scrub_text(text):
    text = TOKEN_PATH.sub(r"\1" + FILTERED, text)
    text = TOKEN_QUERY.sub(r"\1" + FILTERED, text)
    text = HEX_40.sub(FILTERED, text)
    owner = getattr(settings, "MPESA_OWNER_CALLBACK_TOKEN", "")
    if owner:
        text = text.replace(owner, FILTERED)
    return text


def scrub(value, key=None):
    if key in KEEP:
        return value
    if isinstance(key, str) and key.lower() in SENSITIVE_NAMES:
        return FILTERED
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {k: scrub(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def before_send(event, hint):
    return scrub(event)


def before_breadcrumb(crumb, hint):
    return scrub(crumb)
