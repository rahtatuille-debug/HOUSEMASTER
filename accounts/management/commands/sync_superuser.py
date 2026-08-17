import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """
    Creates a superuser from DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD env
    vars if one doesn't exist yet, and re-syncs the password to match the
    current env var value if it does. Meant to be run on every deploy
    (see build command) so a free-tier host with no shell access always
    has a known-working login, even if the env var value changes later —
    unlike `createsuperuser --noinput`, which only sets the password once
    and then errors out (harmlessly) on every subsequent run.

    No-ops quietly if the username/password env vars aren't set, so it's
    safe to leave in the build command permanently.
    """

    help = "Create or password-sync a superuser from DJANGO_SUPERUSER_* env vars."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")

        if not username or not password:
            self.stdout.write(
                "DJANGO_SUPERUSER_USERNAME/PASSWORD not set, skipping superuser sync."
            )
            return

        user, created = User.objects.get_or_create(
            username=username, defaults={"email": email}
        )
        user.email = email
        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()

        self.stdout.write(
            self.style.SUCCESS(f"Synced superuser {username!r} (created={created}).")
        )
