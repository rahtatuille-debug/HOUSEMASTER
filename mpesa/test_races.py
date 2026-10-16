"""
The same payment arriving or being confirmed several times at the same moment is recorded once (PAY-001 to
PAY-004, PAY-009). These need real concurrent writers, so they run on PostgreSQL (CI's test-postgres job).
"""
import threading
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Profile
from accounts.tests import SchoolScopedAPITestCase
from fees.models import Payment, PaymentClaim
from guardians.models import Guardian
from students.models import School, Student

from . import daraja
from .models import C2BPayment, MpesaAccount, StkRequest
from .secrets_box import seal
from .tests import OWNER, stk_callback

TIMES = 6


def at_once(fn, times=TIMES):
    """Run fn(i) in `times` threads released together; each thread uses its own database connection."""
    barrier, results = threading.Barrier(times), [None] * times

    def run(i):
        try:
            barrier.wait()
            results[i] = fn(i)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(times)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def now_c2b(trans_id, amount, bill_ref):
    return {"TransactionType": "Pay Bill", "TransID": trans_id, "TransAmount": str(amount), "BillRefNumber": bill_ref,
            "TransTime": timezone.localtime(timezone.now(), daraja.NAIROBI).strftime("%Y%m%d%H%M%S"),
            "MSISDN": "2547 ***** 678", "FirstName": "PAT"}


@skipUnless(connection.vendor == "postgresql", "needs concurrent writers (production's Postgres); SQLite's in-memory "
                                               "test database refuses the second writer")
@override_settings(**OWNER)
class PaymentRaceTests(TransactionTestCase):
    def setUp(self):
        self.school = School.objects.create(name="Alpha Academy")
        admin = User.objects.create_user(username="admin", email="admin@a.test", password="x")
        Profile.objects.create(user=admin, school=self.school, role=Profile.Role.ADMIN)
        self.admin_user = admin
        self.amina = Student.objects.create(school=self.school, first_name="Amina", last_name="K", external_id="ADM7")
        parent = User.objects.create_user(username="pat", email="pat@p.test", password="x")
        self.guardian = Guardian.objects.create(user=parent, school=self.school, display_name="Pat")
        self.guardian.students.add(self.amina)
        self.parent_user = parent
        self.account = MpesaAccount.objects.create(school=self.school, shortcode="123456", consumer_key=seal("k"),
                                                   consumer_secret=seal("s"), passkey=seal("p"))

    def admin(self):
        return SchoolScopedAPITestCase.authed_client(self.admin_user)

    def hooks(self, path, body):
        return APIClient().post(f"/api/payments/hooks/{self.account.callback_token}/{path}/", body, format="json")

    def payments(self):
        return Payment.objects.filter(student=self.amina, voided_at__isnull=True)

    def test_a_claim_confirmed_six_times_at_once(self):
        claim = PaymentClaim.objects.create(school=self.school, student=self.amina, claimed_by=self.parent_user,
                                            claimed_by_name="Pat", amount=Decimal("3000"), paid_on=timezone.localdate(),
                                            method="mpesa", reference="QAB12CD34E")
        codes = at_once(lambda i: self.admin().post(f"/api/fees/claims/{claim.id}/confirm/", {}, format="json").status_code)
        self.assertEqual(sorted(codes).count(200), 1, codes)
        self.assertEqual(self.payments().count(), 1)

    def test_an_unmatched_payment_assigned_six_times_at_once(self):
        self.hooks("c2b/confirm", now_c2b("QAB12CD34E", 2000, "NOBODY"))
        c2b = C2BPayment.objects.get()
        codes = at_once(lambda i: self.admin().post(f"/api/fees/mpesa/payments/{c2b.id}/assign/",
                                                    {"student": self.amina.id}, format="json").status_code)
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(self.payments().count(), 1)

    def test_the_prompt_callback_and_the_paybill_confirmation_at_the_same_moment(self):
        StkRequest.objects.create(purpose="fees", school=self.school, student=self.amina, amount=15000,
                                  phone_masked="2547•••678", account_reference="ADM7", checkout_request_id="ws_CO_1",
                                  requested_by=self.parent_user, requested_by_name="Pat")
        callback, confirmation = stk_callback("ws_CO_1", amount=15000, receipt="SKD81QWERT"), now_c2b("SKD81QWERT", 15000, "ADM7")
        at_once(lambda i: self.hooks("stk" if i % 2 else "c2b/confirm", callback if i % 2 else confirmation))
        (payment,) = self.payments()
        self.assertEqual(payment.reference, "SKD81QWERT")

    def test_one_code_entered_for_the_same_child_six_times_at_once(self):
        codes = at_once(lambda i: self.admin().post(f"/api/fees/students/{self.amina.id}/payments/",
                                                    {"amount": 1000, "method": "mpesa", "reference": "QAB12CD34E"},
                                                    format="json").status_code)
        self.assertEqual(codes.count(201), 1, codes)
        self.assertEqual(self.payments().count(), 1)

    def test_a_payment_voided_six_times_at_once(self):
        self.admin().post(f"/api/fees/students/{self.amina.id}/payments/",
                          {"amount": 1000, "method": "cash", "reference": ""}, format="json")
        payment = Payment.objects.get()
        codes = at_once(lambda i: self.admin().post(f"/api/fees/payments/{payment.id}/void/", {"reason": f"r{i}"},
                                                    format="json").status_code)
        self.assertEqual(codes.count(200), 1, codes)
        from activity.models import ActivityLog
        self.assertEqual(ActivityLog.objects.filter(action="fees.void").count(), 1)
