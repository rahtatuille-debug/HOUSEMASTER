"""
Create "HouseMaster Demo College": a British secondary school with about
1,000 students and five years of marks and report cards (students/demo_large.py).

It takes a few minutes and adds several hundred thousand rows, so unlike
seed_demo_school it never runs after migrate: run it by hand on a demo server.
The same rules apply: DEMO_PASSWORD is the shared password, and with DEBUG
off it refuses unless ALLOW_DEMO_SEED=1.

Usage:
  DEMO_PASSWORD=... python manage.py seed_large_demo [--reset]
"""
import os
import time

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boarding.services import delete_school_history
from students import demo_large
from students.models import School


class Command(BaseCommand):
    help = "Create the large demo school with five years of history (--reset rebuilds it)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete and rebuild the large demo school.")

    def handle(self, *args, **options):
        if not settings.DEBUG and os.environ.get("ALLOW_DEMO_SEED") != "1":
            self.stderr.write(
                "Refusing to create demo schools: DEBUG is off, so this looks like a production server, and "
                "demo accounts share one password. Set ALLOW_DEMO_SEED=1 only on a server that exists for demos."
            )
            return
        password = os.environ.get("DEMO_PASSWORD", "")
        if not password:
            self.stdout.write("DEMO_PASSWORD isn't set, so the demo school wasn't created.")
            return
        if len(password) < 10:
            raise CommandError("DEMO_PASSWORD must be at least 10 characters.")

        existing = School.objects.filter(name=demo_large.NAME).first()
        if existing and not options["reset"]:
            from timetable.models import Lesson
            from timetable.services import fill_demo

            if not Lesson.objects.filter(school=existing).exists():  # built before timetables
                with transaction.atomic():
                    self.stdout.write(f"Added a timetable with {fill_demo(existing, rooms=60)} lessons.")
            from boarding.demo import fill_demo as fill_boarding
            from boarding.models import BoardingHouse

            if not BoardingHouse.objects.filter(school=existing).exists():  # built before boarding
                with transaction.atomic():
                    placed = fill_boarding(existing, house_names=("Darwin House", "Austen House"))
                    self.stdout.write(f"Added boarding with {placed} boarders.")
            from admissions.demo import fill_demo as fill_admissions
            from admissions.models import Application

            if not Application.objects.filter(school=existing).exists():  # built before admissions
                with transaction.atomic():
                    self.stdout.write(f"Added {fill_admissions(existing, demo_large.DOMAIN)} applications.")
            self.stdout.write(f"{demo_large.NAME} already exists; nothing to do (use --reset to rebuild it).")
            return
        started = time.monotonic()
        with transaction.atomic():
            if existing:
                users = demo_large.demo_users()
                if users.exclude(profile__school=existing).exclude(guardian__school=existing) \
                        .exclude(profile__isnull=True, guardian__isnull=True).exists():
                    raise CommandError(f"Some {demo_large.NAME} accounts belong to another school; refusing to delete.")
                delete_school_history(existing)
                existing.delete()
                users.delete()
            summary = demo_large.build(make_password(password))
        self.stdout.write(self.style.SUCCESS(f"{summary} ({time.monotonic() - started:.0f} s)"))
