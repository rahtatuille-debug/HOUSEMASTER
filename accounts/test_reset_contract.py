"""
F-1 (follow-up): the contract the "Forgot password" screen relies on.

The screen used to post {"username": ...}, which this endpoint has never
accepted, so every self-service reset failed with a 400. It asks for the
account's email address, and answers the same way whether or not an
account uses it.
"""
from django.core import mail

from .tests import SchoolScopedAPITestCase


class PasswordResetContractTests(SchoolScopedAPITestCase):
    def test_username_field_is_refused_with_email_required(self):
        response = self.client.post("/api/password-reset/", {"username": self.user_a.username}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"email"})
        self.assertEqual(len(mail.outbox), 0)

    def test_email_gets_the_same_answer_whether_or_not_it_has_an_account(self):
        known = self.client.post("/api/password-reset/", {"email": self.user_a.email}, format="json")
        unknown = self.client.post("/api/password-reset/", {"email": "nobody@example.org"}, format="json")
        self.assertEqual((known.status_code, unknown.status_code), (200, 200))
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(len(mail.outbox), 1)

    def test_confirm_takes_token_and_password(self):
        self.client.post("/api/password-reset/", {"email": self.user_a.email}, format="json")
        token = self.user_a.password_reset_tokens.get().token
        response = self.client.post("/api/password-reset/confirm/",
                                    {"token": token, "password": "A-new-long-password-9"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.user_a.refresh_from_db()
        self.assertTrue(self.user_a.check_password("A-new-long-password-9"))
