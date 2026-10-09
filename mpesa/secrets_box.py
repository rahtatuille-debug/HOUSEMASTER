"""The M-Pesa keys at rest: encrypted with a key derived from the server's SECRET_KEY (or MPESA_ENCRYPTION_KEY)."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    seed = getattr(settings, "MPESA_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"mpesa:{seed}".encode()).digest()))


def seal(value):
    return _fernet().encrypt(value.encode()).decode() if value else ""


def unseal(value):
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:  # the server's key changed: the school has to enter its keys again
        return ""
