"""
Tests for the guardian-account flow: invite -> accept -> guardian_me,
plus scoping and permission boundaries relative to staff.
"""
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from django.contrib.auth.models import User

from activity.models import ActivityLog
from communications.models import Announcement
from gradebook.models import Grade, Subject, Term
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

from .models import Guardian


class GuardianInviteFlowTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        self.student = Student.objects.create(
            school=self.school_a, first_name="Amina", last_name="Otieno"
        )

    def test_non_admin_cannot_create_guardian_invite(self):
        response = self.client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace@example.com", "students": [self.student.id]},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_guardian_invite(self):
        response = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace@example.com", "students": [self.student.id]},
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_cannot_invite_guardian_to_another_schools_student(self):
        other_student = Student.objects.create(
            school=self.school_b, first_name="Brian", last_name="Kiptoo"
        )
        response = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Paul Kiptoo", "email": "paul@example.com", "students": [other_student.id]},
        )
        # Another school's record is rejected exactly like one that doesn't exist.
        self.assertEqual(response.status_code, 400)

    def test_requires_at_least_one_student(self):
        response = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace@example.com", "students": []},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("students", response.data)

    def test_full_accept_flow_creates_guardian_linked_to_students(self):
        create = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace@example.com", "students": [self.student.id]},
        )
        token = create.data["token"]

        preview = APIClient().get(f"/api/guardian-invites/preview/{token}/")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data["school_name"], "Alpha Academy")
        self.assertEqual(preview.data["student_names"], ["Amina Otieno"])

        accept = APIClient().post(
            "/api/guardian-invites/accept/", {"token": token, "password": "SuperSecret123!", "accept_privacy": True}
        )
        self.assertEqual(accept.status_code, 201, accept.data)
        self.assertIn("access", accept.data)

        guardian_client = APIClient()
        guardian_client.credentials(HTTP_AUTHORIZATION=f"Bearer {accept.data['access']}")
        me = guardian_client.get("/api/guardian-me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["name"], "Grace Otieno")
        self.assertEqual(me.data["school"]["name"], "Alpha Academy")
        self.assertEqual(len(me.data["students"]), 1)
        self.assertEqual(me.data["students"][0]["first_name"], "Amina")

    def test_guardian_cannot_use_staff_endpoints(self):
        create = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace2@example.com", "students": [self.student.id]},
        )
        accept = APIClient().post(
            "/api/guardian-invites/accept/",
            {"token": create.data["token"], "password": "SuperSecret123!", "accept_privacy": True},
        )
        guardian_client = APIClient()
        guardian_client.credentials(HTTP_AUTHORIZATION=f"Bearer {accept.data['access']}")

        # A guardian has no Profile, so the broad staff surface must reject them.
        response = guardian_client.get("/api/students/")
        self.assertEqual(response.status_code, 403)

    def test_guardian_can_update_own_display_name(self):
        create = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace3@example.com", "students": [self.student.id]},
        )
        accept = APIClient().post(
            "/api/guardian-invites/accept/",
            {"token": create.data["token"], "password": "SuperSecret123!", "accept_privacy": True},
        )
        guardian_client = APIClient()
        guardian_client.credentials(HTTP_AUTHORIZATION=f"Bearer {accept.data['access']}")

        response = guardian_client.patch("/api/guardian-me/", {"name": "Grace M. Otieno"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Grace M. Otieno")


class GuardianStudentPortalTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.year = YearGroup.objects.create(school=self.school_a, name="Year 8")
        self.school_class = SchoolClass.objects.create(year_group=self.year, name="8A")
        self.child = Student.objects.create(
            school=self.school_a, school_class=self.school_class, first_name="Amina", last_name="Otieno"
        )
        self.other_child = Student.objects.create(
            school=self.school_a, first_name="Noah", last_name="Kamau"
        )
        guardian_user = User.objects.create_user(
            username="grace@example.test", email="grace@example.test", password="pass1234"
        )
        self.guardian = Guardian.objects.create(
            user=guardian_user, school=self.school_a, display_name="Grace Otieno"
        )
        self.guardian.students.add(self.child)
        self.guardian_client = self.authed_client(guardian_user)

        subject = Subject.objects.create(school=self.school_a, name="Mathematics")
        term = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.grade = Grade.objects.create(
            student=self.child, subject=subject, term=term, score=86, max_score=100
        )
        Grade.objects.create(student=self.other_child, subject=subject, term=term, score=72, max_score=100)
        self.report = StudentReport.objects.create(
            student=self.child, term=term, progress_summary="Strong progress.", report_comment="Well done.",
            status="finalized",
        )
        StudentReport.objects.create(
            student=self.other_child, term=term, progress_summary="Private.", report_comment="Private.", status="finalized"
        )

    def test_guardian_can_view_only_linked_children_and_their_grades_reports(self):
        response = self.guardian_client.get("/api/guardian-students/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data], [self.child.id])
        self.assertEqual(response.data[0]["school_class_name"], "Year 8 — 8A")

        grades = self.guardian_client.get(f"/api/guardian-students/{self.child.id}/grades/")
        self.assertEqual(grades.status_code, 200)
        self.assertEqual(grades.data[0]["id"], self.grade.id)
        self.assertEqual(grades.data[0]["subject_name"], "Mathematics")

        reports = self.guardian_client.get(f"/api/guardian-students/{self.child.id}/reports/")
        self.assertEqual(reports.status_code, 200)
        self.assertEqual(reports.data[0]["id"], self.report.id)

        StudentReport.objects.create(
            student=self.child, term=Term.objects.create(school=self.school_a, name="Term 2 2026"),
            progress_summary="Internal draft.", report_comment="Internal draft.", status="draft",
        )
        reports = self.guardian_client.get(f"/api/guardian-students/{self.child.id}/reports/")
        self.assertEqual([item["id"] for item in reports.data], [self.report.id])

    def test_guardian_cannot_view_unlinked_child_or_their_records(self):
        self.assertEqual(
            self.guardian_client.get(f"/api/guardian-students/{self.other_child.id}/").status_code, 404
        )
        self.assertEqual(
            self.guardian_client.get(f"/api/guardian-students/{self.other_child.id}/grades/").status_code, 404
        )

    def test_guardian_sees_only_parent_announcements_for_linked_child(self):
        all_parents = Announcement.objects.create(
            school=self.school_a, title="School closure", body="Friday closes early.",
            audience=Announcement.Audience.ALL_PARENTS, status=Announcement.Status.PUBLISHED,
        )
        year_notice = Announcement.objects.create(
            school=self.school_a, title="Year 8 notice", body="Year 8 update.",
            audience=Announcement.Audience.YEAR_GROUP, year_group=self.year,
            status=Announcement.Status.PUBLISHED,
        )
        class_notice = Announcement.objects.create(
            school=self.school_a, title="8A notice", body="8A update.",
            audience=Announcement.Audience.SCHOOL_CLASS, school_class=self.school_class,
            status=Announcement.Status.PUBLISHED,
        )
        staff_notice = Announcement.objects.create(
            school=self.school_a, title="Staff notice", body="Staff only.",
            audience=Announcement.Audience.ALL_STAFF, status=Announcement.Status.PUBLISHED,
        )

        response = self.guardian_client.get("/api/announcements/")
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data]
        self.assertCountEqual(ids, [all_parents.id, year_notice.id, class_notice.id])
        self.assertNotIn(staff_notice.id, ids)


class ParentManagementTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        self.child1 = Student.objects.create(school=self.school_a, first_name="Ann", last_name="One")
        self.child2 = Student.objects.create(school=self.school_a, first_name="Ben", last_name="Two")
        self.other_school_child = Student.objects.create(school=self.school_b, first_name="Cy", last_name="Three")
        parent_user = User.objects.create_user(
            username="parent@alpha.test", email="parent@alpha.test", password="pass1234"
        )
        self.parent = Guardian.objects.create(user=parent_user, school=self.school_a, display_name="Pat Parent")
        self.parent.students.set([self.child1])
        other_user = User.objects.create_user(username="p@beta.test", email="p@beta.test", password="pass1234")
        self.parent_b = Guardian.objects.create(user=other_user, school=self.school_b, display_name="Other")

    def test_admin_lists_only_own_schools_parents(self):
        response = self.admin_client_a.get("/api/parents/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["name"] for row in response.data], ["Pat Parent"])
        self.assertEqual(response.data[0]["student_names"], ["Ann One"])

    def test_teacher_cannot_manage_parents(self):
        self.assertEqual(self.client_a.get("/api/parents/").status_code, 403)
        response = self.client_a.post(f"/api/parents/{self.parent.id}/deactivate/")
        self.assertEqual(response.status_code, 403)

    def test_cannot_touch_another_schools_parent(self):
        response = self.admin_client_a.post(f"/api/parents/{self.parent_b.id}/deactivate/")
        self.assertEqual(response.status_code, 404)

    def test_admin_changes_linked_children_and_it_is_logged(self):
        response = self.admin_client_a.patch(
            f"/api/parents/{self.parent.id}/", {"students": [self.child2.id]}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(self.parent.students.all()), [self.child2])
        entry = ActivityLog.objects.get(action="parent.children_changed")
        self.assertIn("linked Ben Two", entry.summary)
        self.assertIn("unlinked Ann One", entry.summary)

    def test_unlinked_parent_loses_access_to_that_child(self):
        parent_client = self.authed_client(self.parent.user)
        self.assertEqual(parent_client.get(f"/api/guardian-students/{self.child1.id}/").status_code, 200)
        self.admin_client_a.patch(f"/api/parents/{self.parent.id}/", {"students": []}, format="json")
        self.assertEqual(parent_client.get(f"/api/guardian-students/{self.child1.id}/").status_code, 404)

    def test_cannot_link_another_schools_student(self):
        response = self.admin_client_a.patch(
            f"/api/parents/{self.parent.id}/", {"students": [self.other_school_child.id]}, format="json"
        )
        # Another school's record is rejected exactly like one that doesn't exist.
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(self.parent.students.all()), [self.child1])

    def test_deactivated_parent_is_locked_out_and_hidden_from_contacts(self):
        parent_client = self.authed_client(self.parent.user)
        response = self.admin_client_a.post(f"/api/parents/{self.parent.id}/deactivate/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(parent_client.get("/api/guardian-me/").status_code, 401)
        contacts = self.client_a.get("/api/conversations/contacts/").data
        self.assertNotIn(self.parent.user.id, [c["id"] for c in contacts])
        response = self.client_a.post(
            "/api/conversations/", {"participant_ids": [self.parent.user.id], "body": "Hi"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(ActivityLog.objects.filter(action="parent.deactivated").exists())

    def test_reactivated_parent_can_log_in(self):
        self.admin_client_a.post(f"/api/parents/{self.parent.id}/deactivate/")
        self.admin_client_a.post(f"/api/parents/{self.parent.id}/reactivate/")
        login = self.client.post("/api/token/", {"email": "parent@alpha.test", "password": "pass1234", "accept_privacy": True})
        self.assertEqual(login.status_code, 200)


class ParentInviteRenewalAndResetTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        self.child = Student.objects.create(school=self.school_a, first_name="Kid", last_name="One")

    def test_admin_renews_parent_invite(self):
        from .models import GuardianInvite

        invite = GuardianInvite.objects.create(school=self.school_a, name="P", email="p@x.test", invited_by=self.admin_a)
        invite.students.add(self.child)
        old = invite.token
        response = self.admin_client_a.post(f"/api/guardian-invites/{invite.id}/renew/")
        self.assertEqual(response.status_code, 200)
        invite.refresh_from_db()
        self.assertNotEqual(invite.token, old)
        self.assertEqual(self.client_a.post(f"/api/guardian-invites/{invite.id}/renew/").status_code, 403)

    def test_admin_sends_parent_a_password_reset_email(self):
        from django.core import mail

        user = User.objects.create_user(username="pp@x.test", email="pp@x.test", password="pass1234")
        parent = Guardian.objects.create(user=user, school=self.school_a, display_name="Pat")
        response = self.admin_client_a.post(f"/api/parents/{parent.id}/send-password-reset/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[0].to, ["pp@x.test"])
        self.assertEqual(self.client_a.post(f"/api/parents/{parent.id}/send-password-reset/").status_code, 403)


class GuardianStudentProfileTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        from datetime import date

        from attendance.models import AttendanceRecord

        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.child = Student.objects.create(school=self.school_a, first_name="Kid", last_name="Mine",
                                            school_class=klass, medical_notes="Asthma", photo=b"\xff\xd8jpeg")
        Student.objects.filter(id=self.child.id).update(photo_updated_at="2026-01-01T00:00Z")
        self.other = Student.objects.create(school=self.school_a, first_name="Not", last_name="Mine",
                                            school_class=klass, photo=b"\xff\xd8other")
        term = Term.objects.create(school=self.school_a, name="Term 1")
        maths = Subject.objects.create(school=self.school_a, name="Maths")
        Grade.objects.create(student=self.child, subject=maths, term=term, score=90)
        Grade.objects.create(student=self.other, subject=maths, term=term, score=10)
        AttendanceRecord.objects.create(student=self.child, date=date.today(), status="late")
        user = User.objects.create_user(username="pm@x.test", email="pm@x.test", password="x")
        Guardian.objects.create(user=user, school=self.school_a, display_name="Pat").students.add(self.child)
        self.parent = self.authed_client(user)

    def test_parent_sees_own_childs_profile(self):
        data = self.parent.get(f"/api/guardian-students/{self.child.id}/profile/").data
        self.assertEqual(data["student"]["medical_notes"], "Asthma")
        self.assertTrue(data["student"]["has_photo"])
        self.assertEqual(data["attendance"]["overall"]["late"], 1)
        self.assertEqual(data["performance"], [{"term": "Term 1", "student": 90.0}])  # no class average
        self.assertNotIn("parents", data)
        self.assertNotIn("activity", data)

    def test_parent_sees_own_childs_photo_only(self):
        self.assertEqual(self.parent.get(f"/api/guardian-students/{self.child.id}/photo/").content, b"\xff\xd8jpeg")
        self.assertEqual(self.parent.get(f"/api/guardian-students/{self.other.id}/photo/").status_code, 404)
        self.assertEqual(self.parent.get(f"/api/guardian-students/{self.other.id}/profile/").status_code, 404)

    def test_parent_cannot_use_staff_student_endpoints(self):
        self.assertEqual(self.parent.get(f"/api/students/{self.child.id}/profile/").status_code, 403)
        self.assertEqual(self.parent.patch(f"/api/students/{self.child.id}/", {"medical_notes": "x"}).status_code, 403)


class ParentContactDetailsTests(SchoolScopedAPITestCase):
    """Who can see and change a parent's phone numbers, address and notes."""

    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Grade 7")
        self.my_class = SchoolClass.objects.create(year_group=year, name="7 East")
        other_class = SchoolClass.objects.create(year_group=year, name="7 West")
        self.child = Student.objects.create(school=self.school_a, school_class=self.my_class,
                                            first_name="Ann", last_name="One")
        self.other_child = Student.objects.create(school=self.school_a, school_class=other_class,
                                                  first_name="Ben", last_name="Two")
        self.assign(self.user_a, self.my_class, None)
        user = User.objects.create_user(username="parent@alpha.test", email="parent@alpha.test", password="pass1234")
        self.parent = Guardian.objects.create(
            user=user, school=self.school_a, display_name="Pat Parent", phone="+254 712 345 678",
            relationship="mother", address="12 Ngong Road, Nairobi", occupation="Nurse",
            preferred_contact="whatsapp", admin_note="Fees handled by aunt",
        )
        self.parent.students.set([self.child])
        self.parent_client = self.authed_client(user)

    def test_admin_sees_every_contact_detail(self):
        row = self.admin_client_a.get(f"/api/parents/{self.parent.id}/").data
        self.assertEqual(row["phone"], "+254 712 345 678")
        self.assertEqual(row["address"], "12 Ngong Road, Nairobi")
        self.assertEqual(row["admin_note"], "Fees handled by aunt")

    def test_admin_updates_contact_details_and_it_is_logged(self):
        response = self.admin_client_a.patch(
            f"/api/parents/{self.parent.id}/", {"phone_alt": "0722 000 111", "occupation": "Doctor"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.phone_alt, "0722 000 111")
        self.assertEqual(list(self.parent.students.all()), [self.child])  # links untouched
        log = ActivityLog.objects.get(action="parent.contact_changed")
        self.assertIn("second phone", log.summary)
        self.assertNotIn("0722", log.summary)

    def test_bad_phone_and_relationship_are_rejected(self):
        url = f"/api/parents/{self.parent.id}/"
        self.assertEqual(self.admin_client_a.patch(url, {"phone": "call me"}, format="json").status_code, 400)
        self.assertEqual(self.admin_client_a.patch(url, {"relationship": "boss"}, format="json").status_code, 400)
        self.assertEqual(self.admin_client_a.patch(url, {"phone": ""}, format="json").status_code, 200)

    def test_parent_updates_own_details_but_never_the_admin_note(self):
        response = self.parent_client.patch(
            "/api/guardian-me/", {"phone": "0700 111 222", "admin_note": "hacked", "address": "New address"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["contact"]["phone"], "0700 111 222")
        self.assertNotIn("admin_note", response.data["contact"])
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.address, "New address")
        self.assertEqual(self.parent.admin_note, "Fees handled by aunt")
        self.assertNotIn("admin_note", str(self.parent_client.get("/api/guardian-me/").data))

    def test_parent_can_still_change_just_their_name(self):
        response = self.parent_client.patch("/api/guardian-me/", {"name": "Patricia"}, format="json")
        self.assertEqual(response.data["name"], "Patricia")
        self.assertEqual(response.data["contact"]["phone"], "+254 712 345 678")

    def test_teacher_sees_phone_but_not_address_or_note_for_own_students(self):
        parents = self.client_a.get(f"/api/students/{self.child.id}/profile/").data["parents"]
        self.assertEqual(parents[0]["phone"], "+254 712 345 678")
        self.assertEqual(parents[0]["relationship"], "mother")
        for private in ("address", "occupation", "admin_note"):
            self.assertNotIn(private, parents[0])
        self.assertEqual(self.client_a.get(f"/api/students/{self.other_child.id}/profile/").status_code, 404)
        self.assertEqual(self.client_a.get(f"/api/parents/{self.parent.id}/").status_code, 403)

    def test_admin_sees_everything_on_the_student_page(self):
        parents = self.admin_client_a.get(f"/api/students/{self.child.id}/profile/").data["parents"]
        self.assertEqual(parents[0]["admin_note"], "Fees handled by aunt")

    def test_other_schools_cannot_see_or_change_the_parent(self):
        admin_b = User.objects.create_user(username="admin_b", email="admin.b@beta.test", password="pass1234")
        from accounts.models import Profile
        Profile.objects.create(user=admin_b, school=self.school_b, role=Profile.Role.ADMIN)
        client = self.authed_client(admin_b)
        self.assertEqual(client.get(f"/api/parents/{self.parent.id}/").status_code, 404)
        self.assertEqual(client.patch(f"/api/parents/{self.parent.id}/", {"phone": "0700 000 000"},
                                      format="json").status_code, 404)


class GuardianReportCardTests(GuardianStudentPortalTests):
    """Parents download their own child's finalized report card, and never see staff notes."""

    def test_reports_leave_out_the_staff_progress_summary(self):
        rows = self.guardian_client.get(f"/api/guardian-students/{self.child.id}/reports/").data
        self.assertEqual(rows[0]["report_comment"], "Well done.")
        self.assertNotIn("progress_summary", rows[0])

    def test_parent_downloads_a_finalized_report_card(self):
        response = self.guardian_client.get(
            f"/api/guardian-students/{self.child.id}/report-card/", {"term": self.report.term_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("report-card-amina-otieno", response["Content-Disposition"])
        self.assertTrue(ActivityLog.objects.filter(action="report.downloaded").exists())

    def test_no_card_for_unfinalized_reports_or_other_children(self):
        self.report.status = "submitted"
        self.report.save()
        url = f"/api/guardian-students/{self.child.id}/report-card/"
        self.assertEqual(self.guardian_client.get(url, {"term": self.report.term_id}).status_code, 404)
        self.assertEqual(self.guardian_client.get(url, {"term": "abc"}).status_code, 404)
        other = f"/api/guardian-students/{self.other_child.id}/report-card/"
        self.assertEqual(self.guardian_client.get(other, {"term": self.report.term_id}).status_code, 404)

    def test_staff_cannot_use_the_parent_download(self):
        response = self.client_a.get(f"/api/guardian-students/{self.child.id}/report-card/",
                                     {"term": self.report.term_id})
        self.assertEqual(response.status_code, 403)
