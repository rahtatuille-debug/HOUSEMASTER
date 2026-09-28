"""
B-7: the demo seed refuses to run in production.

Demo schools share one password (DEMO_PASSWORD), so creating them on a
real server would give anyone who knows it a way in. With DEBUG off the
command creates nothing unless ALLOW_DEMO_SEED=1 is set on purpose (for a
server that exists only for demos). It exits normally when it refuses, so
a build command that runs it doesn't start failing deploys. The password
never appears in its output.
"""
import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .management.commands.seed_demo_school import Command

PASSWORD = "Shared-Demo-Pass-99"


def run(env, *args):
    out, err = StringIO(), StringIO()
    with patch.dict(os.environ, env), patch.object(Command, "_build") as build, \
            patch.object(Command, "_system_demos") as system_demos:
        call_command("seed_demo_school", *args, stdout=out, stderr=err)
    return build.called or system_demos.called, out.getvalue() + err.getvalue()


class DemoSeedGuardTests(TestCase):
    def setUp(self):
        os.environ.pop("ALLOW_DEMO_SEED", None)

    @override_settings(DEBUG=False)
    def test_refuses_in_production_mode(self):
        seeded, output = run({"DEMO_PASSWORD": PASSWORD})
        self.assertFalse(seeded)
        self.assertIn("Refusing", output)
        self.assertIn("ALLOW_DEMO_SEED", output)

    @override_settings(DEBUG=False)
    def test_refuses_in_production_mode_with_reset_too(self):
        seeded, _ = run({"DEMO_PASSWORD": PASSWORD}, "--reset")
        self.assertFalse(seeded)

    @override_settings(DEBUG=False)
    def test_runs_in_production_mode_with_the_flag(self):
        seeded, _ = run({"DEMO_PASSWORD": PASSWORD, "ALLOW_DEMO_SEED": "1"})
        self.assertTrue(seeded)

    @override_settings(DEBUG=False)
    def test_flag_must_be_exactly_one(self):
        seeded, _ = run({"DEMO_PASSWORD": PASSWORD, "ALLOW_DEMO_SEED": "yes"})
        self.assertFalse(seeded)

    @override_settings(DEBUG=True)
    def test_runs_in_debug(self):
        seeded, _ = run({"DEMO_PASSWORD": PASSWORD})
        self.assertTrue(seeded)

    def test_password_never_in_output(self):
        for debug, env in ((False, {}), (False, {"ALLOW_DEMO_SEED": "1"}), (True, {})):
            with self.subTest(debug=debug, env=env), override_settings(DEBUG=debug):
                _, output = run({"DEMO_PASSWORD": PASSWORD, **env})
                self.assertNotIn(PASSWORD, output)
        with override_settings(DEBUG=True), self.assertRaises(CommandError) as ctx:
            run({"DEMO_PASSWORD": "short"})
        self.assertNotIn("short", str(ctx.exception).replace("too short", ""))

    @override_settings(DEBUG=False)
    def test_deploy_migrate_in_production_creates_nothing_and_does_not_fail(self):
        from django.apps import apps

        from students.apps import seed_demo_after_migrate
        from students.models import School

        err = StringIO()
        with patch.dict(os.environ, {"DEMO_PASSWORD": PASSWORD}), patch("sys.argv", ["manage.py", "migrate"]), \
                patch("sys.stderr", err), patch("sys.stdout", StringIO()):
            seed_demo_after_migrate(sender=apps.get_app_config("students"))
        self.assertFalse(School.objects.filter(name__startswith="HouseMaster Demo").exists())
        self.assertNotIn(PASSWORD, err.getvalue())

