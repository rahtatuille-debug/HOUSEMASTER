"""
Monthly subscriptions (owner's request, 2026-10-08): tiers by school size,
payments recorded by hand, invoices and reminders, a grace period, then the
school is locked (admins can still see and pay). Existing and demo schools
are exempt. A tier with no price is never invoiced.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from guardians.models import Guardian
from students.localtime import school_localdate
from students.models import School, Student

from . import services
from .models import Invoice, Plan, Subscription


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False,
                   BILLING_PAYMENT_INSTRUCTIONS="M-Pesa Paybill 123456", BILLING_OWNER_EMAIL="owner@housemaster.test")
class Base(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.today = school_localdate(self.school_a)
        self.admin = self.authed_client(self.admin_a)
        Plan.objects.all().delete()
        self.small = Plan.objects.create(name="Small", max_students=3, monthly_price=Decimal("5000"))
        self.large = Plan.objects.create(name="Large", max_students=None, monthly_price=Decimal("25000"))
        for n in range(2):
            Student.objects.create(school=self.school_a, first_name=f"S{n}", last_name="K")

    def issue(self, today=None):
        with self.captureOnCommitCallbacks(execute=True):
            return services.issue_due(self.school_a, today or self.today)


class TierAndInvoiceTests(Base):
    def test_new_schools_are_billed_and_existing_or_demo_schools_are_not(self):
        new = School.objects.create(name="Newly registered")
        self.assertFalse(new.subscription.exempt)
        services.make_exempt(new)
        self.assertIsNone(services.issue_due(new))

    def test_the_first_invoice_at_the_tier_price(self):
        invoice = self.issue()
        self.assertEqual((invoice.plan_name, invoice.amount, invoice.students), ("Small", Decimal("5000"), 2))
        self.assertEqual((invoice.period_start, invoice.due_on), (self.today, self.today))
        self.assertEqual(invoice.period_end, services.add_month(self.today) - timedelta(days=1))
        (email,) = mail.outbox
        self.assertIn(invoice.number, email.subject)
        self.assertIn("M-Pesa Paybill 123456", email.body)
        self.assertIsNone(self.issue())  # not again until a week before next month

    def test_the_next_month_a_week_ahead_and_a_bigger_tier_when_the_school_grows(self):
        first = self.issue()
        for n in range(5):
            Student.objects.create(school=self.school_a, first_name=f"T{n}", last_name="K")
        self.assertIsNone(self.issue(first.period_end - timedelta(days=8)))
        second = self.issue(first.period_end - timedelta(days=6))
        self.assertEqual((second.period_start, second.plan_name, second.amount),
                         (first.period_end + timedelta(days=1), "Large", Decimal("25000")))

    def test_no_price_no_invoice(self):
        Plan.objects.update(monthly_price=None)
        self.assertIsNone(self.issue())
        self.assertEqual(services.status(self.school_a)["status"], "active")

    def test_months_end(self):
        self.assertEqual(services.add_month(date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(services.add_month(date(2026, 12, 15)), date(2027, 1, 15))


class LockingTests(Base):
    def setUp(self):
        super().setUp()
        self.invoice = self.issue()
        parent = User.objects.create_user(username="pa@alpha.test", email="pa@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat")
        self.parent = self.authed_client(parent)

    def lock(self):
        """The invoice was due 15 days ago: past the 14-day grace period."""
        Invoice.objects.filter(pk=self.invoice.pk).update(due_on=self.today - timedelta(days=15))
        self.invoice.refresh_from_db()
        services.refresh(self.school_a)

    def test_status_through_the_grace_period(self):
        due = self.invoice.due_on
        self.assertEqual(services.status(self.school_a, due)["status"], "due")
        self.assertEqual(services.status(self.school_a, due + timedelta(days=1))["status"], "overdue")
        self.assertEqual(services.status(self.school_a, due + timedelta(days=14))["status"], "locked")
        self.assertEqual(Subscription.objects.get(school=self.school_a).locked_from, due + timedelta(days=14))

    def test_a_locked_school_only_lets_its_admins_see_billing(self):
        self.lock()
        blocked = self.client_a.get("/api/students/")
        self.assertEqual((blocked.status_code, blocked.data["code"]), (403, "school_locked"))
        self.assertEqual(self.parent.get("/api/guardian-students/").data["code"], "school_locked")
        self.assertEqual(self.admin.get("/api/students/").status_code, 403)
        self.assertEqual(self.admin.get("/api/billing/").status_code, 200)
        self.assertEqual(self.admin.get("/api/me/").data["billing"]["status"], "locked")
        self.assertEqual(self.client_a.get("/api/me/").status_code, 403)
        # Another school carries on.
        self.assertEqual(self.client_b.get("/api/students/").status_code, 200)

    def test_paying_unlocks_and_thanks_the_school(self):
        self.lock()
        with self.captureOnCommitCallbacks(execute=True):
            services.record_payment(self.invoice, self.today, Invoice.Method.MPESA, "QWE123")
        self.assertEqual(self.client_a.get("/api/students/").status_code, 200)
        self.assertEqual(services.status(self.school_a)["status"], "active")
        self.assertEqual(services.paid_until(self.school_a), self.invoice.period_end)
        self.assertIn("payment received", mail.outbox[-1].subject.lower())

    def test_making_a_school_exempt_unlocks_it(self):
        self.lock()
        services.make_exempt(self.school_a, "Partner")
        self.assertEqual(self.client_a.get("/api/students/").status_code, 200)

    def test_reminders_once_each(self):
        due = self.invoice.due_on
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.send_reminders(due + timedelta(days=1))
            services.send_reminders(due + timedelta(days=1))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("overdue", mail.outbox[0].subject)
        with self.captureOnCommitCallbacks(execute=True):
            services.send_reminders(due + timedelta(days=14))
        self.assertIn("locked", mail.outbox[-1].subject)


class SchoolBillingPageTests(Base):
    def setUp(self):
        super().setUp()
        self.invoice = self.issue()

    def test_the_admin_sees_status_tier_and_invoices(self):
        data = self.admin.get("/api/billing/").data
        self.assertEqual((data["status"], data["plan"]["name"], data["students"]), ("due", "Small", 2))
        self.assertEqual([i["number"] for i in data["invoices"]], [self.invoice.number])
        self.assertEqual(data["payment_instructions"], "M-Pesa Paybill 123456")
        self.assertEqual(self.client_a.get("/api/billing/").status_code, 403)  # teachers don't

    def test_telling_the_owner_it_is_paid(self):
        mail.outbox.clear()
        url = f"/api/billing/invoices/{self.invoice.id}/paid/"
        self.assertEqual(self.admin.post(url, {"method": "mpesa"}, format="json").status_code, 400)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.admin.post(url, {"method": "mpesa", "reference": "QWE123"}, format="json")
        self.assertIsNotNone(response.data["school_reported_at"])
        self.assertEqual(mail.outbox[0].to, ["owner@housemaster.test"])
        self.assertEqual(Invoice.objects.get().status, "open")  # only the owner marks it paid

    def test_invoice_pdf(self):
        response = self.admin.get(f"/api/billing/invoices/{self.invoice.id}/pdf/")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_another_school_never_sees_this_ones_invoices(self):
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get("/api/billing/").data["invoices"], [])
        self.assertEqual(self.client_b.get(f"/api/billing/invoices/{self.invoice.id}/pdf/").status_code, 404)
        self.assertEqual(self.client_b.post(f"/api/billing/invoices/{self.invoice.id}/paid/", {"reference": "x"},
                                            format="json").status_code, 404)
        self.assertEqual(APIClient().get("/api/billing/").status_code, 401)


class CommandTests(Base):
    def test_the_daily_run(self):
        from io import StringIO

        out = StringIO()
        call_command("billing_run", stdout=out)
        self.assertIn("Issued", out.getvalue())
        self.assertTrue(Invoice.objects.filter(school=self.school_a).exists())


class MigrationTests(Base):
    def test_schools_already_here_become_exempt_and_the_tiers_have_no_price(self):
        import importlib

        from django.apps import apps

        migration = importlib.import_module("billing.migrations.0002_tiers_and_existing_schools")
        Subscription.objects.all().delete()
        Plan.objects.all().delete()
        migration.forwards(apps, None)
        self.assertTrue(all(s.exempt for s in Subscription.objects.all()))
        self.assertEqual(Subscription.objects.count(), School.objects.count())
        self.assertEqual([(p.name, p.monthly_price) for p in Plan.objects.all()],
                         [("Small", None), ("Medium", None), ("Large", None)])
        migration.backwards(apps, None)
        self.assertFalse(Subscription.objects.exists() or Plan.objects.exists())
