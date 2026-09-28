"""
F-14: lists that grow with time (grades, attendance, conversation
messages) come back a page at a time, with filters still working, other
schools still invisible on every page, and the same small number of
queries however much data there is.
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.tests import SchoolScopedAPITestCase
from attendance.models import AttendanceRecord
from gradebook.models import Grade, Subject, Term
from guardians.models import Guardian
from messaging.models import Conversation, ConversationParticipant, Message
from students.models import SchoolClass, Student, YearGroup


class PaginationTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.make_admin(self.user_a, self.user_b)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.other_term = Term.objects.create(school=self.school_a, name="Term 2")
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")

    def make_grades(self, students, per_student=5, term=None):
        Grade.objects.bulk_create([
            Grade(student=s, subject=self.maths, term=term or self.term, score=50 + i, max_score=100)
            for s in students for i in range(per_student)
        ])

    def make_students(self, n, school=None, klass=None):
        school = school or self.school_a
        Student.objects.bulk_create([
            Student(school=school, first_name=f"S{i}", last_name="X", school_class=klass or self.klass) for i in range(n)
        ])
        return list(Student.objects.filter(school=school).order_by("id"))

    def test_grades_come_back_a_page_at_a_time(self):
        self.make_grades(self.make_students(30))  # 150 grades
        response = self.client_a.get("/api/grades/")
        self.assertEqual(set(response.data), {"count", "next", "previous", "results"})
        self.assertEqual(response.data["count"], 150)
        self.assertEqual(len(response.data["results"]), 100)
        last = self.client_a.get("/api/grades/", {"page": 2})
        self.assertEqual(len(last.data["results"]), 50)
        self.assertIsNone(last.data["next"])
        ids = [g["id"] for g in response.data["results"] + last.data["results"]]
        self.assertEqual(ids, sorted(ids), "order must be stable across pages")
        self.assertEqual(len(set(ids)), 150)

    def test_page_size_can_be_raised_up_to_500_only(self):
        self.make_grades(self.make_students(120))  # 600 grades
        self.assertEqual(len(self.client_a.get("/api/grades/", {"page_size": 250}).data["results"]), 250)
        self.assertEqual(len(self.client_a.get("/api/grades/", {"page_size": 5000}).data["results"]), 500)

    def test_filters_work_with_paging(self):
        students = self.make_students(30)
        self.make_grades(students)
        self.make_grades(students, per_student=1, term=self.other_term)
        response = self.client_a.get("/api/grades/", {"term": self.other_term.id, "page_size": 20, "page": 2})
        self.assertEqual(response.data["count"], 30)
        self.assertEqual(len(response.data["results"]), 10)
        self.assertTrue(all(g["term"] == self.other_term.id for g in response.data["results"]))

    def test_other_schools_stay_invisible_on_every_page(self):
        self.make_grades(self.make_students(30))
        year_b = YearGroup.objects.create(school=self.school_b, name="Y")
        klass_b = SchoolClass.objects.create(year_group=year_b, name="B")
        term_b = Term.objects.create(school=self.school_b, name="T")
        subject_b = Subject.objects.create(school=self.school_b, name="Maths")
        students_b = self.make_students(30, school=self.school_b, klass=klass_b)
        Grade.objects.bulk_create([Grade(student=s, subject=subject_b, term=term_b, score=1, max_score=10)
                                   for s in students_b for _ in range(5)])
        own_ids = set(Grade.objects.filter(student__school=self.school_a).values_list("id", flat=True))
        seen = set()
        page = 1
        while True:
            response = self.client_a.get("/api/grades/", {"page": page, "page_size": 40})
            seen |= {g["id"] for g in response.data["results"]}
            if not response.data["next"]:
                break
            page += 1
        self.assertEqual(seen, own_ids)
        self.assertEqual(self.client_a.get("/api/grades/", {"page": 99}).status_code, 404)

    def test_query_count_stays_flat_as_data_grows(self):
        def queries_for(path, params):
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client_a.get(path, params).status_code, 200)
            return len(ctx.captured_queries)

        students = self.make_students(20)
        self.make_grades(students)
        small = queries_for("/api/grades/", {})
        more = self.make_students(1200)
        self.make_grades(more)  # 6,000+ grades
        self.assertEqual(queries_for("/api/grades/", {}), small)
        self.assertEqual(queries_for("/api/grades/", {"page": 30}), small)
        self.assertLessEqual(small, 8)

    def test_attendance_comes_back_a_page_at_a_time(self):
        student = self.make_students(1)[0]
        AttendanceRecord.objects.bulk_create([
            AttendanceRecord(student=student, date=date(2026, 1, 1) + timedelta(days=i), status="present")
            for i in range(130)
        ])
        response = self.client_a.get("/api/attendance/", {"student": student.id})
        self.assertEqual(response.data["count"], 130)
        self.assertEqual(len(response.data["results"]), 100)

    def test_conversation_messages_come_back_a_page_at_a_time_oldest_first(self):
        parent = User.objects.create_user(username="p", email="p@example.org", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="P")
        conversation = Conversation.objects.create(school=self.school_a, created_by=self.user_a)
        for user in (self.user_a, parent):
            ConversationParticipant.objects.create(conversation=conversation, user=user)
        Message.objects.bulk_create([Message(conversation=conversation, sender=self.user_a, body=f"m{i}")
                                     for i in range(120)])
        response = self.client_a.get(f"/api/conversations/{conversation.id}/messages/")
        self.assertEqual(response.data["count"], 120)
        bodies = [m["body"] for m in response.data["results"]]
        self.assertEqual(bodies[:2], ["m0", "m1"])
        second = self.client_a.get(f"/api/conversations/{conversation.id}/messages/", {"page": 2})
        self.assertEqual([m["body"] for m in second.data["results"]][-1], "m119")

    def test_activity_log_keeps_its_own_page_size(self):
        from activity.services import log_activity

        for i in range(60):
            log_activity(school=self.school_a, actor=self.user_a, action="x.y", summary=f"e{i}")
        response = self.client_a.get("/api/activity/")
        self.assertEqual(len(response.data["results"]), 50)
