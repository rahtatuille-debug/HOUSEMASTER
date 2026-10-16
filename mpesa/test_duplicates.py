"""
No payment is counted twice (PAY-001 to PAY-004, PAY-009 in the readiness re-check).

M-Pesa can tell us about one payment more than once (the PIN-prompt callback and the paybill confirmation),
and people can enter a code that is already recorded. One M-Pesa payment can legitimately cover two children,
so a code can be shared on purpose, up to what M-Pesa said was paid. The same races run truly concurrently
on PostgreSQL in test_races.py.
"""
from django.test import override_settings
from django.utils import timezone

from fees.models import Payment, PaymentClaim
from students.models import Student

from . import daraja, services
from .models import C2BPayment, StkRequest
from .tests import OWNER, Base, stk_callback
from .tests import c2b_body as dated_c2b_body


def c2b_body(trans_id, amount, bill_ref):
    """A paybill confirmation made just now (the shared helper's is dated 9 October)."""
    return {**dated_c2b_body(trans_id, amount, bill_ref),
            "TransTime": timezone.localtime(timezone.now(), daraja.NAIROBI).strftime("%Y%m%d%H%M%S")}


@override_settings(**OWNER)
class AutomaticTests(Base):
    """M-Pesa reports one payment two ways: it is recorded once, whichever arrives first."""

    def confirm(self, body):
        with self.captureOnCommitCallbacks(execute=True):
            return self.hooks.post(f"/api/payments/hooks/{self.account.callback_token}/c2b/confirm/", body, format="json")

    def payments(self):
        return Payment.objects.filter(student=self.amina, voided_at__isnull=True)

    def test_prompt_callback_then_paybill_confirmation(self):
        self.pay(15000)
        self.callback(self.account.callback_token, stk_callback("ws_CO_15000", amount=15000, receipt="SKD81QWERT"))
        self.confirm(c2b_body("SKD81QWERT", 15000, "ADM2023/7"))
        (payment,) = self.payments()
        self.assertEqual(payment.reference, "SKD81QWERT")
        self.assertEqual(C2BPayment.objects.get().fee_payment, payment)

    def test_paybill_confirmation_then_prompt_callback(self):
        self.pay(15000)
        self.confirm(c2b_body("SKD81QWERT", 15000, "ADM2023/7"))
        self.callback(self.account.callback_token, stk_callback("ws_CO_15000", amount=15000, receipt="SKD81QWERT"))
        (payment,) = self.payments()
        stk = StkRequest.objects.get()
        self.assertEqual((stk.status, stk.fee_payment), (StkRequest.Status.PAID, payment))

    def test_paid_without_its_code_then_the_paybill_confirmation(self):
        """Asking M-Pesa can say "paid" without the code; the confirmation that follows is the same payment."""
        self.pay(15000)
        stk = StkRequest.objects.get()
        services.complete(stk, 0, "Paid", {})  # what a query answer gives: no receipt
        self.assertEqual(self.payments().get().reference, "")
        self.confirm(c2b_body("SKD81QWERT", 15000, "ADM/2023/7"))
        (payment,) = self.payments()
        self.assertEqual(payment.reference, "SKD81QWERT")
        stk.refresh_from_db()
        self.assertEqual(stk.receipt, "SKD81QWERT")

    def test_paybill_confirmation_then_paid_without_its_code(self):
        self.pay(15000)
        self.confirm(c2b_body("SKD81QWERT", 15000, "ADM2023/7"))
        services.complete(StkRequest.objects.get(), 0, "Paid", {})
        (payment,) = self.payments()
        self.assertEqual(StkRequest.objects.get().fee_payment, payment)

    def test_a_different_payment_of_the_same_amount_still_counts(self):
        """Two real payments: the paybill one has its own code and a different account, so both count."""
        self.pay(15000)
        self.callback(self.account.callback_token, stk_callback("ws_CO_15000", amount=15000, receipt="SKD81QWERT"))
        self.confirm(c2b_body("SKD81ZZZZZ", 15000, "ADM2023/7"))
        self.assertEqual(self.payments().count(), 2)


@override_settings(**OWNER)
class ManualTests(Base):
    """People entering a code that is already recorded."""

    def setUp(self):
        super().setUp()
        self.sibling = Student.objects.create(school=self.school_a, first_name="Baraka", last_name="K", external_id="ADM/2023/8")
        self.parent.students.add(self.sibling)

    def record(self, student, amount, code, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return self.admin.post(f"/api/fees/students/{student.id}/payments/",
                                   {"amount": amount, "method": "mpesa", "reference": code, **extra}, format="json")

    def claim(self, student, amount, code):
        self.parent_client.post(f"/api/guardian-students/{student.id}/fees/claims/",
                                {"amount": amount, "paid_on": str(timezone.localdate()), "method": "mpesa",
                                 "reference": code}, format="json")
        return PaymentClaim.objects.filter(student=student).latest("id")

    def confirm_claim(self, claim, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return self.admin.post(f"/api/fees/claims/{claim.id}/confirm/", extra, format="json")

    def test_a_code_entered_twice_is_refused_and_says_where_it_is(self):
        self.assertEqual(self.record(self.amina, 5000, "QAB12CD34E").status_code, 201)
        response = self.record(self.amina, 5000, "qab12cd34e ")  # case and spaces don't hide it
        self.assertEqual(response.status_code, 400)
        self.assertIn("already recorded", str(response.data["reference"]))
        self.assertIn("Amina K", str(response.data["reference"]))
        self.assertIn("mpesa_code_used", response.data)
        self.assertEqual(Payment.objects.count(), 1)

    def test_one_payment_for_two_children_can_be_shared_on_purpose(self):
        self.record(self.amina, 5000, "QAB12CD34E")
        self.assertEqual(self.record(self.sibling, 5000, "QAB12CD34E", shared=True).status_code, 201)
        self.assertEqual(Payment.objects.filter(reference="QAB12CD34E").count(), 2)

    def test_sharing_cant_add_up_to_more_than_mpesa_said_was_paid(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.hooks.post(f"/api/payments/hooks/{self.account.callback_token}/c2b/confirm/",
                            c2b_body("QAB12CD34E", 8000, "ADM2023/7"), format="json")
        self.assertEqual(self.record(self.sibling, 3000, "QAB12CD34E", shared=True).status_code, 400)
        self.assertEqual(Payment.objects.filter(reference="QAB12CD34E").count(), 1)

    def test_claiming_a_code_m_pesa_already_recorded_is_refused_at_confirmation(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.hooks.post(f"/api/payments/hooks/{self.account.callback_token}/c2b/confirm/",
                            c2b_body("QAB12CD34E", 15000, "ADM2023/7"), format="json")
        claim = self.claim(self.amina, 15000, "QAB12CD34E")
        response = self.confirm_claim(claim)
        self.assertEqual(response.status_code, 400)
        self.assertIn("already recorded", str(response.data))
        claim.refresh_from_db()
        self.assertEqual(claim.status, PaymentClaim.Status.OPEN)  # the bursar can still reject it
        self.assertEqual(Payment.objects.count(), 1)

    def test_one_code_claimed_for_two_children(self):
        first, second = self.claim(self.amina, 3000, "QAB12CD34E"), self.claim(self.sibling, 3000, "QAB12CD34E")
        self.assertEqual(self.confirm_claim(first).status_code, 200)
        self.assertEqual(self.confirm_claim(second).status_code, 400)
        self.assertEqual(self.confirm_claim(second, shared=True).status_code, 200)

    def test_a_claim_confirmed_twice_is_recorded_once(self):
        claim = self.claim(self.amina, 3000, "QAB12CD34E")
        self.assertEqual(self.confirm_claim(claim).status_code, 200)
        self.assertEqual(self.confirm_claim(claim).status_code, 404)  # no longer open
        self.assertEqual(Payment.objects.count(), 1)

    def test_m_pesa_confirming_a_payment_already_entered_by_hand_links_to_it(self):
        self.record(self.amina, 2000, "QAB12CD34E")
        with self.captureOnCommitCallbacks(execute=True):
            self.hooks.post(f"/api/payments/hooks/{self.account.callback_token}/c2b/confirm/",
                            c2b_body("QAB12CD34E", 2000, "CANTEEN"), format="json")
        c2b = C2BPayment.objects.get()
        self.assertEqual((c2b.status, c2b.fee_payment), (C2BPayment.Status.RECORDED, Payment.objects.get()))

    def test_entering_a_code_waiting_on_the_m_pesa_page_is_refused(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.hooks.post(f"/api/payments/hooks/{self.account.callback_token}/c2b/confirm/",
                            c2b_body("QAB12CD34E", 2000, "CANTEEN"), format="json")
        response = self.record(self.amina, 2000, "QAB12CD34E")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Assign it there", str(response.data["reference"]))
        c2b = C2BPayment.objects.get()
        url = f"/api/fees/mpesa/payments/{c2b.id}/assign/"
        self.assertEqual(self.admin.post(url, {"student": self.amina.id}, format="json").status_code, 200)
        self.assertEqual(Payment.objects.count(), 1)

    def test_assigning_twice_records_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.hooks.post(f"/api/payments/hooks/{self.account.callback_token}/c2b/confirm/",
                            c2b_body("QAB12CD34E", 2000, "SOMEONE"), format="json")
        c2b = C2BPayment.objects.get()
        url = f"/api/fees/mpesa/payments/{c2b.id}/assign/"
        self.assertEqual(self.admin.post(url, {"student": self.amina.id}, format="json").status_code, 200)
        self.assertEqual(self.admin.post(url, {"student": self.amina.id}, format="json").status_code, 404)
        self.assertEqual(Payment.objects.count(), 1)

    def test_voiding_twice_is_refused_the_second_time(self):
        self.record(self.amina, 2000, "QAB12CD34E")
        payment = Payment.objects.get()
        url = f"/api/fees/payments/{payment.id}/void/"
        self.assertEqual(self.admin.post(url, {"reason": "typo"}, format="json").status_code, 200)
        self.assertEqual(self.admin.post(url, {"reason": "again"}, format="json").status_code, 404)
        payment.refresh_from_db()
        self.assertEqual(payment.void_reason, "typo")

    def test_a_voided_code_can_be_entered_again(self):
        self.record(self.amina, 2000, "QAB12CD34E")
        self.admin.post(f"/api/fees/payments/{Payment.objects.get().id}/void/", {"reason": "wrong child"}, format="json")
        self.assertEqual(self.record(self.sibling, 2000, "QAB12CD34E").status_code, 201)

    def test_an_absurd_claim_is_refused(self):
        response = self.parent_client.post(f"/api/guardian-students/{self.amina.id}/fees/claims/",
                                           {"amount": "9999999999", "paid_on": str(timezone.localdate()),
                                            "method": "mpesa", "reference": "BIG"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("more than one payment", str(response.data["amount"]))
