import os
import sys

from django.apps import AppConfig
from django.db.models.signals import post_migrate


def seed_demo_after_migrate(sender, **kwargs):
    # Deploys run "manage.py migrate", so setting DEMO_PASSWORD on the server is
    # all it takes to get the demo school. Tests (which migrate internally) and
    # servers without the variable are left alone.
    if not os.environ.get("DEMO_PASSWORD") or sys.argv[1:2] != ["migrate"]:
        return
    from django.core.management import call_command

    call_command("seed_demo_school")


class StudentsConfig(AppConfig):
    name = 'students'

    def ready(self):
        post_migrate.connect(seed_demo_after_migrate, sender=self, dispatch_uid="seed_demo_after_migrate")
