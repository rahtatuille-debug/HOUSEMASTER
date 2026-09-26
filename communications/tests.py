from accounts.tests import SchoolScopedAPITestCase
from students.models import SchoolClass, YearGroup
from unittest.mock import patch

from .models import Announcement


class AnnouncementAPITests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client = self.authed_client(self.admin_a)
        self.year_a = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.class_a = SchoolClass.objects.create(year_group=self.year_a, name="7A")
        self.year_b = YearGroup.objects.create(school=self.school_b, name="Year 7")
        self.class_b = SchoolClass.objects.create(year_group=self.year_b, name="7A")

    def create_draft(self, **overrides):
        payload = {
            "title": "Staff meeting",
            "body": "The staff meeting starts at 3pm.",
            "audience": Announcement.Audience.ALL_STAFF,
        }
        payload.update(overrides)
        return self.admin_client.post("/api/announcements/", payload)

    def test_admin_can_create_and_publish_all_staff_announcement(self):
        self.admin_a.profile.display_name = "Jaden Opil"
        self.admin_a.profile.save(update_fields=["display_name"])
        response = self.create_draft()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], Announcement.Status.DRAFT)
        self.assertEqual(response.data["created_by"], self.admin_a.id)
        self.assertEqual(response.data["created_by_name"], "Jaden Opil")
        self.assertEqual(response.data["created_by_role"], "Admin")

        response = self.admin_client.post(f"/api/announcements/{response.data['id']}/publish/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Announcement.Status.PUBLISHED)
        self.assertIsNotNone(response.data["published_at"])

    def test_teacher_sees_only_published_all_staff_announcements(self):
        staff_notice = Announcement.objects.create(
            school=self.school_a,
            title="Staff only",
            body="Visible to staff.",
            audience=Announcement.Audience.ALL_STAFF,
            status=Announcement.Status.PUBLISHED,
            created_by=self.admin_a,
        )
        parent_notice = Announcement.objects.create(
            school=self.school_a,
            title="Parents only",
            body="Not yet visible to staff.",
            audience=Announcement.Audience.ALL_PARENTS,
            status=Announcement.Status.PUBLISHED,
            created_by=self.admin_a,
        )
        Announcement.objects.create(
            school=self.school_a,
            title="Draft",
            body="Not visible.",
            audience=Announcement.Audience.ALL_STAFF,
            status=Announcement.Status.DRAFT,
            created_by=self.admin_a,
        )

        response = self.client_a.get("/api/announcements/")
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data]
        self.assertIn(staff_notice.id, ids)
        self.assertNotIn(parent_notice.id, ids)
        self.assertEqual(len(ids), 1)

    def test_teacher_cannot_author_or_publish(self):
        response = self.client_a.post(
            "/api/announcements/",
            {"title": "No", "body": "No", "audience": Announcement.Audience.ALL_STAFF},
        )
        self.assertEqual(response.status_code, 403)

    def test_rejects_cross_school_class_target(self):
        response = self.create_draft(
            audience=Announcement.Audience.SCHOOL_CLASS, school_class=self.class_b.id
        )
        # Another school's record is rejected exactly like one that doesn't exist.
        self.assertEqual(response.status_code, 400)

    def test_rejects_target_mismatched_to_audience(self):
        response = self.create_draft(year_group=self.year_a.id)
        self.assertEqual(response.status_code, 400)

    def test_admin_cannot_read_another_schools_announcement(self):
        announcement_b = Announcement.objects.create(
            school=self.school_b,
            title="Beta update",
            body="Private",
            audience=Announcement.Audience.ALL_STAFF,
            status=Announcement.Status.PUBLISHED,
        )
        response = self.admin_client.get(f"/api/announcements/{announcement_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_published_announcement_cannot_be_edited_and_can_be_archived(self):
        created = self.create_draft()
        announcement_id = created.data["id"]
        self.admin_client.post(f"/api/announcements/{announcement_id}/publish/")

        response = self.admin_client.patch(
            f"/api/announcements/{announcement_id}/", {"title": "Changed"}
        )
        self.assertEqual(response.status_code, 400)

        response = self.admin_client.post(f"/api/announcements/{announcement_id}/archive/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Announcement.Status.ARCHIVED)

    @patch("communications.views.generate_announcement_text")
    def test_admin_can_generate_editable_text_without_creating_announcement(self, mock_generate):
        mock_generate.return_value = ("Closure notice", "School will close early on Friday.")
        response = self.admin_client.post(
            "/api/announcements/generate-text/",
            {"summary": "Tell staff that school closes early Friday", "audience": "all_staff"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["title"], "Closure notice")
        self.assertEqual(Announcement.objects.count(), 0)
        mock_generate.assert_called_once()

    @patch("communications.views.generate_announcement_text")
    def test_teacher_can_generate_text_but_cannot_create_announcement(self, mock_generate):
        mock_generate.return_value = ("Update", "A generated update.")
        response = self.client_a.post(
            "/api/announcements/generate-text/",
            {"summary": "Explain that the assembly starts later", "audience": "all_staff"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["body"], "A generated update.")

    def test_generate_text_returns_503_when_ai_is_not_configured(self):
        with patch(
            "communications.views.generate_announcement_text",
            side_effect=RuntimeError("GEMINI_API_KEY is not set."),
        ):
            response = self.admin_client.post(
                "/api/announcements/generate-text/",
                {"summary": "Let staff know the meeting is at three", "audience": "all_staff"},
            )
        self.assertEqual(response.status_code, 503)


class GenerateTextRateLimitTests(SchoolScopedAPITestCase):
    """Same approach as reporting.tests.GenerateActionRateLimitTests — see that class's docstring."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        self.admin_client_a = self.authed_client(self.admin_a)

    @patch("communications.views.generate_announcement_text")
    def test_exceeding_the_rate_returns_429(self, mock_generate):
        from rest_framework.throttling import ScopedRateThrottle

        mock_generate.return_value = ("Title", "Body")
        payload = {"summary": "School closes early on Friday."}

        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"ai_announcement_drafting": "2/min"}):
            first = self.admin_client_a.post("/api/announcements/generate-text/", payload)
            second = self.admin_client_a.post("/api/announcements/generate-text/", payload)
            third = self.admin_client_a.post("/api/announcements/generate-text/", payload)

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(third.status_code, 429)
        self.assertEqual(mock_generate.call_count, 2)

    def test_plain_announcement_list_is_not_throttled(self):
        from rest_framework.throttling import ScopedRateThrottle

        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"ai_announcement_drafting": "0/min"}):
            response = self.admin_client_a.get("/api/announcements/")
        self.assertEqual(response.status_code, 200)


class UrgentAlertTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User

        from gradebook.models import Subject
        from guardians.models import Guardian
        from students.models import SchoolClass, Student, YearGroup

        self.admin_client_a = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.year = year
        self.class_7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.class_7b = SchoolClass.objects.create(year_group=year, name="7B")
        self.assign(self.user_a, self.class_7a, Subject.objects.create(school=self.school_a, name="Maths"))

        def parent(email, school_class, school=None):
            school = school or self.school_a
            student = Student.objects.create(school=school, first_name="Kid", last_name=email[:2],
                                             school_class=school_class)
            user = User.objects.create_user(username=email, email=email, password="pass1234")
            guardian = Guardian.objects.create(user=user, school=school, display_name=email)
            guardian.students.add(student)
            return user

        self.p7a = parent("a@x.test", self.class_7a)
        self.p7b = parent("b@x.test", self.class_7b)
        self.p_other_school = parent("c@x.test", None, school=self.school_b)

    def send(self, client=None, **body):
        body = {"title": "School closed", "body": "Burst pipe, stay home.", "audience": "everyone", **body}
        return (client or self.admin_client_a).post("/api/alerts/", body)

    def recipients(self, alert_id):
        return {r["user"] for r in self.admin_client_a.get(f"/api/alerts/{alert_id}/recipients/").data}

    def test_admin_alerts_everyone_at_their_school_only(self):
        response = self.send()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.recipients(response.data["id"]),
                         {self.user_a.id, self.p7a.id, self.p7b.id})  # not the sender, not school B

    def test_audiences(self):
        staff = self.send(audience="all_staff").data["id"]
        self.assertEqual(self.recipients(staff), {self.user_a.id})
        parents = self.send(audience="all_parents").data["id"]
        self.assertEqual(self.recipients(parents), {self.p7a.id, self.p7b.id})
        klass = self.send(audience="school_class", school_class=self.class_7a.id).data["id"]
        self.assertEqual(self.recipients(klass), {self.p7a.id})
        year = self.send(audience="year_group", year_group=self.year.id).data["id"]
        self.assertEqual(self.recipients(year), {self.p7a.id, self.p7b.id})

    def test_teacher_can_only_alert_parents_of_own_class(self):
        ok = self.send(client=self.client_a, audience="school_class", school_class=self.class_7a.id)
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(self.send(client=self.client_a, audience="school_class",
                                   school_class=self.class_7b.id).status_code, 403)
        self.assertEqual(self.send(client=self.client_a, audience="everyone").status_code, 403)

    def test_parents_cannot_send_alerts(self):
        self.assertEqual(self.send(client=self.authed_client(self.p7a)).status_code, 403)

    def test_banner_shows_until_acknowledged(self):
        alert_id = self.send().data["id"]
        parent = self.authed_client(self.p7a)
        self.assertEqual([a["id"] for a in parent.get("/api/alerts/active/").data], [alert_id])
        self.assertEqual(parent.post(f"/api/alerts/{alert_id}/acknowledge/").status_code, 200)
        self.assertEqual(parent.get("/api/alerts/active/").data, [])
        seen = {r["user"]: r["acknowledged_at"] for r in
                self.admin_client_a.get(f"/api/alerts/{alert_id}/recipients/").data}
        self.assertIsNotNone(seen[self.p7a.id])
        self.assertIsNone(seen[self.p7b.id])
        listed = self.admin_client_a.get("/api/alerts/").data[0]
        self.assertEqual((listed["recipient_count"], listed["acknowledged_count"]), (3, 1))

    def test_ending_an_alert_removes_the_banner_for_everyone(self):
        alert_id = self.send().data["id"]
        self.assertEqual(self.admin_client_a.post(f"/api/alerts/{alert_id}/end/").status_code, 200)
        self.assertEqual(self.authed_client(self.p7b).get("/api/alerts/active/").data, [])

    def test_only_sender_or_admin_see_who_has_seen_it_or_end_it(self):
        alert_id = self.send().data["id"]
        parent = self.authed_client(self.p7a)
        self.assertEqual(parent.get(f"/api/alerts/{alert_id}/recipients/").status_code, 403)
        self.assertEqual(parent.post(f"/api/alerts/{alert_id}/end/").status_code, 403)
        self.assertEqual(self.client_a.get(f"/api/alerts/{alert_id}/recipients/").status_code, 403)
        # Recipients don't get the counts either.
        self.assertIsNone(parent.get(f"/api/alerts/{alert_id}/").data["recipient_count"])

    def test_people_only_see_alerts_sent_to_them(self):
        alert_id = self.send(audience="school_class", school_class=self.class_7b.id).data["id"]
        self.assertEqual(self.authed_client(self.p7a).get(f"/api/alerts/{alert_id}/").status_code, 404)
        self.assertEqual(self.client_a.get("/api/alerts/").data, [])

    def test_other_school_cannot_see_alerts(self):
        alert_id = self.send().data["id"]
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get("/api/alerts/").data, [])
        self.assertEqual(self.client_b.get(f"/api/alerts/{alert_id}/recipients/").status_code, 404)
        self.assertEqual(self.authed_client(self.p_other_school).get("/api/alerts/active/").data, [])

    def test_cannot_target_another_schools_class(self):
        from students.models import SchoolClass, YearGroup

        other_class = SchoolClass.objects.create(
            year_group=YearGroup.objects.create(school=self.school_b, name="Y"), name="Z"
        )
        response = self.send(audience="school_class", school_class=other_class.id)
        self.assertEqual(response.status_code, 400)

    def test_alert_with_no_recipients_is_refused(self):
        from students.models import SchoolClass

        empty = SchoolClass.objects.create(year_group=self.year, name="7C")
        self.assertEqual(self.send(audience="school_class", school_class=empty.id).status_code, 400)

    def test_sending_is_logged(self):
        from activity.models import ActivityLog

        self.send()
        self.assertTrue(ActivityLog.objects.filter(action="alert.sent").exists())
