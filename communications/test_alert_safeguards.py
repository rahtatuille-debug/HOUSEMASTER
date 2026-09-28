"""
B-9: what urgent alerts and class-wide messages were missing
(docs/COMMUNICATIONS_STATUS.md).

- Every urgent alert is emailed as well as shown in the app, in the
  background after it is saved, and a parent's "no notification emails"
  choice doesn't hold it back.
- A per-school limit on alerts, so a stolen admin login can't flood every
  parent; test alerts have their own limit, so testing never uses up the
  budget for a real emergency, and a refused or invalid alert uses nothing.
- Admins can send a test alert that goes to staff only.
- Class-wide messages are rate limited per sender.
"""
from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from rest_framework.settings import api_settings

from communications.models import UrgentAlert
from messaging.models import Conversation

from .tests import UrgentAlertFixture


def rates(**values):
    return patch.dict(api_settings.DEFAULT_THROTTLE_RATES, values)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class AlertEmailTests(UrgentAlertFixture):
    def send_and_deliver(self, **body):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.send(**body)
        return response

    def test_every_alert_is_emailed_without_ticking_anything(self):
        response = self.send_and_deliver()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox),
                         sorted([self.user_a.email, self.p7a.email, self.p7b.email]))
        alert = self.admin_client_a.get(f"/api/alerts/{response.data['id']}/").data
        self.assertEqual((alert["emailed_count"], alert["email_failed_count"]), (3, 0))
        self.assertIsNotNone(alert["emailed_at"])

    def test_email_goes_out_after_the_alert_is_saved_not_during_the_request(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.send()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(response.data["emailed_at"], "emailing is still to come")
        for callback in callbacks:
            callback()
        self.assertEqual(len(mail.outbox), 3)

    def test_parents_who_turned_off_notification_emails_still_get_urgent_alerts(self):
        self.p7a.guardian.email_notifications = False
        self.p7a.guardian.save()
        self.send_and_deliver(audience="school_class", school_class=self.class_7a.id)
        self.assertEqual([m.to[0] for m in mail.outbox], [self.p7a.email])

    def test_a_failed_email_still_counts_and_the_alert_stands(self):
        with patch("django.core.mail.backends.locmem.EmailBackend.send_messages", side_effect=OSError("down")):
            response = self.send_and_deliver()
        alert = UrgentAlert.objects.get(id=response.data["id"])
        self.assertEqual((alert.emailed_count, alert.email_failed_count), (0, 3))
        self.assertEqual(len(self.authed_client(self.p7a).get("/api/alerts/active/").data), 1)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class AlertLimitTests(UrgentAlertFixture):
    def test_school_limit_stops_a_flood(self):
        with rates(alert_school="2/day"):
            codes = [self.send(title=f"Alert {i}").status_code for i in range(3)]
            refused = self.send(title="One more")
        self.assertEqual(codes, [201, 201, 429])
        self.assertIn("Retry-After", refused)
        self.assertRegex(refused.json()["detail"], r"as many urgent alerts as it can for now\. .* Try again in about \d+ hours?\.$")
        self.assertNotIn("seconds", refused.json()["detail"])
        self.assertEqual(UrgentAlert.objects.filter(school=self.school_a).count(), 2)

    def test_limit_is_per_school_and_shared_by_its_admins(self):
        from django.contrib.auth.models import User

        from accounts.models import Profile

        second = User.objects.create_user(username="a2", email="a2@alpha.test", password="x")
        Profile.objects.create(user=second, school=self.school_a, role=Profile.Role.ADMIN)
        admin_b = User.objects.create_user(username="ab", email="ab@beta.test", password="x")
        Profile.objects.create(user=admin_b, school=self.school_b, role=Profile.Role.ADMIN)
        with rates(alert_school="1/day"):
            self.assertEqual(self.send().status_code, 201)
            self.assertEqual(self.send(client=self.authed_client(second)).status_code, 429)
            self.assertEqual(self.send(client=self.authed_client(admin_b)).status_code, 201)

    def test_refused_or_invalid_alerts_use_none_of_the_budget(self):
        from students.models import SchoolClass

        empty = SchoolClass.objects.create(year_group=self.year, name="Empty")
        with rates(alert_school="1/day"):
            self.assertEqual(self.send(audience="school_class", school_class=empty.id).status_code, 400)
            self.assertEqual(self.send(client=self.authed_client(self.p7a)).status_code, 403)
            self.assertEqual(self.send().status_code, 201)

    def test_test_alerts_have_their_own_budget(self):
        with rates(alert_school="1/day", alert_test_school="1/day"):
            self.assertEqual(self.send(is_test=True).status_code, 201)
            self.assertEqual(self.send(is_test=True).status_code, 429)
            self.assertEqual(self.send().status_code, 201, "testing mustn't use up the real budget")
            self.assertEqual(self.send().status_code, 429)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class TestAlertTests(UrgentAlertFixture):
    def test_test_alert_goes_to_staff_only_whatever_the_audience(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.send(is_test=True, audience="everyone")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["is_test"])
        self.assertEqual(response.data["audience"], "all_staff")
        self.assertEqual(self.recipients(response.data["id"]), {self.user_a.id})
        self.assertEqual([m.to[0] for m in mail.outbox], [self.user_a.email])
        self.assertTrue(mail.outbox[0].subject.startswith("TEST: "))
        self.assertIn("This is a test", mail.outbox[0].body)
        self.assertEqual(self.authed_client(self.p7a).get("/api/alerts/active/").data, [])

    def test_only_admins_send_test_alerts(self):
        teacher = self.authed_client(self.user_a)
        response = self.send(client=teacher, is_test=True, audience="school_class", school_class=self.class_7a.id)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(UrgentAlert.objects.exists())

    def test_test_alert_is_logged_as_a_test(self):
        from activity.models import ActivityLog

        self.send(is_test=True)
        self.assertTrue(ActivityLog.objects.filter(action="alert.sent", summary__startswith="Sent a test").exists())


class ClassMessageLimitTests(UrgentAlertFixture):
    def message_class(self, client, body="Trip on Friday"):
        return client.post("/api/conversations/class/", {"school_class": self.class_7a.id, "kind": "class_notice",
                                                         "body": body}, format="json")

    def test_class_messages_are_limited_per_sender(self):
        teacher = self.authed_client(self.user_a)
        with rates(class_message="2/hour"):
            codes = [self.message_class(teacher, f"Note {i}").status_code for i in range(3)]
            admin_code = self.message_class(self.admin_client_a).status_code
        self.assertEqual(codes, [201, 201, 429])
        self.assertEqual(admin_code, 201, "another sender has their own limit")
        self.assertEqual(Conversation.objects.filter(kind="class_notice").count(), 3)

    def test_direct_messages_are_not_counted(self):
        teacher = self.authed_client(self.user_a)
        with rates(class_message="1/hour"):
            self.assertEqual(self.message_class(teacher).status_code, 201)
            direct = teacher.post("/api/conversations/", {"participant_ids": [self.p7a.id], "body": "Hi"},
                                  format="json")
        self.assertEqual(direct.status_code, 201, direct.data)
