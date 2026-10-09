"""
M-Pesa (owner's request, 2026-10-09): parents pay fees and schools pay their
subscription by a PIN prompt (STK Push) or straight to the paybill (C2B).
Safaricom is never called: the Daraja calls are replaced in every test.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from billing.models import Invoice
from fees.models import Payment
from guardians.models import Guardian
from students.localtime import school_localdate
from students.models import Student

from . import daraja, services
from .models import C2BPayment, MpesaAccount, StkRequest
from .secrets_box import seal, unseal

OWNER = dict(MPESA_CALLBACK_BASE_URL="https://api.housemaster.test", MPESA_SHORTCODE="600999",
             MPESA_CONSUMER_KEY="ck", MPESA_CONSUMER_SECRET="cs", MPESA_PASSKEY="pk", MPESA_OWNER_CALLBACK_TOKEN="owner-secret-token",
             EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False,
             BILLING_OWNER_EMAIL="owner@housemaster.test")


def stk_callback(checkout, code=0, amount=None, receipt="SKD81QWERT"):
    body = {"MerchantRequestID": "m1", "CheckoutRequestID": checkout, "ResultCode": code,
            "ResultDesc": "The service request is processed successfully." if code == 0 else "Request cancelled by user"}
    if code == 0:
        body["CallbackMetadata"] = {"Item": [{"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt},
                                             {"Name": "TransactionDate", "Value": 20261009101500}, {"Name": "PhoneNumber", "Value": 254712345678}]}
    return {"Body": {"stkCallback": body}}


def c2b_body(trans_id, amount, bill_ref):
    return {"TransactionType": "Pay Bill", "TransID": trans_id, "TransTime": "20261009101500", "TransAmount": str(amount),
            "BusinessShortCode": "123456", "BillRefNumber": bill_ref, "MSISDN": "2547 ***** 678", "FirstName": "PAT"}


@override_settings(**OWNER)
class Base(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        from fees.models import Charge

        self.amina = Student.objects.create(school=self.school_a, first_name="Amina", last_name="K", external_id="ADM/2023/7")
        Charge.objects.create(school=self.school_a, student=self.amina, description="Tuition", amount=Decimal("15000"))
        parent = User.objects.create_user(username="pat", email="pat@parents.test", password="pass1234")
        self.parent = Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat Parent")
        self.parent.students.add(self.amina)
        self.parent_client = self.authed_client(parent)
        self.admin = self.authed_client(self.admin_a)
        self.account = MpesaAccount.objects.create(school=self.school_a, shortcode="123456", consumer_key=seal("k"),
                                                   consumer_secret=seal("s"), passkey=seal("p"))
        self.hooks = APIClient()

    def pay(self, amount=15000, phone="0712 345 678"):
        with mock.patch.object(daraja, "stk_push", return_value=("m1", f"ws_CO_{amount}")) as push:
            response = self.parent_client.post(f"/api/guardian-students/{self.amina.id}/fees/mpesa/",
                                               {"phone": phone, "amount": amount}, format="json")
        return response, push

    def callback(self, token, body):
        with self.captureOnCommitCallbacks(execute=True):
            return self.hooks.post(f"/api/mpesa/hooks/{token}/stk/", body, format="json")


class FeesStkTests(Base):
    def test_a_parent_pays_and_the_payment_and_receipt_follow(self):
        response, push = self.pay()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "pending")
        kwargs = push.call_args.kwargs
        self.assertEqual((kwargs["phone"], kwargs["amount"], kwargs["account_reference"]), ("254712345678", 15000, "ADM20237"))
        self.assertEqual(kwargs["callback_url"], f"https://api.housemaster.test/api/mpesa/hooks/{self.account.callback_token}/stk/")
        self.assertEqual(StkRequest.objects.get().phone_masked, "2547•••678")  # never the whole number
        self.assertEqual(self.callback(self.account.callback_token, stk_callback("ws_CO_15000", amount=15000)).data["ResultCode"], 0)
        payment = Payment.objects.get()
        self.assertEqual((payment.amount, payment.method, payment.reference, payment.recorded_by_name),
                         (Decimal("15000"), "mpesa", "SKD81QWERT", "M-Pesa"))
        self.assertIn("Receipt", mail.outbox[-1].subject)
        status = self.parent_client.get(f"/api/guardian-students/{self.amina.id}/fees/mpesa/{response.data['id']}/").data
        self.assertEqual((status["status"], status["receipt"]), ("paid", "SKD81QWERT"))
        # The same callback again changes nothing.
        self.callback(self.account.callback_token, stk_callback("ws_CO_15000", amount=15000))
        self.assertEqual(Payment.objects.count(), 1)

    def test_cancelled_on_the_phone(self):
        self.pay()
        self.callback(self.account.callback_token, stk_callback("ws_CO_15000", code=1032))
        self.assertEqual(StkRequest.objects.get().status, "failed")
        self.assertFalse(Payment.objects.exists())

    def test_a_forged_callback_does_nothing(self):
        self.pay()
        self.callback("wrong-token", stk_callback("ws_CO_15000", amount=15000))
        self.callback(self.account.callback_token, stk_callback("ws_CO_unknown", amount=15000))
        self.callback(self.account.callback_token, stk_callback("ws_CO_15000", amount=1))  # amount differs
        self.assertFalse(Payment.objects.exists())

    def test_a_lost_callback_is_settled_by_asking(self):
        response, _ = self.pay()
        StkRequest.objects.update(created_at=timezone.now() - timedelta(seconds=30))
        with mock.patch.object(daraja, "stk_query", return_value=(0, "processed successfully")):
            data = self.parent_client.get(f"/api/guardian-students/{self.amina.id}/fees/mpesa/{response.data['id']}/").data
        self.assertEqual(data["status"], "paid")
        self.assertEqual(Payment.objects.get().amount, Decimal("15000"))
        # The late callback fills in the receipt.
        self.callback(self.account.callback_token, stk_callback("ws_CO_15000", amount=15000))
        self.assertEqual(Payment.objects.get().reference, "SKD81QWERT")

    def test_bad_phone_amount_and_too_many(self):
        self.assertEqual(self.pay(phone="12345")[0].status_code, 400)
        self.assertEqual(self.pay(amount="10.5")[0].status_code, 400)
        self.assertEqual(self.pay(amount=300000)[0].status_code, 400)
        cache.clear()
        for n in range(5):
            self.assertEqual(self.pay(amount=100 + n)[0].status_code, 201)
        self.assertEqual(self.pay(amount=200)[0].status_code, 429)

    def test_only_parents_and_only_when_connected(self):
        from studentaccounts.models import StudentAccount

        login = User.objects.create_user(username="amina.k", password="pass1234")
        StudentAccount.objects.create(user=login, student=self.amina, must_change_password=False)
        response = self.authed_client(login).post(f"/api/guardian-students/{self.amina.id}/fees/mpesa/",
                                                  {"phone": "0712345678", "amount": 10}, format="json")
        self.assertEqual(response.status_code, 403)
        self.account.enabled = False
        self.account.save()
        self.assertEqual(self.pay()[0].status_code, 400)

    def test_what_the_parent_sees(self):
        info = self.parent_client.get(f"/api/guardian-students/{self.amina.id}/fees/").data["mpesa"]
        self.assertEqual(info, {"kind": "paybill", "number": "123456", "account": "ADM20237"})


class FeesC2BTests(Base):
    def confirm(self, body, token=None):
        with self.captureOnCommitCallbacks(execute=True):
            return self.hooks.post(f"/api/mpesa/hooks/{token or self.account.callback_token}/c2b/confirm/", body, format="json")

    def test_paid_to_the_paybill_with_the_admission_number(self):
        self.assertEqual(self.confirm(c2b_body("SKA1", 5000, "adm 2023 7")).data["ResultCode"], 0)
        payment = Payment.objects.get()
        self.assertEqual((payment.student, payment.amount, payment.reference), (self.amina, Decimal("5000"), "SKA1"))
        self.confirm(c2b_body("SKA1", 5000, "adm 2023 7"))  # sent twice
        self.assertEqual(Payment.objects.count(), 1)

    def test_unmatched_then_assigned_by_the_bursar(self):
        self.confirm(c2b_body("SKA2", 3000, "Amina form 1"))
        self.assertFalse(Payment.objects.exists())
        (row,) = self.admin.get("/api/fees/mpesa/payments/").data
        self.assertEqual((row["bill_ref"], row["status"]), ("Amina form 1", "unmatched"))
        with self.captureOnCommitCallbacks(execute=True):
            done = self.admin.post(f"/api/fees/mpesa/payments/{row['id']}/assign/", {"student": self.amina.id}, format="json").data
        self.assertEqual(done["status"], "recorded")
        self.assertEqual(Payment.objects.get().reference, "SKA2")
        self.assertEqual(self.admin.get("/api/fees/mpesa/payments/").data, [])

    def test_forged_or_other_schools(self):
        self.confirm(c2b_body("SKA3", 3000, "ADM20237"), token="nope")
        self.assertFalse(C2BPayment.objects.exists())
        self.confirm(c2b_body("SKA4", 3000, "Amina"))
        c2b = C2BPayment.objects.get()
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get("/api/fees/mpesa/payments/").data, [])
        self.assertEqual(self.client_b.post(f"/api/fees/mpesa/payments/{c2b.id}/assign/", {"student": self.amina.id},
                                            format="json").status_code, 404)


class FeesSettingsTests(Base):
    def test_keys_are_encrypted_and_never_sent_back(self):
        MpesaAccount.objects.all().delete()
        data = self.admin.put("/api/fees/mpesa/", {"kind": "till", "shortcode": "174379", "till_number": "8812345",
                                                   "environment": "production", "consumer_key": "KEY", "consumer_secret": "SECRET",
                                                   "passkey": "PASS"}, format="json").data
        self.assertTrue(data["connected"])
        self.assertNotIn("KEY", str(data))
        account = MpesaAccount.objects.get()
        self.assertNotEqual(account.consumer_key, "KEY")
        self.assertEqual(unseal(account.consumer_secret), "SECRET")
        # Saving again without the keys keeps them.
        self.admin.put("/api/fees/mpesa/", {"kind": "paybill", "shortcode": "174379", "environment": "sandbox"}, format="json")
        self.assertEqual(unseal(MpesaAccount.objects.get().passkey), "PASS")
        self.assertEqual(self.client_a.get("/api/fees/mpesa/").status_code, 403)

    def test_connect_registers_the_confirmation_address(self):
        with mock.patch.object(daraja, "register_c2b") as register:
            data = self.admin.post("/api/fees/mpesa/connect/").data
        self.assertIsNotNone(data["c2b_registered_at"])
        self.assertEqual(register.call_args.kwargs["confirmation_url"],
                         f"https://api.housemaster.test/api/mpesa/hooks/{self.account.callback_token}/c2b/confirm/")
        with mock.patch.object(daraja, "register_c2b", side_effect=daraja.DarajaError("M-Pesa didn't accept the keys.")):
            self.assertEqual(self.admin.post("/api/fees/mpesa/connect/").status_code, 400)


class SubscriptionTests(Base):
    def setUp(self):
        super().setUp()
        today = school_localdate(self.school_a)
        self.invoice = Invoice.objects.create(school=self.school_a, number="HM-202610-0001-1", plan_name="Per student",
                                              students=300, amount=Decimal("15000"), currency="KES", period_start=today,
                                              period_end=today + timedelta(days=30), issued_on=today, due_on=today)

    def test_the_admin_pays_with_the_pin_prompt(self):
        self.assertEqual(self.admin.get("/api/billing/").data["mpesa"], {"paybill": "600999", "account": f"HM{self.school_a.id:04d}"})
        with mock.patch.object(daraja, "stk_push", return_value=("m", "ws_CO_sub")) as push:
            response = self.admin.post(f"/api/billing/invoices/{self.invoice.id}/mpesa/", {"phone": "0712345678"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(push.call_args.kwargs["callback_url"], "https://api.housemaster.test/api/mpesa/hooks/owner-secret-token/stk/")
        self.callback(self.account.callback_token, stk_callback("ws_CO_sub", amount=15000))  # a school's token: ignored
        self.assertEqual(Invoice.objects.get().status, "open")
        self.callback("owner-secret-token", stk_callback("ws_CO_sub", amount=15000))
        invoice = Invoice.objects.get()
        self.assertEqual((invoice.status, invoice.payment_method, invoice.payment_reference), ("paid", "mpesa", "SKD81QWERT"))
        self.assertEqual(self.admin.get(f"/api/billing/mpesa/{response.data['id']}/").data["status"], "paid")
        self.assertEqual(self.client_a.post(f"/api/billing/invoices/{self.invoice.id}/mpesa/", {"phone": "0712345678"},
                                            format="json").status_code, 403)

    def test_paid_to_the_owners_paybill(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.hooks.post("/api/mpesa/hooks/owner-secret-token/c2b/confirm/",
                            c2b_body("SKB1", 15000, f"hm{self.school_a.id:04d}"), format="json")
        self.assertEqual(Invoice.objects.get().status, "paid")

    def test_short_or_unknown_payments_go_to_the_owner(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.hooks.post("/api/mpesa/hooks/owner-secret-token/c2b/confirm/", c2b_body("SKB2", 500, f"HM{self.school_a.id:04d}"), format="json")
            self.hooks.post("/api/mpesa/hooks/owner-secret-token/c2b/confirm/", c2b_body("SKB3", 15000, "rent"), format="json")
        self.assertEqual(Invoice.objects.get().status, "open")
        self.assertEqual(C2BPayment.objects.filter(status="unmatched").count(), 2)
        self.assertEqual([m.to for m in mail.outbox[-2:]], [["owner@housemaster.test"]] * 2)

    @override_settings(MPESA_OWNER_CALLBACK_TOKEN="")
    def test_off_until_the_owner_sets_it_up(self):
        self.assertIsNone(self.admin.get("/api/billing/").data["mpesa"])
        self.assertEqual(self.admin.post(f"/api/billing/invoices/{self.invoice.id}/mpesa/", {"phone": "0712345678"},
                                         format="json").status_code, 400)


class DarajaTests(SimpleTestCase):
    """What's sent to Safaricom (with the network replaced)."""

    def creds(self, **extra):
        return daraja.Credentials(environment="sandbox", shortcode="174379", consumer_key="k", consumer_secret="s",
                                  passkey="pk", **extra)

    def test_stk_push_payload(self):
        token = mock.Mock(status_code=200, json=lambda: {"access_token": "T"})
        sent = mock.Mock(status_code=200, json=lambda: {"ResponseCode": "0", "MerchantRequestID": "m", "CheckoutRequestID": "c"})
        with mock.patch("requests.get", return_value=token), mock.patch("requests.post", return_value=sent) as post:
            self.assertEqual(daraja.stk_push(self.creds(), phone="254712345678", amount=10, account_reference="ADM20237XYZ123",
                                             description="School fees", callback_url="https://x/cb"), ("m", "c"))
        url, body = post.call_args.args[0], post.call_args.kwargs["json"]
        self.assertEqual(url, "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest")
        self.assertEqual((body["TransactionType"], body["PartyB"], body["AccountReference"]), ("CustomerPayBillOnline", "174379", "ADM20237XYZ1"))
        import base64

        self.assertEqual(base64.b64decode(body["Password"]).decode(), f"174379pk{body['Timestamp']}")
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer T"})

    def test_till_uses_buy_goods(self):
        token = mock.Mock(status_code=200, json=lambda: {"access_token": "T"})
        sent = mock.Mock(status_code=200, json=lambda: {"ResponseCode": "0", "CheckoutRequestID": "c"})
        with mock.patch("requests.get", return_value=token), mock.patch("requests.post", return_value=sent) as post:
            daraja.stk_push(self.creds(kind="till", till_number="8812345"), phone="254712345678", amount=10,
                            account_reference="x", description="d", callback_url="https://x/cb")
        body = post.call_args.kwargs["json"]
        self.assertEqual((body["TransactionType"], body["BusinessShortCode"], body["PartyB"]), ("CustomerBuyGoodsOnline", "174379", "8812345"))

    def test_bad_keys(self):
        with mock.patch("requests.get", return_value=mock.Mock(status_code=400)):
            with self.assertRaises(daraja.DarajaError):
                daraja.access_token(self.creds())

    def test_phones(self):
        for raw in ("0712345678", "+254 712 345 678", "712345678", "0112345678"):
            self.assertRegex(services.normalize_phone(raw), r"^254[17]\d{8}$")
        for bad in ("12345", "0812345678", "", "25471234567"):
            with self.assertRaises(Exception):
                services.normalize_phone(bad)
