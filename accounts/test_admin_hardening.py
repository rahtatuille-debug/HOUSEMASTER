"""
F-17: the Django admin.

- Its address comes from DJANGO_ADMIN_PATH, so production can move it off
  the guessable /admin/.
- Password attempts on its login page are limited per client address.
- sync_superuser creates the superuser only if it's missing, and changes
  the password only when SYNC_SUPERUSER_RESET_PASSWORD=true is set for
  that deploy.
"""
import os
import subprocess
import sys
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

from housemaster.test_settings_guard import BASE_DIR

# The admin's pages load their CSS through the static-files manifest, which
# only exists after collectstatic; plain storage is enough for these tests.
PLAIN_STATIC = override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})

SUPERUSER_ENV = {"DJANGO_SUPERUSER_USERNAME": "root", "DJANGO_SUPERUSER_EMAIL": "root@example.org",
                 "DJANGO_SUPERUSER_PASSWORD": "First-Long-Password-1"}


def sync(env):
    out = StringIO()
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("DJANGO_SUPERUSER_", "SYNC_SUPERUSER_"))}
    with patch.dict(os.environ, {**clean, **env}, clear=True):
        call_command("sync_superuser", stdout=out)
    return out.getvalue()


class SyncSuperuserTests(TestCase):
    def test_creates_the_superuser_when_missing(self):
        output = sync(SUPERUSER_ENV)
        user = User.objects.get(username="root")
        self.assertTrue(user.is_superuser and user.is_staff)
        self.assertTrue(user.check_password("First-Long-Password-1"))
        self.assertIn("Created", output)

    def test_does_not_overwrite_the_password_by_default(self):
        sync(SUPERUSER_ENV)
        user = User.objects.get(username="root")
        user.set_password("Changed-By-The-Owner-2")
        user.save()
        output = sync({**SUPERUSER_ENV, "DJANGO_SUPERUSER_PASSWORD": "Env-Value-3"})
        self.assertTrue(User.objects.get(username="root").check_password("Changed-By-The-Owner-2"))
        self.assertIn("left unchanged", output)

    def test_overwrites_the_password_when_asked_and_says_so_loudly(self):
        sync(SUPERUSER_ENV)
        output = sync({**SUPERUSER_ENV, "DJANGO_SUPERUSER_PASSWORD": "Reset-Value-4",
                       "SYNC_SUPERUSER_RESET_PASSWORD": "true"})
        self.assertTrue(User.objects.get(username="root").check_password("Reset-Value-4"))
        self.assertIn("PASSWORD RESET", output)
        self.assertIn("remove SYNC_SUPERUSER_RESET_PASSWORD", output)

    def test_does_nothing_without_the_env_vars(self):
        output = sync({})
        self.assertFalse(User.objects.exists())
        self.assertIn("skipping", output)


@PLAIN_STATIC
class AdminPathTests(TestCase):
    def admin_path_from_settings(self, env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
        clean.update({"HOUSEMASTER_SKIP_DOTENV": "1", "DJANGO_DEBUG": "True", **env})
        result = subprocess.run([sys.executable, "-c", "import housemaster.settings as s; print(s.ADMIN_PATH)"],
                                cwd=BASE_DIR, env=clean, capture_output=True, text=True)
        return result.stdout.strip()

    def test_default_path_is_admin(self):
        self.assertEqual(self.admin_path_from_settings({}), "admin/")

    def test_path_comes_from_the_environment_and_is_normalised(self):
        self.assertEqual(self.admin_path_from_settings({"DJANGO_ADMIN_PATH": "/manage-7f3c2a"}), "manage-7f3c2a/")

    def test_admin_is_served_at_the_configured_path(self):
        from django.conf import settings

        response = self.client.get(f"/{settings.ADMIN_PATH}login/")
        self.assertEqual(response.status_code, 200)


@PLAIN_STATIC
class AdminLoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_superuser("root", "root@example.org", "Right-Password-1")

    def attempt(self, password="wrong", ip="198.51.100.4"):
        from django.conf import settings

        return self.client.post(f"/{settings.ADMIN_PATH}login/", {"username": "root", "password": password},
                                REMOTE_ADDR=ip)

    @override_settings(ADMIN_LOGIN_RATE=3)
    def test_password_attempts_are_limited_per_address(self):
        codes = [self.attempt().status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 200])  # the form is shown again with an error
        self.assertEqual(self.attempt(password="Right-Password-1").status_code, 429)
        self.assertEqual(self.attempt(ip="198.51.100.5").status_code, 200)

    @override_settings(ADMIN_LOGIN_RATE=3)
    def test_viewing_the_login_page_is_not_limited(self):
        from django.conf import settings

        for _ in range(5):
            self.assertEqual(self.client.get(f"/{settings.ADMIN_PATH}login/").status_code, 200)
