"""
F-09: text that looks like a spreadsheet formula must be written as text in
every workbook the app produces, so opening an export can never run it.
"""
import io

import openpyxl

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Subject
from students.models import SchoolClass, Student, YearGroup

HOSTILE = ['=HYPERLINK("http://x","y")', "-2+3", "+1", "@SUM(A1)", "\tTab", "\rCR"]


def cells(content):
    wb = openpyxl.load_workbook(io.BytesIO(content))
    return [cell for ws in wb.worksheets for row in ws.iter_rows() for cell in row if cell.value is not None]


class FormulaInjectionTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.make_admin(self.user_a)
        year = YearGroup.objects.create(school=self.school_a, name="=YEAR()")
        self.klass = SchoolClass.objects.create(year_group=year, name="=CLASS()")
        self.students = [
            Student.objects.create(school=self.school_a, first_name=value, last_name="Pupil", school_class=self.klass,
                                   house="+House")
            for value in HOSTILE
        ]
        self.normal = Student.objects.create(school=self.school_a, first_name="Amina", last_name="Otieno",
                                             school_class=self.klass)
        Subject.objects.create(school=self.school_a, name="=SUBJECT()")

    def assert_all_text(self, content, expected_values):
        found = {cell.value: cell.data_type for cell in cells(content) if isinstance(cell.value, str)}
        for value in expected_values:
            value = value.replace("\r", "\n")  # XML stores a lone carriage return as a newline
            self.assertIn(value, found, f"{value!r} missing from the workbook")
            self.assertEqual(found[value], "s", f"{value!r} was written as {found[value]!r}, not as text")

    def test_class_list_export(self):
        response = self.client_a.get("/api/exports/class-list/", {"school_class": self.klass.id})
        self.assertEqual(response.status_code, 200)
        self.assert_all_text(response.content, HOSTILE + ["+House"])

    def test_normal_values_are_unchanged(self):
        response = self.client_a.get("/api/exports/class-list/", {"school_class": self.klass.id})
        values = {cell.value: cell.data_type for cell in cells(response.content)}
        self.assertEqual(values["Amina"], "s")
        self.assertEqual(values["Otieno"], "s")

    def test_family_data_export(self):
        response = self.client_a.get(f"/api/students/{self.students[0].id}/data-export/")
        self.assertEqual(response.status_code, 200)
        self.assert_all_text(response.content, [HOSTILE[0], "+House", "=CLASS()", "=YEAR()"])

    def test_import_template_lists_class_names_as_text(self):
        response = self.client_a.get("/api/import/template/")
        self.assertEqual(response.status_code, 200)
        self.assert_all_text(response.content, ["=CLASS()", "=YEAR()"])

    def test_staff_template_lists_class_and_subject_names_as_text(self):
        response = self.client_a.get("/api/import/staff-template/")
        self.assertEqual(response.status_code, 200)
        self.assert_all_text(response.content, ["=SUBJECT()"])
