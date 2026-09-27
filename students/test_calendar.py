"""Year group order, graduating years, quarters and a school's own words."""
from datetime import date

from accounts.tests import SchoolScopedAPITestCase

from .models import SchoolClass, Student, YearGroup


class CalendarTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)

    def finish(self, **overrides):
        body = {"name": "Alpha", "education_system": "american", "grading_scale": "american", "report_tone": "formal",
                "year_groups": [{"name": "Grade 11", "classes": ["11A"]}, {"name": "Grade 12", "classes": ["12A"]}],
                "subjects": ["English"],
                "terms": [{"name": "Quarter 1", "start_date": "2026-08-25", "end_date": "2026-10-24"}]}
        body.update(overrides)
        return self.admin.post("/api/setup/finish/", body, format="json")

    def test_setup_orders_year_groups_and_marks_the_last_as_final(self):
        self.assertEqual(self.finish().status_code, 200)
        groups = list(YearGroup.objects.filter(school=self.school_a).order_by("order").values_list("name", "order", "is_final"))
        self.assertEqual(groups, [("Grade 11", 0, False), ("Grade 12", 1, True)])

    def test_american_schools_can_use_quarters(self):
        american = next(s for s in self.admin.get("/api/setup/").data["systems"] if s["key"] == "american")
        self.assertEqual([t["name"][:9] for t in american["alternative_terms"]["terms"]],
                         ["Quarter 1", "Quarter 2", "Quarter 3", "Quarter 4"])
        self.finish(vocab_overrides={"term": "Quarter", "terms": "Quarters"})
        words = self.admin.get("/api/me/").data["school"]["vocab"]
        self.assertEqual((words["term"], words["terms"], words["class"]), ("Quarter", "Quarters", "Homeroom"))

    def test_school_words_are_checked(self):
        url = f"/api/schools/{self.school_a.id}/"
        self.assertEqual(self.admin.patch(url, {"vocab_overrides": {"class": "Stream"}}, format="json").status_code, 200)
        self.assertEqual(self.admin.get("/api/me/").data["school"]["vocab"]["class"], "Stream")
        self.assertEqual(self.admin.patch(url, {"vocab_overrides": {"password": "x"}}, format="json").status_code, 400)

    def test_final_year_students_graduate_at_year_end(self):
        self.finish()
        c11 = SchoolClass.objects.get(name="11A")
        c12 = SchoolClass.objects.get(name="12A")
        senior = Student.objects.create(school=self.school_a, school_class=c12, first_name="Sam", last_name="S")
        junior = Student.objects.create(school=self.school_a, school_class=c11, first_name="Jo", last_name="J")
        moves = [{"from_class": c12.id, "to_class": None}, {"from_class": c11.id, "to_class": c12.id}]
        preview = self.admin.post("/api/promotion/", {"moves": moves}, format="json").data
        self.assertIn("Graduating", [m["to_name"] for m in preview["moves"]])
        self.admin.post("/api/promotion/", {"moves": moves, "commit": True}, format="json")
        senior.refresh_from_db()
        junior.refresh_from_db()
        self.assertEqual((senior.is_active, senior.graduated_on), (False, date.today()))
        self.assertEqual((junior.school_class, junior.graduated_on), (c12, None))
