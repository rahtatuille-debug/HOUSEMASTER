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
        response = self.create_draft()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], Announcement.Status.DRAFT)
        self.assertEqual(response.data["created_by"], self.admin_a.id)

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
        self.assertEqual(response.status_code, 403)

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
