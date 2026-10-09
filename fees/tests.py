"""
School fees (owner's request, 2026-10-09): fee items per term, billing a
term, extras and bursaries, payments recorded by hand with numbered
receipts, parents seeing balances and saying they've paid.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings

from accounts.models import Profile, StaffRole
from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Term
from guardians.models import Guardian
from students.localtime import school_localdate
from students.models import SchoolClass, Student, YearGroup

from .models import Charge, Payment, PaymentClaim


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class Base(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.today = school_localdate(self.school_a)
        self.term = Term.objects.create(school=self.school_a, name="Term 3 2026")
        self.form1 = YearGroup.objects.create(school=self.school_a, name="Form 1")
        self.form2 = YearGroup.objects.create(school=self.school_a, name="Form 2")
        c1 = SchoolClass.objects.create(year_group=self.form1, name="1 East")
        c2 = SchoolClass.objects.create(year_group=self.form2, name="2 East")
        self.amina = Student.objects.create(school=self.school_a, first_name="Amina", last_name="K", school_class=c1,
                                            mode_of_learning="boarding")
        self.ben = Student.objects.create(school=self.school_a, first_name="Ben", last_name="O", school_class=c2)
        parent = User.objects.create_user(username="pat", email="pat@parents.test", password="pass1234")
        self.parent = Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat Parent")
        self.parent.students.add(self.amina)
        self.parent_client = self.authed_client(parent)
        self.admin = self.authed_client(self.admin_a)

    def item(self, name, amount, **extra):
        response = self.admin.post("/api/fee-items/", {"term": self.term.id, "name": name, "amount": amount, **extra},
                                   format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def bill(self):
        return self.admin.post("/api/fees/bill-term/", {"term": self.term.id}, format="json").data["created"]

    def pay(self, student, amount, client=None, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.admin).post(f"/api/fees/students/{student.id}/payments/",
                                               {"amount": amount, "method": "mpesa", "reference": "QWE123", **extra},
                                               format="json")


class BillingTests(Base):
    def test_bill_the_term_by_year_group_and_boarding(self):
        self.item("Tuition", "15000")
        self.item("Boarding", "12000", applies_to="boarding")
        self.item("Form 2 trip", "2500", year_group=self.form2.id)
        self.assertEqual(self.bill(), 4)  # Amina: tuition + boarding; Ben: tuition + trip
        self.assertEqual(self.bill(), 0)  # never twice
        self.assertEqual(self.admin.get(f"/api/fees/students/{self.amina.id}/").data["balance"], Decimal("27000"))
        self.assertEqual(self.admin.get(f"/api/fees/students/{self.ben.id}/").data["balance"], Decimal("17500"))
        # A student who joins later is billed when the term is billed again.
        cara = Student.objects.create(school=self.school_a, first_name="Cara", last_name="M",
                                      school_class=self.ben.school_class)
        self.assertEqual(self.bill(), 2)
        self.assertEqual(Charge.objects.filter(student=cara).count(), 2)

    def test_an_item_already_billed_cant_be_deleted(self):
        item = self.item("Tuition", "15000")
        self.bill()
        self.assertEqual(self.admin.delete(f"/api/fee-items/{item['id']}/").status_code, 400)

    def test_extras_and_bursaries(self):
        self.item("Tuition", "15000")
        self.bill()
        url = f"/api/fees/students/{self.ben.id}/charges/"
        self.admin.post(url, {"kind": "discount", "description": "Bursary", "amount": "5000"}, format="json")
        data = self.admin.post(url, {"kind": "extra", "description": "Lost textbook", "amount": "800"}, format="json").data
        self.assertEqual(data["balance"], Decimal("10800"))
        self.assertEqual([c["amount"] for c in data["charges"]], [Decimal("15000.00"), Decimal("-5000.00"), Decimal("800.00")])
        self.assertEqual(self.admin.post(url, {"kind": "fee", "description": "x", "amount": "1"}, format="json").status_code, 400)


class PaymentTests(Base):
    def setUp(self):
        super().setUp()
        self.item("Tuition", "15000")
        self.bill()

    def test_a_payment_gets_a_receipt_number_and_the_parents_an_email(self):
        data = self.pay(self.amina, "10000", payer_name="Pat Parent").data
        self.assertEqual(data["balance"], Decimal("5000"))
        (payment,) = data["payments"]
        self.assertEqual(payment["receipt_number"], f"R{self.today:%Y}-00001")
        (email,) = mail.outbox
        self.assertEqual(email.to, ["pat@parents.test"])
        self.assertIn("KES 10,000.00", email.body)
        self.assertIn("KES 5,000.00", email.body)  # the balance left
        self.assertEqual(self.pay(self.ben, "15000").data["payments"][0]["receipt_number"], f"R{self.today:%Y}-00002")

    def test_void_keeps_the_receipt_and_the_balance_goes_back(self):
        payment_id = self.pay(self.amina, "10000").data["payments"][0]["id"]
        self.assertEqual(self.admin.post(f"/api/fees/payments/{payment_id}/void/", {}, format="json").status_code, 400)
        data = self.admin.post(f"/api/fees/payments/{payment_id}/void/", {"reason": "Entered twice"}, format="json").data
        self.assertEqual(data["balance"], Decimal("15000"))
        self.assertTrue(data["payments"][0]["voided"])
        self.assertEqual(self.pay(self.amina, "1000").data["payments"][-1]["receipt_number"], f"R{self.today:%Y}-00002")

    def test_amounts_and_dates_that_dont_make_sense(self):
        self.assertEqual(self.pay(self.amina, "-5").status_code, 400)
        self.assertEqual(self.pay(self.amina, "lots").status_code, 400)
        self.assertEqual(self.pay(self.amina, "5", paid_on=(self.today + timedelta(days=2)).isoformat()).status_code, 400)
        self.assertEqual(self.pay(self.amina, "5", method="barter").status_code, 400)

    def test_receipt_pdf(self):
        payment_id = self.pay(self.amina, "10000").data["payments"][0]["id"]
        response = self.admin.get(f"/api/fees/payments/{payment_id}/receipt/")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_balances_and_reminders(self):
        self.pay(self.ben, "15000")
        data = self.admin.get("/api/fees/students/").data
        self.assertEqual([(r["name"], r["balance"]) for r in data["students"]], [("Amina K", Decimal("15000")), ("Ben O", Decimal("0"))])
        self.assertEqual((data["totals"]["balance"], data["totals"]["owing"]), (Decimal("15000"), 1))
        self.assertEqual([r["name"] for r in self.admin.get("/api/fees/students/?owing=1").data["students"]], ["Amina K"])
        self.admin.patch("/api/fees/settings/", {"payment_instructions": "M-Pesa Paybill 222111"}, format="json")
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.admin.post("/api/fees/remind/", {}, format="json").data["emailed"], 1)
        self.assertIn("M-Pesa Paybill 222111", mail.outbox[0].body)


class ParentTests(Base):
    def setUp(self):
        super().setUp()
        self.item("Tuition", "15000")
        self.bill()

    def test_a_parent_sees_the_balance_and_receipts(self):
        payment_id = self.pay(self.amina, "10000").data["payments"][0]["id"]
        void_id = self.pay(self.amina, "50").data["payments"][-1]["id"]
        self.admin.post(f"/api/fees/payments/{void_id}/void/", {"reason": "Wrong child"}, format="json")
        data = self.parent_client.get(f"/api/guardian-students/{self.amina.id}/fees/").data
        self.assertEqual(data["balance"], Decimal("5000"))
        self.assertEqual([p["id"] for p in data["payments"]], [payment_id])  # not the voided one
        self.assertNotIn("recorded_by_name", data["payments"][0])
        receipt = self.parent_client.get(f"/api/guardian-students/{self.amina.id}/fees/receipts/{payment_id}/")
        self.assertTrue(receipt.content.startswith(b"%PDF"))
        self.assertEqual(self.parent_client.get(f"/api/guardian-students/{self.amina.id}/fees/receipts/{void_id}/").status_code, 404)

    def test_a_parent_says_they_paid_and_the_bursar_confirms(self):
        bursar = User.objects.create_user(username="bursar", email="bursar@alpha.test", password="pass1234")
        StaffRole.objects.create(profile=Profile.objects.create(user=bursar, school=self.school_a, role=Profile.Role.TEACHER),
                                 role=StaffRole.Role.BURSAR)
        bursar_client = self.authed_client(bursar)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.parent_client.post(f"/api/guardian-students/{self.amina.id}/fees/claims/",
                                               {"amount": "15000", "method": "mpesa", "reference": "RKT55X"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["claims"][0]["status"], "open")
        self.assertEqual(mail.outbox[-1].to, ["bursar@alpha.test"])
        self.assertEqual(response.data["balance"], Decimal("15000"))  # not paid until confirmed
        (claim,) = bursar_client.get("/api/fees/claims/").data
        with self.captureOnCommitCallbacks(execute=True):
            confirmed = bursar_client.post(f"/api/fees/claims/{claim['id']}/confirm/", {"amount": "14000"}, format="json").data
        self.assertEqual((confirmed["status"], confirmed["receipt_number"]), ("confirmed", f"R{self.today:%Y}-00001"))
        self.assertEqual(self.parent_client.get(f"/api/guardian-students/{self.amina.id}/fees/").data["balance"], Decimal("1000"))
        self.assertEqual(bursar_client.post(f"/api/fees/claims/{claim['id']}/confirm/").status_code, 404)

    def test_reject_a_claim(self):
        self.parent_client.post(f"/api/guardian-students/{self.amina.id}/fees/claims/",
                                {"amount": "15000", "method": "mpesa", "reference": "NOPE"}, format="json")
        claim = PaymentClaim.objects.get()
        self.assertEqual(self.admin.post(f"/api/fees/claims/{claim.id}/reject/", {}, format="json").status_code, 400)
        self.admin.post(f"/api/fees/claims/{claim.id}/reject/", {"reason": "No payment with that code"}, format="json")
        data = self.parent_client.get(f"/api/guardian-students/{self.amina.id}/fees/").data
        self.assertEqual((data["claims"][0]["status_label"], data["claims"][0]["reject_reason"]),
                         ("Not found", "No payment with that code"))
        self.assertFalse(Payment.objects.exists())


class AccessTests(Base):
    def test_only_the_bursar_and_admins(self):
        for url in ("/api/fees/students/", "/api/fee-items/", "/api/fees/claims/", "/api/fees/settings/"):
            self.assertEqual(self.client_a.get(url).status_code, 403, url)
        self.assertEqual(self.parent_client.get("/api/fees/students/").status_code, 403)
        self.assertFalse(self.client_a.get("/api/me/").data["permissions"]["manage_fees"])
        self.assertTrue(self.admin.get("/api/me/").data["permissions"]["manage_fees"])

    def test_another_school_never_sees_or_touches_these(self):
        self.item("Tuition", "15000")
        self.bill()
        payment_id = self.pay(self.amina, "100").data["payments"][0]["id"]
        self.make_admin(self.user_b)
        other = self.client_b
        self.assertEqual(other.get("/api/fees/students/").data["students"], [])
        self.assertEqual(other.get("/api/fee-items/").data, [])
        self.assertEqual(other.get(f"/api/fees/students/{self.amina.id}/").status_code, 404)
        self.assertEqual(self.pay(self.amina, "100", client=other).status_code, 404)
        self.assertEqual(other.post(f"/api/fees/payments/{payment_id}/void/", {"reason": "x"}, format="json").status_code, 404)
        self.assertEqual(other.get(f"/api/fees/payments/{payment_id}/receipt/").status_code, 404)
        self.assertEqual(other.post("/api/fees/bill-term/", {"term": self.term.id}, format="json").status_code, 400)
        response = other.post("/api/fee-items/", {"term": self.term.id, "name": "x", "amount": "1"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_students_and_other_parents_dont_see_fees(self):
        from studentaccounts.models import StudentAccount

        login = User.objects.create_user(username="amina.k", password="pass1234")
        StudentAccount.objects.create(user=login, student=self.amina, must_change_password=False)
        self.assertEqual(self.authed_client(login).get(f"/api/guardian-students/{self.amina.id}/fees/").status_code, 403)
        stranger = User.objects.create_user(username="sam", email="sam@parents.test", password="pass1234")
        Guardian.objects.create(user=stranger, school=self.school_a, display_name="Sam").students.add(self.ben)
        self.assertEqual(self.authed_client(stranger).get(f"/api/guardian-students/{self.amina.id}/fees/").status_code, 404)
