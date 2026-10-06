"""
Phone and browser notifications (web push) for routine notices: a new
announcement or a report that is ready. Urgent alerts keep using email, and
SMS comes later.

Each device turns this on for itself. What we send is a short notice with
the school's name and no child's name or announcement text: it is
encrypted for the device, but it still passes through the browser maker's
push service. Nothing is sent until the owner sets the VAPID keys
(docs/ENVIRONMENT.md). A device the push service says is gone is forgotten.
"""
import base64
import json
import logging
import os
import time
from urllib.parse import urlsplit

import http_ece
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.db.models import Q
from py_vapid import Vapid02

from activity.services import log_activity

from .models import PushSubscription

logger = logging.getLogger(__name__)

# The browser makers' push services. The server sends to the address a device
# gives it, so anything else (an internal address, say) is refused.
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "push.services.mozilla.com",
              "web.push.apple.com", "push.apple.com", "notify.windows.com")
TTL_SECONDS = 24 * 60 * 60


def enabled():
    return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY)


def allowed_endpoint(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def _b64decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def valid_keys(p256dh, auth):
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _b64decode(p256dh))
        return len(_b64decode(auth)) == 16
    except (ValueError, TypeError):
        return False


def _encrypt(sub, payload):
    server_key = ec.generate_private_key(ec.SECP256R1())
    return http_ece.encrypt(payload, salt=os.urandom(16), private_key=server_key, dh=_b64decode(sub.p256dh),
                            auth_secret=_b64decode(sub.auth), version="aes128gcm")


def _headers(endpoint):
    parts = urlsplit(endpoint)
    vapid = Vapid02.from_raw(settings.VAPID_PRIVATE_KEY.encode())
    claims = {"sub": settings.VAPID_SUBJECT, "aud": f"{parts.scheme}://{parts.netloc}", "exp": int(time.time()) + 12 * 3600}
    headers = vapid.sign(claims)
    headers.update({"TTL": str(TTL_SECONDS), "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                    "Urgency": "normal"})
    return headers


def send_to_users(user_ids, title, body, url="/"):
    """Send one notice to every device of these users. Returns (sent, attempted)."""
    if not enabled() or not user_ids:
        return 0, 0
    payload = json.dumps({"title": title, "body": body, "url": url}).encode()
    subs = list(PushSubscription.objects.filter(user_id__in=user_ids))
    sent, gone = 0, []
    for sub in subs:
        if not allowed_endpoint(sub.endpoint):  # stored before a rule change: never send there
            gone.append(sub.id)
            continue
        try:
            response = requests.post(sub.endpoint, data=_encrypt(sub, payload), headers=_headers(sub.endpoint),
                                     timeout=10, allow_redirects=False)
        except Exception:  # one device's push service being down shouldn't stop the rest
            logger.exception("Push notification failed")
            continue
        if response.status_code in (404, 410):
            gone.append(sub.id)
        elif 200 <= response.status_code < 300:
            sent += 1
        else:
            logger.warning("Push service answered %s", response.status_code)
    if gone:
        PushSubscription.objects.filter(id__in=gone).delete()
    return sent, len(subs)


def announcement_user_ids(announcement):
    """Parents in this announcement's audience who have a device turned on (their email choice doesn't matter)."""
    from guardians.models import Guardian

    from .models import Announcement

    parents = Guardian.objects.filter(school=announcement.school, user__is_active=True, user__push_subscriptions__isnull=False)
    audience = announcement.audience
    if audience == Announcement.Audience.YEAR_GROUP:
        parents = parents.filter(students__school_class__year_group=announcement.year_group, students__is_active=True)
    elif audience == Announcement.Audience.SCHOOL_CLASS:
        parents = parents.filter(students__school_class=announcement.school_class, students__is_active=True)
    elif audience != Announcement.Audience.ALL_PARENTS:
        return []
    return sorted(set(parents.values_list("user_id", flat=True)))


def report_user_ids(reports):
    from guardians.models import Guardian

    return sorted(set(Guardian.objects.filter(
        Q(students__in=[r.student_id for r in reports]), user__is_active=True, user__push_subscriptions__isnull=False,
    ).values_list("user_id", flat=True)))


def push_and_log(school, actor, user_ids, body, target=None, what=""):
    sent, attempted = send_to_users(user_ids, school.name, body)
    if attempted:
        log_activity(school=school, actor=actor, action="notification.pushed", target=target,
                     summary=f"Sent {sent} of {attempted} phone or browser notifications{what}")

