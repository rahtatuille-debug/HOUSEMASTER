"""
Approve all (owner's request, 2026-10-08): finalize every report waiting for
approval in one class or a whole year group, for a term. Reports with a blank
comment or summary stay waiting. Leaders approve any class; a Head of Year
their own year group; nobody else.
"""
from django.contrib.auth.models import User
from django.core import mail

from accounts.models import StaffRole
from accounts.test_roles import RoleFixture
from activity.models import ActivityLog
from guardians.models import Guardian
from students.models import Student

from .models import StudentReport

WAITING = "/api/reports/waiting/"
APPROVE = "/api/reports/approve-all/"


class ApproveAllTests(RoleFixture):
    def setUp(self):
        super().setUp()
        self.dee = Student.objects.create(school=self.school_a, first_name="Dee", last_name="K", school_class=self.c2w)
        self.reports = {s.first_name: StudentReport.objects.create(
            student=s, term=self.term, status="submitted", report_comment="Good work", progress_summary="On track")
            for s in (self.amina, self.ben, self.cate)}
        # Waiting, but not finished: stays waiting.
        self.reports["Dee"] = StudentReport.objects.create(student=self.dee, term=self.term, status="submitted",
                                                           report_comment="", progress_summary="On track")
        parent = User.objects.create_user(username="p@alpha.test", email="p@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.ben)
        _, self.lead = self.staff("lead@alpha.test", "teacher", StaffRole.Role.LEADERSHIP)
        _, self.hoy = self.staff("hoy@alpha.test", "teacher", ("head_of_year", {"year_group": self.form2}))

    def status(self, name):
        self.reports[name].refresh_from_db()
        return self.reports[name].status

    def approve(self, client, **target):
        with self.captureOnCommitCallbacks(execute=True):
            return client.post(APPROVE, {"term": self.term.id, **target}, format="json")

    def test_waiting_is_grouped_by_year_group_and_class(self):
        groups = self.lead.get(WAITING).data
        form2 = next(g for g in groups if g["year_group"] == self.form2.id)
        self.assertEqual((form2["term_name"], form2["count"], form2["blank"]), ("T1", 3, 1))
        self.assertEqual([(c["name"], c["count"], c["blank"]) for c in form2["classes"]],
                         [("2 East", 1, 0), ("2 West", 2, 1)])
        self.assertEqual(sorted(g["year_group_name"] for g in groups), ["Form 2", "Form 3"])

    def test_leader_approves_a_whole_year_group(self):
        response = self.approve(self.lead, year_group=self.form2.id)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 2, "blank": 1})
        self.assertEqual([self.status(n) for n in ("Amina", "Ben", "Dee", "Cate")],
                         ["finalized", "finalized", "submitted", "submitted"])
        self.assertTrue(self.reports["Ben"].school_class_id)  # the class of the time is recorded
        self.assertEqual([m.to for m in mail.outbox], [["p@alpha.test"]])
        self.assertTrue(ActivityLog.objects.filter(action="report.class_finalized", summary__icontains="Form 2").exists())

    def test_or_one_class(self):
        self.assertEqual(self.approve(self.lead, school_class=self.c3e.id).data, {"count": 1, "blank": 0})
        self.assertEqual([self.status(n) for n in ("Cate", "Amina")], ["finalized", "submitted"])

    def test_head_of_year_approves_their_year_only(self):
        self.assertEqual([g["year_group_name"] for g in self.hoy.get(WAITING).data], ["Form 2"])
        self.assertEqual(self.approve(self.hoy, year_group=self.form3.id).status_code, 403)
        self.assertEqual(self.approve(self.hoy, school_class=self.c3e.id).status_code, 403)
        self.assertEqual(self.status("Cate"), "submitted")
        self.assertEqual(self.approve(self.hoy, school_class=self.c2e.id).data, {"count": 1, "blank": 0})

    def test_teachers_cannot_and_see_nothing_waiting(self):
        self.assertEqual(self.client_a.get(WAITING).data, [])
        self.assertEqual(self.approve(self.client_a, school_class=self.c2e.id).status_code, 403)
        self.assertEqual(self.status("Amina"), "submitted")

    def test_bad_requests(self):
        self.assertEqual(self.approve(self.lead).status_code, 400)
        self.make_admin(self.user_b)
        self.assertEqual(self.approve(self.client_b, year_group=self.form2.id).status_code, 404)
        self.assertEqual(self.client_b.get(WAITING).data, [])
        self.assertEqual(self.status("Amina"), "submitted")

    def test_admins_approve_too(self):
        self.assertEqual(self.approve(self.admin, year_group=self.form3.id).data, {"count": 1, "blank": 0})
