"""
Secrets at rest: the schools' M-Pesa keys and callback tokens, encrypted with Fernet.

MPESA_ENCRYPTION_KEY is a comma-separated list of keys: the first encrypts, every one of them decrypts, so a
key can be replaced without losing what the old one encrypted (`manage.py mpesa_rekey` then re-encrypts
everything with the new first key). A key derived from SECRET_KEY is always tried last, because that is what
encrypted the keys before MPESA_ENCRYPTION_KEY existed; without MPESA_ENCRYPTION_KEY it is the only key, which
production refuses for new secrets (PAY-008 in the readiness re-check: changing SECRET_KEY would have silently
disconnected every school).
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

logger = logging.getLogger(__name__)


class UnreadableSecret(Exception):
    """Encrypted with a key the server no longer has."""


class NoEncryptionKey(Exception):
    """Production has no MPESA_ENCRYPTION_KEY, so new secrets would depend on SECRET_KEY."""


def _fernet_for(seed):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"mpesa:{seed}".encode()).digest()))


def configured_keys():
    return [k.strip() for k in (getattr(settings, "MPESA_ENCRYPTION_KEY", "") or "").split(",") if k.strip()]


def _box():
    return MultiFernet([_fernet_for(k) for k in configured_keys()] + [_fernet_for(settings.SECRET_KEY)])


def _key_required():
    return not settings.DEBUG and not getattr(settings, "TESTING", False)


def seal(value, require_key=True):
    """require_key=False only for the migration that encrypts secrets that were already stored in plain text."""
    if not value:
        return ""
    if require_key and _key_required() and not configured_keys():
        raise NoEncryptionKey("Set MPESA_ENCRYPTION_KEY before saving M-Pesa keys (docs/ENVIRONMENT.md).")
    return _box().encrypt(value.encode()).decode()


def unseal(value):
    if not value:
        return ""
    try:
        return _box().decrypt(value.encode()).decode()
    except InvalidToken:
        logger.error("An M-Pesa secret can't be decrypted with any configured key: MPESA_ENCRYPTION_KEY or "
                     "SECRET_KEY changed without keeping the old key.")
        raise UnreadableSecret


def reseal(value):
    """The same secret, encrypted with the current first key."""
    return _box().rotate(value.encode()).decode() if value else ""
