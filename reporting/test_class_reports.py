"""Whole-class report actions: generate for a class, submit all, finalize all."""
from unittest.mock import patch

from django.core.cache import cache
from rest_framework.throttling import ScopedRateThrottle

from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from gradebook.models import Term
from students.models import SchoolClass, Student, YearGroup

from .models import StudentReport


def fake_generate(student, term):
    report, _ = StudentReport.objects.update_or_create(
        student=student, term=term, defaults={"progress_summary": "AI summary", "report_comment": "AI comment"},
    )
    return report


class ClassReportTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.admin_client_a = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Grade 7")
        self.class_a = SchoolClass.objects.create(year_group=year, name="7 East")
        self.other_class = SchoolClass.objects.create(year_group=year, name="7 West")
        self.term = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.students = [
            Student.objects.create(school=self.school_a, school_class=self.class_a, first_name=f"S{i}", last_name="A")
            for i in range(4)
        ]
        self.outsider = Student.objects.create(school=self.school_a, school_class=self.other_class,
                                               first_name="Other", last_name="Class")
        Student.objects.create(school=self.school_a, school_class=self.class_a, first_name="Left",
                               last_name="School", is_active=False)
        # Teacher A teaches 7 East only.
        self.assign(self.user_a, self.class_a, None)

        year_b = YearGroup.objects.create(school=self.school_b, name="Grade 7")
        self.class_b = SchoolClass.objects.create(year_group=year_b, name="7 East")
        self.term_b = Term.objects.create(school=self.school_b, name="Term 1 2026")

    def start(self, client=None, **body):
        body = {"school_class": self.class_a.id, "term": self.term.id, **body}
        return (client or self.client_a).post("/api/reports/generate-class/", body)

    def step(self, run, student_id, client=None):
        return (client or self.client_a).post("/api/reports/generate-class/next/", {"run": run, "student": student_id})

    @patch("reporting.views.generate_report", side_effect=fake_generate)
    def test_generates_a_report_for_every_active_student_without_one(self, _gen):
        StudentReport.objects.create(student=self.students[0], term=self.term,
                                     progress_summary="Teacher's own", report_comment="Edited")
        response = self.start()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["already_have_reports"], 1)
        todo = [s["id"] for s in response.data["students"]]
        self.assertEqual(sorted(todo), sorted(s.id for s in self.students[1:]))

        for student_id in todo:
            r = self.step(response.data["run"], student_id)
            self.assertEqual(r.status_code, 200)
            self.assertFalse(r.data["skipped"])
        self.assertEqual(StudentReport.objects.filter(term=self.term).count(), 4)
        # The existing report was left exactly as the teacher wrote it.
        self.assertEqual(StudentReport.objects.get(student=self.students[0]).report_comment, "Edited")
        self.assertTrue(ActivityLog.objects.filter(action="report.class_generated").exists())

    @patch("reporting.views.generate_report", side_effect=fake_generate)
    def test_a_step_skips_a_student_who_got_a_report_meanwhile(self, gen):
        run = self.start().data["run"]
        StudentReport.objects.create(student=self.students[1], term=self.term,
                                     progress_summary="x", report_comment="Written by hand")
        r = self.step(run, self.students[1].id)
        self.assertTrue(r.data["skipped"])
        gen.assert_not_called()
        self.assertEqual(StudentReport.objects.get(student=self.students[1]).report_comment, "Written by hand")

    @patch("reporting.views.generate_report", side_effect=fake_generate)
    def test_run_only_covers_its_own_students_and_user(self, gen):
        run = self.start().data["run"]
        self.assertEqual(self.step(run, self.outsider.id).status_code, 403)
        self.assertEqual(self.step(run, self.students[1].id, client=self.admin_client_a).status_code, 403)
        self.assertEqual(self.step("forged", self.students[1].id).status_code, 400)
        gen.assert_not_called()

    def test_teachers_only_run_classes_they_teach(self):
        response = self.start(school_class=self.other_class.id)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.start(client=self.admin_client_a, school_class=self.other_class.id).status_code, 200)

    def test_other_schools_classes_and_terms_are_not_found(self):
        self.assertEqual(self.start(client=self.admin_client_a, school_class=self.class_b.id).status_code, 404)
        self.assertEqual(self.start(client=self.admin_client_a, term=self.term_b.id).status_code, 404)

    def test_locked_term_is_refused(self):
        self.term.is_locked = True
        self.term.save()
        self.assertEqual(self.start().status_code, 400)

    def test_class_runs_have_their_own_limit(self):
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"ai_class_report_generation": "1/min"}):
            self.assertEqual(self.start().status_code, 200)
            self.assertEqual(self.start().status_code, 429)
            # Single reports use a separate limit and aren't affected.
            with patch("reporting.views.generate_report", side_effect=fake_generate):
                single = self.client_a.post("/api/reports/generate/",
                                            {"student": self.students[0].id, "term": self.term.id})
            self.assertEqual(single.status_code, 200)

    def test_steps_are_not_throttled_per_report(self):
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"ai_report_generation": "0/min"}), \
                patch("reporting.views.generate_report", side_effect=fake_generate):
            run = self.start().data["run"]
            for s in self.students:
                self.assertEqual(self.step(run, s.id).status_code, 200)

    def test_submit_class_submits_only_this_class_drafts(self):
        for s in self.students[:3]:
            StudentReport.objects.create(student=s, term=self.term, progress_summary="x", report_comment="y")
        StudentReport.objects.filter(student=self.students[2]).update(status="finalized")
        other = StudentReport.objects.create(student=self.outsider, term=self.term, progress_summary="x",
                                             report_comment="y")
        response = self.client_a.post("/api/reports/submit-class/",
                                      {"school_class": self.class_a.id, "term": self.term.id})
        self.assertEqual(response.data["count"], 2)
        statuses = dict(StudentReport.objects.values_list("student_id", "status"))
        self.assertEqual(statuses[self.students[0].id], "submitted")
        self.assertEqual(statuses[self.students[2].id], "finalized")
        other.refresh_from_db()
        self.assertEqual(other.status, "draft")
        self.assertEqual(StudentReport.objects.get(student=self.students[0]).submitted_by, self.user_a)

    def test_only_admins_finalize_a_class_and_only_submitted_reports(self):
        StudentReport.objects.create(student=self.students[0], term=self.term, progress_summary="x",
                                     report_comment="y", status="submitted")
        StudentReport.objects.create(student=self.students[1], term=self.term, progress_summary="x",
                                     report_comment="y")
        body = {"school_class": self.class_a.id, "term": self.term.id}
        self.assertEqual(self.client_a.post("/api/reports/finalize-class/", body).status_code, 403)
        response = self.admin_client_a.post("/api/reports/finalize-class/", body)
        self.assertEqual(response.data["count"], 1)
        statuses = dict(StudentReport.objects.values_list("student_id", "status"))
        self.assertEqual(statuses[self.students[0].id], "finalized")
        self.assertEqual(statuses[self.students[1].id], "draft")
        self.assertTrue(ActivityLog.objects.filter(action="report.class_finalized").exists())
