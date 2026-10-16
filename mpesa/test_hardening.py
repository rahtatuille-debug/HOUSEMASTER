"""
The M-Pesa connection itself (PAY-005 to PAY-008 in the readiness re-check): who can change where the money
goes, the secret in the callback addresses, rate limits on those addresses, and the encryption key.
"""
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import override_settings

from accounts.models import Profile, StaffRole
from activity.models import ActivityLog

from . import daraja, secrets_box, views
from .models import MpesaAccount, hash_token
from .secrets_box import NoEncryptionKey, UnreadableSecret, seal, unseal
from .tests import OWNER, Base

SETTINGS = {"kind": "paybill", "shortcode": "777888", "environment": "production"}


@override_settings(**OWNER)
class WhoChangesWhereTheMoneyGoes(Base):
    """PAY-006: one bursar alone could repoint the paybill, with no alert."""

    def setUp(self):
        super().setUp()
        Profile.objects.filter(user=self.user_a).update(role=Profile.Role.TEACHER)
        StaffRole.objects.create(profile=self.user_a.profile, role=StaffRole.Role.BURSAR)
        self.bursar = self.authed_client(self.user_a)

    def test_a_bursar_sees_the_settings_but_cant_change_them(self):
        self.assertFalse(self.bursar.get("/api/fees/mpesa/").data["can_change"])
        self.assertTrue(self.admin.get("/api/fees/mpesa/").data["can_change"])
        self.assertEqual(self.bursar.put("/api/fees/mpesa/", SETTINGS, format="json").status_code, 403)
        self.assertEqual(self.bursar.post("/api/fees/mpesa/new-address/").status_code, 403)
        self.assertEqual(MpesaAccount.objects.get().shortcode, "123456")

    def test_every_admin_is_told_what_changed(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.admin.put("/api/fees/mpesa/", SETTINGS, format="json")
        self.assertEqual(response.status_code, 200)
        (email,) = [m for m in mail.outbox if "M-Pesa settings changed" in m.subject]
        self.assertIn(self.admin_a.email, email.to)
        self.assertIn("Before: paybill 123456", email.body)
        self.assertIn("Now: paybill 777888", email.body)
        log = ActivityLog.objects.filter(action="mpesa.settings").latest("id")
        self.assertIn("from paybill 123456", log.summary)
        self.assertIn("to paybill 777888", log.summary)

    def test_saving_without_a_change_sends_nothing(self):
        same = {"kind": "paybill", "shortcode": "123456", "environment": "sandbox"}
        with self.captureOnCommitCallbacks(execute=True):
            self.admin.put("/api/fees/mpesa/", same, format="json")
        self.assertFalse([m for m in mail.outbox if "M-Pesa" in m.subject])


@override_settings(**OWNER)
class CallbackAddressSecret(Base):
    """PAY-005: the secret in the addresses Safaricom calls."""

    def stk(self, token):
        return self.hooks.post(f"/api/payments/hooks/{token}/c2b/confirm/",
                               {"TransID": "QX1", "TransAmount": "100", "BillRefNumber": "ADM2023/7"}, format="json")

    def test_stored_as_a_hash_and_matched_by_it(self):
        token = self.account.callback_token
        self.assertEqual(self.account.token_hash, hash_token(token))
        self.assertNotIn(token, str(MpesaAccount.objects.filter(pk=self.account.pk).values().get()))
        self.stk(token)
        self.assertEqual(self.account.school.c2b_payments.count(), 1)

    def test_a_new_address_retires_the_old_one(self):
        old = self.account.callback_token
        self.account.c2b_registered_at = self.account.updated_at
        self.account.save()
        with mock.patch.object(daraja, "register_c2b") as register, self.captureOnCommitCallbacks(execute=True):
            response = self.admin.post("/api/fees/mpesa/new-address/")
        self.assertEqual(response.status_code, 200)
        self.account.refresh_from_db()
        new = self.account.callback_token
        self.assertNotEqual(old, new)
        self.assertIn(new, register.call_args.kwargs["confirmation_url"])
        self.stk(old)
        self.assertEqual(self.account.school.c2b_payments.count(), 0)  # the old address does nothing now
        self.stk(new)
        self.assertEqual(self.account.school.c2b_payments.count(), 1)
        self.assertTrue([m for m in mail.outbox if "callback address changed" in m.subject])

    def test_if_m_pesa_refuses_the_new_address_nothing_changes(self):
        old = self.account.callback_token
        self.account.c2b_registered_at = self.account.updated_at
        self.account.save()
        with mock.patch.object(daraja, "register_c2b", side_effect=daraja.DarajaError("URLs already registered")):
            response = self.admin.post("/api/fees/mpesa/new-address/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("nothing changed", str(response.data))
        self.account.refresh_from_db()
        self.assertEqual(self.account.callback_token, old)


@override_settings(**OWNER)
class RateLimits(Base):
    """PAY-007: the callback addresses had no limit at all."""

    def test_the_callback_addresses_are_limited_per_address(self):
        with mock.patch.dict(views.CallbackThrottle.THROTTLE_RATES, {"mpesa_callback": "3/minute"}):
            codes = [self.hooks.post(f"/api/payments/hooks/{'0' * 40}/stk/", {}, format="json").status_code
                     for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])

    def test_junk_is_a_warning_not_an_error_report(self):
        with self.assertLogs("mpesa.services", level="WARNING") as logs:
            self.hooks.post(f"/api/payments/hooks/{self.account.callback_token}/stk/", "{not json",
                            content_type="application/json")
        self.assertEqual([r.levelname for r in logs.records], ["WARNING"])


class EncryptionKey(Base):
    """PAY-008: the keys were encrypted with a key derived from SECRET_KEY, and a change lost them silently."""

    def test_secrets_from_before_the_key_was_set_still_open(self):
        old = seal("SECRET")  # no MPESA_ENCRYPTION_KEY: the SECRET_KEY-derived key
        with override_settings(MPESA_ENCRYPTION_KEY="new-key-1"):
            self.assertEqual(unseal(old), "SECRET")
            self.assertNotEqual(secrets_box.reseal(old), old)

    def test_a_key_can_be_replaced_keeping_the_old_one_to_read(self):
        with override_settings(MPESA_ENCRYPTION_KEY="key-a"):
            sealed = seal("SECRET")
        with override_settings(MPESA_ENCRYPTION_KEY="key-b,key-a"):
            self.assertEqual(unseal(sealed), "SECRET")
        with override_settings(MPESA_ENCRYPTION_KEY="key-b", SECRET_KEY="another-secret-key-" + "x" * 40):
            with self.assertRaises(UnreadableSecret), self.assertLogs("mpesa.secrets_box", level="ERROR"):
                unseal(sealed)

    def test_unreadable_keys_say_so_instead_of_failing_quietly(self):
        MpesaAccount.objects.filter(pk=self.account.pk).update(consumer_key="gAAAAA-not-a-real-token")
        with self.assertLogs("mpesa.secrets_box", level="ERROR"):
            response = self.parent_client.post(f"/api/guardian-students/{self.amina.id}/fees/mpesa/",
                                               {"phone": "0712345678", "amount": 100}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("can't be read", str(response.data))

    @override_settings(DEBUG=False, TESTING=False, MPESA_ENCRYPTION_KEY="")
    def test_production_wont_store_new_keys_without_a_key_of_their_own(self):
        with self.assertRaises(NoEncryptionKey):
            seal("SECRET")
        response = self.admin.put("/api/fees/mpesa/", {**SETTINGS, "consumer_key": "K", "consumer_secret": "S",
                                                       "passkey": "P"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("MPESA_ENCRYPTION_KEY", str(response.data))

    def test_rekey_moves_everything_to_the_new_key(self):
        token = self.account.callback_token
        out = StringIO()
        with override_settings(MPESA_ENCRYPTION_KEY="key-new"):
            call_command("mpesa_rekey", stdout=out)
            self.assertIn("1 school", out.getvalue())
        # Readable with only the new key now (SECRET_KEY changed too).
        with override_settings(MPESA_ENCRYPTION_KEY="key-new", SECRET_KEY="another-secret-key-" + "x" * 40):
            account = MpesaAccount.objects.get(pk=self.account.pk)
            self.assertEqual(account.callback_token, token)
            self.assertEqual(unseal(account.passkey), "p")
