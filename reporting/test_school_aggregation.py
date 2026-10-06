"""
E-2: whole-school analytics reads marks already averaged by the database (one row per student, term, subject and
assessment type) and works each student's results out once. The results must be exactly what averaging every mark
in Python gives, weights and all.
"""
import random
from collections import defaultdict
from fractions import Fraction
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import tag
from django.test.utils import CaptureQueriesContext

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import AssessmentType, Grade, Subject, Term
from reporting import analytics
from students.models import SchoolClass, Student, YearGroup


class PerMarkGrades(analytics.SchoolGrades):
    """Every mark brought into Python one by one and each assessment type averaged exactly: the reference the
    database-aggregated loader must match."""

    def __init__(self, school):
        super().__init__(school)
        self.marks = defaultdict(lambda: defaultdict(list))
        self.mark_counts = defaultdict(int)
        self._averages, self._subjects, self._years = {}, {}, None
        names = dict(Subject.objects.filter(school=school).values_list("id", "name"))
        per_type = defaultdict(list)
        for g in Grade.objects.filter(student_id__in=self.students).order_by("?"):  # any order
            per_type[(g.student_id, g.term_id, g.subject_id, g.assessment_type_id)].append(
                Fraction(g.score) * 100 / Fraction(g.max_score))
        for (student_id, term_id, subject_id, type_id), percents in per_type.items():
            self.marks[(student_id, term_id)][names[subject_id]].append((float(sum(percents) / len(percents)), type_id))
            self.mark_counts[(student_id, term_id)] += len(percents)


class AggregationFixture(SchoolScopedAPITestCase):
    students_per_class, marks_per_type = 6, 3

    def setUp(self):
        super().setUp()
        rng = random.Random(7)
        self.year = YearGroup.objects.create(school=self.school_a, name="Year 9")
        classes = [SchoolClass.objects.create(year_group=self.year, name=f"9{c}") for c in "ABC"]
        self.terms = [Term.objects.create(school=self.school_a, name=f"T{n}", start_date=date(2026, n * 3, 1))
                      for n in (1, 2)]
        types = [AssessmentType.objects.create(school=self.school_a, name="Exam", weight=Decimal("70")),
                 AssessmentType.objects.create(school=self.school_a, name="CAT", weight=Decimal("30")), None]
        subjects = [Subject.objects.create(school=self.school_a, name=n) for n in ("Maths", "English", "Biology")]
        grades = []
        for klass in classes:
            for n in range(self.students_per_class):
                s = Student.objects.create(school=self.school_a, first_name=f"S{klass.name}{n}", last_name="K",
                                           school_class=klass)
                for term in self.terms:
                    for subject in subjects:
                        for kind in types:
                            for _ in range(rng.randint(0, self.marks_per_type)):
                                out_of = rng.choice([20, 30, 50, 100])
                                grades.append(Grade(student=s, subject=subject, term=term, assessment_type=kind,
                                                    max_score=out_of,
                                                    score=Decimal(str(round(rng.uniform(0, out_of), 2)))))
        Grade.objects.bulk_create(grades)
        self.mark_total = len(grades)

    def both(self):
        return analytics.SchoolGrades(self.school_a), PerMarkGrades(self.school_a)


class SchoolAggregationTests(AggregationFixture):
    def test_every_student_and_group_result_is_the_same_as_averaging_every_mark(self):
        new, old = self.both()
        for term in self.terms:
            for sid in old.students:
                self.assertEqual(new.student_average(sid, term.id), old.student_average(sid, term.id))
                self.assertEqual(new.subject_percents(sid, term.id).keys(), old.subject_percents(sid, term.id).keys())
                for subject, value in old.subject_percents(sid, term.id).items():
                    self.assertAlmostEqual(new.subject_percents(sid, term.id)[subject], value, places=9)
        term = new.term(None)
        self.assertEqual(analytics.school_analytics(new, self.school_a, term),
                         analytics.school_analytics(old, self.school_a, term))

    def test_mark_counts_count_every_mark(self):
        new, old = self.both()
        self.assertEqual(sum(new.mark_counts.values()), self.mark_total)
        self.assertEqual(dict(new.mark_counts), dict(old.mark_counts))

    def test_fewer_rows_come_from_the_database(self):
        new, _old = self.both()
        grouped = sum(len(per) for subjects in new.marks.values() for per in subjects.values())
        self.assertLess(grouped, self.mark_total)


@tag("slow")
class SchoolAggregationScaleTests(AggregationFixture):
    """A bigger school: the same results, and a fixed number of queries however many marks there are."""

    students_per_class, marks_per_type = 60, 4

    def test_a_bigger_school_gives_the_same_results_in_a_fixed_number_of_queries(self):
        with CaptureQueriesContext(connection) as queries:
            new = analytics.SchoolGrades(self.school_a)
            result = analytics.school_analytics(new, self.school_a, new.term(None))
        self.assertLessEqual(len(queries), 15)
        old = PerMarkGrades(self.school_a)
        self.assertEqual(result, analytics.school_analytics(old, self.school_a, old.term(None)))
