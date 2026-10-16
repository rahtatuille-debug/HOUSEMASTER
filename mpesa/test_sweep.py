"""
OPS-002: a prompt whose callback never came (a lost callback, a server asleep, a parent who closed the page) is
settled by asking M-Pesa, for up to a day, including prompts we had already given up on.
"""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from fees.models import Payment

from . import daraja, services
from .models import StkRequest
from .tests import OWNER, Base


@override_settings(**OWNER)
class SweepTests(Base):
    def prompt(self, minutes_ago, status=StkRequest.Status.PENDING, description=""):
        stk = StkRequest.objects.create(purpose="fees", school=self.school_a, student=self.amina, amount=15000,
                                        phone_masked="2547•••678", account_reference="ADM20237",
                                        checkout_request_id=f"ws_CO_{StkRequest.objects.count()}", status=status,
                                        result_description=description)
        StkRequest.objects.filter(pk=stk.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
        return stk

    def sweep(self, answer):
        with mock.patch.object(daraja, "stk_query", return_value=answer) as query, \
                self.captureOnCommitCallbacks(execute=True):
            counts = services.sweep()
        return counts, query

    def test_a_lost_callback_is_settled_as_paid(self):
        stk = self.prompt(5)
        counts, _ = self.sweep((0, "The service request is processed successfully."))
        stk.refresh_from_db()
        self.assertEqual((stk.status, counts["paid"]), (StkRequest.Status.PAID, 1))
        self.assertEqual(Payment.objects.filter(student=self.amina).count(), 1)

    def test_a_prompt_we_gave_up_on_still_counts_when_m_pesa_says_paid(self):
        stk = self.prompt(30, StkRequest.Status.FAILED, services.TIMED_OUT)
        self.sweep((0, "processed successfully"))
        stk.refresh_from_db()
        self.assertEqual(stk.status, StkRequest.Status.PAID)
        self.assertEqual(Payment.objects.filter(student=self.amina).count(), 1)

    def test_m_pesas_own_no_replaces_ours_and_stops_the_asking(self):
        stk = self.prompt(30, StkRequest.Status.FAILED, services.TIMED_OUT)
        self.sweep((1032, "Request cancelled by user"))
        stk.refresh_from_db()
        self.assertEqual((stk.status, stk.result_description), (StkRequest.Status.FAILED, "Request cancelled by user"))
        StkRequest.objects.filter(pk=stk.pk).update(checked_at=None)
        _, query = self.sweep((0, "paid"))
        query.assert_not_called()

    def test_still_processing_waits_then_times_out_then_keeps_being_asked(self):
        stk = self.prompt(5)
        self.sweep((None, "still processing"))
        stk.refresh_from_db()
        self.assertEqual((stk.status, stk.result_description), (StkRequest.Status.FAILED, services.TIMED_OUT))
        _, query = self.sweep((None, ""))
        query.assert_not_called()  # asked a moment ago
        StkRequest.objects.filter(pk=stk.pk).update(checked_at=timezone.now() - timedelta(minutes=3))
        _, query = self.sweep((None, ""))
        query.assert_called_once()

    def test_after_a_day_it_stops(self):
        old = self.prompt(60 * 25)
        _, query = self.sweep((0, "paid"))
        query.assert_not_called()
        old.refresh_from_db()
        self.assertEqual(old.status, StkRequest.Status.FAILED)

    def test_the_command(self):
        self.prompt(5)
        out = StringIO()
        with mock.patch.object(daraja, "stk_query", return_value=(0, "paid")):
            call_command("mpesa_sweep", stdout=out)
        self.assertIn("1 paid", out.getvalue())

    def test_opening_the_m_pesa_page_sweeps_that_school(self):
        cache.clear()
        stk = self.prompt(5)
        with mock.patch.object(daraja, "stk_query", return_value=(0, "paid")):
            self.admin.get("/api/fees/mpesa/payments/")
        stk.refresh_from_db()
        self.assertEqual(stk.status, StkRequest.Status.PAID)
