"""
D-1: every position says what it is based on; a student with too few of the usual subjects isn't ranked
("not ranked: incomplete marks") instead of being placed on one or two marks; "most improved" says why a student
is left out. The same rule on the performance pages, the Excel export and the 8-4-4 report card.
"""
import io

import openpyxl

from gradebook.systems import term_summary
from students.models import School

from .test_rankings import RankingFixture


class RankBasisTests(RankingFixture):
    def setUp(self):
        super().setUp()
        # The owner chose to rank everyone by default (0%); these tests use a school that sets 75%.
        School.objects.filter(pk=self.school_a.pk).update(ranking_min_share=75)
        self.school_a.refresh_from_db()
        everything = {self.maths: 70, self.english: 70, self.chem: 70}
        self.ann = self.pupil("Ann", self.east, {**everything, self.maths: 90}, everything)
        self.ben = self.pupil("Ben", self.east, everything, everything)
        self.cat = self.pupil("Cat", self.east, {self.maths: 99}, everything)  # one mark so far this term
        self.dan = self.pupil("Dan", self.east, {**everything, self.chem: 50})  # new: no marks last term
        self.eve = self.pupil("Eve", self.east, everything, {self.maths: 70})  # one subject last term

    def test_a_student_with_incomplete_marks_is_not_ranked_and_says_so(self):
        rows = self.rows(scope="class", id=self.east.id)
        self.assertIsNone(rows["Cat"]["position"])  # 99% on one subject would have put her first
        self.assertEqual(rows["Cat"]["not_ranked"], "incomplete_marks")
        self.assertEqual(rows["Cat"]["not_ranked_label"], "Not ranked: incomplete marks (1 of 3 subjects)")
        self.assertEqual({n: (r["position"], r["of"]) for n, r in rows.items() if n != "Cat"},
                         {"Ann": (1, 4), "Ben": (2, 4), "Eve": (2, 4), "Dan": (4, 4)})

    def test_each_position_shows_what_it_counts(self):
        rows = self.rows(scope="class", id=self.east.id)
        self.assertEqual(rows["Ann"]["basis"], {"subjects": 3, "marks": 3, "usual_subjects": 3})
        self.assertEqual(rows["Cat"]["basis"], {"subjects": 1, "marks": 1, "usual_subjects": 3})

    def test_by_default_everyone_with_a_mark_is_ranked(self):
        School.objects.filter(pk=self.school_a.pk).update(ranking_min_share=School._meta.get_field("ranking_min_share")
                                                          .default)
        rows = self.rows(scope="class", id=self.east.id)
        self.assertEqual(rows["Cat"]["position"], 1)  # ranked on her one mark, and the basis says so
        self.assertEqual(rows["Cat"]["basis"]["subjects"], 1)
        self.assertEqual(rows["Cat"]["not_ranked"], None)

    def test_the_school_sets_the_share_and_can_turn_it_off(self):
        School.objects.filter(pk=self.school_a.pk).update(ranking_min_share=0)
        self.assertEqual(self.rows(scope="class", id=self.east.id)["Cat"]["position"], 1)
        response = self.admin.patch(f"/api/schools/{self.school_a.id}/", {"ranking_min_share": 50}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_most_improved_says_why_a_student_is_left_out(self):
        rows = self.rows(scope="class", id=self.east.id)
        self.assertEqual(rows["Dan"]["improvement_note"], "Not in most improved: no marks last term")
        self.assertEqual(rows["Cat"]["improvement_note"], "Not in most improved: incomplete marks this term")
        self.assertEqual(rows["Eve"]["improvement_note"], "Not in most improved: incomplete marks last term")
        self.assertIsNone(rows["Eve"]["improvement_position"])
        self.assertEqual(rows["Ann"]["improvement_note"], "")
        self.assertEqual({rows["Ann"]["improvement_position"], rows["Ben"]["improvement_position"]}, {1, 2})

    def test_the_export_uses_the_same_rule(self):
        response = self.admin.get("/api/exports/grades/", {"school_class": self.east.id, "term": self.t2.id})
        sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
        header = [c.value for c in sheet[1]]
        by_name = {row[header.index("First name")]: row[header.index("Position")]
                   for row in sheet.iter_rows(min_row=2, values_only=True)}
        self.assertEqual(by_name, {"Ann": 1, "Ben": 2, "Eve": 2, "Dan": 4, "Cat": "Not ranked: incomplete marks"})


class KcseRankBasisTests(RankBasisTests):
    system, scale = "844", "kcse"

    def test_the_report_card_uses_the_same_rule(self):
        self.assertIsNone(term_summary(self.cat, self.t2)["positions"])
        stream = term_summary(self.ben, self.t2)["positions"]["stream"]
        self.assertEqual(stream["of"], 4)  # Cat isn't counted
        rows = self.rows(scope="class", id=self.east.id)
        for student in (self.ann, self.ben, self.dan, self.eve):
            self.assertEqual(rows[student.first_name]["position"],
                             term_summary(student, self.t2)["positions"]["stream"]["position"])
