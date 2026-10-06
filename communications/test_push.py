"""Phone and browser notifications (web push) for routine notices: new announcements and reports."""
import base64
import os
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth.models import User
from django.test import override_settings

from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from gradebook.models import Term
from guardians.models import Guardian
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

from .models import Announcement, PushSubscription


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def vapid_keys():
    key = ec.generate_private_key(ec.SECP256R1())
    private = b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = b64(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    return private, public


def browser_keys():
    """What a browser hands over when it subscribes: its public key and a 16-byte secret."""
    key = ec.generate_private_key(ec.SECP256R1())
    return {"p256dh": b64(key.public_key().public_bytes(serialization.Encoding.X962,
                                                         serialization.PublicFormat.UncompressedPoint)),
            "auth": b64(os.urandom(16))}


PRIVATE, PUBLIC = vapid_keys()
KEYS = override_settings(VAPID_PRIVATE_KEY=PRIVATE, VAPID_PUBLIC_KEY=PUBLIC, VAPID_SUBJECT="mailto:ops@example.org",
                         NOTIFICATIONS_IN_BACKGROUND=False,
                         EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def ok(status=201):
    return mock.Mock(status_code=status)


class PushBase(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Grade 7")
        self.class_7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.class_7b = SchoolClass.objects.create(year_group=year, name="7B")
        self.term = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.kid_7a = Student.objects.create(school=self.school_a, school_class=self.class_7a, first_name="Amina",
                                             last_name="Test")
        self.kid_7b = Student.objects.create(school=self.school_a, school_class=self.class_7b, first_name="Brian",
                                             last_name="Test")
        self.p_7a = self.parent("p7a@alpha.test", [self.kid_7a])
        self.p_7b = self.parent("p7b@alpha.test", [self.kid_7b])
        beta_kid = Student.objects.create(school=self.school_b, first_name="Zed", last_name="B")
        self.p_beta = self.parent("beta@beta.test", [beta_kid], school=self.school_b)

    def parent(self, email, kids, school=None, **extra):
        user = User.objects.create_user(username=email, email=email, password="pass1234")
        g = Guardian.objects.create(user=user, school=school or self.school_a, display_name=email.split("@")[0], **extra)
        g.students.set(kids)
        return g

    def subscribe(self, user, endpoint=FCM):
        return self.authed_client(user).post("/api/push/subscribe/", {"endpoint": endpoint, "keys": browser_keys()},
                                             format="json")


@KEYS
class SubscribeTests(PushBase):
    def test_settings_say_whether_push_is_set_up(self):
        response = self.authed_client(self.p_7a.user).get("/api/push/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"enabled": True, "public_key": PUBLIC, "subscribed": False})
        with override_settings(VAPID_PRIVATE_KEY="", VAPID_PUBLIC_KEY=""):
            self.assertEqual(self.authed_client(self.p_7a.user).get("/api/push/").data,
                             {"enabled": False, "public_key": "", "subscribed": False})

    def test_needs_a_login(self):
        self.assertEqual(self.client.get("/api/push/").status_code, 401)
        self.assertEqual(self.client.post("/api/push/subscribe/", {}, format="json").status_code, 401)

    def test_a_parent_turns_it_on_for_this_device_and_off_again(self):
        self.assertEqual(self.subscribe(self.p_7a.user).status_code, 201)
        self.assertEqual(PushSubscription.objects.get().user, self.p_7a.user)
        self.assertTrue(self.authed_client(self.p_7a.user).get("/api/push/").data["subscribed"])
        # Subscribing again from the same device updates, not duplicates.
        self.assertEqual(self.subscribe(self.p_7a.user).status_code, 201)
        self.assertEqual(PushSubscription.objects.count(), 1)
        response = self.authed_client(self.p_7a.user).post("/api/push/unsubscribe/", {"endpoint": FCM}, format="json")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(PushSubscription.objects.exists())
        self.assertTrue(ActivityLog.objects.filter(action="push.subscribed").exists())

    def test_only_known_push_services_are_accepted(self):
        """The server later sends to this address, so it must be a real push service, never an internal one."""
        for endpoint in ["http://fcm.googleapis.com/fcm/send/x", "https://127.0.0.1/x", "https://evil.example/x",
                         "https://fcm.googleapis.com.evil.example/x", "https://169.254.169.254/latest/",
                         "not a url", ""]:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.subscribe(self.p_7a.user, endpoint).status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())
        for endpoint in [FCM, "https://updates.push.services.mozilla.com/wpush/v2/x", "https://web.push.apple.com/x",
                         "https://wns2-par02p.notify.windows.com/w/?token=x"]:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.subscribe(self.p_7a.user, endpoint).status_code, 201)

    def test_bad_keys_are_refused(self):
        response = self.authed_client(self.p_7a.user).post("/api/push/subscribe/", {
            "endpoint": FCM, "keys": {"p256dh": "nope", "auth": "x"}}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_cannot_turn_off_someone_elses_device(self):
        self.subscribe(self.p_7a.user)
        self.authed_client(self.p_7b.user).post("/api/push/unsubscribe/", {"endpoint": FCM}, format="json")
        self.assertEqual(PushSubscription.objects.count(), 1)

    def test_a_device_moving_to_another_account_belongs_to_the_new_account(self):
        self.subscribe(self.p_7a.user)
        self.subscribe(self.p_7b.user)
        self.assertEqual(PushSubscription.objects.get().user, self.p_7b.user)


@KEYS
class SendTests(PushBase):
    def publish(self, **fields):
        a = Announcement.objects.create(school=self.school_a, title="Sports day", body="Friday at 9am.",
                                        created_by=self.admin_a, **fields)
        with mock.patch("communications.push.requests.post", return_value=ok()) as post:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.admin_client.post(f"/api/announcements/{a.id}/publish/").status_code, 200)
        return post

    def test_an_announcement_reaches_that_audiences_devices_only(self):
        self.subscribe(self.p_7a.user, FCM + "-a")
        self.subscribe(self.p_7b.user, FCM + "-b")
        self.subscribe(self.p_beta.user, FCM + "-beta")
        post = self.publish(audience="school_class", school_class=self.class_7a)
        self.assertEqual([c.args[0] for c in post.call_args_list], [FCM + "-a"])
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Content-Encoding"], "aes128gcm")
        self.assertTrue(headers["Authorization"].startswith("vapid t="))
        self.assertIn("TTL", headers)
        # The payload is encrypted: neither the title nor the body is readable on the wire.
        self.assertNotIn(b"Sports", post.call_args.kwargs["data"])
        self.assertTrue(ActivityLog.objects.filter(action="notification.pushed", summary__startswith="Sent 1 of 1").exists())

    def test_whole_school_announcement(self):
        self.subscribe(self.p_7a.user, FCM + "-a")
        self.subscribe(self.p_7b.user, FCM + "-b")
        self.subscribe(self.p_beta.user, FCM + "-beta")
        post = self.publish(audience="all_parents")
        self.assertEqual(sorted(c.args[0] for c in post.call_args_list), [FCM + "-a", FCM + "-b"])

    def test_parents_who_turned_email_off_still_get_push_they_asked_for(self):
        self.p_7a.email_notifications = False
        self.p_7a.save()
        self.subscribe(self.p_7a.user)
        self.assertEqual(self.publish(audience="all_parents").call_count, 1)

    def test_staff_announcements_push_to_no_parent(self):
        self.subscribe(self.p_7a.user)
        self.assertEqual(self.publish(audience="all_staff").call_count, 0)

    def test_a_gone_device_is_forgotten(self):
        self.subscribe(self.p_7a.user)
        a = Announcement.objects.create(school=self.school_a, title="x", body="y", created_by=self.admin_a,
                                        audience="all_parents")
        with mock.patch("communications.push.requests.post", return_value=ok(410)):
            with self.captureOnCommitCallbacks(execute=True):
                self.admin_client.post(f"/api/announcements/{a.id}/publish/")
        self.assertFalse(PushSubscription.objects.exists())

    def test_a_failing_push_service_does_not_break_publishing(self):
        self.subscribe(self.p_7a.user)
        a = Announcement.objects.create(school=self.school_a, title="x", body="y", created_by=self.admin_a,
                                        audience="all_parents")
        with mock.patch("communications.push.requests.post", side_effect=OSError("down")):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.admin_client.post(f"/api/announcements/{a.id}/publish/").status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)

    def test_nothing_is_sent_until_the_owner_sets_the_keys(self):
        self.subscribe(self.p_7a.user)
        with override_settings(VAPID_PRIVATE_KEY="", VAPID_PUBLIC_KEY=""):
            self.assertEqual(self.publish(audience="all_parents").call_count, 0)

    def test_a_finalized_report_pushes_to_that_childs_parents(self):
        self.subscribe(self.p_7a.user, FCM + "-a")
        self.subscribe(self.p_7b.user, FCM + "-b")
        report = StudentReport.objects.create(student=self.kid_7a, term=self.term, progress_summary="Staff only",
                                              report_comment="Well done", status="submitted")
        with mock.patch("communications.push.requests.post", return_value=ok()) as post:
            with self.captureOnCommitCallbacks(execute=True):
                self.admin_client.post(f"/api/reports/{report.id}/finalize/")
        self.assertEqual([c.args[0] for c in post.call_args_list], [FCM + "-a"])

    def test_the_message_can_be_read_by_the_device(self):
        """Round trip: what we send decrypts with the browser's keys to a short notice with no child name."""
        import json

        import http_ece

        key = ec.generate_private_key(ec.SECP256R1())
        auth = os.urandom(16)
        keys = {"p256dh": b64(key.public_key().public_bytes(serialization.Encoding.X962,
                                                            serialization.PublicFormat.UncompressedPoint)),
                "auth": b64(auth)}
        self.authed_client(self.p_7a.user).post("/api/push/subscribe/", {"endpoint": FCM, "keys": keys}, format="json")
        report = StudentReport.objects.create(student=self.kid_7a, term=self.term, progress_summary="x",
                                              report_comment="y", status="submitted")
        with mock.patch("communications.push.requests.post", return_value=ok()) as post:
            with self.captureOnCommitCallbacks(execute=True):
                self.admin_client.post(f"/api/reports/{report.id}/finalize/")
        message = json.loads(http_ece.decrypt(post.call_args.kwargs["data"], private_key=key, auth_secret=auth,
                                              version="aes128gcm"))
        self.assertEqual(message["title"], "Alpha Academy")
        self.assertEqual(message["body"], "A new report is ready in HouseMaster.")
        self.assertNotIn("Amina", json.dumps(message))
