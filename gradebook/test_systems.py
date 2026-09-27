"""Per-system results: KCSE points and positions, GPA, IB criteria, CBC levels, and the entry APIs."""
from django.contrib.auth.models import User
from django.test import SimpleTestCase

from accounts.tests import SchoolScopedAPITestCase
from guardians.models import Guardian
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

from .models import Grade, Subject, SubjectReport, Term
from .systems import honor_roll, mean_grade, myp_grade, term_summary


class RuleTests(SimpleTestCase):
    def test_mean_grade_rounds_mean_points(self):
        self.assertEqual([mean_grade(p) for p in (12, 11.5, 11.49, 7.5, 6.4, 1, 0.2)],
                         ["A", "A", "A-", "B-", "C", "E", "E"])

    def test_myp_boundaries(self):
        crit = lambda total: {"A": min(8, total), "B": max(0, min(8, total - 8)), "C": max(0, min(8, total - 16)),
                              "D": max(0, total - 24)}
        self.assertEqual([myp_grade(crit(t)) for t in (0, 5, 6, 10, 15, 19, 24, 28, 32)], [1, 1, 2, 3, 4, 5, 6, 7, 7])
        self.assertIsNone(myp_grade({"A": 5, "B": 5, "C": 5}))
        self.assertIsNone(myp_grade({"A": 9, "B": 5, "C": 5, "D": 5}))

    def test_honor_roll(self):
        self.assertEqual([honor_roll(g) for g in (3.9, 3.5, 3.2, 2.9, None)],
                         ["High honor roll", "High honor roll", "Honor roll", "", ""])


class SummaryTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        year = YearGroup.objects.create(school=self.school_a, name="Form 2")
        self.east = SchoolClass.objects.create(year_group=year, name="2 East")
        self.west = SchoolClass.objects.create(year_group=year, name="2 West")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.maths = Subject.objects.create(school=self.school_a, name="Mathematics", credits=2)
        self.english = Subject.objects.create(school=self.school_a, name="English")

    def student(self, name, klass, maths, english):
        s = Student.objects.create(school=self.school_a, school_class=klass, first_name=name, last_name="X")
        Grade.objects.create(student=s, subject=self.maths, term=self.term, score=maths)
        Grade.objects.create(student=s, subject=self.english, term=self.term, score=english)
        return s

    def use(self, system, scale):
        self.school_a.education_system, self.school_a.grading_scale = system, scale
        self.school_a.save()

    def test_844_points_mean_grade_and_positions(self):
        self.use("844", "kcse")
        top = self.student("Top", self.east, 85, 81)       # A + A = 12, 12
        tie = self.student("Tie", self.west, 90, 80)      # also A + A
        mid = self.student("Mid", self.east, 62, 50)      # B- (8) + C (6) = 7 mean -> C+
        low = self.student("Low", self.east, 20, 31)      # E (1) + D- (2)
        s = term_summary(Student.objects.get(pk=mid.pk), self.term)
        self.assertEqual([(r["subject"], r["kcse_grade"], r["points"]) for r in s["subjects"]],
                         [("English", "C", 6), ("Mathematics", "B-", 8)])
        self.assertEqual((s["total_points"], s["mean_points"], s["mean_grade"], s["total_marks"]), (14, 7.0, "C+", 112))
        self.assertEqual(s["positions"], {"stream": {"position": 2, "of": 3}, "form": {"position": 3, "of": 4}})
        # Equal mean points: the higher average mark comes first; exact ties share a place.
        self.assertEqual(term_summary(tie, self.term)["positions"]["form"], {"position": 1, "of": 4})
        self.assertEqual(term_summary(top, self.term)["positions"]["form"], {"position": 2, "of": 4})
        self.assertEqual(term_summary(low, self.term)["mean_grade"], "D-")

    def test_cbc_has_levels_and_never_positions(self):
        self.use("cbc", "cbc4")
        s = term_summary(self.student("Amina", self.east, 85, 45), self.term)
        self.assertEqual([r["level"] for r in s["subjects"]], ["AE", "EE"])
        self.assertNotIn("positions", s)
        self.assertEqual((s["average"], s["average_level"]), (65.0, "ME"))

    def test_american_gpa_weighted_by_credits(self):
        self.use("american", "american")
        s = term_summary(self.student("Sam", self.east, 92, 75), self.term)  # Maths A (4) x2 credits, English C (2) x1
        self.assertEqual(s["gpa"], 3.33)
        self.assertEqual(s["honor_roll"], "Honor roll")

    def test_ib_criteria_decide_the_grade_when_complete(self):
        self.use("ib", "ib")
        student = self.student("Ivy", self.east, 55, 55)
        SubjectReport.objects.create(student=student, subject=self.maths, term=self.term,
                                     criteria={"A": 8, "B": 7, "C": 7, "D": 7})
        s = term_summary(student, self.term)
        grades = {r["subject"]: r["ib_grade"] for r in s["subjects"]}
        self.assertEqual(grades, {"Mathematics": 7, "English": 4})
        self.assertEqual(s["ib_total"], 11)

    def test_british_effort_and_target_come_from_the_teacher(self):
        self.use("british", "igcse")
        student = self.student("Ben", self.east, 72, 64)
        SubjectReport.objects.create(student=student, subject=self.english, term=self.term, effort="1", target="A",
                                     comment="Reads widely.")
        english = term_summary(student, self.term)["subjects"][0]
        self.assertEqual((english["level"], english["effort"], english["target"], english["comment"]),
                         ("C", "1", "A", "Reads widely."))


class EntryAPITests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.school_a.education_system = "ib"
        self.school_a.save()
        self.admin = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="MYP 3")
        self.klass = SchoolClass.objects.create(year_group=year, name="MYP 3A")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.maths = Subject.objects.create(school=self.school_a, name="Mathematics")
        self.art = Subject.objects.create(school=self.school_a, name="Arts")
        self.kid = Student.objects.create(school=self.school_a, school_class=self.klass, first_name="Ivy", last_name="X")
        self.assign(self.user_a, self.klass, self.maths)

    def save(self, client, subject, **entry):
        return client.post("/api/subject-reports/", {
            "term": self.term.id, "subject": subject.id, "school_class": self.klass.id,
            "entries": [{"student": self.kid.id, **entry}]}, format="json")

    def test_teacher_saves_entries_for_their_subject(self):
        response = self.save(self.client_a, self.maths, comment="Strong reasoning.", criteria={"A": 6, "B": 7, "C": "", "D": 5})
        self.assertEqual(response.status_code, 200)
        entry = SubjectReport.objects.get()
        self.assertEqual((entry.comment, entry.criteria), ("Strong reasoning.", {"A": 6, "B": 7, "D": 5}))
        listing = self.client_a.get("/api/subject-reports/", {"term": self.term.id, "subject": self.maths.id,
                                                               "school_class": self.klass.id}).data
        self.assertEqual(listing["fields"], ["criteria"])
        self.assertEqual(listing["students"][0]["comment"], "Strong reasoning.")

    def test_teacher_cannot_save_for_other_subjects_and_bad_criteria_are_refused(self):
        self.assertEqual(self.save(self.client_a, self.art, comment="x").status_code, 403)
        self.assertEqual(self.save(self.client_a, self.maths, criteria={"A": 9}).status_code, 400)
        self.assertEqual(self.save(self.client_a, self.maths, criteria={"E": 3}).status_code, 400)
        self.assertFalse(SubjectReport.objects.exists())

    def test_locked_terms_and_other_schools(self):
        self.term.is_locked = True
        self.term.save()
        self.assertEqual(self.save(self.admin, self.maths, comment="x").status_code, 400)
        other = self.client_b.get("/api/subject-reports/", {"term": self.term.id, "subject": self.maths.id,
                                                             "school_class": self.klass.id})
        self.assertEqual(other.status_code, 404)

    def test_report_extras_are_checked_and_principal_remarks_are_for_admins(self):
        report = StudentReport.objects.create(student=self.kid, term=self.term, progress_summary="s", report_comment="c")
        url = f"/api/reports/{report.id}/"
        ok = self.client_a.patch(url, {"extra": {"atl": {"Thinking skills": "P"}}}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data["extra"], {"atl": {"Thinking skills": "P"}})
        self.assertEqual(self.client_a.patch(url, {"extra": {"atl": {"Thinking skills": "Z"}}}, format="json").status_code, 400)
        self.assertEqual(self.client_a.patch(url, {"principal_comment": "Well done"}, format="json").status_code, 403)
        self.assertEqual(self.admin.patch(url, {"principal_comment": "Well done"}, format="json").status_code, 200)

    def test_term_summary_for_staff_and_parents_after_finalizing(self):
        Grade.objects.create(student=self.kid, subject=self.maths, term=self.term, score=70)
        staff = self.admin.get(f"/api/students/{self.kid.id}/term-summary/", {"term": self.term.id})
        self.assertEqual(staff.data["subjects"][0]["ib_grade"], 6)
        user = User.objects.create_user(username="p@alpha.test", email="p@alpha.test", password="pass1234")
        Guardian.objects.create(user=user, school=self.school_a).students.add(self.kid)
        parent = self.authed_client(user)
        url = f"/api/guardian-students/{self.kid.id}/term-summary/"
        self.assertEqual(parent.get(url, {"term": self.term.id}).status_code, 404)
        StudentReport.objects.create(student=self.kid, term=self.term, progress_summary="s", report_comment="c",
                                     status="finalized")
        self.assertEqual(parent.get(url, {"term": self.term.id}).data["ib_total"], 6)


class ReportCardTests(SummaryTests):
    def test_every_system_prints_a_report_card(self):
        from reporting.exports import reports_pdf

        student = self.student("Nia", self.east, 74, 58)
        self.student("Other", self.west, 60, 60)
        SubjectReport.objects.create(student=student, subject=self.maths, term=self.term, comment="Good work.",
                                     effort="2", target="A", criteria={"A": 6, "B": 6, "C": 6, "D": 6})
        StudentReport.objects.create(
            student=student, term=self.term, progress_summary="s", report_comment="A good term.", status="finalized",
            principal_comment="Keep it up.",
            extra={"competencies": {"Citizenship": "ME"}, "values": {"Respect": "EE"}, "atl": {"Thinking skills": "P"}})
        for system, scale in (("cbc", "cbc4"), ("844", "kcse"), ("british", "igcse9"), ("ib", "ib"),
                              ("american", "american"), ("", "percent")):
            self.use(system, scale)
            content, count = reports_pdf(self.school_a, [student], self.term)
            self.assertEqual(count, 1, system)
            self.assertTrue(content.startswith(b"%PDF"), system)
