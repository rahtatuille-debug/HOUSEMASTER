"""
E-1: the Students list is paged by the server when asked (?page= / ?page_size=), in a stable order, with search
and filters on the server. Without page parameters the whole list comes back as before, for the shipped frontend.
"""
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.tests import SchoolScopedAPITestCase
from support.models import SupportConcern
from students.models import SchoolClass, Student, YearGroup


class StudentPagingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.c7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.c7b = SchoolClass.objects.create(year_group=year, name="7B")
        for n in range(30):
            Student.objects.create(school=self.school_a, first_name=f"Kid{n:02d}", last_name=f"L{n % 7}",
                                   external_id=f"ADM{n:03d}", school_class=self.c7a if n % 2 else self.c7b)
        Student.objects.create(school=self.school_b, first_name="Other", last_name="School")

    def test_without_page_parameters_the_whole_list_comes_back(self):
        data = self.admin.get("/api/students/").data
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 30)

    def test_pages_are_stable_and_cover_everyone_once(self):
        seen = []
        page = self.admin.get("/api/students/", {"page_size": 8}).data
        self.assertEqual(page["count"], 30)
        while True:
            seen += [s["id"] for s in page["results"]]
            if not page["next"]:
                break
            page = self.admin.get(page["next"]).data
        self.assertEqual(len(seen), 30)
        self.assertEqual(len(set(seen)), 30)
        names = [(s.last_name, s.first_name) for s in Student.objects.filter(id__in=seen)]
        ordered = [(r["last_name"], r["first_name"]) for r in self.admin.get("/api/students/", {"page_size": 30}).data["results"]]
        self.assertEqual(ordered, sorted(names))

    def test_search_and_filters_run_on_the_server(self):
        self.assertEqual(self.admin.get("/api/students/", {"page_size": 50, "q": "kid07"}).data["count"], 1)
        self.assertEqual(self.admin.get("/api/students/", {"page_size": 50, "q": "ADM01"}).data["count"], 10)
        self.assertEqual(self.admin.get("/api/students/", {"page_size": 50, "school_class": self.c7a.id}).data["count"], 15)
        flagged = Student.objects.get(first_name="Kid03")
        SupportConcern.objects.create(school=self.school_a, student=flagged, status="open")
        data = self.admin.get("/api/students/", {"page_size": 50, "needs_support": 1}).data
        self.assertEqual([r["id"] for r in data["results"]], [flagged.id])

    def test_teachers_and_other_schools_page_only_what_they_may_see(self):
        from gradebook.models import Subject

        self.assign(self.user_a, self.c7a, Subject.objects.create(school=self.school_a, name="Maths"))
        teacher = self.authed_client(self.user_a)
        self.assertEqual(teacher.get("/api/students/", {"page_size": 50}).data["count"], 15)
        self.assertEqual(teacher.get("/api/students/", {"page_size": 50, "school_class": self.c7b.id}).data["count"], 0)
        self.make_admin(self.user_b)
        data = self.client_b.get("/api/students/", {"page_size": 50, "q": "Kid"}).data
        self.assertEqual(data["count"], 0)

    def test_a_page_costs_a_fixed_number_of_queries(self):
        with CaptureQueriesContext(connection) as small:
            self.admin.get("/api/students/", {"page_size": 5})
        with CaptureQueriesContext(connection) as large:
            self.admin.get("/api/students/", {"page_size": 30})
        self.assertEqual(len(small), len(large))
