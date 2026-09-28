"""
The settings must refuse to start in production mode (DEBUG off) when a
critical environment variable is missing or unsafe, instead of silently
falling back to a development default. Each case imports the settings in a
fresh Python process with a controlled environment.
"""
import os
import subprocess
import sys
from pathlib import Path

from django.core import checks
from django.test import SimpleTestCase, override_settings

BASE_DIR = Path(__file__).resolve().parent.parent

GOOD_KEY = "k" * 60

PRODUCTION_ENV = {
    "DJANGO_DEBUG": "False",
    "SECRET_KEY": GOOD_KEY,
    "DATABASE_URL": "postgresql://user:pw@db.example.org:5432/housemaster",
    "DJANGO_ALLOWED_HOSTS": "api.example.org",
    "CORS_ALLOWED_ORIGINS": "https://app.example.org",
    "FRONTEND_URL": "https://app.example.org",
    "DRF_NUM_PROXIES": "1",
}


def import_settings(env, argv=("manage.py", "runserver")):
    """Import housemaster.settings in a clean process; return (ok, stderr)."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "SECRET_KEY", "DATABASE_URL",
                                                                      "CORS_", "FRONTEND_URL", "DRF_",
                                                                      "ALLOW_REMOTE_TEST_DB"))}
    # Never let a developer's .env leak into these cases.
    clean["HOUSEMASTER_SKIP_DOTENV"] = "1"
    clean.update(env)
    code = f"import sys; sys.argv = {list(argv)!r}; import housemaster.settings"
    result = subprocess.run([sys.executable, "-c", code], cwd=BASE_DIR, env=clean,
                            capture_output=True, text=True, timeout=60)
    return result.returncode == 0, result.stderr


class ProductionSettingsFailClosedTests(SimpleTestCase):
    def assertRefuses(self, env, message):
        ok, stderr = import_settings(env)
        self.assertFalse(ok, "settings imported but should have refused")
        self.assertIn("ImproperlyConfigured", stderr)
        self.assertIn(message, stderr)

    def test_happy_path_imports(self):
        ok, stderr = import_settings(PRODUCTION_ENV)
        self.assertTrue(ok, stderr)

    def test_debug_defaults_to_off(self):
        env = {k: v for k, v in PRODUCTION_ENV.items() if k != "DJANGO_DEBUG"}
        env.pop("SECRET_KEY")
        # With DJANGO_DEBUG unset the app is in production mode, so a missing
        # key must stop it rather than fall back to a development key.
        self.assertRefuses(env, "SECRET_KEY")

    def test_missing_secret_key(self):
        env = dict(PRODUCTION_ENV)
        env.pop("SECRET_KEY")
        self.assertRefuses(env, "SECRET_KEY")

    def test_short_secret_key(self):
        self.assertRefuses({**PRODUCTION_ENV, "SECRET_KEY": "x" * 49}, "SECRET_KEY")

    def test_insecure_secret_key(self):
        self.assertRefuses({**PRODUCTION_ENV, "SECRET_KEY": "django-insecure-" + "x" * 60}, "SECRET_KEY")

    def test_missing_database_url(self):
        env = dict(PRODUCTION_ENV)
        env.pop("DATABASE_URL")
        self.assertRefuses(env, "DATABASE_URL")

    def test_empty_allowed_hosts(self):
        self.assertRefuses({**PRODUCTION_ENV, "DJANGO_ALLOWED_HOSTS": " , "}, "DJANGO_ALLOWED_HOSTS")

    def test_empty_cors_origins(self):
        env = dict(PRODUCTION_ENV)
        env.pop("CORS_ALLOWED_ORIGINS")
        self.assertRefuses(env, "CORS_ALLOWED_ORIGINS")

    def test_wildcard_cors_origin(self):
        self.assertRefuses({**PRODUCTION_ENV, "CORS_ALLOWED_ORIGINS": "*"}, "CORS_ALLOWED_ORIGINS")

    def test_localhost_cors_origin(self):
        self.assertRefuses({**PRODUCTION_ENV, "CORS_ALLOWED_ORIGINS": "https://app.example.org,http://localhost:5173"},
                           "CORS_ALLOWED_ORIGINS")

    def test_loopback_ip_cors_origin(self):
        self.assertRefuses({**PRODUCTION_ENV, "CORS_ALLOWED_ORIGINS": "http://127.0.0.1:5173"}, "CORS_ALLOWED_ORIGINS")

    def test_development_mode_still_works_without_any_env(self):
        ok, stderr = import_settings({"DJANGO_DEBUG": "True"})
        self.assertTrue(ok, stderr)

    def test_old_committed_key_is_gone(self):
        # The key that used to be the fallback was published in this public
        # repository. It must not be anywhere in the settings any more.
        source = (BASE_DIR / "housemaster" / "settings.py").read_text()
        self.assertNotIn("y9g=yf", source)


class DeploySystemCheckTests(SimpleTestCase):
    """F-03/F-18: misconfiguration that can't stop startup is an ERROR in `check --deploy`."""

    def run_deploy_checks(self):
        from housemaster.checks import production_configuration
        return {m.id for m in production_configuration(app_configs=None)}

    @override_settings(DEBUG=False, FRONTEND_URL="http://localhost:5173",
                       EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", DRF_NUM_PROXIES=1)
    def test_localhost_frontend_url_is_an_error(self):
        self.assertIn("housemaster.E001", self.run_deploy_checks())

    @override_settings(DEBUG=False, FRONTEND_URL="https://app.example.org",
                       EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend", DRF_NUM_PROXIES=1)
    def test_console_email_is_an_error(self):
        self.assertIn("housemaster.E002", self.run_deploy_checks())

    @override_settings(DEBUG=False, FRONTEND_URL="https://app.example.org",
                       EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", DRF_NUM_PROXIES=None)
    def test_missing_proxy_count_is_a_warning(self):
        self.assertIn("housemaster.W001", self.run_deploy_checks())

    @override_settings(DEBUG=False, FRONTEND_URL="https://app.example.org",
                       EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", DRF_NUM_PROXIES=1)
    def test_good_configuration_has_no_errors(self):
        from housemaster.checks import production_configuration
        errors = [m for m in production_configuration(app_configs=None) if m.level >= checks.ERROR]
        self.assertEqual(errors, [])

    @override_settings(DEBUG=True, FRONTEND_URL="http://localhost:5173",
                       EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend", DRF_NUM_PROXIES=None)
    def test_development_is_left_alone(self):
        self.assertEqual(self.run_deploy_checks(), set())


class ClientIPDebugMiddlewareTests(SimpleTestCase):
    """F-05: LOG_CLIENT_IP_DEBUG lets the owner see Render's real proxy hops."""

    def test_logs_forwarded_for_and_identity_for_the_first_requests_only(self):
        from django.http import HttpResponse
        from django.test import RequestFactory

        from housemaster.middleware import ClientIPDebugMiddleware

        middleware = ClientIPDebugMiddleware(lambda request: HttpResponse("ok"))
        factory = RequestFactory()
        with self.assertLogs("housemaster.client_ip", level="INFO") as logs:
            for i in range(25):
                middleware(factory.get("/api/me/", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.9",
                                       REMOTE_ADDR="10.10.10.10"))
        self.assertEqual(len(logs.records), ClientIPDebugMiddleware.LIMIT)
        self.assertIn("10.0.0.0, 203.0.113.9", logs.output[0])
        self.assertIn("REMOTE_ADDR=10.10.10.10", logs.output[0])
        self.assertIn("identity=", logs.output[0])
