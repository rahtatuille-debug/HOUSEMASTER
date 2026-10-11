"""
The five extra performance graphs (P-1 … P-5): their numbers, what they hide, and who may see them.

Every expected number below is worked out by hand in the comments, with the school's assessment types
CAT (weight 30) and Exam (weight 70): a subject's result is the weighted mean of the types that have marks.
"""
import os
from datetime import date, datetime, timezone as dt_timezone
from unittest import skipUnless

from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import AssessmentType, Grade, Subject, Term
from guardians.models import Guardian
from reporting.charts import CHARTS
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

URL = "/api/analytics/charts/"


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


class ChartsTestCase(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        school = self.school_a
        school.education_system, school.grading_scale = "british", "igcse9"
        school.support_min_marks = 1
        school.save()
        self.admin = self.authed_client(self.admin_a)
        self.y7 = YearGroup.objects.create(school=school, name="Year 7")
        self.c7a = SchoolClass.objects.create(year_group=self.y7, name="7A")
        self.c7b = SchoolClass.objects.create(year_group=self.y7, name="7B")  # a tiny class: 2 students
        self.t1 = Term.objects.create(school=school, name="T1", start_date=date(2026, 1, 5), end_date=date(2026, 3, 31))
        self.t2 = Term.objects.create(school=school, name="T2", start_date=date(2026, 5, 4), end_date=date(2026, 7, 31))
        self.t3 = Term.objects.create(school=school, name="T3", start_date=date(2026, 9, 1), end_date=date(2026, 11, 30))
        self.cat = AssessmentType.objects.create(school=school, name="CAT", weight=30, order=1)
        self.exam = AssessmentType.objects.create(school=school, name="Exam", weight=70, order=2)
        self.maths = Subject.objects.create(school=school, name="Maths")
        self.english = Subject.objects.create(school=school, name="English")

        # Ann (7A):
        #   T1 Maths: CAT 60, Exam 80 -> 0.3*60 + 0.7*80 = 74.0;  T1 English: CAT 50 only -> 50.0;  T1 average 62.0
        #   T2 Maths: CAT 70 and 90 (mean 80), Exam 40/50 = 80%   -> 80.0;  T2 English: no marks (a gap)
        #   T3 Maths: Exam 45/50 = 90.0;  T3 English: Exam 30/40 = 75.0
        self.ann = self.student("Ann", self.c7a, [
            (self.t1, self.maths, self.cat, 60, 100), (self.t1, self.maths, self.exam, 80, 100),
            (self.t1, self.english, self.cat, 50, 100),
            (self.t2, self.maths, self.cat, 70, 100), (self.t2, self.maths, self.cat, 90, 100),
            (self.t2, self.maths, self.exam, 40, 50),
            (self.t3, self.maths, self.exam, 45, 50), (self.t3, self.english, self.exam, 30, 40),
        ])
        # Five classmates with Maths CAT 50 and Exam 50 in T1 (Maths 50.0), nothing else.
        self.mates = [self.student(f"Mate{i}", self.c7a, [(self.t1, self.maths, self.cat, 50, 100),
                                                           (self.t1, self.maths, self.exam, 50, 100)])
                      for i in range(5)]
        # 7B has two students: too few for a class comparison.
        self.cy = self.student("Cy", self.c7b, [(self.t1, self.maths, self.exam, 40, 100)])
        self.di = self.student("Di", self.c7b, [(self.t1, self.maths, self.exam, 60, 100)])
        # Another school's student.
        self.other = Student.objects.create(school=self.school_b, first_name="Zed", last_name="B")

    def student(self, name, klass, marks):
        s = Student.objects.create(school=self.school_a, first_name=name, last_name="X", school_class=klass)
        for term, subject, kind, score, out_of in marks:
            Grade.objects.create(student=s, subject=subject, term=term, assessment_type=kind, score=score,
                                 max_score=out_of)
        return s

    def chart(self, client=None, **params):
        return (client or self.admin).get(URL, params)


class SubjectTrendsTests(ChartsTestCase):
    """P-1."""

    def test_numbers_per_subject_and_term(self):
        data = self.chart(chart="subject_trends", scope="student", id=self.ann.id).data
        self.assertEqual([t["name"] for t in data["terms"]], ["T1", "T2", "T3"])
        lines = {s["subject"]: [(p["term"], p["student"]) for p in s["points"]] for s in data["subjects"]}
        self.assertEqual(lines["Maths"], [("T1", 74.0), ("T2", 80.0), ("T3", 90.0)])
        # A term with no marks is a gap (None), never a zero.
        self.assertEqual(lines["English"], [("T1", 50.0), ("T2", None), ("T3", 75.0)])

    def test_subject_lines_agree_with_the_existing_term_average(self):
        trends = self.chart(chart="subject_trends", scope="student", id=self.ann.id).data
        existing = self.admin.get("/api/analytics/performance/", {"scope": "student", "id": self.ann.id}).data
        for i, row in enumerate(existing["trend"]):
            values = [s["points"][i]["student"] for s in trends["subjects"] if s["points"][i]["student"] is not None]
            self.assertAlmostEqual(round(sum(values) / len(values), 1), row["student"])

    def test_class_line_only_when_enough_classmates_have_marks(self):
        data = self.chart(chart="subject_trends", scope="student", id=self.ann.id).data
        maths = next(s for s in data["subjects"] if s["subject"] == "Maths")
        # T1 Maths class: Ann 74 + five mates at 50 -> 324 / 6 = 54.0 (six students, at least 5).
        self.assertEqual(maths["points"][0]["class"], 54.0)
        # T2 Maths: only Ann has marks -> no class line.
        self.assertIsNone(maths["points"][1]["class"])
        self.assertEqual(data["compare"]["min_students"], 5)
        # 7B has two students: the class line is never shown.
        tiny = self.chart(chart="subject_trends", scope="student", id=self.cy.id).data
        self.assertTrue(all(p["class"] is None for s in tiny["subjects"] for p in s["points"]))

    def test_group_scopes(self):
        data = self.chart(chart="subject_trends", scope="class", id=self.c7a.id).data
        maths = next(s for s in data["subjects"] if s["subject"] == "Maths")
        self.assertEqual([p["average"] for p in maths["points"]], [54.0, 80.0, 90.0])
        self.assertNotIn("student", maths["points"][0])
        year = self.chart(chart="subject_trends", scope="year_group", id=self.y7.id).data
        y_maths = next(s for s in year["subjects"] if s["subject"] == "Maths")
        # T1 Year 7 Maths: Ann 74, mates 5 x 50, Cy 40, Di 60 -> 424 / 8 = 53.0
        self.assertEqual(y_maths["points"][0]["average"], 53.0)
        school = self.chart(chart="subject_trends", scope="school").data
        self.assertEqual(next(s for s in school["subjects"] if s["subject"] == "Maths")["points"][0]["average"], 53.0)

    def test_one_term_only(self):
        data = self.chart(chart="subject_trends", scope="student", id=self.cy.id).data
        self.assertEqual(len(data["terms"]), 3)  # the school's graded terms
        self.assertEqual([p["student"] for p in data["subjects"][0]["points"]], [40.0, None, None])

    def test_levels_school(self):
        school = self.school_a
        school.education_system, school.grading_scale = "", "cbc4"
        school.save()
        data = self.chart(chart="subject_trends", scope="student", id=self.ann.id).data
        self.assertEqual(data["grading"]["scale"], "cbc4")
        self.assertEqual([lvl["code"] for lvl in data["grading"]["levels"]][:1], ["EE"])
        self.assertEqual(next(s for s in data["subjects"] if s["subject"] == "Maths")["points"][0]["student"], 74.0)

    def test_query_count_is_flat_as_subjects_and_terms_grow(self):
        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.chart(chart="subject_trends", scope="student", id=self.ann.id).status_code, 200)
            return len(ctx.captured_queries)

        before = count()
        for n in range(6):
            term = Term.objects.create(school=self.school_a, name=f"Extra {n}", start_date=date(2027, 1, n + 1))
            subject = Subject.objects.create(school=self.school_a, name=f"Extra subject {n}")
            Grade.objects.create(student=self.ann, subject=subject, term=term, score=50, assessment_type=self.cat)
        self.assertEqual(count(), before)


class AssessmentTypeTests(ChartsTestCase):
    """P-2."""

    def test_averages_and_counts_per_type(self):
        data = self.chart(chart="assessment_types", scope="student", id=self.ann.id, term=self.t1.id).data
        types = {t["name"]: t for t in data["types"]}
        # CAT: Maths 60, English 50 -> 55.0 over 2 marks. Exam: Maths 80 -> 80.0 over 1 mark.
        self.assertEqual((types["CAT"]["student"], types["CAT"]["marks"]), (55.0, 2))
        self.assertEqual((types["Exam"]["student"], types["Exam"]["marks"]), (80.0, 1))
        # Weights are information only.
        self.assertEqual((types["CAT"]["weight"], types["Exam"]["weight"]), (30.0, 70.0))
        # Class (6 students with CAT marks): Ann 55, mates 50 -> 305 / 6 = 50.8; Exam: 80 + 250 = 330 / 6 = 55.0
        self.assertEqual((types["CAT"]["class"], types["Exam"]["class"]), (50.8, 55.0))

    def test_one_subject(self):
        data = self.chart(chart="assessment_types", scope="student", id=self.ann.id, term=self.t2.id,
                          subject="Maths").data
        types = {t["name"]: t for t in data["types"]}
        # T2 Maths: CAT 70 and 90 -> 80.0 over 2 marks; Exam 40/50 -> 80.0 over 1 mark. Weights not applied again.
        self.assertEqual((types["CAT"]["student"], types["CAT"]["marks"]), (80.0, 2))
        self.assertEqual((types["Exam"]["student"], types["Exam"]["marks"]), (80.0, 1))
        self.assertIsNone(types["CAT"]["class"])  # only Ann has T2 marks
        self.assertEqual(data["subjects"], ["Maths"])  # the subjects with marks this term

    def test_too_few_marks_is_hidden_with_the_reason(self):
        self.school_a.support_min_marks = 2
        self.school_a.save()
        data = self.chart(chart="assessment_types", scope="student", id=self.ann.id, term=self.t1.id).data
        exam = next(t for t in data["types"] if t["name"] == "Exam")
        self.assertIsNone(exam["student"])
        self.assertEqual(exam["marks"], 1)
        self.assertEqual(exam["reason"], "Not enough data (1 mark; needs 2)")
        self.assertEqual(next(t for t in data["types"] if t["name"] == "CAT")["student"], 55.0)

    def test_school_defined_type_names(self):
        self.cat.name, self.exam.name = "Continuous assessment", "End-term"
        self.cat.save()
        self.exam.save()
        data = self.chart(chart="assessment_types", scope="student", id=self.ann.id, term=self.t1.id).data
        self.assertEqual([t["name"] for t in data["types"]], ["Continuous assessment", "End-term"])

    def test_marks_without_a_type(self):
        Grade.objects.create(student=self.ann, subject=self.english, term=self.t1, score=70)
        data = self.chart(chart="assessment_types", scope="student", id=self.ann.id, term=self.t1.id).data
        untyped = next(t for t in data["types"] if t["id"] is None)
        self.assertEqual((untyped["name"], untyped["student"], untyped["marks"], untyped["weight"]),
                         ("No assessment type", 70.0, 1, None))

    def test_query_count_is_flat(self):
        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.chart(chart="assessment_types", scope="student", id=self.ann.id, term=self.t1.id)
            return len(ctx.captured_queries)

        before = count()
        for n in range(5):
            kind = AssessmentType.objects.create(school=self.school_a, name=f"Quiz {n}", weight=5)
            Grade.objects.create(student=self.ann, subject=self.maths, term=self.t1, score=50, assessment_type=kind)
        self.assertEqual(count(), before)


class MarksInTermTests(ChartsTestCase):
    """P-3."""

    def stamp(self, grade, when):
        Grade.objects.filter(pk=grade.pk).update(recorded_at=when)

    def test_points_dates_and_time_zone(self):
        grades = list(Grade.objects.filter(student=self.ann, term=self.t1).order_by("id"))
        # Africa/Nairobi is UTC+3: 23:30 UTC on 31 Jan is 02:30 on 1 Feb there; 21:30 UTC is 00:30 on 1 Feb.
        self.stamp(grades[0], utc(2026, 1, 31, 23, 30))
        self.stamp(grades[1], utc(2026, 1, 31, 21, 30))
        self.stamp(grades[2], utc(2026, 1, 31, 20, 59))  # 23:59 on 31 Jan
        data = self.chart(chart="marks", scope="student", id=self.ann.id, term=self.t1.id).data
        self.assertEqual(data["date_basis"], "recorded")
        self.assertEqual(data["time_zone"], "Africa/Nairobi")
        self.assertEqual((data["term"]["start"], data["term"]["end"]), ("2026-01-05", "2026-03-31"))
        self.assertEqual([(p["date"], p["subject"], p["assessment_type"], p["percent"]) for p in data["points"]], [
            ("2026-01-31", "English", "CAT", 50.0),
            ("2026-02-01", "Maths", "Exam", 80.0),
            ("2026-02-01", "Maths", "CAT", 60.0),
        ])

    def test_marks_recorded_outside_the_term_are_left_out_and_counted(self):
        grades = list(Grade.objects.filter(student=self.ann, term=self.t1).order_by("id"))
        for g in grades:
            self.stamp(g, utc(2026, 2, 10, 9, 0))
        self.stamp(grades[2], utc(2026, 4, 10, 9, 0))
        data = self.chart(chart="marks", scope="student", id=self.ann.id, term=self.t1.id).data
        self.assertEqual(len(data["points"]), 2)
        self.assertEqual(data["outside_term"], 1)

    def test_no_marks(self):
        data = self.chart(chart="marks", scope="student", id=self.cy.id, term=self.t2.id).data
        self.assertEqual((data["points"], data["outside_term"]), ([], 0))

    def test_query_count_is_flat_as_marks_grow(self):
        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.chart(chart="marks", scope="student", id=self.ann.id, term=self.t1.id)
            return len(ctx.captured_queries)

        before = count()
        for n in range(30):
            Grade.objects.create(student=self.ann, subject=self.maths, term=self.t1, score=n, assessment_type=self.cat)
        self.assertEqual(count(), before)


class RankTests(ChartsTestCase):
    """P-4."""

    def test_positions_equal_the_rankings_table_every_term(self):
        data = self.chart(chart="ranks", scope="student", id=self.ann.id).data
        self.assertTrue(data["ranked"])
        for point in data["points"]:
            table = self.admin.get("/api/analytics/performance/",
                                   {"scope": "class", "id": self.c7a.id, "term": point["term_id"]}).data
            row = next(r for r in table["students"] if r["id"] == self.ann.id)
            if row["position"] is None:
                self.assertIsNone(point["class"]["position"])
            else:
                self.assertEqual((point["class"]["position"], point["class"]["of"]), (row["position"], row["of"]))
            year = self.admin.get("/api/analytics/performance/",
                                  {"scope": "year_group", "id": self.y7.id, "term": point["term_id"]}).data
            yrow = next(r for r in year["students"] if r["id"] == self.ann.id)
            self.assertEqual(point["year_group"]["position"], yrow["position"])
        # T1: Ann 62.0 is top of 7A (mates 50) -> 1st of 6; Year 7 also has Cy 40 and Di 60 -> 1st of 8.
        t1 = data["points"][0]
        self.assertEqual((t1["class"], t1["year_group"]), ({"position": 1, "of": 6}, {"position": 1, "of": 8}))
        # The admin may also see the whole school.
        self.assertEqual(t1["school"], {"position": 1, "of": 8})

    def test_ties_share_a_position(self):
        t1 = self.chart(chart="ranks", scope="student", id=self.mates[0].id).data["points"][0]
        # Five mates on 50.0 behind Ann's 62.0 -> all 2nd of 6.
        self.assertEqual(t1["class"], {"position": 2, "of": 6})

    def test_unranked_term_is_a_gap_with_the_reason(self):
        self.school_a.ranking_min_share = 100
        self.school_a.save()
        # T1 usual subjects in 7A is 1 (mates take only Maths), so Ann is complete; in T3 Ann alone has 2.
        # Give a mate a T1 English mark so the usual becomes... still 1. Instead check a T2 term with no marks:
        data = self.chart(chart="ranks", scope="student", id=self.mates[0].id).data
        t2 = data["points"][1]
        self.assertEqual(t2["class"], {"position": None, "reason": "No marks this term"})
        table_t1 = self.admin.get("/api/analytics/performance/",
                                  {"scope": "class", "id": self.c7a.id, "term": self.t1.id}).data
        # Ann has 2 subjects, the mates 1 -> usual 1 -> everyone complete.
        self.assertTrue(all(r["not_ranked"] is None for r in table_t1["students"]))
        # Make the usual 2 subjects: four mates get an English mark; mate 0 keeps only Maths.
        for mate in self.mates[1:]:
            Grade.objects.create(student=mate, subject=self.english, term=self.t1, score=50, assessment_type=self.cat)
        table_t1 = self.admin.get("/api/analytics/performance/",
                                  {"scope": "class", "id": self.c7a.id, "term": self.t1.id}).data
        row = next(r for r in table_t1["students"] if r["id"] == self.mates[0].id)
        point = self.chart(chart="ranks", scope="student", id=self.mates[0].id).data["points"][0]
        self.assertIsNone(point["class"]["position"])
        self.assertEqual(point["class"]["reason"], row["not_ranked_label"])
        self.assertEqual(row["not_ranked_label"], "Not ranked: incomplete marks (1 of 2 subjects)")

    def test_cbc_learners_are_not_ranked(self):
        self.school_a.education_system, self.school_a.grading_scale = "cbc", "cbc4"
        self.school_a.save()
        data = self.chart(chart="ranks", scope="student", id=self.ann.id).data
        self.assertFalse(data["ranked"])
        self.assertEqual(data["points"], [])
        self.assertIn("CBC", data["reason"])

    def test_teachers_do_not_see_the_school_position(self):
        self.assign(self.user_a, self.c7a, self.maths)
        teacher = self.authed_client(self.user_a)
        t1 = self.chart(teacher, chart="ranks", scope="student", id=self.ann.id).data["points"][0]
        self.assertNotIn("school", t1)
        self.assertEqual(t1["class"], {"position": 1, "of": 6})

    def test_query_count_is_flat_as_terms_grow(self):
        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.chart(chart="ranks", scope="student", id=self.ann.id)
            return len(ctx.captured_queries)

        before = count()
        for n in range(4):
            term = Term.objects.create(school=self.school_a, name=f"Extra {n}", start_date=date(2027, 1, n + 1))
            for s in [self.ann, *self.mates]:
                Grade.objects.create(student=s, subject=self.maths, term=term, score=40 + n, assessment_type=self.cat)
        self.assertEqual(count(), before)


class ChartPermissionTests(ChartsTestCase):
    """Who may ask: the same answers as the existing performance endpoint."""

    def test_teacher_outside_their_classes_and_other_schools_get_not_found(self):
        self.assign(self.user_a, self.c7b, self.maths)
        teacher = self.authed_client(self.user_a)
        missing = self.chart(teacher, chart="subject_trends", scope="student", id=999999)
        for chart in CHARTS:
            outside = self.chart(teacher, chart=chart, scope="student", id=self.ann.id, term=self.t1.id)
            other_school = self.chart(teacher, chart=chart, scope="student", id=self.other.id, term=self.t1.id)
            for answer in (outside, other_school):
                self.assertEqual((answer.status_code, answer.data), (missing.status_code, missing.data))
        self.assertEqual(missing.status_code, 404)
        # Their own class works.
        for chart in CHARTS:
            self.assertEqual(self.chart(teacher, chart=chart, scope="student", id=self.cy.id, term=self.t1.id).status_code,
                             200)

    def test_another_schools_admin_gets_not_found(self):
        self.make_admin(self.user_b)
        other = self.authed_client(self.user_b)
        for chart in CHARTS:
            answer = self.chart(other, chart=chart, scope="student", id=self.ann.id, term=self.t1.id)
            self.assertEqual(answer.status_code, 404)

    def test_group_scopes_follow_the_existing_rules(self):
        self.assign(self.user_a, self.c7b, self.maths)
        teacher = self.authed_client(self.user_a)
        existing = self.admin.get("/api/analytics/performance/", {"scope": "class", "id": self.c7a.id})
        self.assertEqual(existing.status_code, 200)
        mine = teacher.get("/api/analytics/performance/", {"scope": "class", "id": self.c7a.id})
        answer = self.chart(teacher, chart="subject_trends", scope="class", id=self.c7a.id)
        self.assertEqual((answer.status_code, answer.data), (mine.status_code, mine.data))
        self.assertEqual(self.chart(teacher, chart="subject_trends", scope="school").status_code, 403)
        # Only subject trends have group scopes.
        self.assertEqual(self.chart(chart="ranks", scope="class", id=self.c7a.id).status_code, 400)
        self.assertEqual(self.chart(chart="nope", scope="student", id=self.ann.id).status_code, 400)

    def test_guardians_and_students_cannot_use_the_staff_endpoint(self):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username="g", email="g@alpha.test", password="pass1234")
        Guardian.objects.create(user=user, school=self.school_a)
        self.assertEqual(self.chart(self.authed_client(user), chart="marks", scope="student", id=self.ann.id).status_code,
                         403)


class GuardianChartTests(ChartsTestCase):
    """Parents: only their own children, and nothing they can't already see."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User

        user = User.objects.create_user(username="parent", email="parent@alpha.test", password="pass1234")
        guardian = Guardian.objects.create(user=user, school=self.school_a)
        guardian.students.add(self.ann)
        self.parent = self.authed_client(user)
        StudentReport.objects.create(student=self.ann, term=self.t1, progress_summary="Good.", report_comment="Well done.",
                                     status="finalized")
        StudentReport.objects.create(student=self.ann, term=self.t3, progress_summary="Good.", report_comment="Draft.",
                                     status="draft")

    def get(self, student, **params):
        return self.parent.get(f"/api/guardian-students/{student.id}/charts/", params)

    def test_subject_trends_only_for_finalized_terms_and_no_class_line(self):
        data = self.get(self.ann, chart="subject_trends").data
        self.assertEqual([t["name"] for t in data["terms"]], ["T1"])
        lines = {s["subject"]: [p["student"] for p in s["points"]] for s in data["subjects"]}
        self.assertEqual(lines, {"English": [50.0], "Maths": [74.0]})
        self.assertNotIn("class", str(data["subjects"]))
        self.assertNotIn("compare", data)

    def test_marks_without_assessment_types(self):
        Grade.objects.filter(student=self.ann, term=self.t2).update(recorded_at=utc(2026, 6, 1, 9, 0))
        data = self.get(self.ann, chart="marks", term=self.t2.id).data
        self.assertEqual(sorted(p["percent"] for p in data["points"]), [70.0, 80.0, 90.0])
        self.assertTrue(all("assessment_type" not in p for p in data["points"]))

    def test_no_assessment_type_chart_for_parents(self):
        self.assertEqual(self.get(self.ann, chart="assessment_types", term=self.t1.id).status_code, 404)

    def test_ranks_only_where_parents_already_see_them(self):
        # A British school's report card shows no positions, so parents get none here either.
        data = self.get(self.ann, chart="ranks").data
        self.assertEqual((data["ranked"], data["points"]), (False, []))
        # 8-4-4 report cards show stream and form positions on finalized reports: those, and only those.
        self.school_a.education_system, self.school_a.grading_scale = "844", "kcse"
        self.school_a.save()
        data = self.get(self.ann, chart="ranks").data
        self.assertTrue(data["ranked"])
        self.assertEqual([p["term"] for p in data["points"]], ["T1"])
        self.assertEqual(set(data["points"][0]), {"term", "term_id", "class", "year_group"})

    def test_someone_elses_child_is_not_found(self):
        for chart in [c for c in CHARTS if c != "assessment_types"]:
            self.assertEqual(self.get(self.cy, chart=chart, term=self.t1.id).status_code, 404)
            self.assertEqual(self.get(self.other, chart=chart, term=self.t1.id).status_code, 404)


@skipUnless(os.environ.get("HOUSEMASTER_SLOW_TESTS"), "slow: set HOUSEMASTER_SLOW_TESTS=1 (not run in CI)")
class SlowChartTests(ChartsTestCase):
    """The charts on a school the size of the demo (233,000 marks): queries stay the same and it stays quick."""

    def test_large_school(self):
        import time

        term_ids = [self.t1.id, self.t2.id, self.t3.id]
        subjects = [Subject.objects.create(school=self.school_a, name=f"Bulk {i}") for i in range(10)]
        students = Student.objects.bulk_create([Student(school=self.school_a, first_name=f"S{i}", last_name="Bulk",
                                                         school_class=self.c7a if i % 2 else self.c7b)
                                                for i in range(2600)])
        rows, kinds = [], [self.cat, self.exam]
        for s in students:
            for t in term_ids:
                for subject in subjects[:3]:
                    for k in range(10):
                        rows.append(Grade(student=s, subject=subject, term_id=t, assessment_type=kinds[k % 2],
                                          score=(s.id + k) % 100))
        Grade.objects.bulk_create(rows, batch_size=5000)
        self.assertGreaterEqual(Grade.objects.count(), 233000)
        for chart in CHARTS:
            with CaptureQueriesContext(connection) as ctx:
                started = time.monotonic()
                answer = self.chart(chart=chart, scope="student", id=students[0].id, term=self.t1.id)
                took = time.monotonic() - started
            self.assertEqual(answer.status_code, 200)
            self.assertLess(len(ctx.captured_queries), 25, chart)
            print(f"{chart}: {len(ctx.captured_queries)} queries, {took:.2f}s")
