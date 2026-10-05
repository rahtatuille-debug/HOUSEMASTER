"""
A-4: a report's class is recorded once, at its first finalization. Sending it back and finalizing it again
(after the student moved up) keeps the class of the time. An admin can correct it, and that is logged.
Old reports that never had it recorded say so instead of showing today's class.
"""
from io import StringIO

from django.core.management import call_command

from activity.models import ActivityLog
from reporting.models import StudentReport
from reporting.test_report_history import ReportHistoryTests
from students.models import SchoolClass, YearGroup


def load_tests(loader, tests, pattern):
    # Only the tests written here: the fixture and helpers come from ReportHistoryTests, whose own tests run there.
    names = [n for n in vars(ReportClassStampTests) if n.startswith("test_")]
    return loader.suiteClass(ReportClassStampTests(n) for n in sorted(names))


class ReportClassStampTests(ReportHistoryTests):
    def send_back(self):
        response = self.admin.post(f"/api/reports/{self.report.id}/send-back/", {"note": "Fix the comment"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def resubmit(self):
        StudentReport.objects.filter(pk=self.report.pk).update(status="submitted")

    def test_finalizing_again_after_moving_up_keeps_the_class_of_the_time(self):
        self.finalize()
        self.send_back()
        self.move_up()
        self.resubmit()
        self.finalize()
        self.assertEqual((self.report.school_class, self.report.class_name, self.report.grading_scale),
                         (self.c11, "Year 11 · 11A", "igcse9"))
        self.assertNotIn("12A", self.pdf_text())

    def test_finalizing_the_whole_class_again_keeps_it_too(self):
        self.finalize()
        self.send_back()
        self.move_up()
        self.resubmit()
        response = self.admin.post("/api/reports/finalize-class/", {"school_class": self.c12.id, "term": self.term.id},
                                   format="json")
        self.assertEqual(response.data["count"], 1, response.data)
        self.report.refresh_from_db()
        self.assertEqual(self.report.class_name, "Year 11 · 11A")

    def test_an_old_report_with_nothing_recorded_says_so(self):
        StudentReport.objects.filter(pk=self.report.pk).update(status="finalized")  # from before classes were recorded
        self.kid.school_class = self.c12  # moved by hand, not by the year-end tool
        self.kid.save()
        text = self.pdf_text()
        self.assertIn("not recorded", text)
        self.assertNotIn("12A", text)

    def test_an_admin_can_correct_the_class_and_it_is_logged(self):
        self.finalize()
        url = f"/api/reports/{self.report.id}/correct-class/"
        self.assertEqual(self.admin.post(url, {"school_class": self.c12.id}, format="json").status_code, 400)  # reason
        response = self.admin.post(url, {"school_class": self.c12.id, "reason": "Was in 12A that term"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.report.refresh_from_db()
        self.assertEqual((self.report.school_class, self.report.class_name, self.report.grading_scale),
                         (self.c12, "Year 12 · 12A", "igcse"))
        log = ActivityLog.objects.get(action="report.class_corrected")
        self.assertEqual((log.details["before"], log.details["after"]), (self.c11.id, self.c12.id))
        self.assertNotIn("12A that term", str(log.details))

    def test_only_admins_of_the_school_correct_it_and_only_to_their_own_classes(self):
        self.finalize()
        url = f"/api/reports/{self.report.id}/correct-class/"
        body = {"school_class": self.c12.id, "reason": "x"}
        self.assertEqual(self.authed_client(self.user_a).post(url, body, format="json").status_code, 403)
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.post(url, body, format="json").status_code, 404)
        other = SchoolClass.objects.create(year_group=YearGroup.objects.create(school=self.school_b, name="Y"), name="Z")
        self.assertEqual(self.admin.post(url, {"school_class": other.id, "reason": "x"}, format="json").status_code, 400)
        draft = StudentReport.objects.create(student=self.kid, term=self.term.__class__.objects.create(
            school=self.school_a, name="Autumn 2026", start_date=self.term.end_date, end_date=self.term.end_date))
        self.assertEqual(self.admin.post(f"/api/reports/{draft.id}/correct-class/", body, format="json").status_code, 400)
        self.report.refresh_from_db()
        self.assertEqual(self.report.school_class, self.c11)

    def old_log(self):
        # The school's activity log goes back to before the term, so the backfill can tell nobody moved.
        from datetime import datetime

        from django.utils import timezone

        log = ActivityLog.objects.create(school=self.school_a, action="student.created", summary="Added")
        ActivityLog.objects.filter(pk=log.pk).update(created_at=timezone.make_aware(datetime(2026, 1, 5)))

    def test_the_backfill_records_only_what_it_can_be_sure_of_and_is_a_dry_run_by_default(self):
        StudentReport.objects.filter(pk=self.report.pk).update(status="finalized")  # nothing recorded, nobody moved
        self.old_log()
        out = StringIO()
        call_command("backfill_report_classes", stdout=out)
        self.assertIn("Would record 1", out.getvalue())
        self.report.refresh_from_db()
        self.assertEqual(self.report.class_name, "")
        call_command("backfill_report_classes", "--apply", stdout=StringIO())
        self.report.refresh_from_db()
        self.assertEqual(self.report.class_name, "Year 11 · 11A")
        self.assertNotIn("Ola", out.getvalue())  # counts only

    def test_the_backfill_leaves_reports_whose_student_may_have_moved(self):
        StudentReport.objects.filter(pk=self.report.pk).update(status="finalized")
        self.old_log()
        self.admin.patch(f"/api/students/{self.kid.id}/", {"school_class": self.c12.id}, format="json")
        out = StringIO()
        call_command("backfill_report_classes", "--apply", stdout=out)
        self.report.refresh_from_db()
        self.assertEqual(self.report.class_name, "")
        self.assertIn("1 left as 'not recorded'", out.getvalue())

    def test_the_backfill_leaves_everything_when_the_log_does_not_go_back_far_enough(self):
        StudentReport.objects.filter(pk=self.report.pk).update(status="finalized")
        out = StringIO()
        call_command("backfill_report_classes", "--apply", stdout=out)
        self.assertIn("Recorded 0", out.getvalue())
