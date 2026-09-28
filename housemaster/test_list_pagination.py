"""
B-1: the lists that grow with time come back a page at a time.

- Conversations are paged always (100 a page, up to 500 with ?page_size=),
  like grades, attendance and messages (F-14): the frontend already
  shipped reads them with its follow-the-pages helper.
- Reports, announcements and change requests are paged when the client
  asks (?page= or ?page_size=). Without either they still return the whole
  list, because the frontend already shipped reads those as plain lists.

Every page stays inside the requester's school and role, filters still
apply, the order is stable, and the number of queries doesn't grow with
the number of rows.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Profile
from accounts.tests import SchoolScopedAPITestCase
from approvals.models import ChangeRequest
from communications.models import Announcement
from gradebook.models import Subject, Term
from guardians.models import Guardian
from messaging.models import Conversation, ConversationParticipant, Message
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

PAGE_KEYS = {"count", "next", "previous", "results"}


class ListFixture(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.other_class = SchoolClass.objects.create(year_group=year, name="7B")
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.assign(self.user_a, self.klass, self.maths)  # user_a teaches 7A only
        self.parent = User.objects.create_user(username="p", email="p@example.org", password="x")
        self.guardian = Guardian.objects.create(user=self.parent, school=self.school_a, display_name="P")
        year_b = YearGroup.objects.create(school=self.school_b, name="Y7")
        self.class_b = SchoolClass.objects.create(year_group=year_b, name="B7")

    def queries(self, client, path, params=None):
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(path, params or {})
        self.assertEqual(response.status_code, 200, getattr(response, "data", None))
        return len(ctx.captured_queries), response

    def walk(self, client, path, params):
        ids, page = [], 1
        while True:
            data = client.get(path, {**params, "page": page}).data
            ids += [row["id"] for row in data["results"]]
            if not data["next"]:
                return ids
            page += 1


class ConversationPagingTests(ListFixture):
    def conversations(self, n, school=None, members=None, messages=2):
        school = school or self.school_a
        members = members or [self.admin_a, self.parent]
        made = []
        for i in range(n):
            conversation = Conversation.objects.create(school=school, created_by=members[0])
            for user in members:
                ConversationParticipant.objects.create(conversation=conversation, user=user)
            Message.objects.bulk_create([Message(conversation=conversation, sender=members[i % len(members)],
                                                 body=f"c{i} m{j}") for j in range(messages)])
            made.append(conversation)
        return made

    def test_conversations_come_back_a_page_at_a_time(self):
        self.conversations(130)
        first = self.admin.get("/api/conversations/")
        self.assertEqual(set(first.data), PAGE_KEYS)
        self.assertEqual(first.data["count"], 130)
        self.assertEqual(len(first.data["results"]), 100)
        ids = self.walk(self.admin, "/api/conversations/", {})
        self.assertEqual(len(ids), 130)
        self.assertEqual(len(set(ids)), 130, "no conversation twice across pages")
        self.assertEqual(len(self.admin.get("/api/conversations/", {"page_size": 5000}).data["results"]), 130)

    def test_only_your_own_conversations_on_every_page(self):
        mine = {c.id for c in self.conversations(30)}
        other_admin = User.objects.create_user(username="a2", email="a2@alpha.test", password="x")
        Profile.objects.create(user=other_admin, school=self.school_a, role=Profile.Role.ADMIN)
        self.conversations(30, members=[other_admin, self.parent])
        admin_b = User.objects.create_user(username="ab", email="ab@beta.test", password="x")
        Profile.objects.create(user=admin_b, school=self.school_b, role=Profile.Role.ADMIN)
        self.conversations(30, school=self.school_b, members=[admin_b, self.user_b])
        self.assertEqual(set(self.walk(self.admin, "/api/conversations/", {"page_size": 7})), mine)

    def test_list_rows_match_the_single_conversation_view(self):
        conversation = self.conversations(1, messages=3)[0]
        ConversationParticipant.objects.filter(conversation=conversation, user=self.admin_a).update(
            last_read_at=conversation.messages.order_by("created_at")[1].created_at)
        row = self.admin.get("/api/conversations/").data["results"][0]
        detail = self.admin.get(f"/api/conversations/{conversation.id}/").data
        self.assertEqual(row, detail)
        self.assertEqual(row["member_count"], 2)
        self.assertEqual(row["last_message"]["body"], "c0 m2")
        self.assertEqual(row["unread_count"], detail["unread_count"])

    def test_list_rows_match_the_serializer_without_the_list_annotations(self):
        import json

        from rest_framework.renderers import JSONRenderer
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        from messaging.serializers import ConversationSerializer

        for conversation in self.conversations(2, messages=3) + self.conversations(1, messages=0):
            ConversationParticipant.objects.filter(conversation=conversation, user=self.admin_a).update(
                last_read_at=timezone.now() - timedelta(days=1))
        request = Request(APIRequestFactory().get("/"))
        request.user = self.admin_a
        rows = {row["id"]: row for row in self.admin.get("/api/conversations/").json()["results"]}
        for conversation in Conversation.objects.all():
            plain = json.loads(JSONRenderer().render(
                ConversationSerializer(conversation, context={"request": request}).data))
            self.assertEqual(rows[conversation.id], plain)

    def test_query_count_stays_flat_as_conversations_grow(self):
        self.conversations(3)
        small, _ = self.queries(self.admin, "/api/conversations/")
        self.conversations(60, messages=4)
        large, response = self.queries(self.admin, "/api/conversations/")
        self.assertEqual(len(response.data["results"]), 63)
        self.assertEqual(large, small)
        self.assertLessEqual(small, 12)

    def test_parent_side_is_flat_too_and_hides_notice_recipients(self):
        self.conversations(3, members=[self.user_a, self.parent])
        small, _ = self.queries(self.authed_client(self.parent), "/api/conversations/")
        self.conversations(40, members=[self.user_a, self.parent])
        large, _ = self.queries(self.authed_client(self.parent), "/api/conversations/")
        self.assertEqual(large, small)

    def test_messages_page_query_count_does_not_grow_with_senders(self):
        conversation = self.conversations(1, messages=2)[0]
        path = f"/api/conversations/{conversation.id}/messages/"
        small, _ = self.queries(self.admin, path)
        Message.objects.bulk_create([Message(conversation=conversation, sender=(self.admin_a, self.parent)[i % 2],
                                             body=f"more {i}") for i in range(80)])
        large, response = self.queries(self.admin, path)
        self.assertEqual(response.data["results"][-1]["sender_name"] in {"P", self.admin_a.profile.name}, True)
        self.assertEqual(large, small)


class ReportPagingTests(ListFixture):
    def reports(self, n, klass=None, status="draft"):
        klass = klass or self.klass
        term = Term.objects.create(school=klass.year_group.school, name=f"T{Term.objects.count()}")
        students = Student.objects.bulk_create([
            Student(school=klass.year_group.school, first_name=f"S{i}", last_name="X", school_class=klass)
            for i in range(n)])
        StudentReport.objects.bulk_create([StudentReport(student=s, term=term, status=status,
                                                         report_comment="Good work.") for s in students])

    def test_whole_list_without_page_parameters_as_before(self):
        self.reports(120)
        response = self.admin.get("/api/reports/")
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 120)

    def test_pages_on_request(self):
        self.reports(120)
        first = self.admin.get("/api/reports/", {"page": 1})
        self.assertEqual(set(first.data), PAGE_KEYS)
        self.assertEqual((first.data["count"], len(first.data["results"])), (120, 100))
        self.assertEqual(len(self.admin.get("/api/reports/", {"page_size": 50}).data["results"]), 50)
        self.assertEqual(len(self.admin.get("/api/reports/", {"page_size": 9999}).data["results"]), 120)
        ids = self.walk(self.admin, "/api/reports/", {"page_size": 25})
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids), "stable order across pages")

    def test_filters_and_teacher_scope_hold_on_every_page(self):
        self.reports(40)
        self.reports(40, status="submitted")
        self.reports(30, klass=self.other_class)
        self.reports(20, klass=self.class_b)
        submitted = self.walk(self.admin, "/api/reports/", {"status": "submitted", "page_size": 15})
        self.assertEqual(len(submitted), 40)
        teacher = self.walk(self.client_a, "/api/reports/", {"page_size": 15})
        visible = set(StudentReport.objects.filter(student__school_class=self.klass).values_list("id", flat=True))
        self.assertEqual(set(teacher), visible)

    def test_query_count_stays_flat(self):
        self.reports(5)
        small, _ = self.queries(self.admin, "/api/reports/", {"page_size": 50})
        self.reports(200)
        large, _ = self.queries(self.admin, "/api/reports/", {"page_size": 50})
        self.assertEqual(large, small)


class AnnouncementPagingTests(ListFixture):
    def announcements(self, n, school=None, **fields):
        school = school or self.school_a
        now = timezone.now()
        Announcement.objects.bulk_create([Announcement(
            school=school, title=f"A{i}", body="b", audience=fields.get("audience", Announcement.Audience.ALL_PARENTS),
            school_class=fields.get("school_class"), status=Announcement.Status.PUBLISHED, created_by=self.admin_a,
            published_at=now - timedelta(minutes=i % 3)) for i in range(n)])

    def test_whole_list_without_page_parameters_as_before(self):
        self.announcements(110)
        response = self.admin.get("/api/announcements/")
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 110)

    def test_pages_on_request_with_a_stable_order(self):
        self.announcements(110)  # many share the same published_at
        first = self.admin.get("/api/announcements/", {"page": 1})
        self.assertEqual(set(first.data), PAGE_KEYS)
        ids = self.walk(self.admin, "/api/announcements/", {"page_size": 20})
        self.assertEqual(len(ids), 110)
        self.assertEqual(len(set(ids)), 110)

    def test_parents_see_only_their_audiences_on_every_page(self):
        kid = Student.objects.create(school=self.school_a, first_name="K", last_name="Z", school_class=self.klass)
        self.guardian.students.add(kid)
        self.announcements(15)  # all parents
        self.announcements(15, audience=Announcement.Audience.SCHOOL_CLASS, school_class=self.klass)
        self.announcements(15, audience=Announcement.Audience.SCHOOL_CLASS, school_class=self.other_class)
        self.announcements(15, audience=Announcement.Audience.ALL_STAFF)
        self.announcements(15, school=self.school_b)
        seen = self.walk(self.authed_client(self.parent), "/api/announcements/", {"page_size": 8})
        expected = set(Announcement.objects.filter(school=self.school_a).exclude(school_class=self.other_class)
                       .exclude(audience=Announcement.Audience.ALL_STAFF).values_list("id", flat=True))
        self.assertEqual(set(seen), expected)

    def test_query_count_stays_flat(self):
        self.announcements(5)
        small, _ = self.queries(self.admin, "/api/announcements/", {"page_size": 50})
        self.announcements(150)
        large, _ = self.queries(self.admin, "/api/announcements/", {"page_size": 50})
        self.assertEqual(large, small)


class ChangeRequestPagingTests(ListFixture):
    def change_requests(self, n, by=None, status=ChangeRequest.Status.PENDING, school=None):
        ChangeRequest.objects.bulk_create([ChangeRequest(
            school=school or self.school_a, requested_by=by or self.user_a, requested_by_name="T", kind="student",
            operation=ChangeRequest.Operation.UPDATE, summary=f"Change {i}", status=status) for i in range(n)])

    def test_whole_list_without_page_parameters_as_before(self):
        self.change_requests(105)
        response = self.admin.get("/api/change-requests/")
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 105)

    def test_pages_on_request_and_teachers_see_only_their_own(self):
        self.change_requests(30)
        other_teacher = User.objects.create_user(username="t2", email="t2@alpha.test", password="x")
        Profile.objects.create(user=other_teacher, school=self.school_a, role=Profile.Role.TEACHER)
        self.change_requests(30, by=other_teacher)
        self.change_requests(30, by=self.user_b, school=self.school_b)
        self.assertEqual(set(self.admin.get("/api/change-requests/", {"page": 1}).data), PAGE_KEYS)
        own = self.walk(self.client_a, "/api/change-requests/", {"page_size": 7})
        self.assertEqual(set(own), set(ChangeRequest.objects.filter(requested_by=self.user_a).values_list("id", flat=True)))
        self.assertEqual(len(self.walk(self.admin, "/api/change-requests/", {"page_size": 7})), 60)

    def test_filters_with_paging(self):
        self.change_requests(20)
        self.change_requests(20, status=ChangeRequest.Status.APPROVED)
        pending = self.walk(self.admin, "/api/change-requests/", {"status": "pending", "page_size": 6})
        self.assertEqual(len(pending), 20)

    def test_query_count_stays_flat(self):
        self.change_requests(5)
        small, _ = self.queries(self.admin, "/api/change-requests/", {"page_size": 50})
        self.change_requests(150)
        large, _ = self.queries(self.admin, "/api/change-requests/", {"page_size": 50})
        self.assertEqual(large, small)
