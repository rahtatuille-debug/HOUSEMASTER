"""The refresh token in an httpOnly cookie (accounts/refresh_cookie.py), when AUTH_REFRESH_COOKIE is on."""
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from .tests import SchoolScopedAPITestCase

APP = {"HTTP_ORIGIN": "http://localhost:5173", "HTTP_X_REQUESTED_WITH": "HouseMaster"}


@override_settings(AUTH_REFRESH_COOKIE=True)
class RefreshCookieTests(SchoolScopedAPITestCase):
    def login(self, client):
        cache.clear()
        return client.post("/api/token/", {"email": "teacher.a@alpha.test", "password": "pass1234"}, format="json")

    def test_signing_in_keeps_the_refresh_token_out_of_reach_of_page_scripts(self):
        client = APIClient()
        response = self.login(client)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("refresh", response.json())
        self.assertTrue(response.json()["refresh_cookie"])
        cookie = response.cookies["hm_refresh"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual((cookie["path"], cookie["samesite"]), ("/api/token/", "Strict"))

    def test_refresh_from_the_cookie_rotates_it(self):
        client = APIClient()
        self.login(client)
        old = client.cookies["hm_refresh"].value
        response = client.post("/api/token/refresh/", {}, format="json", **APP)
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        new = client.cookies["hm_refresh"].value
        self.assertNotEqual(old, new)
        replay = APIClient()
        replay.cookies["hm_refresh"] = old
        self.assertEqual(replay.post("/api/token/refresh/", {}, format="json", **APP).status_code, 401)

    def test_refresh_needs_the_apps_header_and_origin(self):
        client = APIClient()
        self.login(client)
        self.assertEqual(client.post("/api/token/refresh/", {}, format="json",
                                     HTTP_ORIGIN="http://localhost:5173").status_code, 403)
        self.assertEqual(client.post("/api/token/refresh/", {}, format="json", HTTP_ORIGIN="https://evil.example",
                                     HTTP_X_REQUESTED_WITH="HouseMaster").status_code, 403)

    def test_logout_retires_the_token_and_clears_the_cookie(self):
        client = APIClient()
        self.login(client)
        token = client.cookies["hm_refresh"].value
        response = client.post("/api/token/logout/", {}, format="json", **APP)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies["hm_refresh"].value, "")
        replay = APIClient()
        replay.cookies["hm_refresh"] = token
        self.assertEqual(replay.post("/api/token/refresh/", {}, format="json", **APP).status_code, 401)

    @override_settings(AUTH_REFRESH_COOKIE=False)
    def test_off_by_default_nothing_changes(self):
        response = self.login(APIClient())
        self.assertIn("refresh", response.json())
        self.assertNotIn("hm_refresh", response.cookies)
