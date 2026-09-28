"""
E-4: `manage.py test` must never run against a remote database. An earlier
test run picked up a developer's .env and created a stray test database on
the production Neon server.
"""
from django.test import SimpleTestCase

from housemaster.test_settings_guard import import_settings


class RemoteTestDatabaseGuardTests(SimpleTestCase):
    """E-4: `manage.py test` must never run against a remote database."""

    def test_refuses_remote_database_for_tests(self):
        ok, stderr = import_settings({"DJANGO_DEBUG": "True",
                                      "DATABASE_URL": "postgresql://u:p@ep-cool-name.neon.tech/neondb"},
                                     argv=("manage.py", "test"))
        self.assertFalse(ok)
        self.assertIn("remote database", stderr)
        # The message must never echo the connection string.
        self.assertNotIn("neon.tech", stderr)

    def test_allows_local_database_for_tests(self):
        ok, stderr = import_settings({"DJANGO_DEBUG": "True",
                                      "DATABASE_URL": "postgresql://u:p@localhost:5432/housemaster"},
                                     argv=("manage.py", "test"))
        self.assertTrue(ok, stderr)

    def test_allows_sqlite_for_tests(self):
        ok, stderr = import_settings({"DJANGO_DEBUG": "True"}, argv=("manage.py", "test"))
        self.assertTrue(ok, stderr)

    def test_explicit_override_allows_remote(self):
        ok, stderr = import_settings({"DJANGO_DEBUG": "True", "ALLOW_REMOTE_TEST_DB": "1",
                                      "DATABASE_URL": "postgresql://u:p@db.example.org/ci"},
                                     argv=("manage.py", "test"))
        self.assertTrue(ok, stderr)


