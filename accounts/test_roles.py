"""
Staff roles (owner's request, 2026-10-08): Leadership, Head of Year, Head of
Department, Class Teacher, Nurse, Admissions Officer, Secretary and a
read-only Governor. Each role sees and does what accounts.scoping allows,
and nothing more; another school sees nothing.
"""
from datetime import date

from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings

from activity.models import ActivityLog
from approvals.models import ChangeRequest
from discipline.models import DisciplineIncident
from gradebook.models import Grade, Subject, Term
from guardians.models import Guardian
from reporting.models import StudentReport
from students.localtime import school_localdate
from students.models import SchoolClass, Student, YearGroup

from .models import Profile, StaffRole
from .tests import SchoolScopedAPITestCase

ROLES = "/api/staff-roles/"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class RoleFixture(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        self.form2 = YearGroup.objects.create(school=self.school_a, name="Form 2")
        self.form3 = YearGroup.objects.create(school=self.school_a, name="Form 3")
        self.c2e = SchoolClass.objects.create(year_group=self.form2, name="2 East")  # user_a teaches maths here
        self.c2w = SchoolClass.objects.create(year_group=self.form2, name="2 West")
        self.c3e = SchoolClass.objects.create(year_group=self.form3, name="3 East")
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.english = Subject.objects.create(school=self.school_a, name="English")
        self.term = Term.objects.create(school=self.school_a, name="T1", start_date=date(2026, 1, 5),
                                        end_date=date(2026, 12, 18))
        self.assign(self.user_a, self.c2e, self.maths)
        self.maths_3e = self.staff("maths3e@alpha.test")
        self.assign(self.maths_3e[0], self.c3e, self.maths)
        self.amina = self.pupil("Amina", self.c2e)
        self.ben = self.pupil("Ben", self.c2w)
        self.cate = self.pupil("Cate", self.c3e)
        for s in (self.amina, self.ben, self.cate):
            DisciplineIncident.objects.create(school=self.school_a, student=s, date=school_localdate(self.school_a),
                                              category="late", description=f"Late {s.first_name}")
            Grade.objects.create(student=s, subject=self.maths, term=self.term, score=60)

    def pupil(self, name, klass):
        return Student.objects.create(school=self.school_a, first_name=name, last_name="K", school_class=klass,
                                      medical_notes=f"{name} is allergic to nuts")

    def staff(self, email, role="teacher", *roles):
        user = User.objects.create_user(username=email, email=email, password="pass1234")
        profile = Profile.objects.create(user=user, school=self.school_a, role=role, display_name=email.split("@")[0])
        for r in roles:
            name, scope = r if isinstance(r, tuple) else (r, {})
            StaffRole.objects.create(profile=profile, role=name, **scope)
        return user, self.authed_client(user)

    @staticmethod
    def names(response):
        rows = response.data["results"] if isinstance(response.data, dict) else response.data
        return sorted(r.get("first_name") or r.get("student_name", "") for r in rows)


class ManagingRolesTests(RoleFixture):
    def test_an_admin_gives_and_removes_roles_and_it_is_logged(self):
        user, _ = self.staff("hoy@alpha.test")
        response = self.admin.post(ROLES, {"profile": user.profile.id, "role": "head_of_year",
                                           "year_group": self.form2.id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["scope_name"], "Form 2")
        self.assertTrue(ActivityLog.objects.filter(action="staff.role_added", summary__icontains="Head of Year").exists())
        staff = {r["id"]: r for r in self.admin.get("/api/staff/").data}
        self.assertEqual(staff[user.profile.id]["roles"][0]["role_label"], "Head of Year")
        self.assertEqual(self.admin.delete(f"{ROLES}{response.data['id']}/").status_code, 204)
        self.assertFalse(StaffRole.objects.exists())
        self.assertTrue(ActivityLog.objects.filter(action="staff.role_removed").exists())

    def test_a_scoped_role_needs_its_scope_and_duplicates_are_refused(self):
        user, _ = self.staff("x@alpha.test")
        bad = self.admin.post(ROLES, {"profile": user.profile.id, "role": "class_teacher"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("school_class", bad.data)
        ok = self.admin.post(ROLES, {"profile": user.profile.id, "role": "nurse", "year_group": self.form2.id},
                             format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertIsNone(StaffRole.objects.get().year_group)  # an unscoped role keeps no scope
        again = self.admin.post(ROLES, {"profile": user.profile.id, "role": "nurse"}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_only_admins_manage_roles_and_only_at_their_school(self):
        user, client = self.staff("lead@alpha.test", "teacher", StaffRole.Role.LEADERSHIP)
        self.assertEqual(client.post(ROLES, {"profile": user.profile.id, "role": "nurse"}, format="json").status_code, 403)
        self.assertEqual(self.client_a.get(ROLES).status_code, 403)
        other_year = YearGroup.objects.create(school=self.school_b, name="Y")
        response = self.admin.post(ROLES, {"profile": user.profile.id, "role": "head_of_year",
                                           "year_group": other_year.id}, format="json")
        self.assertEqual(response.status_code, 400)
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get(ROLES).data, [])
        self.assertEqual(self.client_b.post(ROLES, {"profile": user.profile.id, "role": "nurse"},
                                            format="json").status_code, 400)

    def test_governors_hold_no_roles_and_teachers_with_classes_cant_become_governors(self):
        gov, _ = self.staff("gov@alpha.test", "governor")
        self.assertEqual(self.admin.post(ROLES, {"profile": gov.profile.id, "role": "nurse"}, format="json").status_code, 400)
        response = self.admin.patch(f"/api/staff/{self.user_a.profile.id}/", {"role": "governor"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_me_lists_roles_and_what_to_offer(self):
        _, client = self.staff("hoy@alpha.test", "teacher", ("head_of_year", {"year_group": self.form2}))
        me = client.get("/api/me/").data
        self.assertEqual(me["roles"][0]["scope_name"], "Form 2")
        self.assertTrue(me["permissions"]["approve_reports"])
        self.assertFalse(me["permissions"]["is_leader"])
        self.assertEqual(me["permissions"]["classes"]["pastoral"], sorted([self.c2e.id, self.c2w.id]))
        self.assertFalse(self.client_a.get("/api/me/").data["permissions"]["approve_reports"])
        self.assertIsNone(self.admin.get("/api/me/").data["permissions"]["classes"]["academic"])


class LeadershipTests(RoleFixture):
    def setUp(self):
        super().setUp()
        self.lead_user, self.lead = self.staff("lead@alpha.test", "teacher", StaffRole.Role.LEADERSHIP)

    def test_sees_everything_pastoral_and_academic(self):
        self.assertEqual(self.names(self.lead.get("/api/students/")), ["Amina", "Ben", "Cate"])
        self.assertEqual(len(self.lead.get("/api/discipline/incidents/").data), 3)
        self.assertEqual(len(self.lead.get("/api/grades/").data["results"]), 3)
        self.assertEqual(self.lead.get("/api/dashboard/").status_code, 200)
        self.assertEqual(self.lead.get("/api/analytics/performance/", {"scope": "school"}).status_code, 200)

    def test_but_not_settings_staff_the_log_or_data_erasure(self):
        for url in ("/api/staff/", "/api/activity/", f"/api/students/{self.amina.id}/data-export/", ROLES,
                    "/api/teaching-assignments/"):
            self.assertEqual(self.lead.get(url).status_code, 403, url)

    def test_approves_teacher_requests_except_school_settings(self):
        common = dict(school=self.school_a, requested_by=self.user_a, operation="update", summary="x")
        cr = ChangeRequest.objects.create(kind="year_group", target_id=self.form2.id, data={"name": "Form Two"}, **common)
        self.assertEqual(self.lead.post(f"/api/change-requests/{cr.id}/approve/").status_code, 200)
        self.form2.refresh_from_db()
        self.assertEqual(self.form2.name, "Form Two")
        school_cr = ChangeRequest.objects.create(kind="school", target_id=self.school_a.id, data={"name": "Z"}, **common)
        self.assertEqual(self.lead.post(f"/api/change-requests/{school_cr.id}/approve/").status_code, 403)
        self.assertEqual(self.client_a.post(f"/api/change-requests/{cr.id}/reject/").status_code, 403)  # asker, not approver

    def test_approves_any_report(self):
        report = StudentReport.objects.create(student=self.cate, term=self.term, status="submitted",
                                              report_comment="Good", progress_summary="Fine")
        response = self.lead.post(f"/api/reports/{report.id}/finalize/")
        self.assertEqual(response.status_code, 200, response.data)


class HeadOfYearTests(RoleFixture):
    def setUp(self):
        super().setUp()
        _, self.hoy = self.staff("hoy@alpha.test", "teacher", ("head_of_year", {"year_group": self.form2}))

    def test_sees_their_whole_year_and_nothing_else(self):
        self.assertEqual(self.names(self.hoy.get("/api/students/")), ["Amina", "Ben"])
        self.assertEqual(sorted(r["student_name"] for r in self.hoy.get("/api/discipline/incidents/").data),
                         ["Amina K", "Ben K"])
        classes = [c["name"] for c in self.hoy.get("/api/attendance/summary/").data["classes"]]
        self.assertEqual(classes, ["2 East", "2 West"])
        self.assertEqual(self.hoy.get(f"/api/students/{self.cate.id}/").status_code, 404)

    def test_approves_reports_for_their_year_only(self):
        mine = StudentReport.objects.create(student=self.ben, term=self.term, status="submitted",
                                            report_comment="Good", progress_summary="Fine")
        theirs = StudentReport.objects.create(student=self.cate, term=self.term, status="submitted",
                                              report_comment="Good", progress_summary="Fine")
        self.assertEqual(self.hoy.post(f"/api/reports/{mine.id}/finalize/").status_code, 200)
        self.assertEqual(self.hoy.post(f"/api/reports/{theirs.id}/finalize/").status_code, 404)
        # A plain teacher can't approve even their own pupil's report.
        own = StudentReport.objects.create(student=self.amina, term=self.term, status="submitted",
                                           report_comment="Good", progress_summary="Fine")
        self.assertEqual(self.client_a.post(f"/api/reports/{own.id}/finalize/").status_code, 403)

    def test_parents_in_their_year_can_message_them(self):
        hoy_user = User.objects.get(username="hoy@alpha.test")
        parent = User.objects.create_user(username="p@alpha.test", email="p@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.ben)
        ids = [c["id"] for c in self.authed_client(parent).get("/api/conversations/contacts/").json()]
        self.assertIn(hoy_user.id, ids)


class ClassTeacherAndDepartmentTests(RoleFixture):
    def test_class_teacher_sees_their_class_but_grades_only_what_they_teach(self):
        _, ct = self.staff("ct@alpha.test", "teacher", ("class_teacher", {"school_class": self.c2w}))
        self.assertEqual(self.names(ct.get("/api/students/")), ["Ben"])
        self.assertEqual(len(ct.get("/api/grades/").data["results"]), 1)
        response = ct.post("/api/grades/", {"student": self.ben.id, "subject": self.english.id, "term": self.term.id,
                                            "score": 50, "max_score": 100}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_head_of_department_reads_and_grades_their_subject_across_classes_but_no_pastoral(self):
        _, hod = self.staff("hod@alpha.test", "teacher", ("head_of_department", {"subject": self.maths}))
        self.assertEqual(sorted(g["student"] for g in hod.get("/api/grades/").data["results"]),
                         sorted([self.amina.id, self.cate.id]))  # maths is taught in 2 East and 3 East
        ok = hod.post("/api/grades/", {"student": self.cate.id, "subject": self.maths.id, "term": self.term.id,
                                       "score": 70, "max_score": 100}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        no = hod.post("/api/grades/", {"student": self.cate.id, "subject": self.english.id, "term": self.term.id,
                                       "score": 70, "max_score": 100}, format="json")
        self.assertEqual(no.status_code, 403)
        self.assertEqual(hod.get("/api/discipline/incidents/").data, [])
        profile = hod.get(f"/api/students/{self.cate.id}/profile/").data
        self.assertEqual(profile["sections"], {"academic": True, "pastoral": False})
        self.assertIsNone(profile["attendance"])
        self.assertIsNone(profile["discipline"])


class NurseTests(RoleFixture):
    def setUp(self):
        super().setUp()
        _, self.nurse = self.staff("nurse@alpha.test", "teacher", StaffRole.Role.NURSE)

    def test_sees_every_student_and_health_notes_but_not_grades_or_behaviour(self):
        self.assertEqual(self.names(self.nurse.get("/api/students/")), ["Amina", "Ben", "Cate"])
        student = self.nurse.get(f"/api/students/{self.cate.id}/").data
        self.assertEqual(student["medical_notes"], "Cate is allergic to nuts")
        profile = self.nurse.get(f"/api/students/{self.cate.id}/profile/").data
        self.assertEqual(profile["sections"], {"academic": False, "pastoral": False})
        self.assertEqual(profile["grades_by_term"], [])
        self.assertEqual(self.nurse.get("/api/grades/").data["results"], [])
        self.assertEqual(self.nurse.get("/api/discipline/incidents/").data, [])

    def test_updates_health_notes_only(self):
        ok = self.nurse.patch(f"/api/students/{self.cate.id}/", {"medical_notes": "Asthma"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        no = self.nurse.patch(f"/api/students/{self.cate.id}/", {"first_name": "Kate"}, format="json")
        self.assertEqual(no.status_code, 404)

    def test_runs_the_sick_bay_for_day_students_without_boarding(self):
        response = self.nurse.post("/api/boarding/sick-bay/", {"student": self.cate.id, "complaint": "Headache",
                                                               "tell_parents": False}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(self.nurse.get("/api/boarding/sick-bay/").data), 1)
        self.assertEqual(self.client_a.get("/api/boarding/sick-bay/").status_code, 403)
        outsider = Student.objects.create(school=self.school_b, first_name="Zed", last_name="B")
        bad = self.nurse.post("/api/boarding/sick-bay/", {"student": outsider.id, "complaint": "x"}, format="json")
        self.assertEqual(bad.status_code, 400)


class OfficeTests(RoleFixture):
    def test_secretary_keeps_every_register_and_parents_but_not_pastoral_or_grades(self):
        _, sec = self.staff("sec@alpha.test", "teacher", StaffRole.Role.SECRETARY)
        self.assertEqual(len(sec.get("/api/attendance/summary/").data["classes"]), 3)
        late = sec.post("/api/attendance/", {"student": self.cate.id, "date": school_localdate(self.school_a).isoformat(),
                                             "status": "late"}, format="json")
        self.assertEqual(late.status_code, 201, late.data)
        self.assertEqual(sec.get("/api/guardian-invites/").status_code, 200)
        self.assertEqual(sec.get("/api/discipline/incidents/").data, [])
        self.assertEqual(sec.get("/api/grades/").data["results"], [])
        response = sec.post("/api/announcements/", {"title": "Fees", "body": "Due Friday", "audience": "all_parents"},
                            format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(sec.get("/api/admissions/applications/").status_code, 403)

    def test_admissions_officer_runs_admissions_only(self):
        _, adm = self.staff("adm@alpha.test", "teacher", StaffRole.Role.ADMISSIONS)
        self.assertEqual(adm.get("/api/admissions/applications/").status_code, 200)
        self.assertEqual(adm.get("/api/admissions/settings/").status_code, 200)
        self.assertEqual(adm.get("/api/guardian-invites/").status_code, 403)
        self.assertEqual(adm.get("/api/discipline/incidents/").data, [])
        self.assertEqual(self.client_a.get("/api/admissions/applications/").status_code, 403)


class GovernorTests(RoleFixture):
    def setUp(self):
        super().setUp()
        _, self.gov = self.staff("gov@alpha.test", "governor")

    def test_sees_the_school_summary_with_no_names(self):
        me = self.gov.get("/api/me/").data
        self.assertTrue(me["permissions"]["is_governor"])
        summary = self.gov.get("/api/governor/summary/")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data["students"], 3)
        self.assertEqual(summary.data["behaviour_last_30_days"]["total"], 3)
        for name in ("Amina", "Ben", "Cate"):
            self.assertNotIn(name, str(summary.data))

    def test_reaches_nothing_else(self):
        for url in ("/api/students/", f"/api/students/{self.amina.id}/", "/api/announcements/", "/api/conversations/",
                    "/api/grades/", "/api/dashboard/", "/api/teacher-home/", "/api/timetable/week/",
                    "/api/discipline/incidents/", "/api/attendance/summary/"):
            self.assertEqual(self.gov.get(url).status_code, 403, url)
        self.assertEqual(self.gov.post("/api/announcements/", {"title": "x", "body": "y", "audience": "all_staff"},
                                       format="json").status_code, 403)
        self.assertEqual(self.client_a.get("/api/governor/summary/").status_code, 403)

    def test_staff_cant_message_governors(self):
        ids = [c["id"] for c in self.client_a.get("/api/conversations/contacts/").json()]
        gov = User.objects.get(username="gov@alpha.test")
        self.assertNotIn(gov.id, ids)
        response = self.client_a.post("/api/conversations/", {"participant_ids": [gov.id], "body": "Hi"}, format="json")
        self.assertEqual(response.status_code, 400)


class NoRoleChangesTests(RoleFixture):
    def test_a_plain_teacher_is_exactly_as_before(self):
        self.assertEqual(self.names(self.client_a.get("/api/students/")), ["Amina"])
        self.assertEqual(self.client_a.get("/api/dashboard/").status_code, 403)
        self.assertEqual(self.client_a.get("/api/guardian-invites/").status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
