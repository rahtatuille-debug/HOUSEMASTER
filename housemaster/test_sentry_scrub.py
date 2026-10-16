"""
Secrets never reach Sentry: an error in an M-Pesa callback, captured exactly as production configures
Sentry, must not carry the school's callback token anywhere in the event.
"""
import json

import sentry_sdk
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.transport import Transport

from accounts.tests import SchoolScopedAPITestCase
from housemaster.sentry_scrub import before_breadcrumb, before_send, scrub
from mpesa.models import MpesaAccount
from mpesa.secrets_box import seal


class Capture(Transport):
    events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type in ("event", "transaction"):
                Capture.events.append(item.payload.json)


class ScrubTests(SimpleTestCase):
    def test_secrets_in_paths_and_queries_are_removed(self):
        token = "a" * 40
        cases = {
            f"/api/payments/hooks/{token}/stk/": "/api/payments/hooks/[Filtered]/stk/",
            "/api/calendar/ical/Zx9-abc.ics": "/api/calendar/ical/[Filtered]",
            "https://app.example/join/Zx9-abc": "https://app.example/join/[Filtered]",
            "/apply/confirm/Zx9-abc": "/apply/confirm/[Filtered]",
            "/apply/Zx9-abc": "/apply/[Filtered]",
            "/reset-password/Zx9-abc/": "/reset-password/[Filtered]/",
            "/api/invites/preview/Zx9-abc/": "/api/invites/preview/[Filtered]/",
            "/login?next=/x&token=Zx9": "/login?next=/x&token=[Filtered]",
            f"expected {token}": "expected [Filtered]",
        }
        for raw, clean in cases.items():
            self.assertEqual(scrub(raw), clean, raw)

    def test_values_under_sensitive_names_are_dropped_and_ids_kept(self):
        event = {"release": "f" * 40, "event_id": "e" * 32,
                 "exception": {"values": [{"stacktrace": {"frames": [
                     {"vars": {"token": "short-secret", "passkey": "p", "consumer_secret": "s", "count": 3}}]}}]}}
        frame = scrub(event)["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        self.assertEqual(frame, {"token": "[Filtered]", "passkey": "[Filtered]", "consumer_secret": "[Filtered]",
                                 "count": 3})
        self.assertEqual(scrub(event)["release"], "f" * 40)

    @override_settings(MPESA_OWNER_CALLBACK_TOKEN="owner-secret-value-xyz")
    def test_the_owner_token_is_removed_whatever_its_form(self):
        self.assertEqual(before_breadcrumb({"message": "called with owner-secret-value-xyz"}, {}),
                         {"message": "called with [Filtered]"})


class CallbackErrorTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.account = MpesaAccount.objects.create(school=self.school_a, shortcode="123456", consumer_key=seal("k"),
                                                   consumer_secret=seal("s"), passkey=seal("p"))
        Capture.events = []
        # As in settings.py, with a fake address and a transport that keeps events here.
        sentry_sdk.init(dsn="https://key@o0.ingest.sentry.io/0", transport=Capture, integrations=[DjangoIntegration()],
                        traces_sample_rate=1.0, send_default_pii=False, before_send=before_send,
                        before_send_transaction=before_send, before_breadcrumb=before_breadcrumb)

    def tearDown(self):
        sentry_sdk.get_client().close()
        sentry_sdk.init()  # off again for the other tests
        super().tearDown()

    def test_a_failing_callback_sends_no_token(self):
        token = self.account.callback_token
        client = APIClient()
        client.post(f"/api/payments/hooks/{token}/stk/", "{not json", content_type="application/json")
        client.post(f"/api/payments/hooks/{token}/c2b/confirm/", {"TransID": "X1", "TransAmount": "abc"}, format="json")
        sentry_sdk.flush()
        self.assertTrue(any(e.get("exception") for e in Capture.events), "the callback error wasn't captured")
        for event in Capture.events:
            self.assertNotIn(token, json.dumps(event, default=str))
